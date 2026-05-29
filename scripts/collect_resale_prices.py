#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二次流通市場（新品/未使用）価格自動収集スクリプト。

対応プラットフォーム:
  - eBay completed listings (新品) — Finding API → HTML fallback
  - Amazon JP 新品出品 — HTML scraping (Cloud IP ブロック時は site_blocked)
  - メルカリ 新品/未使用 — Playwright SPA scraping
  - ヤフオク 落札済み 未使用 — HTML scraping

結果は sale_prices テーブルに保存する。
  condition = 'new_unopened'
  data_source = 'resale_market'
  id = 決定論的 (product_alias + shop_id のハッシュ) → INSERT OR REPLACE で更新

対象商品: カメラジャンル全品 (genre='camera' の products)

絶対禁止: 自動購入・自動応募・CAPTCHA突破・ログイン突破・複数アカウント運用・高頻度アクセス・規約違反行為
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

JST = timezone(timedelta(hours=9))

# ─────────────────────────────────────────────────────────────
# ロガー
# ─────────────────────────────────────────────────────────────
logger = logging.getLogger("collect_resale_prices")


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ─────────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────────

# 価格範囲フィルタ（円）
PRICE_MIN_JPY = 5_000
PRICE_MAX_JPY = 2_000_000

# アウトライア除去比率
OUTLIER_RATIO = 2.5

# リクエスト間隔（秒）— 高頻度アクセス防止
REQUEST_INTERVAL_SEC = 2.0

# HTML ブロック検出シグナル
_BLOCKED_SIGNALS = (
    "Access Denied",
    "Robot Check",
    "Sign in to confirm",
    "Just a moment",
    "cf-error",
    "captcha",
    "Captcha",
    "verify you are human",
    "ロボットではありません",
    "不正なアクセス",
)


# ─────────────────────────────────────────────────────────────
# 商品ターゲット設定
# ─────────────────────────────────────────────────────────────

# カメラ製品の検索キーワード設定
# product_id / product_alias は DB の products テーブルと対応
CAMERA_PRODUCT_CONFIGS: list[dict] = [
    {
        "product_id": "prod_gr4",
        "product_alias": "gr4",
        "name": "RICOH GR IV",
        "ebay_keywords": ["Ricoh GR IV"],
        "amazon_keywords": ["RICOH GR IV カメラ"],
        "mercari_keywords": ["RICOH GR IV"],
        "yahoo_keywords": ["RICOH GR IV"],
    },
    {
        "product_id": "prod_gr4_hdf",
        "product_alias": "gr4_hdf",
        "name": "RICOH GR IV HDF",
        "ebay_keywords": ["Ricoh GR IV HDF"],
        "amazon_keywords": ["RICOH GR IV HDF"],
        "mercari_keywords": ["RICOH GR IV HDF"],
        "yahoo_keywords": ["RICOH GR IV HDF"],
    },
    {
        "product_id": "prod_gr4_mono",
        "product_alias": "gr4_mono",
        "name": "RICOH GR IV Monochrome",
        "ebay_keywords": ["Ricoh GR IV Monochrome"],
        "amazon_keywords": ["RICOH GR IV Monochrome"],
        "mercari_keywords": ["RICOH GR IV Monochrome"],
        "yahoo_keywords": ["RICOH GR IV モノクローム"],
    },
    {
        "product_id": "prod_gr3x",
        "product_alias": "gr3x",
        "name": "RICOH GR IIIx",
        "ebay_keywords": ["Ricoh GR IIIx"],
        "amazon_keywords": ["RICOH GR IIIx"],
        "mercari_keywords": ["RICOH GR IIIx"],
        "yahoo_keywords": ["RICOH GR IIIx"],
    },
    {
        "product_id": "prod_x100vi",
        "product_alias": "x100vi",
        "name": "FUJIFILM X100VI",
        "ebay_keywords": ["FUJIFILM X100VI"],
        "amazon_keywords": ["FUJIFILM X100VI"],
        "mercari_keywords": ["FUJIFILM X100VI"],
        "yahoo_keywords": ["富士フイルム X100VI"],
    },
]

