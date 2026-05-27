"""ネットオフ 買取価格コレクター。
URL: https://www.netoff.co.jp/mobilebuy/
取得方式: requests（静的HTML）
スマホ買取価格一覧ページから取得。

2026-05-27 調査結果:
  - /sell/?keyword=... は一般売却ページでスマホ買取価格なし（価格はJS動的ロード）
  - /mobilebuy/ に iPhone 17 シリーズの価格一覧が静的HTML で掲載されている
  価格形式: "256GB 上限 159,600 円買取" (256GB + 上限 + 数字 + 円)
  iPhone 17 Pro (non-Max) は "iPhone 17 Pro 1TB" マーカーで開始するブロックに掲載
  iPhone 17 Pro Max は "iPhone 17 Pro Max" マーカーで開始するブロックに掲載
"""
import re
import time
from typing import Optional

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

MOBILEBUY_URL = "https://www.netoff.co.jp/mobilebuy/"

# 各モデルのブロックを特定するマーカー文字列
# （ページ内で先頭から最初に出現するキャプションテキスト）
MODEL_MARKERS = {
    "iphone17pro256": ("iPhone 17 Pro 1TB", 256),
    "iphone17pro512": ("iPhone 17 Pro 1TB", 512),
    "iphone17pm256":  ("iPhone 17 Pro Max",  256),
    "iphone17pm512":  ("iPhone 17 Pro Max",  512),
}


def _extract_price_from_block(text: str, model_marker: str, storage_gb: int) -> Optional[int]:
    """ページテキストから指定モデル・容量の買取上限価格を抽出する。

    ページ構造例:
      "iPhone 17 Pro Max 2TB 上限 282,450 円買取 1TB 上限 235,200 円買取
       512GB 上限 204,750 円買取 256GB 上限 173,250 円買取 iPhone Air ..."
    """
    idx = text.find(model_marker)
    if idx == -1:
        return None

    # 次の iPhone / iPad / Galaxy モデルまでのブロックを切り出す
    rest = text[idx + len(model_marker):]
    next_model = re.search(r' iPhone | iPad | Galaxy | Google | AQUOS ', rest)
    block = rest[:next_model.start()] if next_model else rest[:600]

    # "{N}GB 上限 {price} 円" パターン（ページ内のスペース区切り形式）
    m = re.search(rf'{storage_gb}GB\s+上限\s+([\d,]+)\s+円', block)
    if m:
        try:
            price = int(m.group(1).replace(",", ""))
            if 10000 <= price <= 5_000_000:
                return price
        except ValueError:
            pass
    return None


class NetoffCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "netoff"
    SHOP_NAME = "ネットオフ"
    BASE_URL  = "https://www.netoff.co.jp/"
    REQUIRES_JS = False

    # 全製品共通で1回だけページを取得してキャッシュ
    _page_text_cache: Optional[str] = None

    def _build_url(self, product_alias: str, product_name: str) -> str:
        """対象モデルが存在する場合は mobilebuy URL を返す。"""
        return MOBILEBUY_URL if product_alias in MODEL_MARKERS else ""

    def _fetch_html(self, url: str) -> Optional[str]:
        """mobilebuy/ は全モデル共通ページ。取得後キャッシュする。"""
        if NetoffCsvCollector._page_text_cache is not None:
            return NetoffCsvCollector._page_text_cache

        import requests as _req
        time.sleep(1.5)
        try:
            sess = _req.Session()
            sess.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ja,en;q=0.9",
            })
            resp = sess.get(url, timeout=15, allow_redirects=True)
            resp.raise_for_status()
            NetoffCsvCollector._page_text_cache = resp.text
            return resp.text
        except Exception as e:
            self.last_failure_reason = "connection_error"
            return None

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)

        marker_info = MODEL_MARKERS.get(product_alias)
        if not marker_info:
            return None

        model_marker, storage_gb = marker_info
        return _extract_price_from_block(text, model_marker, storage_gb)

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return MOBILEBUY_URL
