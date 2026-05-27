"""パソコン工房 買取価格コレクター。
URL: https://www.pc-koubou.jp/kaitori/re/
取得方式: なし（商品非対応）

2026-05-27 調査結果:
  - パソコン工房はPC・ゲーミングPC専門の買取店。
  - PS5 Pro / Nintendo Switch 2 は取り扱い対象外（ゲーム機買取はリストにない）。
  - /pc/used/buy/?keyword=... はPC中古商品ページであり買取検索ではない。
  → 全製品 product_not_listed として記録する。
"""
from typing import Optional

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

# パソコン工房が対応する製品なし（ゲーム機・スマホ買取非対応）
SUPPORTED_PRODUCTS: set[str] = set()


class PasakoCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "pasoko"
    SHOP_NAME = "パソコン工房"
    BASE_URL  = "https://www.pc-koubou.jp/"
    REQUIRES_JS = False

    def _build_url(self, product_alias: str, product_name: str) -> str:
        """非対応製品 — 空文字を返す。"""
        return ""

    def fetch(self, product_alias: str, product_name: str, condition: str = "new_unopened_simfree"):
        """URL が空 = 取り扱いなし → product_not_listed として記録。"""
        self.last_failure_reason = "product_not_listed"
        self.last_confidence = "high"
        return None

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        return None

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return fallback_url
