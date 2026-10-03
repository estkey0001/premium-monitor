"""公式の在庫表示の意味（新UI・旧UI・案件スキャナーで同じ規則を使う）。

在庫ありと言ってよいのは、在庫の表示（「在庫あり」など）が明示されているときだけ。
空・知らない表示・価格だけ取れた、は在庫不明（UNKNOWN）。予約・抽選は在庫ありにしない。
"""

from __future__ import annotations

OUT_OF_STOCK_MARKS = ("SOLD OUT", "OUT OF STOCK", "NOT IN STOCK", "在庫切れ", "在庫なし", "入荷待ち", "品切れ",
                      "売り切れ", "販売終了")
IN_STOCK_MARKS = ("在庫あり", "IN STOCK")


def stock_state(stock_status: str, sale_method: str = "") -> str:
    """IN_STOCK / OUT_OF_STOCK / UNKNOWN / RESERVATION / LOTTERY。"""
    sm = str(sale_method or "").lower()
    if sm in ("lottery", "抽選"):
        return "LOTTERY"
    if sm in ("reservation", "preorder", "予約"):
        return "RESERVATION"
    s = str(stock_status or "").strip().upper()
    if not s:
        return "UNKNOWN"
    if any(k in s for k in OUT_OF_STOCK_MARKS):
        return "OUT_OF_STOCK"
    if any(k in s for k in IN_STOCK_MARKS):
        return "IN_STOCK"
    return "UNKNOWN"


def sale_method_of(product) -> str:
    """商品の販売方式（lottery / discontinued / soldout / normal）。案件スキャナーで共通に使う。"""
    if getattr(product, "is_lottery", False):
        return "lottery"
    if getattr(product, "is_discontinued", False):
        return "discontinued"
    if is_out_of_stock(getattr(product, "official_stock_status", "") or ""):
        return "soldout"
    return "normal"


def is_explicit_in_stock(stock_status: str) -> bool:
    """在庫ありが明示されているか（不明は False）。"""
    return stock_state(stock_status) == "IN_STOCK"


def is_out_of_stock(stock_status: str) -> bool:
    return stock_state(stock_status) == "OUT_OF_STOCK"
