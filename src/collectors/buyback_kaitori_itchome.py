"""買取一丁目 買取価格コレクター（CSV更新用）。
URL: https://www.1-chome.com/ (トップページの強化買取商品一覧)
実装: Playwright (SPA) + inner_text() + 直接regex
価格形式: 未開封\n¥178,000 (円記号 + カンマ区切り数字)

対応商品:
- iPhone 17 Pro 256/512GB → 確認済み
- iPhone 17 Pro Max 256/512GB → 確認済み
- Nintendo Switch 2 / PS5 Pro → 未掲載 (スキップ)
"""
import logging
import re
import time
from typing import Optional

from src.collectors.buyback_base_csv import HONEST_UA, BaseCsvBuybackCollector

logger = logging.getLogger(__name__)

# トップページに強化買取商品の価格が掲載
PRODUCT_URLS = {
    "iphone17pro256":  "https://www.1-chome.com/",
    "iphone17pro512":  "https://www.1-chome.com/",
    "iphone17pm256":   "https://www.1-chome.com/",
    "iphone17pm512":   "https://www.1-chome.com/",
    "switch2":         "",  # 未掲載 → スキップ
    "ps5_pro":         "",  # 未掲載 → スキップ
}

# 商品特定用の直接正規表現パターン (Playwright inner_text に適用)
# テキスト例: "iPhone 17 Pro 256GB\n\n新品\n\n未開封\n¥178,000\n開封済未使用品\n¥168,000"
# [\s\n]+ で空白/改行の表記揺れ（\xa0 含む）に対応。
# 商品名から「未開封」までは 200 文字以内で、途中に別の商品名（iPhone）を挟まないものに限る
# （未開封の価格が無い商品で、次の商品の未開封の価格を拾わない）。
# Phase 11: 緩いフォールバック（商品名の後の最初の ¥…・ページ全体の最高値）は削除した。
# 未開封以外（開封済未使用品）の価格や別商品の価格を新品の価格として保存しうるため。一致しなければ price_not_found。
PRICE_PATTERNS = {
    "iphone17pro256": r'iPhone 17 Pro 256GB(?:(?!iPhone).){0,200}?未開封[\s\n]+¥([\d,]+)',
    "iphone17pro512": r'iPhone 17 Pro 512GB(?:(?!iPhone).){0,200}?未開封[\s\n]+¥([\d,]+)',
    "iphone17pm256":  r'iPhone 17 Pro Max 256GB(?:(?!iPhone).){0,200}?未開封[\s\n]+¥([\d,]+)',
    "iphone17pm512":  r'iPhone 17 Pro Max 512GB(?:(?!iPhone).){0,200}?未開封[\s\n]+¥([\d,]+)',
}


class KaitoriItchomeCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "kaitori_itchome"
    SHOP_NAME = "買取一丁目"
    BASE_URL  = "https://www.1-chome.com/"
    REQUIRES_JS = True  # SPA のため Playwright 必須

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _fetch_html(self, url: str) -> Optional[str]:
        """SPA のため、常にPlaywrightを使用。inner_text()を返す。

        wait_until="domcontentloaded" を使用（SPA では network-idle は永遠に完了しないため）。
        本文が短すぎる場合は追加で 5 秒待機して再取得（1 回のみ）。
        """
        # 同じドメインの間隔は共通の _polite_fetch が守る（Phase 12）
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[買取一丁目] Playwright not installed")
            self.last_failure_reason = "playwright_not_installed"
            return None

        for attempt in range(2):  # タイムアウト失敗時に1回リトライ
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    try:
                        context = browser.new_context(
                            user_agent=HONEST_UA,
                            locale="ja-JP",
                            extra_http_headers={"Accept-Language": "ja,en;q=0.9"},
                        )
                        page = context.new_page()
                        # SPA は network-idle に到達しないため domcontentloaded で十分
                        _resp = page.goto(url, timeout=45000, wait_until="domcontentloaded")
                        if _resp is not None and _resp.status in (401, 403, 429):
                            # 拒否の応答は本文として扱わない（Phase 12 監査 M5）
                            from src.collectors.polite import status_reason
                            self.last_http_status = _resp.status
                            self.last_failure_reason = status_reason(_resp.status)
                            browser.close()
                            return None

                        # domcontentloaded 後に JS 描画を待つ
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=10000)
                        except Exception:
                            pass  # タイムアウトしても inner_text を試みる

                        # SPA 描画完了まで待機
                        page.wait_for_timeout(5000)
                        text = page.inner_text("body")

                        # 本文が短すぎる場合は追加待機して再取得（1 回）
                        if not text or len(text) < 500:
                            logger.debug(
                                "[買取一丁目] 本文短い (%d chars)、5s 追加待機",
                                len(text) if text else 0,
                            )
                            page.wait_for_timeout(5000)
                            text = page.inner_text("body")

                        self.last_html_length = len(text) if text else 0
                    finally:
                        browser.close()

                    if text and len(text) >= 100:
                        self.last_failure_reason = None
                        return text

                    logger.warning("[買取一丁目] 本文取得失敗 (attempt %d, %d chars)",
                                   attempt + 1, len(text) if text else 0)
                    self.last_failure_reason = "empty_html"
                    if attempt < 1:
                        __import__("src.collectors.polite", fromlist=["polite_wait"]).polite_wait(url, self.SHOP_ID)  # 再試行も同じドメインの間隔をあける

            except Exception as e:
                err_str = str(e)
                logger.warning("[買取一丁目] Playwright error (attempt %d): %s", attempt + 1, e)
                if "Timeout" in type(e).__name__ or "timeout" in err_str.lower():
                    self.last_failure_reason = "timeout"
                else:
                    self.last_failure_reason = "playwright_error"
                if attempt < 1:
                    __import__("src.collectors.polite", fromlist=["polite_wait"]).polite_wait(url, self.SHOP_ID)  # 再試行も同じドメインの間隔をあける
                    continue
                return None

        return None

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        """html は Playwright inner_text() の plain text (BS4 不使用)。"""
        text = html  # inner_text() をそのまま使用

        # 商品名と「未開封」の価格の組だけを使う（フォールバックなし）
        pat = PRICE_PATTERNS.get(product_alias)
        if pat:
            m = re.search(pat, text, re.DOTALL)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass
        self.last_failure_reason = "price_not_found"
        return None

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return "https://www.1-chome.com/"
