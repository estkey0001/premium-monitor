#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二次流通市場（新品/未使用）価格自動収集スクリプト。

対応プラットフォーム:
  - eBay completed listings (新品) — Finding API → HTML fallback
  - Amazon JP 新品出品 — HTML scraping (Cloud IP ブロック時は site_blocked)
  - メルカリ 新品/未使用 — Playwright SPA scraping
  - ヤフオク 落札済み 未使用 — HTML scraping
  - 楽天市場 新品出品 — HTML scraping
  - ラクマ 新品/未使用 — HTML scraping (fril.jp)

結果は sale_prices テーブルに保存する。
  condition = 'new_unopened'
  data_source = 'resale_market'
  id = 決定論的 (product_alias + shop_id のハッシュ) → INSERT OR REPLACE で更新

対象商品: カメラ・iPhone・ゲーム機 全品

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

# iPhone製品の検索キーワード設定
IPHONE_PRODUCT_CONFIGS: list[dict] = [
    {
        "product_id": "prod_iphone17pro_256",
        "product_alias": "iphone17pro256",
        "name": "iPhone 17 Pro 256GB",
        "ebay_keywords": ["iPhone 17 Pro 256GB"],
        "amazon_keywords": [],
        "mercari_keywords": ["iPhone 17 Pro 256GB"],
        "yahoo_keywords": ["iPhone 17 Pro 256GB"],
    },
    {
        "product_id": "prod_iphone17pro_512",
        "product_alias": "iphone17pro512",
        "name": "iPhone 17 Pro 512GB",
        "ebay_keywords": ["iPhone 17 Pro 512GB"],
        "amazon_keywords": [],
        "mercari_keywords": [],
        "yahoo_keywords": ["iPhone 17 Pro 512GB"],
    },
    {
        "product_id": "prod_iphone17pm_256",
        "product_alias": "iphone17pm256",
        "name": "iPhone 17 Pro Max 256GB",
        "ebay_keywords": ["iPhone 17 Pro Max 256GB"],
        "amazon_keywords": [],
        "mercari_keywords": [],
        "yahoo_keywords": ["iPhone 17 Pro Max 256GB"],
    },
    {
        "product_id": "prod_iphone17pm_512",
        "product_alias": "iphone17pm512",
        "name": "iPhone 17 Pro Max 512GB",
        "ebay_keywords": ["iPhone 17 Pro Max 512GB"],
        "amazon_keywords": [],
        "mercari_keywords": [],
        "yahoo_keywords": ["iPhone 17 Pro Max 512GB"],
    },
]

# ゲーム機の検索キーワード設定
GAME_PRODUCT_CONFIGS: list[dict] = [
    {
        "product_id": "prod_switch2",
        "product_alias": "switch2",
        "name": "Nintendo Switch 2",
        "ebay_keywords": ["Nintendo Switch 2"],
        "amazon_keywords": [],
        "mercari_keywords": [],
        "yahoo_keywords": ["Nintendo Switch 2"],
    },
    {
        "product_id": "prod_ps5_pro",
        "product_alias": "ps5_pro",
        "name": "PlayStation 5 Pro",
        "ebay_keywords": ["PlayStation 5 Pro"],
        "amazon_keywords": [],
        "mercari_keywords": [],
        "yahoo_keywords": ["PlayStation 5 Pro"],
    },
]

# 全商品設定（全カテゴリ統合）
ALL_PRODUCT_CONFIGS: list[dict] = (
    CAMERA_PRODUCT_CONFIGS + IPHONE_PRODUCT_CONFIGS + GAME_PRODUCT_CONFIGS
)

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
# ラクマ コレクター
# ─────────────────────────────────────────────────────────────


