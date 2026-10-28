"""買取の取得の別名（alias）→ 正本の商品 ID。

買取の収集（scripts/update_buyback_prices.py）と、その報告（collector_report の suspicious_prices・price_changes など）は
別名（例: iphone17pro256）で商品を指す。正本の商品 ID（例: prod_iphone17pro_256）とは、アンダースコアの有無などで一致しない
ものがあるので、報告を商品に結び付けるときは、この表を使う（`prod_<alias>` と決めつけない）。
公式の価格は official_registry.verified_price_of が唯一の出どころ。ここに価格を持たない。
"""
from __future__ import annotations

ALIAS_PRODUCT_ID: dict[str, str] = {
    "iphone17pro256": "prod_iphone17pro_256", "iphone17pro512": "prod_iphone17pro_512",
    "iphone17pm256": "prod_iphone17pm_256", "iphone17pm512": "prod_iphone17pm_512",
    "switch2": "prod_switch2", "ps5_pro": "prod_ps5_pro",
    "iphone17_256": "prod_iphone17_256", "iphone16pro256": "prod_iphone16pro_256", "airpods_pro3": "prod_airpods_pro3",
    "iphoneair_256": "prod_iphoneair_256", "iphoneduo_256": "prod_iphoneduo_256",
    "x100vi": "prod_x100vi", "z8": "prod_z8", "r5ii": "prod_r5ii",
    "gr4": "prod_gr4", "gr4_hdf": "prod_gr4_hdf", "gr4_mono": "prod_gr4_mono",
}


def product_id_of(alias: str, known_product_ids=None) -> str:
    """別名に対応する正本の商品 ID。表に無ければ、`prod_<alias>` が正本に実在するときだけそれを返す。無ければ空。"""
    alias = str(alias or "")
    pid = ALIAS_PRODUCT_ID.get(alias)
    if pid:
        return pid
    guess = f"prod_{alias}"
    return guess if known_product_ids is not None and guess in known_product_ids else ""
