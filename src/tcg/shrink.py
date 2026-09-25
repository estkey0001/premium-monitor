# -*- coding: utf-8 -*-
"""Task8: シュリンク状態の管理。

最重要: 「BOX販売」=「シュリンク付き」と仮定しない。
ONE PIECE 公式ショップのように BOX 販売でもテープカットする店舗があるため、
販売条件は source ごとに保持し、記載が無ければ UNKNOWN のままにする。
"""
from __future__ import annotations

from typing import Optional

from .models import (
    SHRINK_SEALED, SHRINK_REMOVED, SHRINK_TAPE_CUT, SHRINK_OPENED_BOX,
    SHRINK_PACK_ONLY, SHRINK_UNKNOWN,
)

# 店舗ごとの既知の販売条件（公式に明記されているもののみ）
# 「BOX販売あり」だけでは登録しない。
STORE_SHRINK_POLICY: dict[str, dict] = {
    "ONEPIECE_CARD_OFFICIAL_SHOP": {
        "shrink_status": SHRINK_TAPE_CUT,
        "note": "公式ショップは BOX 販売時にテープカットを行う場合がある（公式記載）",
    },
}

_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # テープカットは「シュリンクあり」より先に判定する
    (SHRINK_TAPE_CUT, ("テープカット", "テープ開封", "tape cut", "テープをカット")),
    (SHRINK_REMOVED, ("シュリンクなし", "シュリンク無し", "シュリンク剥がし",
                      "シュリンク開封", "シュリンク除去", "シュリンクレス")),
    (SHRINK_OPENED_BOX, ("開封済", "開封済み", "中身確認済", "opened box")),
    (SHRINK_SEALED, ("シュリンク付", "シュリンク付き", "未開封シュリンク",
                     "シュリンク有り", "sealed shrink")),
    (SHRINK_PACK_ONLY, ("パック販売", "パックのみ", "ばら売り", "バラ売り", "pack only")),
)


def detect_shrink_status(text: str = "", store_key: str = "") -> str:
    """テキストと店舗ポリシーからシュリンク状態を判定。不明は UNKNOWN。

    テキストの明示記載を店舗ポリシーより優先する。
    """
    raw = text or ""
    low = raw.lower()
    for status, words in _PATTERNS:
        if any((w in raw) or (w.lower() in low) for w in words):
            return status

    policy = STORE_SHRINK_POLICY.get((store_key or "").upper())
    if policy:
        return policy["shrink_status"]
    return SHRINK_UNKNOWN


def shrink_policy_note(store_key: str) -> Optional[str]:
    """店舗固有のシュリンク条件の注意書き。無ければ None。"""
    policy = STORE_SHRINK_POLICY.get((store_key or "").upper())
    return policy["note"] if policy else None


def is_sealed(shrink_status: str) -> Optional[bool]:
    """シュリンク付きか。UNKNOWN は None（False と区別する）。"""
    if shrink_status == SHRINK_SEALED:
        return True
    if shrink_status in (SHRINK_REMOVED, SHRINK_TAPE_CUT, SHRINK_OPENED_BOX):
        return False
    return None


def assume_shrink_from_box(box_available: Optional[bool]) -> str:
    """BOX販売情報からシュリンク状態を推定しようとしても常に UNKNOWN を返す。

    「BOX = シュリンク付き」という仮定を明示的に禁止するためのガード関数。
    """
    return SHRINK_UNKNOWN