class RakumaResaleCollector:
    """ラクマ（fril.jp）新品/未使用 出品価格コレクター。

    公開の fril.jp 検索ページを使用。ログイン不要。
    """

    SHOP_ID = "rakuma"
    SHOP_NAME = "ラクマ(新品/未使用)"

    SEARCH_URL = (
        "https://fril.jp/search"
        "?query={keyword}"
        "&sort_column=created_at"
        "&sort_order=desc"
    )

    def collect(self, product_alias: str, keywords: list[str]) -> Optional[dict]:
        """fril.jp から新品/未使用の価格を取得する。"""
        keyword = keywords[0] if keywords else ""
        if not keyword:
            return None

        url = self.SEARCH_URL.format(keyword=urllib.parse.quote(keyword))
        html = _fetch_html(url, headers={"Accept-Language": "ja"})
        if not html:
            logger.info("[Rakuma:%s] HTML取得失敗 → スキップ", product_alias)
            return None

        if _is_blocked(html):
            logger.info("[Rakuma:%s] ブロック検出 → スキップ", product_alias)
            return None

        prices = self._parse_prices(html)
        if not prices:
            logger.info("[Rakuma:%s] 価格なし (keyword='%s')", product_alias, keyword)
            return None

        prices = _remove_outliers(prices)
        if not prices:
            return None

        median_jpy = int(statistics.median(prices))
        logger.info(
            "[Rakuma:%s] ¥%s (median of %d listings)",
            product_alias, f"{median_jpy:,}", len(prices),
        )
        return {
            "price_jpy": median_jpy,
            "listing_count": len(prices),
            "url": url,
            "collector_method": "html",
        }

    def _parse_prices(self, html: str) -> list[int]:
        """ラクマ（fril.jp）検索結果から価格を抽出する。"""
        prices: list[int] = []

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")

            # パターン1: <span class="item-price"> または data-price 属性
            for el in soup.select(".item-price, [data-price]"):
                # data-price 属性を優先
                val = el.get("data-price", "")
                if val:
                    try:
                        p = int(val)
                        if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                            prices.append(p)
                        continue
                    except ValueError:
                        pass
                # テキストから抽出
                txt = el.get_text(strip=True).replace("¥", "").replace(",", "").strip()
                try:
                    p = int(txt)
                    if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                        prices.append(p)
                except ValueError:
                    pass

        except ImportError:
            pass

        # フォールバック: JSON の "price": 数値 パターン
        if not prices:
            for m in re.finditer(r'"price":\s*(\d+)', html):
                try:
                    p = int(m.group(1))
                    if PRICE_MIN_JPY <= p <= PRICE_MAX_JPY:
                        prices.append(p)
                except ValueError:
                    pass

        # さらにフォールバック: ¥XX,XXX 形式
        if not prices:
            for m in re.finditer(r'[¥￥]([\d,]{4,9})', html):
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


# 状態推定キーワード（出品タイトル/状態テキストから condition を推定）
_USED_HINTS = ("中古", "美品", "良品", "used", "ジャンク", "難あり", "傷", "訳あり",
               "開封済", "b品", "c品")
_NEW_HINTS = ("新品未開封", "新品・未開封", "未開封", "新品同様", "ほぼ新品",
              "新品未使用", "新品", "未使用", "sealed", "brand new", "new")


def _infer_condition(text: Optional[str], default: str = "new_unopened") -> str:
    """出品タイトル/状態テキストから買取・販売条件を推定する（Task 1）。

    各コレクターは新品/未使用フィルタ済みクエリで取得するが、タイトルに中古を示す
    語が含まれる場合は used_a を返して下流（ランキング/せどり）で除外できるようにする。
    新品系の語が明示されていれば new_unopened を返す。判定できなければ default。
    """
    if not text:
        return default
    t = str(text).lower()
    # 中古を示す語が含まれていれば used 扱い（下流で除外される）
    if any(k in t for k in _USED_HINTS):
        # 「新品同様」「ほぼ新品」は新品系として扱う（中古語より優先）
        if any(k in t for k in ("新品同様", "ほぼ新品", "新品未使用", "新品未開封")):
            return "new_unopened"
        return "used_a"
    if any(k in t for k in _NEW_HINTS):
        return "new_unopened"
    return default


def _save_sale_price(
    repo,
    product_alias: str,
    product_id: str,
    shop_id: str,
    shop_name: str,
    price_jpy: int,
    url: str,
    now: datetime,
    condition: Optional[str] = None,
    title: Optional[str] = None,
) -> None:
    """sale_prices テーブルに保存する（INSERT OR REPLACE）。

    condition を明示しない場合は title から推定する（Task 1: condition 推定）。
    どちらも無ければ new_unopened（クエリが新品/未使用フィルタ済みのため）。
    """
    from src.models.sale_price import SalePriceModel

    sp_id = _make_sp_id(product_alias, shop_id)
    _cond = condition or _infer_condition(title, default="new_unopened")

    sp = SalePriceModel(
        id=sp_id,
        product_id=product_id,
        product_alias=product_alias,
        shop_name=shop_name,
        shop_id=shop_id,
        sale_price=price_jpy,
        condition=_cond,
        url=url,
        link_verified=False,
        observed_at=now,
        data_source="resale_market",
        is_active=True,
    )
    repo.insert_sale_price(sp)
    logger.debug("保存: %s / %s ¥%s [%s]", product_alias, shop_name, f"{price_jpy:,}", _cond)


