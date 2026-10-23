# -*- coding: utf-8 -*-
"""TCG の定価（メーカー希望小売価格）の台帳（Market Research Foundation I1）。

公式の商品 API（pokemon-card.com の resultAPI）で「商品1個の希望小売価格」と明示されたものだけを、商品の同一性
（商品 ID・名前・種類・発売日・公式ページの URL）つきで記録する。

- パックの価格（1パックの値段）から BOX の価格を作らない（パック価格 × 入数の推測はしない）。BOX の定価が公式に
  明示されていない商品は excluded に理由つきで残す
- 価格は取得に成功した日の値。取得に失敗した日は台帳を書き換えない（失敗した時刻を成功として保存しない）
- ここでは利益の計算をしない（TCG の買取・成約・二次流通の実データが無い。I2）。プレミアの計算は既存の
  config/tcg_retail_prices.yaml と公式 API の商品単価（collect_tcg_events.registry_retail_prices）のまま
"""
from __future__ import annotations

SCHEMA = 1
BASIS_UNIT = "product_unit"

EX_PACK_PRICE_ONLY = "PACK_PRICE_ONLY"      # 1パックの価格だけ。BOX の定価は公式に明示されていない
EX_NO_PRICE = "NO_PRICE"
EX_NO_OFFICIAL_URL = "NO_OFFICIAL_URL"


def build_msrp(registry: list[dict], generated_at: str, previous: dict | None = None) -> dict:
    """商品の登録（公式 API 由来）から、同一性つきの定価の台帳と、定価にできなかった商品の理由を作る。

    previous: 前回の台帳。今日の公式 API に載らなかった商品（一部だけ取れた日・掲載が外れた日）は、前回の行を
    そのまま残す（carried_over: true。checked_at は前回の確認の時刻のまま変えない。取れなかった日の時刻を確認として書かない）。
    """
    verified, excluded = [], []
    for rec in registry or []:
        pid = rec.get("product_id")
        if not pid:
            continue
        price = rec.get("retail_price")
        basis = rec.get("retail_price_basis")
        url = rec.get("official_url") or ""
        reason = ""
        if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
            reason = EX_PACK_PRICE_ONLY if basis == "pack" else EX_NO_PRICE
        elif basis != BASIS_UNIT:
            reason = EX_PACK_PRICE_ONLY
        elif not url:
            reason = EX_NO_OFFICIAL_URL
        if reason:
            excluded.append({"product_id": pid, "name": rec.get("name", ""), "tcg": rec.get("tcg", ""), "reason": reason})
            continue
        verified.append({
            "product_id": pid, "name": rec.get("name", ""), "tcg": rec.get("tcg", ""),
            "product_type": rec.get("product_type", ""), "box_opportunity_eligible": bool(rec.get("box_opportunity_eligible")),
            "release_date": rec.get("release_date") or "", "retail_price": price, "price_text": rec.get("price_text") or "",
            "basis": BASIS_UNIT, "source": "official_product_api", "official_url": url,
            "checked_at": generated_at})
    today = {v["product_id"] for v in verified} | {e["product_id"] for e in excluded}
    for old in ((previous or {}).get("verified") or []):
        if isinstance(old, dict) and old.get("product_id") and old["product_id"] not in today and old.get("checked_at"):
            verified.append({**old, "carried_over": True})
    return {"schema": SCHEMA, "generated_at": generated_at,
            "note": "公式の商品 API で商品1個の希望小売価格と明示されたものだけ（パック価格から BOX の価格は作らない）。"
                    "利益の計算には使っていない",
            "verified": verified, "excluded": excluded,
            "counts": {"verified": len(verified), "excluded": len(excluded),
                       "box_eligible": sum(1 for v in verified if v.get("box_opportunity_eligible")),
                       "carried_over": sum(1 for v in verified if v.get("carried_over"))}}
