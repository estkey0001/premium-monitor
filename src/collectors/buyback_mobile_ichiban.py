"""モバイル一番 買取価格コレクター（CSV更新用）。
URL: https://www.mobile-ichiban.com/ (トップページに買取価格一覧)
実装:
  1. requests で静的HTML取得を試みる（fast path）
  2. 取得できない or 本文が短すぎる場合 → Playwright fallback
     - wait_until="domcontentloaded"（networkidle 禁止: timeout の主因）
     - timeout=60s
     - 本文取得後 text_length < 1000 なら 5秒待って再取得（1回まで）
価格形式: 新品\n178,000円 (カンマ区切り + 円)

禁止:
  - timeoutで失敗したあと古い価格を使う
  - 商品名と無関係な価格をfallback採用する

対応商品:
  - iPhone 17 Pro 256/512GB → 確認済み
  - iPhone 17 Pro Max 256/512GB → 確認済み
  - PS5 Pro (CFI-7000B01) → 確認済み
  - Nintendo Switch 2 → 未掲載 (スキップ)
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

logger = logging.getLogger(__name__)

# トップページに全商品の価格が掲載
PRODUCT_URLS = {
    "iphone17pro256":  "https://www.mobile-ichiban.com/",
    "iphone17pro512":  "https://www.mobile-ichiban.com/",
    "iphone17pm256":   "https://www.mobile-ichiban.com/",
    "iphone17pm512":   "https://www.mobile-ichiban.com/",
    "switch2":         "",   # 未掲載 → スキップ
    "ps5_pro":         "https://www.mobile-ichiban.com/",
}

# 商品特定用の直接正規表現パターン (requests BS4テキスト / Playwright inner_text に対応)
#
# ページ構造（BS4 plain text / inner_text）:
#   iPhone 17 Pro 256GB
#   simfree未開封
#   新品
#   カラー*
#   選択してください
#   銀  青  橙
#   必須項目です
#   確定
#   181,500円   ← ここが買取価格
#
# 注意: "iPhone 17 Pro 256GB" は "iPhone 17 Pro Max 256GB" にはマッチしない (Max が間にある)
# 価格は「確定」の次の行に表示されるので `確定\n([\d,]+)円` を使う
PRICE_PATTERNS = {
    "iphone17pro256": r'iPhone 17 Pro 256GB\s+simfree未開封.*?確定\s+([\d,]+)円',
    "iphone17pro512": r'iPhone 17 Pro 512GB\s+simfree未開封.*?確定\s+([\d,]+)円',
    "iphone17pm256":  r'iPhone 17 Pro Max 256GB\s+simfree未開封.*?確定\s+([\d,]+)円',
    "iphone17pm512":  r'iPhone 17 Pro Max 512GB\s+simfree未開封.*?確定\s+([\d,]+)円',
    "ps5_pro":        r'PlayStation 5 Pro.*?新品.*?確定\s+([\d,]+)円',
}

# 商品ブロックを特定するためのアンカーキーワード（商品名と容量の両方）
PRODUCT_ANCHORS = {
    "iphone17pro256": ("iPhone 17 Pro", "256"),
    "iphone17pro512": ("iPhone 17 Pro", "512"),
    "iphone17pm256":  ("iPhone 17 Pro Max", "256"),
    "iphone17pm512":  ("iPhone 17 Pro Max", "512"),
    "ps5_pro":        ("PlayStation 5 Pro", None),
}

# requests で取得した HTML が "十分な本文を含む" と見なす最小文字数
# モバイル一番のトップページは通常 20,000 文字以上
_MIN_CONTENT_LENGTH = 5000

# Playwright タイムアウト設定（ミリ秒）
# GitHub Actions ではネットワーク遅延があるため余裕を持たせる
_PW_GOTO_TIMEOUT_MS  = 60_000   # page.goto: 60秒
_PW_LOAD_TIMEOUT_MS  = 10_000   # wait_for_load_state: 10秒（domcontentloaded）
_PW_RETRY_WAIT_MS    = 5_000    # 本文が短い場合の追加待機: 5秒

# requests タイムアウト（秒）
_REQUESTS_TIMEOUT = 20


class MobileIchibanCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "mobile_ichiban"
    SHOP_NAME = "モバイル一番"
    BASE_URL  = "https://www.mobile-ichiban.com/"
    REQUIRES_JS = True

    def __init__(self, timeout: int = 20):
        super().__init__(timeout=timeout)
        # debug 追加フィールド
        self.last_elapsed_seconds: float = 0.0
        self.last_text_length: int = 0
        self.last_error_type: str = ""

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    # ─────────────────────────────────────────────────────────────────────────
    # fetch HTML: requests fast path → Playwright fallback
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_html(self, url: str) -> Optional[str]:
        """
        Step 1: requests で静的HTMLを試みる（高速・安定）
        Step 2: 本文が短すぎる or 取得失敗 → Playwright（domcontentloaded, 60s）
        失敗時は last_failure_reason に "timeout" / "empty_html" を設定する。
        """
        self.last_fetch_url = url
        self.last_http_status = 0
        self.last_html_length = 0
        self.last_elapsed_seconds = 0.0
        self.last_text_length = 0
        self.last_error_type = ""

        t0 = time.monotonic()
        time.sleep(1.5)  # レートリミット遵守

        # ── Step1: requests fast path ──────────────────────────────────────
        html_from_requests: Optional[str] = None
        try:
            resp = self.session.get(url, timeout=_REQUESTS_TIMEOUT)
            self.last_http_status = resp.status_code
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            html_from_requests = resp.text
            logger.debug("[モバイル一番] requests OK: %d chars", len(html_from_requests))
        except Exception as e:
            logger.debug("[モバイル一番] requests failed (%s), fallback to Playwright", e)

        # requests で十分な本文が取れた場合: BS4 でプレーンテキストに変換し、
        # 実際に価格データ（新品＋円）が含まれている場合のみ fast path として使う。
        # モバイル一番はトップページの価格テーブルをJSで描画するため、
        # 静的HTMLには価格データが含まれないことが多い → Playwright へフォールバック。
        if html_from_requests and len(html_from_requests) >= _MIN_CONTENT_LENGTH:
            self.last_html_length = len(html_from_requests)
            try:
                from bs4 import BeautifulSoup
                plain_text = BeautifulSoup(html_from_requests, "html.parser").get_text("\n", strip=True)
            except Exception:
                plain_text = html_from_requests
            self.last_text_length = len(plain_text)
            # 価格データ存在チェック: "新品" かつ "円" かつ 6桁数字 が含まれるか
            import re as _re
            _has_price_data = bool(_re.search(r'新品.*?\d{2,3},\d{3}円', plain_text, _re.DOTALL))
            if _has_price_data:
                self.last_elapsed_seconds = time.monotonic() - t0
                logger.debug("[モバイル一番] requests fast path (価格あり): html=%d, text=%d chars",
                             self.last_html_length, self.last_text_length)
                return plain_text
            else:
                logger.debug("[モバイル一番] requests 本文に価格データなし(%d chars)、Playwright へ",
                             self.last_text_length)

        # ── Step2: Playwright fallback ─────────────────────────────────────
        text = self._fetch_with_playwright_optimized(url)
        self.last_elapsed_seconds = time.monotonic() - t0

        if text is None:
            # last_failure_reason は _fetch_with_playwright_optimized 内で設定済み
            return None

        self.last_html_length = len(text)
        self.last_text_length = len(text)
        return text

    def _fetch_with_playwright_optimized(self, url: str) -> Optional[str]:
        """
        Playwright 取得（domcontentloaded 使用）。
        - networkidle を使わない（タイムアウトの主因）
        - 本文が短い場合は 5秒待ってリトライ（1回）
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
        except ImportError:
            logger.warning("[モバイル一番] Playwright not installed")
            self.last_failure_reason = "playwright_not_installed"
            self.last_error_type = "ImportError"
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        locale="ja-JP",
                    )
                    page = context.new_page()

                    # goto: domcontentloaded で十分（networkidle はタイムアウトの原因）
                    page.goto(url, timeout=_PW_GOTO_TIMEOUT_MS, wait_until="domcontentloaded")

                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=_PW_LOAD_TIMEOUT_MS)
                    except Exception:
                        pass  # タイムアウトしても inner_text は試みる

                    # 1回目の本文取得
                    text = page.inner_text("body")
                    self.last_text_length = len(text) if text else 0

                    # 本文が短すぎる場合: JS描画完了を待って再取得（1回のみ）
                    if not text or len(text) < 500:
                        logger.debug("[モバイル一番] 本文短い (%d chars)、%dms 追加待機して再取得",
                                     len(text) if text else 0, _PW_RETRY_WAIT_MS)
                        page.wait_for_timeout(_PW_RETRY_WAIT_MS)
                        text = page.inner_text("body")
                        self.last_text_length = len(text) if text else 0
                        logger.debug("[モバイル一番] 再取得後: %d chars", self.last_text_length)

                    if not text or len(text) < 100:
                        logger.warning("[モバイル一番] Playwright: 本文取得失敗 (%d chars)",
                                       self.last_text_length)
                        self.last_failure_reason = "empty_html"
                        self.last_error_type = "empty_body"
                        return None

                    return text

                finally:
                    browser.close()

        except Exception as e:
            err_type = type(e).__name__
            self.last_error_type = err_type
            err_str = str(e)

            if "Timeout" in err_type or "timeout" in err_str.lower():
                logger.warning("[モバイル一番] Playwright timeout: %s", e)
                self.last_failure_reason = "timeout"
            else:
                logger.warning("[モバイル一番] Playwright error (%s): %s", err_type, e)
                self.last_failure_reason = f"playwright_{err_type.lower()}"
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # _parse_price
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        """html は Playwright inner_text() または requests BS4テキスト。
        商品名が本文に存在しない場合は None を返す（誤マッチ防止）。
        """
        text = html

        # ── 前処理: 商品の容量キーワードが本文にあるか確認 ──────────────────────
        # 例: "iphone17pro512" → "512GB" が本文にないなら JS未描画 → None を返す
        _cap_check = {
            "iphone17pro256": "256GB",
            "iphone17pro512": "512GB",
            "iphone17pm256":  "256GB",
            "iphone17pm512":  "512GB",
        }
        _product_kw_check = {
            "iphone17pro256": "iPhone 17 Pro",
            "iphone17pro512": "iPhone 17 Pro",
            "iphone17pm256":  "iPhone 17 Pro Max",
            "iphone17pm512":  "iPhone 17 Pro Max",
            "ps5_pro":        "PlayStation 5 Pro",
        }
        _required_kw = _product_kw_check.get(product_alias, "")
        _cap_kw = _cap_check.get(product_alias, "")
        if _required_kw and _required_kw not in text:
            # 商品名が本文にない → JS未描画またはページ構造変更
            logger.debug("[モバイル一番] %s: 商品名'%s'が本文にない → None", product_alias, _required_kw)
            return None
        if _cap_kw and _cap_kw not in text:
            # 容量が本文にない（ナビだけに商品名がある場合も弾く）
            logger.debug("[モバイル一番] %s: 容量'%s'が本文にない → None", product_alias, _cap_kw)
            return None

        # ── Step1: メインパターン（確定\n価格 構造に対応）────────────────────────
        # ページ構造: ProductName\nsimfree未開封\n新品\nカラー*\n...\n確定\nPRICE円
        pat = PRICE_PATTERNS.get(product_alias)
        if pat:
            m = re.search(pat, text, re.DOTALL)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 50000 <= price <= 5_000_000:  # 最低5万円（誤マッチ防止）
                        return price
                except ValueError:
                    pass

        # ── Step2: 商品ブロック検索 → 近傍600文字から価格を抽出 ─────────────────
        anchor_info = PRODUCT_ANCHORS.get(product_alias)
        if anchor_info:
            model_kw, cap_kw = anchor_info
            # 商品名＋容量 を含む正確な行を探す（容量が後続行にある前提）
            # 例: "iPhone 17 Pro 256GB" の行を直接検索
            _exact_kw = f"{model_kw} {cap_kw}GB" if cap_kw else model_kw
            m_anchor = re.search(re.escape(_exact_kw) if cap_kw else re.escape(model_kw), text)
            if m_anchor:
                start = m_anchor.start()
                block = text[start:start + 600]
                # 「確定\n価格」パターンを優先（ページ構造に合わせる）
                for near_pat in [
                    r'確定\s+([\d,]+)円',
                    r'simfree未開封.*?確定\s+([\d,]+)円',
                    r'([\d]{3},\d{3})円',  # 6桁以上の価格のみ（誤マッチ防止）
                ]:
                    m2 = re.search(near_pat, block, re.DOTALL)
                    if m2:
                        try:
                            price = int(m2.group(1).replace(",", ""))
                            if 50000 <= price <= 5_000_000:  # 最低5万円以上
                                return price
                        except ValueError:
                            pass

        return None  # 商品名マッチなしの全文fallback禁止

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return "https://www.mobile-ichiban.com/"