# ─────────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────────


def _make_sp_id(product_alias: str, shop_id: str) -> str:
    """product_alias + shop_id から決定論的 ID を生成する。

    同一組み合わせは常に同じ ID → INSERT OR REPLACE で既存レコードを更新。
    """
    h = hashlib.sha1(f"{product_alias}::{shop_id}".encode()).hexdigest()[:20]
    return f"resale_{h}"


def _remove_outliers(prices: list[float]) -> list[float]:
    """中央値から OUTLIER_RATIO 倍以上離れた価格を除外する。"""
    if len(prices) < 3:
        return prices
    med = statistics.median(prices)
    if med <= 0:
        return prices
    return [p for p in prices if (med / OUTLIER_RATIO) <= p <= (med * OUTLIER_RATIO)]


def _is_blocked(html: str) -> bool:
    """HTML がアクセス拒否ページかどうか判定する。"""
    if len(html) < 300:
        return True
    return any(sig in html for sig in _BLOCKED_SIGNALS)


def _fetch_html(url: str, headers: Optional[dict] = None, timeout: int = 20) -> Optional[str]:
    """URL から HTML を取得する（requests → urllib フォールバック）。

    ブロック / 接続エラー時は None を返す。
    """
    default_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    hdrs = {"User-Agent": default_ua, "Accept-Language": "ja,en;q=0.9"}
    if headers:
        hdrs.update(headers)

    try:
        import requests
        resp = requests.get(url, headers=hdrs, timeout=timeout)
        if resp.status_code in (403, 429, 503):
            logger.debug("HTTP %d → blocked: %s", resp.status_code, url[:80])
            return None
        if resp.status_code != 200:
            logger.debug("HTTP %d: %s", resp.status_code, url[:80])
            return None
        if _is_blocked(resp.text):
            logger.debug("ブロック検出: %s", url[:80])
            return None
        return resp.text
    except Exception as e:
        logger.debug("requests 失敗 (%s): %s", url[:80], e)

    # urllib フォールバック
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        if _is_blocked(raw):
            return None
        return raw
    except Exception as e:
        logger.debug("urllib 失敗 (%s): %s", url[:80], e)
        return None


# ─────────────────────────────────────────────────────────────
# eBay コレクター（既存 EbayCompletedCollector をラップ）
# ─────────────────────────────────────────────────────────────


class EbayResaleCollector:
    """eBay成約価格 → sale_pricesモデル変換コレクター。

    Finding API (EBAY_APP_ID) → HTML fallback → site_blocked の順で試行。
    """

    SHOP_ID = "ebay_completed_new"
    SHOP_NAME = "eBay (新品落札)"

    def collect(self, product_alias: str, product_id: str, keywords: list[str]) -> Optional[dict]:
        """eBay 成約価格を収集する。

        Returns:
            {price_jpy, listing_count, url, collector_method} または None
        """
        try:
            from src.collectors.overseas.ebay_completed import EbayCompletedCollector
            collector = EbayCompletedCollector()
            result = collector.collect(
                product_id=product_id,
                product_alias=product_alias,
                keywords=keywords,
                condition_filter="new",
            )
        except Exception as e:
            logger.warning("[eBay:%s] 収集エラー: %s", product_alias, e)
            return None

        if result.failure_reason in ("site_blocked", "html_blocked"):
            logger.info("[eBay:%s] サイトブロック → スキップ", product_alias)
            return None

        if result.price_jpy <= 0 or result.listing_count == 0:
            logger.info("[eBay:%s] 価格取得なし (reason=%s)", product_alias, result.failure_reason)
            return None

        logger.info(
            "[eBay:%s] ¥%s (method=%s, count=%d, confidence=%s)",
            product_alias,
            f"{result.price_jpy:,}",
            result.collector_method,
            result.listing_count,
            result.confidence,
        )
        return {
            "price_jpy": result.price_jpy,
            "listing_count": result.listing_count,
            "url": result.url,
            "collector_method": result.collector_method,
        }


