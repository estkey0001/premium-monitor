# -*- coding: utf-8 -*-
"""TCG Lottery Hub: 利益の見せ方。定価（公式）と、根拠のある買取（src/tcg/buyback.py）から出した純利益・ROI だけを表示する。

- 定価 = msrp.json の verified の行で、商品 ID が完全一致・TCG が一致・（商品マスタの種別が分かるときは）種別も一致するものだけ。
- 純利益・ROI は、定価（同じ販売単位）・費用の分かる経路・新鮮で同一性確認済みの買取価格がそろったときだけ。無ければ None（「算出前」）。数値を作らない。
- 点数や優先度を利益に見せない。利益の並び替えは提供しない。
"""
from __future__ import annotations

from typing import Optional

PENDING_LABEL = "算出前"
PENDING_REASON = "買取の根拠が無いため算出していません"


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
        if r.get("carried_over"):                                # 公式の API から消えた商品の古い定価は、利益の根拠にしない
            continue
        hits.append(r)
    if len(hits) != 1:                                           # 0 件も、複数ヒット（曖昧）も採用しない
        return None
    r = hits[0]
    return {"retail_price": r["retail_price"], "price_text": str(r.get("price_text") or ""),
            "checked_at": r.get("checked_at") or None, "official_url": r.get("official_url") or None}


def profit_view(msrp: Optional[dict], calc: Optional[dict] = None) -> dict:
    """商品の利益欄。定価は出せるときだけ。純利益・ROI は src/tcg/buyback.profit_for が PROFITABLE / NO_PROFIT を返したときだけ入れる。
    それ以外は None（算出前）。数値を作らない。"""
    if isinstance(calc, dict) and calc.get("status") in ("PROFITABLE", "NO_PROFIT") and isinstance(calc.get("net_profit"), int):
        return {"msrp": msrp, "net_profit": calc["net_profit"], "roi_pct": calc["roi_pct"],
                "label": f'{calc["net_profit"]:+,}円', "reason": calc.get("route_note") or "", "status": calc["status"],
                "sell_price": calc["sell_price"], "sell_shop": calc["sell_shop"], "acquisition_cost": calc["acquisition_cost"],
                "route": calc.get("route"), "single_source": bool(calc.get("single_source"))}
    reason = (calc or {}).get("reason") or PENDING_REASON
    return {"msrp": msrp, "net_profit": None, "roi_pct": None, "label": PENDING_LABEL, "reason": reason,
            "status": "NOT_CALCULATED"}
