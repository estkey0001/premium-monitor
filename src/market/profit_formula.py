"""公式で定価で買って買取店に売る案件（RETAIL_TO_BUYBACK）の利益の式（正本）。

案件のスキャナー（beginner_deal_scanner）・候補の優先順位（discovery.priority）・順位レポート
（scripts/generate_ranking_report.py）が、同じ式を使う（費用を別々の固定値で持たない。順位レポートだけ 1,300 円で
500 円ずれていた。Production Integrity 監査 M-2）。

    純利益 = 買取の価格 − 公式の価格 − 費用
    費用   = 買取店への発送 + 振込手数料 + 移動・持ち込み + 保険 + クレカ手数料 + 購入送料（公式の一次情報で確認したもの）

購入送料が分からない購入元は、確定の利益にしない（0 円とみなさない）。`beginner_costs` は None を返す。
スキャナーは従来どおり「分からなければ 0 を足し、確定の判定で外す」ので、shipping_unknown_as_zero=True で呼ぶ。
"""
from __future__ import annotations

from src.market import official_shipping
from src.models.beginner_deal import DEFAULT_COSTS

# クレカ手数料率: 公式・量販店ともポイント考慮で 0 とみなす（スキャナーが従来から強制している値。DEFAULT_COSTS の既定も 0）
CC_FEE_RATE = 0.0
FIXED_COST_KEYS = ("shipping_jpy", "transfer_fee_jpy", "transport_jpy", "insurance_jpy")


def fixed_costs() -> int:
    """購入元に依らない費用（買取店への発送・振込手数料・移動・保険）。"""
    return sum(int(DEFAULT_COSTS[k]) for k in FIXED_COST_KEYS)


def beginner_costs(product_id: str, official_url: str, official_price, *,
                   shipping_unknown_as_zero: bool = False) -> int | None:
    """公式で買って買取店に売るときの費用の合計。購入送料が分からなければ None（as_zero なら 0 を足す）。"""
    try:
        price = int(official_price or 0)
    except (TypeError, ValueError):
        price = 0
    fee = official_shipping.purchase_shipping(product_id, official_url, price)["fee"]
    if fee is None:
        if not shipping_unknown_as_zero:
            return None
        fee = 0
    return fixed_costs() + int(fee) + int(price * CC_FEE_RATE)


def net_profit(official_price, sell_price, costs) -> int:
    """純利益（円）。"""
    return int(sell_price) - int(official_price) - int(costs)