# ─────────────────────────────────────────────────────────────
# Amazon JP コレクター
# ─────────────────────────────────────────────────────────────


class AmazonJpResaleCollector:
    """Amazon JP 新品出品価格コレクター。

    公開検索ページ (https://www.amazon.co.jp/s?k=...) から新品出品価格を取得。
    Cloud IP ブロック時は graceful fallback。
    """

    SHOP_ID = "amazon_jp_new"
    SHOP_NAME = "Amazon JP (新品出品)"

    # Amazon 新品コンディションフィルタ (condition-type=1294724011 = New)
    SEARCH_URL = (
        "https://www.amazon.co.jp/s"
        "?k={keyword}"
        "&rh=p_n_condition-type%3A1294724011"  # 新品コンディション
        "&s=price-asc-rank"
    )

    def collect(self, product_alias: str, keywords: list[str]) -> Optional[dict]:
        """Amazon JP の新品出品価格を取得する。"""
        keyword = keywords[0] if keywords else ""
        if not keyword:
            return None

        url = self.SEARCH_URL.format(keyword=urllib.parse.quote(keyword))
        html = _fetch_html(url, headers={"Accept-Language": "ja-JP,ja;q=0.9"})
        if not html:
            logger.info("[Amazon:%s] HTML取得失敗 → スキップ", product_alias)
            return None

        prices = self._parse_prices(html)
        if not prices:
            logger.info("[Amazon:%s] 価格なし (keyword='%s')", product_alias, keyword)
            return None

        prices = _remove_outliers(prices)
        if not prices:
            return None

        median_jpy = int(statistics.median(prices))
        logger.info(
            "[Amazon:%s] ¥%s (median of %d listings)",
            product_alias, f"{median_jpy:,}", len(prices),
        )
        return {
            "price_jpy": median_jpy,
            "listing_count": len(prices),
            "url": url,
            "collector_method": "html",
        }

    def _parse_prices(self, html: str) -> list[int]:
        """Amazon 検索結果 HTML から価格リストを抽出する。"""
        prices: list[int] = []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")

            # パターン1: .a-price-whole（整数部）
            for el in soup.select(".a-price .a-price-whole"):
                txt = el.get_text(strip=True).replace(",", "").replace(".", "")
                try:
                    p = int(txt)
                    if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                        prices.append(p)
                except ValueError:
                    pass

            # パターン2: aria-label="¥XX,XXX" 属性
            if not prices:
                for el in soup.select("[aria-label]"):
                    label = el.get("aria-label", "")
                    m = re.search(r'[¥￥]([0-9,]+)', label)
                    if m:
                        try:
                            p = int(m.group(1).replace(",", ""))
                            if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                                prices.append(p)
                        except ValueError:
                            pass

        except ImportError:
            # BeautifulSoup なし → regex のみ
            pass

        # フォールバック: 正規表現で ¥XX,XXX を検索
        if not prices:
            for m in re.finditer(r'[¥￥"]([\d,]{4,8})', html):
                try:
                    p = int(m.group(1).replace(",", ""))
                    if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                        prices.append(p)
                except ValueError:
                    pass

        return prices


# ─────────────────────────────────────────────────────────────
# メルカリ コレクター
# ─────────────────────────────────────────────────────────────


