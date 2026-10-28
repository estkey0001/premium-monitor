"""TCG の詳細ページの取得枠の再配分（Coverage Wave 4 Stage O）。

詳細ページは取得元ごとに間隔（同じドメイン 60 秒以上）を空けて取るので、実行全体の取得数に上限（DETAIL_BUDGET_TOTAL）を置く。
取得元ごとの上限（cap）を固定で決めると、小さい取得元が余らせた枠を、読み残しの多い取得元（カードラボ）が使えない。
そこで **取得枠の小さい取得元から先に取り、最後に残りを一番大きい取得元に渡す**。後ろの取得元の最低枠（MIN_QUOTA）は先に確保しておく
（先の取得元が使い切って、後ろの取得元が1件も読めない状態を作らない）。
"""
from __future__ import annotations

DETAIL_BUDGET_TOTAL = 40      # 1 回の実行で読む詳細ページの総数（間隔を守るための上限）
MIN_QUOTA = 4                 # どの取得元にも最低これだけは残す（対象があれば）


def order_by_cap(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """取得枠の小さい順（同じなら ID の順）。最後に一番大きい取得元が、余りを使える。"""
    return sorted(items, key=lambda x: (int(x[1]), x[0]))


def next_allowance(cap: int, left: int, remaining_caps: list[int], min_quota: int = MIN_QUOTA) -> int:
    """次に動く取得元に渡す枠。上限 cap・残り left から、後ろの取得元の最低枠を引いた分まで。"""
    reserved = sum(min(min_quota, int(c)) for c in remaining_caps)
    return max(0, min(int(cap), int(left) - reserved))
