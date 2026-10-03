"""公式の在庫表示の意味（新UI・旧UI・案件スキャナーで同じ規則を使う）。

在庫ありと言ってよいのは、在庫の表示（「在庫あり」など）が明示されているときだけ。
空・知らない表示・価格だけ取れた、は在庫不明（UNKNOWN）。予約・抽選は在庫ありにしない。
"""

from __future__ import annotations

OUT_OF_STOCK_MARKS = ("SOLD OUT", "OUT OF STOCK", "NOT IN STOCK", "在庫切れ", "在庫なし", "在庫ありません",
                      "在庫がありません", "入荷待ち", "品切れ", "売り切れ", "販売終了")
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


# ── 在庫再開（UI Phase 4）: 状態の正本と、在庫の鮮度 ─────────────────────────────
# 在庫の状態（1か所で定義）。true / false の2値にしない（品切れ・未確認・取得失敗を区別する）
IN_STOCK, OUT_OF_STOCK, UNKNOWN = "IN_STOCK", "OUT_OF_STOCK", "UNKNOWN"
RESERVATION, LOTTERY, PREORDER, RELEASE_WAIT = "RESERVATION", "LOTTERY", "PREORDER", "RELEASE_WAIT"
STOCK_STATES = (IN_STOCK, OUT_OF_STOCK, UNKNOWN, RESERVATION, LOTTERY, PREORDER, RELEASE_WAIT)
DEFINITE_STATES = (IN_STOCK, OUT_OF_STOCK)          # 在庫の有無が分かっている状態（再入荷の判定に使う）

# ユーザー向けの文言（色だけで伝えない）
STATE_LABELS = {IN_STOCK: "購入可能", OUT_OF_STOCK: "在庫切れ", UNKNOWN: "在庫未確認",
                RESERVATION: "予約受付", PREORDER: "予約受付", LOTTERY: "抽選", RELEASE_WAIT: "発売待ち"}
STALE_LABEL = "在庫未確認（更新待ち）"   # 在庫ありだったが、確認から時間が経って今も在庫があるか分からない

# 在庫の表示を「購入可能」と言ってよい時間（最後に在庫ありを確認してから）。
# 価格の鮮度（14日）や公式定価の確認（180日）とは別。在庫は数時間で変わるので短くする。
# - 公式ストア・量販店の EC: 3時間（取得は日次。それを超えた在庫ありは「更新待ち」にする）
# - 人が公式ページで確認した在庫: 3時間
# - TCG の入荷情報: 既存の TTL（src/tcg/freshness.TTL_SECONDS。EC 在庫復活 15分・店頭 2時間 など）。
#   TTL の無い種類は 2時間
STOCK_FRESH_SECONDS = {"official_store": 3 * 3600, "manual_verified": 3 * 3600, "retail_ec": 3 * 3600}
TCG_DEFAULT_FRESH_SECONDS = 2 * 3600


def freshness_seconds(source_type: str, event_type: str = "") -> int:
    """在庫ありの観測を「購入可能」と言ってよい秒数。"""
    if source_type == "tcg_event":
        from src.tcg.freshness import TTL_SECONDS
        return int(TTL_SECONDS.get(event_type) or TCG_DEFAULT_FRESH_SECONDS)
    return int(STOCK_FRESH_SECONDS.get(source_type, 3 * 3600))
