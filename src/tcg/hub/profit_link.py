# -*- coding: utf-8 -*-
"""TCG Lottery Hub: 利益の見せ方。定価（公式）だけ表示し、純利益・ROI は根拠が無いので出さない。

- 定価 = msrp.json の verified の行で、商品 ID が完全一致・TCG が一致・（商品マスタの種別が分かるときは）種別も一致するものだけ。
- TCG の買取・二次流通・eBay の実データが無いので、純利益・ROI は常に None（「算出前」）。数値を作らない。
- 点数や優先度を利益に見せない。利益の並び替えは提供しない。
"""
from __future__ import annotations

from typing import Optional

PENDING_LABEL = "算出前"
PENDING_REASON = "買取・二次流通・eBay の根拠が無いため算出していません"


def _price(v) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def msrp_for(product_id, tcg, product_type, msrp_rows) -> Optional[dict]:
    """商品の定価（検証済みの公式価格）。条件を満たす行が無ければ None（推測しない）。"""
    if not isinstance(product_id, str) or not product_id or not isinstance(tcg, str) or not tcg:
        return None
    hits = []
    for r in msrp_rows if isinstance(msrp_rows, list) else []:
        if not isinstance(r, dict) or r.get("product_id") != product_id or r.get("tcg") != tcg:
            continue
        if product_type and r.get("product_type") and r.get("product_type") != product_type:
            continue
        if _price(r.get("retail_price")) is None or r.get("basis") != "product_unit":
            continue
        hits.append(r)
    if len(hits) != 1:                                           # 0 件も、複数ヒット（曖昧）も採用しない
        return None
    r = hits[0]
    return {"retail_price": r["retail_price"], "price_text": str(r.get("price_text") or ""),
            "checked_at": r.get("checked_at") or None, "official_url": r.get("official_url") or None}


def profit_view(msrp: Optional[dict]) -> dict:
    """商品の利益欄。定価は出せるときだけ。純利益・ROI は根拠が無いので None。"""
    return {"msrp": msrp, "net_profit": None, "roi_pct": None,
            "label": PENDING_LABEL, "reason": PENDING_REASON}