class MercariResaleCollector:
    """メルカリ 新品/未使用 出品価格コレクター。

    SPA (React) のため Playwright が必要。
    item_condition_id=1 は「新品、未使用」フィルタ。
    """

    SHOP_ID = "mercari_new"
    SHOP_NAME = "メルカリ (新品/未使用)"

    # status=on_sale: 出品中, item_condition_id=1: 新品・未使用
    SEARCH_URL = (
        "https://jp.mercari.com/search"
        "?keyword={keyword}"
        "&status=on_sale"
        "&item_condition_id=1"
    )

    def collect(self, product_alias: str, keywords: list[str]) -> Optional[dict]:
        """メルカリの新品/未使用出品価格を Playwright で取得する。"""
        keyword = keywords[0] if keywords else ""
        if not keyword:
            return None

        url = self.SEARCH_URL.format(keyword=urllib.parse.quote(keyword))

        prices = self._fetch_with_playwright(url)
        if not prices:
            logger.info("[Mercari:%s] 価格取得なし → スキップ", product_alias)
            return None

        prices = _remove_outliers(prices)
        if not prices:
            return None

        median_jpy = int(statistics.median(prices))
        logger.info(
            "[Mercari:%s] ¥%s (median of %d listings)",
            product_alias, f"{median_jpy:,}", len(prices),
        )
        return {
            "price_jpy": median_jpy,
            "listing_count": len(prices),
            "url": url,
            "collector_method": "playwright",
        }

    def _fetch_with_playwright(self, url: str) -> list[int]:
        """Playwright で SPA をレンダリングして価格リストを取得する。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.debug("Playwright 未インストール → Mercari スキップ")
            return []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="ja-JP",
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # SPA レンダリング待機
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()

            if _is_blocked(html):
                logger.info("[Mercari] ブロック検出")
                return []

            return self._parse_prices(html)

        except Exception as e:
            logger.warning("[Mercari] Playwright 失敗: %s", e)
            return []

    def _parse_prices(self, html: str) -> list[int]:
        """メルカリ HTML から価格を抽出する。"""
        prices: list[int] = []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")

            # パターン1: data-testid="price" または class="merPrice"
            for el in soup.select('[data-testid="price"], .merPrice__value, .item__price'):
                txt = el.get_text(strip=True).replace("¥", "").replace(",", "").strip()
                try:
                    p = int(txt)
                    if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                        prices.append(p)
                except ValueError:
                    pass

        except ImportError:
            pass

        # フォールバック: JSON の price フィールド
        if not prices:
            # メルカリの Next.js JSON データから抽出
            for m in re.finditer(r'"price"\s*:\s*(\d+)', html):
                try:
                    p = int(m.group(1))
                    if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                        prices.append(p)
                except ValueError:
                    pass

        return prices[:50]  # 最大50件


# ─────────────────────────────────────────────────────────────
# ヤフオク コレクター
# ─────────────────────────────────────────────────────────────


class YahooAuctionResaleCollector:
    """ヤフオク 落札済み（未使用/新品）価格コレクター。

    公開の落札済みオークション検索ページを使用。ログイン不要。
    """

    SHOP_ID = "yahoo_auction_new"
    SHOP_NAME = "ヤフオク (新品/未使用落札)"

    # va=除外キーワード（中古を除外）, istatus=2: 落札済み
    # condition_type=1: 未使用
    SEARCH_URL = (
        "https://auctions.yahoo.co.jp/search/search"
        "?p={keyword}"
        "&va={keyword}"
        "&istatus=2"          # 落札済み
        "&n=20"               # 20件
        "&s1=cbids&o1=d"      # 入札数降順
        "&ei=utf-8"
        "&auccat="
        "&tab_ex=commerce"
        "&item_condition=1"   # 未使用
    )

    def collect(self, product_alias: str, keywords: list[str]) -> Optional[dict]:
        """ヤフオク落札価格を取得する。"""
        keyword = keywords[0] if keywords else ""
        if not keyword:
            return None

        url = self.SEARCH_URL.format(keyword=urllib.parse.quote(keyword))
        html = _fetch_html(url)
        if not html:
            logger.info("[YahooAuction:%s] HTML取得失敗 → スキップ", product_alias)
            return None

        prices = self._parse_prices(html)
        if not prices:
            logger.info("[YahooAuction:%s] 価格なし", product_alias)
            return None

        prices = _remove_outliers(prices)
        if not prices:
            return None

        median_jpy = int(statistics.median(prices))
        logger.info(
            "[YahooAuction:%s] ¥%s (median of %d listings)",
            product_alias, f"{median_jpy:,}", len(prices),
        )
        return {
            "price_jpy": median_jpy,
            "listing_count": len(prices),
            "url": url,
            "collector_method": "html",
        }

    def _parse_prices(self, html: str) -> list[int]:
        """ヤフオク検索結果から落札価格を抽出する。"""
        prices: list[int] = []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")

            # 落札価格セレクタ
            for el in soup.select(".Product__price, .rb_mrkp span, .bb_price"):
                txt = el.get_text(strip=True).replace("¥", "").replace(",", "").strip()
                try:
                    p = int(txt)
                    if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                        prices.append(p)
                except ValueError:
                    pass

        except ImportError:
            pass

        # フォールバック
        if not prices:
            for m in re.finditer(r'[¥￥"]([\d,]{4,9})', html):
                try:
                    p = int(m.group(1).replace(",", ""))
                    if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                        prices.append(p)
                except ValueError:
                    pass

        return prices[:30]


# ─────────────────────────────────────────────────────────────
# 楽天市場 コレクター
# ─────────────────────────────────────────────────────────────


class RakutenResaleCollector:
    """楽天市場 新品出品価格コレクター。

    公開の楽天市場商品検索を使用。ログイン不要。
    """

    SHOP_ID = "rakuten_new"
    SHOP_NAME = "楽天市場 (新品)"

    SEARCH_URL = (
        "https://search.rakuten.co.jp/search/mall/{keyword}/"
        "?f=1"       # 新品のみ
        "&s=1"       # 価格昇順
        "&min=5000"
    )

    def collect(self, product_alias: str, keywords: list[str]) -> Optional[dict]:
        """楽天市場の新品出品価格を取得する。"""
        keyword = keywords[0] if keywords else ""
        if not keyword:
            return None

        url = self.SEARCH_URL.format(keyword=urllib.parse.quote(keyword))
        html = _fetch_html(url, headers={"Accept-Language": "ja"})
        if not html:
            logger.info("[Rakuten:%s] HTML取得失敗 → スキップ", product_alias)
            return None

        prices = self._parse_prices(html)
        if not prices:
            logger.info("[Rakuten:%s] 価格なし", product_alias)
            return None

        prices = _remove_outliers(prices)
        if not prices:
            return None

        median_jpy = int(statistics.median(prices))
        logger.info(
            "[Rakuten:%s] ¥%s (median of %d listings)",
            product_alias, f"{median_jpy:,}", len(prices),
        )
        return {
            "price_jpy": median_jpy,
            "listing_count": len(prices),
            "url": url,
            "collector_method": "html",
        }

    def _parse_prices(self, html: str) -> list[int]:
        """楽天市場検索結果から価格を抽出する。"""
        prices: list[int] = []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")

            # パターン1: .price クラス
            for el in soup.select(".price, .searchresultitem .important"):
                txt = el.get_text(strip=True).replace("円", "").replace(",", "").replace("¥", "").strip()
                try:
                    p = int(txt)
                    if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                        prices.append(p)
                except ValueError:
                    pass

        except ImportError:
            pass

        # フォールバック
        if not prices:
            for m in re.finditer(r'([\d,]{5,9})円', html):
                try:
                    p = int(m.group(1).replace(",", ""))
                    if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                        prices.append(p)
                except ValueError:
                    pass

        return prices[:30]


# ─────────────────────────────────────────────────────────────
# sale_prices 保存ヘルパー
# ─────────────────────────────────────────────────────────────


def _save_sale_price(
    repo,
    product_alias: str,
    product_id: str,
    shop_id: str,
    shop_name: str,
    price_jpy: int,
    url: str,
    now: datetime,
) -> None:
    """sale_prices テーブルに保存する（INSERT OR REPLACE）。"""
    from src.models.sale_price import SalePriceModel

    sp_id = _make_sp_id(product_alias, shop_id)

    sp = SalePriceModel(
        id=sp_id,
        product_id=product_id,
        product_alias=product_alias,
        shop_name=shop_name,
        shop_id=shop_id,
        sale_price=price_jpy,
        condition="new_unopened",
        url=url,
        link_verified=False,
        observed_at=now,
        data_source="resale_market",
        is_active=True,
    )
    repo.insert_sale_price(sp)
    logger.debug("保存: %s / %s ¥%s", product_alias, shop_name, f"{price_jpy:,}")


# ─────────────────────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────────────────────


def run_collection(
    skip_ebay: bool = False,
    skip_amazon: bool = False,
    skip_mercari: bool = False,
    skip_yahoo: bool = False,
    skip_rakuten: bool = False,
    target_alias: Optional[str] = None,
) -> dict:
    """全プラットフォームの価格収集を実行する。

    Returns:
        {"saved": int, "skipped": int, "errors": list}
    """
    from src.db.database import Database
    from src.db.repository import Repository

    db = Database()
    db.init_schema()
    repo = Repository(db)

    now = datetime.now(tz=JST)
    logger.info("収集開始: %s JST", now.strftime("%Y-%m-%d %H:%M"))

    # コレクター初期化
    ebay_collector     = EbayResaleCollector()     if not skip_ebay     else None
    amazon_collector   = AmazonJpResaleCollector() if not skip_amazon   else None
    mercari_collector  = MercariResaleCollector()  if not skip_mercari  else None
    yahoo_collector    = YahooAuctionResaleCollector() if not skip_yahoo else None
    rakuten_collector  = RakutenResaleCollector()  if not skip_rakuten  else None

    # 収集対象を絞り込む（--target 指定時）
    targets = CAMERA_PRODUCT_CONFIGS
    if target_alias:
        targets = [c for c in targets if c["product_alias"] == target_alias]
        if not targets:
            logger.warning("対象商品が見つかりません: %s", target_alias)

    stats = {"saved": 0, "skipped": 0, "errors": []}
    # プラットフォームごとのステータス（LP表示用）
    # "ok" | "blocked" | "no_data" | "skipped" | "error"
    platform_status: dict[str, str] = {
        "ebay": "skipped",
        "amazon": "skipped",
        "mercari": "skipped",
        "yahoo": "skipped",
        "rakuten": "skipped",
    }

    for cfg in targets:
        alias  = cfg["product_alias"]
        pid    = cfg["product_id"]
        name   = cfg["name"]
        logger.info("─── %s (%s) ───", name, alias)

        # ──── eBay ────
        if ebay_collector:
            try:
                result = ebay_collector.collect(
                    product_alias=alias,
                    product_id=pid,
                    keywords=cfg["ebay_keywords"],
                )
                if result:
                    _save_sale_price(
                        repo=repo,
                        product_alias=alias,
                        product_id=pid,
                        shop_id=EbayResaleCollector.SHOP_ID,
                        shop_name=EbayResaleCollector.SHOP_NAME,
                        price_jpy=result["price_jpy"],
                        url=result["url"],
                        now=now,
                    )
                    stats["saved"] += 1
                    # 1件でも成功したらステータスを更新
                    if platform_status["ebay"] != "ok":
                        method = result.get("collector_method", "")
                        platform_status["ebay"] = "ok_api" if method == "api" else "ok_html"
                else:
                    # 取得なし（ブロックまたはデータ無し）
                    if platform_status["ebay"] == "skipped":
                        platform_status["ebay"] = "blocked"
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning("[eBay:%s] エラー: %s", alias, e)
                stats["errors"].append(f"ebay:{alias}: {e}")
                if platform_status["ebay"] == "skipped":
                    platform_status["ebay"] = "error"
            time.sleep(REQUEST_INTERVAL_SEC)

        # ──── Amazon JP ────
        if amazon_collector:
            try:
                result = amazon_collector.collect(
                    product_alias=alias,
                    keywords=cfg["amazon_keywords"],
                )
                if result:
                    _save_sale_price(
                        repo=repo,
                        product_alias=alias,
                        product_id=pid,
                        shop_id=AmazonJpResaleCollector.SHOP_ID,
                        shop_name=AmazonJpResaleCollector.SHOP_NAME,
                        price_jpy=result["price_jpy"],
                        url=result["url"],
                        now=now,
                    )
                    stats["saved"] += 1
                    platform_status["amazon"] = "ok_html"
                else:
                    if platform_status["amazon"] == "skipped":
                        platform_status["amazon"] = "blocked"
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning("[Amazon:%s] エラー: %s", alias, e)
                stats["errors"].append(f"amazon:{alias}: {e}")
                if platform_status["amazon"] == "skipped":
                    platform_status["amazon"] = "error"
            time.sleep(REQUEST_INTERVAL_SEC)

        # ──── メルカリ ────
        if mercari_collector:
            try:
                result = mercari_collector.collect(
                    product_alias=alias,
                    keywords=cfg["mercari_keywords"],
                )
                if result:
                    _save_sale_price(
                        repo=repo,
                        product_alias=alias,
                        product_id=pid,
                        shop_id=MercariResaleCollector.SHOP_ID,
                        shop_name=MercariResaleCollector.SHOP_NAME,
                        price_jpy=result["price_jpy"],
                        url=result["url"],
                        now=now,
                    )
                    stats["saved"] += 1
                    platform_status["mercari"] = "ok_html"
                else:
                    if platform_status["mercari"] == "skipped":
                        platform_status["mercari"] = "blocked"
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning("[Mercari:%s] エラー: %s", alias, e)
                stats["errors"].append(f"mercari:{alias}: {e}")
                if platform_status["mercari"] == "skipped":
                    platform_status["mercari"] = "error"
            time.sleep(REQUEST_INTERVAL_SEC)

        # ──── ヤフオク ────
        if yahoo_collector:
            try:
                result = yahoo_collector.collect(
                    product_alias=alias,
                    keywords=cfg["yahoo_keywords"],
                )
                if result:
                    _save_sale_price(
                        repo=repo,
                        product_alias=alias,
                        product_id=pid,
                        shop_id=YahooAuctionResaleCollector.SHOP_ID,
                        shop_name=YahooAuctionResaleCollector.SHOP_NAME,
                        price_jpy=result["price_jpy"],
                        url=result["url"],
                        now=now,
                    )
                    stats["saved"] += 1
                    platform_status["yahoo"] = "ok_html"
                else:
                    if platform_status["yahoo"] == "skipped":
                        platform_status["yahoo"] = "blocked"
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning("[Yahoo:%s] エラー: %s", alias, e)
                stats["errors"].append(f"yahoo:{alias}: {e}")
                if platform_status["yahoo"] == "skipped":
                    platform_status["yahoo"] = "error"
            time.sleep(REQUEST_INTERVAL_SEC)

        # ──── 楽天市場 ────
        if rakuten_collector:
            try:
                result = rakuten_collector.collect(
                    product_alias=alias,
                    keywords=cfg["amazon_keywords"],  # Amazon と同じキーワードを流用
                )
                if result:
                    _save_sale_price(
                        repo=repo,
                        product_alias=alias,
                        product_id=pid,
                        shop_id=RakutenResaleCollector.SHOP_ID,
                        shop_name=RakutenResaleCollector.SHOP_NAME,
                        price_jpy=result["price_jpy"],
                        url=result["url"],
                        now=now,
                    )
                    stats["saved"] += 1
                    platform_status["rakuten"] = "ok_html"
                else:
                    if platform_status["rakuten"] == "skipped":
                        platform_status["rakuten"] = "blocked"
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning("[Rakuten:%s] エラー: %s", alias, e)
                stats["errors"].append(f"rakuten:{alias}: {e}")
                if platform_status["rakuten"] == "skipped":
                    platform_status["rakuten"] = "error"
            time.sleep(REQUEST_INTERVAL_SEC)

    logger.info(
        "収集完了: saved=%d / skipped=%d / errors=%d",
        stats["saved"], stats["skipped"], len(stats["errors"]),
    )
    if stats["errors"]:
        for err in stats["errors"]:
            logger.warning("  ERROR: %s", err)

    # ── ステータスレポートを書き出す（LP生成側で参照） ──
    _save_collection_status_report(platform_status, now, stats)

    return stats


def _save_collection_status_report(platform_status: dict, now: datetime, stats: dict) -> None:
    """収集ステータスをJSONレポートとして保存する。

    LP生成時に参照して「eBay自動取得制限中」などの表示に使う。
    exports/resale_collection_status.json に保存。
    """
    report = {
        "collected_at": now.isoformat(),
        "platforms": {
            "ebay": {
                "status": platform_status.get("ebay", "skipped"),
                # ok_api: Finding API成功, ok_html: HTML成功, blocked: Cloud IPブロック
                # skipped: 実行せず, error: 例外, no_data: レスポンスあるが価格なし
                "label_jp": _platform_label_jp(platform_status.get("ebay", "skipped")),
                "needs_ebay_app_id": platform_status.get("ebay") == "blocked",
            },
            "amazon": {
                "status": platform_status.get("amazon", "skipped"),
                "label_jp": _platform_label_jp(platform_status.get("amazon", "skipped")),
            },
            "mercari": {
                "status": platform_status.get("mercari", "skipped"),
                "label_jp": _platform_label_jp(platform_status.get("mercari", "skipped")),
            },
            "yahoo": {
                "status": platform_status.get("yahoo", "skipped"),
                "label_jp": _platform_label_jp(platform_status.get("yahoo", "skipped")),
            },
            "rakuten": {
                "status": platform_status.get("rakuten", "skipped"),
                "label_jp": _platform_label_jp(platform_status.get("rakuten", "skipped")),
            },
        },
        "summary": {
            "saved": stats.get("saved", 0),
            "skipped": stats.get("skipped", 0),
            "errors": stats.get("errors", []),
        },
    }

    try:
        report_dir = PROJECT_ROOT / "exports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "resale_collection_status.json"
        import json as _json
        report_path.write_text(_json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("収集ステータスレポート保存: %s", report_path)
    except Exception as e:
        logger.warning("ステータスレポート保存失敗: %s", e)


def _platform_label_jp(status: str) -> str:
    """ステータスを日本語ラベルに変換する。"""
    return {
        "ok_api":    "自動取得済（API）",
        "ok_html":   "自動取得済（HTML）",
        "blocked":   "自動取得制限中（Cloud IP）",
        "no_data":   "価格データなし",
        "skipped":   "実行スキップ",
        "error":     "取得エラー",
    }.get(status, status)


# ─────────────────────────────────────────────────────────────
# CLI エントリポイント
# ─────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="二次流通市場（新品/未使用）価格自動収集スクリプト",
    )
    parser.add_argument("--skip-ebay",    action="store_true", help="eBay収集をスキップ")
    parser.add_argument("--skip-amazon",  action="store_true", help="Amazon収集をスキップ")
    parser.add_argument("--skip-mercari", action="store_true", help="メルカリ収集をスキップ")
    parser.add_argument("--skip-yahoo",   action="store_true", help="ヤフオク収集をスキップ")
    parser.add_argument("--skip-rakuten", action="store_true", help="楽天市場収集をスキップ")
    parser.add_argument("--target",       type=str, default=None,
                        help="特定 product_alias のみ対象 (例: gr4)")
    parser.add_argument("--verbose",      action="store_true", help="詳細ログ")
    args = parser.parse_args()

    setup_logging(args.verbose)

    now = datetime.now(tz=JST)
    logger.info("=" * 60)
    logger.info("collect_resale_prices 開始: %s", now.strftime("%Y-%m-%d %H:%M JST"))
    logger.info("=" * 60)

    try:
        stats = run_collection(
            skip_ebay=args.skip_ebay,
            skip_amazon=args.skip_amazon,
            skip_mercari=args.skip_mercari,
            skip_yahoo=args.skip_yahoo,
            skip_rakuten=args.skip_rakuten,
            target_alias=args.target,
        )
    except Exception as e:
        logger.error("収集中に予期しないエラー: %s", e, exc_info=True)
        return 1

    # エラーがあっても 0 で終了（continue-on-error と同様の動作）
    # 収集失敗は警告として扱い、LP更新を止めない
    return 0


if __name__ == "__main__":
    sys.exit(main())
