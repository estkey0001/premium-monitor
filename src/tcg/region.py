# -*- coding: utf-8 -*-
"""都道府県 → 地方ブロックの対応と、Task26 の表示順制御。

位置情報は推測しない。ユーザー設定 region のみを使い、未設定なら全国表示。
"""
from __future__ import annotations

from typing import Optional

REGION_OF_PREFECTURE: dict[str, str] = {}
_BLOCKS: dict[str, tuple[str, ...]] = {
    "HOKKAIDO": ("北海道",),
    "TOHOKU": ("青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"),
    "KANTO": ("茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"),
    "CHUBU": ("新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
              "岐阜県", "静岡県", "愛知県"),
    "KANSAI": ("三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"),
    "CHUGOKU": ("鳥取県", "島根県", "岡山県", "広島県", "山口県"),
    "SHIKOKU": ("徳島県", "香川県", "愛媛県", "高知県"),
    "KYUSHU": ("福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県",
               "鹿児島県", "沖縄県"),
}
for _blk, _prefs in _BLOCKS.items():
    for _p in _prefs:
        REGION_OF_PREFECTURE[_p] = _blk

REGION_LABELS: dict[str, str] = {
    "HOKKAIDO": "北海道", "TOHOKU": "東北", "KANTO": "関東", "CHUBU": "中部",
    "KANSAI": "関西", "CHUGOKU": "中国", "SHIKOKU": "四国", "KYUSHU": "九州",
}


def region_of(prefecture: Optional[str]) -> Optional[str]:
    """都道府県名から地方ブロックを返す。不明は None（推測しない）。"""
    if not prefecture:
        return None
    p = prefecture.strip()
    if p in REGION_OF_PREFECTURE:
        return REGION_OF_PREFECTURE[p]
    for full, blk in REGION_OF_PREFECTURE.items():
        if full.rstrip("都道府県") and p.startswith(full.rstrip("都道府県")):
            return blk
    return None


def display_rank(event: dict, user_prefecture: Optional[str] = None,
                 user_region: Optional[str] = None) -> int:
    """Task26: 表示順のランク（小さいほど先）。

    ユーザー設定が無ければ全件同順（全国表示）。位置情報は推測しない。
    """
    if not user_prefecture and not user_region:
        return 0
    pref = event.get("prefecture")
    if user_prefecture and pref and pref.startswith(user_prefecture.rstrip("都道府県")):
        return 0
    ev_region = region_of(pref)
    target_region = user_region or region_of(user_prefecture)
    if target_region and ev_region == target_region:
        return 1
    return 2


def sort_for_display(events: list[dict], user_prefecture: Optional[str] = None,
                     user_region: Optional[str] = None) -> list[dict]:
    """地域優先で並べ替える（安定ソート）。"""
    return sorted(events, key=lambda e: display_rank(e, user_prefecture, user_region))