# ─────────────────────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────────────────────


def run_collection(
    skip_ebay: bool = False,
    skip_amazon: bool = False,
    skip_mercari: bool = False,
    skip_yahoo: bool = False,
    skip_rakuten: bool = False,
    skip_rakuma: bool = False,
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
    ebay_collector     = EbayResaleCollector()        if not skip_ebay     else None
    amazon_collector   = AmazonJpResaleCollector()    if not skip_amazon   else None
    mercari_collector  = MercariResaleCollector()     if not skip_mercari  else None
    yahoo_collector    = YahooAuctionResaleCollector() if not skip_yahoo   else None
    rakuten_collector  = RakutenResaleCollector()     if not skip_rakuten  else None
    rakuma_collector   = RakumaResaleCollector()      if not skip_rakuma   else None

    # 収集対象を絞り込む（--target 指定時）
    targets = ALL_PRODUCT_CONFIGS
    if target_alias:
        targets = [c for c in targets if c["product_alias"] == target_alias]
        if not targets:
            logger.warning("対象商品が見つかりません: %s", target_alias)

    stats = {"saved": 0, "skipped": 0, "errors": []}
    # プラットフォームごとのステータス（LP表示用）
    # "ok_api" | "ok_html" | "blocked" | "blocked_cloud_ip" | "no_data"
    # | "html_failed" | "skipped" | "error" | "api_key_missing" | "not_supported"
    platform_status: dict[str, str] = {
        "ebay":         "skipped",
        "amazon":       "skipped",
        "mercari":      "skipped",
        "yahoo":        "skipped",
        "rakuten":      "skipped",
        "rakuma_direct": "skipped",
    }

    # 商品ごとのプラットフォーム収集結果を追跡する
    # alias -> {platform: status}
    # status: "ok_html" | "ok_api" | "blocked_cloud_ip" | "html_failed" | "no_data" | "skipped"
    product_results: dict[str, dict] = {}

    for cfg in targets:
        alias  = cfg["product_alias"]
        pid    = cfg["product_id"]
        name   = cfg["name"]
        logger.info("─── %s (%s) ───", name, alias)

        # 商品の結果辞書を初期化
        product_results[alias] = {
            "ebay":    "skipped",
            "amazon":  "skipped",
            "mercari": "skipped",
            "yahoo":   "skipped",
            "rakuten": "skipped",
            "rakuma":  "skipped",
        }

        # ──── eBay ────
        if ebay_collector:
            kws = cfg.get("ebay_keywords", [])
            if not kws:
                product_results[alias]["ebay"] = "not_supported"
            else:
                try:
                    result = ebay_collector.collect(
                        product_alias=alias,
                        product_id=pid,
                        keywords=kws,
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
                        method = result.get("collector_method", "")
                        _st = "ok_api" if method == "api" else "ok_html"
                        if platform_status["ebay"] not in ("ok_api", "ok_html"):
                            platform_status["ebay"] = _st
                        product_results[alias]["ebay"] = _st
                    else:
                        # 取得なし（ブロックまたはデータ無し）
                        if platform_status["ebay"] == "skipped":
                            platform_status["ebay"] = "blocked_cloud_ip"
                        product_results[alias]["ebay"] = "blocked_cloud_ip"
                        stats["skipped"] += 1
                except Exception as e:
                    logger.warning("[eBay:%s] エラー: %s", alias, e)
                    stats["errors"].append(f"ebay:{alias}: {e}")
                    if platform_status["ebay"] == "skipped":
                        platform_status["ebay"] = "error"
                    product_results[alias]["ebay"] = "html_failed"
            time.sleep(REQUEST_INTERVAL_SEC)

        # ──── Amazon JP ────
        if amazon_collector:
            kws = cfg.get("amazon_keywords", [])
            if not kws:
                product_results[alias]["amazon"] = "not_supported"
            else:
                try:
                    result = amazon_collector.collect(
                        product_alias=alias,
                        keywords=kws,
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
                        if platform_status["amazon"] not in ("ok_api", "ok_html"):
                            platform_status["amazon"] = "ok_html"
                        product_results[alias]["amazon"] = "ok_html"
                    else:
                        if platform_status["amazon"] == "skipped":
                            platform_status["amazon"] = "blocked_cloud_ip"
                        product_results[alias]["amazon"] = "blocked_cloud_ip"
                        stats["skipped"] += 1
                except Exception as e:
                    logger.warning("[Amazon:%s] エラー: %s", alias, e)
                    stats["errors"].append(f"amazon:{alias}: {e}")
                    if platform_status["amazon"] == "skipped":
                        platform_status["amazon"] = "error"
                    product_results[alias]["amazon"] = "html_failed"
            time.sleep(REQUEST_INTERVAL_SEC)

        # ──── メルカリ ────
        if mercari_collector:
            kws = cfg.get("mercari_keywords", [])
            if not kws:
                product_results[alias]["mercari"] = "not_supported"
            else:
                try:
                    result = mercari_collector.collect(
                        product_alias=alias,
                        keywords=kws,
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
                        if platform_status["mercari"] not in ("ok_api", "ok_html"):
                            platform_status["mercari"] = "ok_html"
                        product_results[alias]["mercari"] = "ok_html"
                    else:
                        if platform_status["mercari"] == "skipped":
                            platform_status["mercari"] = "blocked_cloud_ip"
                        product_results[alias]["mercari"] = "blocked_cloud_ip"
                        stats["skipped"] += 1
                except Exception as e:
                    logger.warning("[Mercari:%s] エラー: %s", alias, e)
                    stats["errors"].append(f"mercari:{alias}: {e}")
                    if platform_status["mercari"] == "skipped":
                        platform_status["mercari"] = "error"
                    product_results[alias]["mercari"] = "html_failed"
            time.sleep(REQUEST_INTERVAL_SEC)

        # ──── ヤフオク ────
        if yahoo_collector:
            kws = cfg.get("yahoo_keywords", [])
            if not kws:
                product_results[alias]["yahoo"] = "not_supported"
            else:
                try:
                    result = yahoo_collector.collect(
                        product_alias=alias,
                        keywords=kws,
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
                        if platform_status["yahoo"] not in ("ok_api", "ok_html"):
                            platform_status["yahoo"] = "ok_html"
                        product_results[alias]["yahoo"] = "ok_html"
                    else:
                        if platform_status["yahoo"] == "skipped":
                            platform_status["yahoo"] = "no_data"
                        product_results[alias]["yahoo"] = "no_data"
                        stats["skipped"] += 1
                except Exception as e:
                    logger.warning("[Yahoo:%s] エラー: %s", alias, e)
                    stats["errors"].append(f"yahoo:{alias}: {e}")
                    if platform_status["yahoo"] == "skipped":
                        platform_status["yahoo"] = "error"
                    product_results[alias]["yahoo"] = "html_failed"
            time.sleep(REQUEST_INTERVAL_SEC)

        # ──── 楽天市場 ────
        if rakuten_collector:
            # Amazon と同じキーワードを流用（空の場合はスキップ）
            kws = cfg.get("amazon_keywords", [])
            if not kws:
                product_results[alias]["rakuten"] = "not_supported"
            else:
                try:
                    result = rakuten_collector.collect(
                        product_alias=alias,
                        keywords=kws,
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
                        if platform_status["rakuten"] not in ("ok_api", "ok_html"):
                            platform_status["rakuten"] = "ok_html"
                        product_results[alias]["rakuten"] = "ok_html"
                    else:
                        if platform_status["rakuten"] == "skipped":
                            platform_status["rakuten"] = "html_failed"
                        product_results[alias]["rakuten"] = "html_failed"
                        stats["skipped"] += 1
                except Exception as e:
                    logger.warning("[Rakuten:%s] エラー: %s", alias, e)
                    stats["errors"].append(f"rakuten:{alias}: {e}")
                    if platform_status["rakuten"] == "skipped":
                        platform_status["rakuten"] = "error"
                    product_results[alias]["rakuten"] = "html_failed"
            time.sleep(REQUEST_INTERVAL_SEC)

        # ──── ラクマ ────
        if rakuma_collector:
            # ヤフオクキーワードを流用（新品未開封系の検索語）
            kws = cfg.get("yahoo_keywords", [])
            if not kws:
                product_results[alias]["rakuma"] = "not_supported"
            else:
                try:
                    result = rakuma_collector.collect(
                        product_alias=alias,
                        keywords=kws,
                    )
                    if result:
                        _save_sale_price(
                            repo=repo,
                            product_alias=alias,
                            product_id=pid,
                            shop_id=RakumaResaleCollector.SHOP_ID,
                            shop_name=RakumaResaleCollector.SHOP_NAME,
                            price_jpy=result["price_jpy"],
                            url=result["url"],
                            now=now,
                        )
                        stats["saved"] += 1
                        if platform_status["rakuma_direct"] not in ("ok_api", "ok_html"):
                            platform_status["rakuma_direct"] = "ok_html"
                        product_results[alias]["rakuma"] = "ok_html"
                    else:
                        if platform_status["rakuma_direct"] == "skipped":
                            platform_status["rakuma_direct"] = "blocked_cloud_ip"
                        product_results[alias]["rakuma"] = "blocked_cloud_ip"
                        stats["skipped"] += 1
                except Exception as e:
                    logger.warning("[Rakuma:%s] エラー: %s", alias, e)
                    stats["errors"].append(f"rakuma:{alias}: {e}")
                    if platform_status["rakuma_direct"] == "skipped":
                        platform_status["rakuma_direct"] = "error"
                    product_results[alias]["rakuma"] = "html_failed"
            time.sleep(REQUEST_INTERVAL_SEC)

    logger.info(
        "収集完了: saved=%d / skipped=%d / errors=%d",
        stats["saved"], stats["skipped"], len(stats["errors"]),
    )
    if stats["errors"]:
        for err in stats["errors"]:
            logger.warning("  ERROR: %s", err)

    # ── ステータスレポートを書き出す（LP生成側で参照） ──
    _save_collection_status_report(platform_status, now, stats, product_results)

    return stats


def _save_collection_status_report(
    platform_status: dict,
    now: datetime,
    stats: dict,
    product_results: Optional[dict] = None,
) -> None:
    """収集ステータスをJSONレポートとして保存する。

    LP生成時に参照して「eBay自動取得制限中」などの表示に使う。
    exports/resale_collection_status.json に保存。
    """
    ebay_st = platform_status.get("ebay", "skipped")
    report = {
        "collected_at": now.isoformat(),
        "platforms": {
            "ebay": {
                "status": ebay_st,
                # ok_api: Finding API成功, ok_html: HTML成功, blocked_cloud_ip: Cloud IPブロック
                # skipped: 実行せず, error: 例外, no_data: レスポンスあるが価格なし
                "label_jp": _platform_label_jp(ebay_st),
                "needs_ebay_app_id": ebay_st in ("blocked", "blocked_cloud_ip"),
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
            "rakuma_direct": {
                "status": platform_status.get("rakuma_direct", "skipped"),
                "label_jp": _platform_label_jp(platform_status.get("rakuma_direct", "skipped")),
            },
        },
        "summary": {
            "saved": stats.get("saved", 0),
            "skipped": stats.get("skipped", 0),
            "errors": stats.get("errors", []),
        },
    }

    # 商品ごとの収集結果を追加（product_results が渡された場合）
    if product_results:
        report["products"] = product_results

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
        "ok_api":           "自動取得済（API）",
        "ok_html":          "自動取得済（HTML）",
        "blocked":          "自動取得制限中（Cloud IP）",
        "blocked_cloud_ip": "Cloud IP制限中（EBAY_APP_ID推奨）",
        "html_failed":      "HTML取得失敗",
        "no_data":          "該当商品なし",
        "skipped":          "実行スキップ",
        "error":            "取得エラー",
        "api_key_missing":  "APIキー未設定",
        "not_supported":    "未対応",
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
    parser.add_argument("--skip-rakuma",  action="store_true", help="ラクマ収集をスキップ")
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
            skip_rakuma=args.skip_rakuma,
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
