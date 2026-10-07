"""じゃんぱら 買取価格コレクター（CSV更新用）。
買取価格ページ: https://buy.janpara.co.jp/buy/search/result/
注: www.janpara.co.jp/buy/ は buy.janpara.co.jp へリダイレクトされる。
    JS レンダリング必須。レートリミット (429) が発生しやすいため、
    Playwright + リトライ（バックオフ付き）で対応。

2026-05-27 GitHub Actions での挙動:
    GitHub Actions IP では全リクエストで429が返却される。
    初回スリープを 8s、429 バックオフを 30s/60s に延長して対策。
    それでも継続的に429の場合は rate_limited_429 として記録。
"""
import logging
import re
import time
from typing import Optional

from src.collectors.buyback_base_csv import HONEST_UA, BaseCsvBuybackCollector

logger = logging.getLogger(__name__)

# buy.janpara.co.jp の買取価格検索URL
PRODUCT_URLS = {
    "iphone17pro256":  "https://buy.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+256GB",
    "iphone17pro512":  "https://buy.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+512GB",
    "iphone17pm256":   "https://buy.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+Max+256GB",
    "iphone17pm512":   "https://buy.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+Max+512GB",
    "switch2":         "https://buy.janpara.co.jp/buy/search/result/?KEYWORDS=Nintendo+Switch+2",
    "ps5_pro":         "https://buy.janpara.co.jp/buy/search/result/?KEYWORDS=PS5+Pro",
}


class JanparaCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "janpara"
    SHOP_NAME = "じゃんぱら"
    BASE_URL  = "https://buy.janpara.co.jp/"
    REQUIRES_JS = True  # JS レンダリング必須 + 429 対策

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _fetch_html(self, url: str) -> Optional[str]:
        """Playwright + リトライ（429対策）。inner_text() または page.content() を返す。

        レートリミット対策（Phase 12）:
          - 同じドメインの間隔は共通の _polite_fetch（robots.txt・rate_limit_sec・最低60秒）が守る
          - 429 は再試行しない（rate_limited_429 として記録して終わる。以後の商品は店ごと打ち切られる）
          - 一時的な失敗（タイムアウトなど Playwright の例外）だけ1回再試行する
        """
        # 同じドメインの間隔は共通の _polite_fetch が守る（Phase 12）
        for attempt in range(2):  # 一時的な失敗のときだけ1回再試行
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        user_agent=HONEST_UA,
                        extra_http_headers={
                            "Accept-Language": "ja,en;q=0.9",
                        },
                    )
                    page = context.new_page()
                    resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    status = resp.status if resp else 0

                    # 429 検出: Playwright は例外を投げず status で判定
                    if status in (401, 403, 429):
                        # 拒否の応答は本文として扱わない・再試行しない（Phase 12 再監査 M-A）
                        from src.collectors.polite import status_reason
                        browser.close()
                        self.last_http_status = status
                        self.last_failure_reason = status_reason(status)
                        logger.warning("[じゃんぱら] HTTP %s — 再試行しない", status)
                        return None

                    page.wait_for_timeout(3000)  # JS描画待機
                    # inner_text で plain text (パース処理を軽量化)
                    text = page.inner_text("body")
                    browser.close()
                    self.last_failure_reason = None
                    return text

            except ImportError:
                logger.warning("[じゃんぱら] Playwright not installed")
                self.last_failure_reason = "playwright_not_installed"
                return None
            except Exception as e:
                logger.warning("[じゃんぱら] Playwright error (attempt %d): %s", attempt + 1, e)
                self.last_failure_reason = "playwright_error"
                if attempt < 1:
                    __import__("src.collectors.polite", fromlist=["polite_wait"]).polite_wait(url, self.SHOP_ID)  # 再試行も同じ間隔
                    continue
                return None

        return None

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        """html は Playwright inner_text() の plain text または page.content()。"""
        text = html

        # inner_text で取得した場合の買取価格パターン
        for pat in [
            r'買取上限[^¥￥\d]{0,30}[¥￥]\s*([\d,]{5,})',
            r'買取価格[^¥￥\d]{0,30}[¥￥]\s*([\d,]{5,})',
            r'買取[^¥￥\d]{0,20}[¥￥]\s*([\d,]{5,})',
            # ¥なしで「158,000円」形式の場合
            r'買取[^¥￥\d]{0,30}([\d,]{5,})円',
            # じゃんぱら: 「158,000円」のように価格が独立して表示される場合
            r'([\d]{2,3},\d{3})円',
        ]:
            m = re.search(pat, text)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        return self.extract_price(text)

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        """検索結果ページのURLをそのまま返す（確認リンクとして使用）。"""
        return fallback_url
