"""
新品・未使用条件フィルタ共通モジュール。

初心者・Pro・ランキング・せどりルート・alerts・reports
すべてで共通して使用する条件定義と判定関数を提供します。
"""
from __future__ import annotations

# ── 許可条件（新品・未使用・未開封）──
UNUSED_CONDITIONS: frozenset[str] = frozenset({
    "new",
    "unused",
    "sealed",
    "brand_new",
    "新品",
    "未使用",
    "未開封",
    "新品未使用",
    "新品未開封",
})

# ── 除外条件（中古・ジャンク・状態不明等）──
USED_EXCLUDE_CONDITIONS: frozenset[str] = frozenset({
    "used",
    "中古",
    "開封済み",
    "ジャンク",
    "訳あり",
    "傷あり",
    "状態不明",
    "動作未確認",
})


def is_unused(condition: str | None) -> bool:
    """商品の状態が新品・未使用・未開封かどうかを判定する。

    Args:
        condition: 状態文字列（例: "新品", "new", "未使用" など）

    Returns:
        True: 新品・未使用として許可
        False: 中古・ジャンク・状態不明として除外
    """
    if not condition:
        # 状態不明は除外
        return False
    cond_lower = condition.strip().lower()
    cond_orig = condition.strip()

    # 除外条件に一致する場合はFalse
    if cond_orig in USED_EXCLUDE_CONDITIONS:
        return False
    if cond_lower in {c.lower() for c in USED_EXCLUDE_CONDITIONS}:
        return False

    # 許可条件に一致する場合はTrue
    if cond_orig in UNUSED_CONDITIONS:
        return True
    if cond_lower in {c.lower() for c in UNUSED_CONDITIONS}:
        return True

    # どちらにも該当しない場合は除外（不明は除外）
    return False


def is_used(condition: str | None) -> bool:
    """商品の状態が中古・使用済みかどうかを判定する。"""
    return not is_unused(condition)


def filter_unused(items: list, condition_field: str = "buy_condition") -> list:
    """リストから新品・未使用アイテムのみを返す。

    Args:
        items: フィルタ対象のリスト（dict または object）
        condition_field: 状態を示すフィールド名（デフォルト: "buy_condition"）

    Returns:
        新品・未使用のみのリスト
    """
    result = []
    for item in items:
        if isinstance(item, dict):
            cond = item.get(condition_field, "")
        else:
            cond = getattr(item, condition_field, "")
        if is_unused(cond):
            result.append(item)
    return result
