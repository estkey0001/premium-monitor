"""新UIのジャンル（カテゴリ）。

ジャンルは独立したタブではなく、HOME と各一覧の絞り込み（URL の category=）として使う。
既存データのジャンル名（products.genre・TCG の種類・旧来の抽選のブランド）を、ここだけで6ジャンルに読み替える。
"""

from __future__ import annotations

from dataclasses import dataclass

ALL = "all"


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    icon: str      # icons.py の名前


CATEGORIES: tuple[Category, ...] = (
    Category("smartphone", "スマホ", "smartphone"),
    Category("tcg", "TCG", "cards"),
    Category("camera", "カメラ", "camera"),
    Category("game", "ゲーム", "gamepad"),
    Category("pc", "PC", "laptop"),
    Category("other", "その他", "box"),
)
KEYS: tuple[str, ...] = tuple(c.key for c in CATEGORIES)
LABELS: dict[str, str] = {c.key: c.label for c in CATEGORIES}

# products.genre（config/products.yaml）→ ジャンル
_GENRE_MAP = {
    "iphone": "smartphone", "smartphone": "smartphone",
    "camera": "camera",
    "game_console": "game", "game": "game",
    "pc": "pc",
    # タブレット・ウェアラブル・オーディオは「その他」
    "tablet": "other", "wearable": "other", "audio": "other",
    "tcg": "tcg",
}

# ジャンルが分からない旧来の抽選（ブランド・商品名だけ）を読み替える語
_TEXT_HINTS = (
    ("game", ("playstation", "ps5", "nintendo", "switch", "xbox", "任天堂", "プレイステーション")),
    ("camera", ("fujifilm", "富士フイルム", "ricoh", "リコー", "canon", "キヤノン", "nikon", "ニコン",
                "leica", "ライカ", "hasselblad", "panasonic lumix", "sony α", "x100", "gr iv", "gr iii")),
    ("smartphone", ("iphone", "pixel", "galaxy")),
    ("pc", ("macbook", "mac mini", "imac", "ノートpc", "laptop")),
    ("tcg", ("ポケモンカード", "ポケカ", "ワンピースカード", "遊戯王", "pokemon card", "one piece card")),
)


def from_genre(genre) -> str:
    """products.genre などのジャンル名 → 6ジャンルのキー。分からなければ「その他」。"""
    return _GENRE_MAP.get(str(genre or "").strip().lower(), "other")


def from_text(*texts) -> str:
    """ブランド・商品名からジャンルを推定する（ジャンルの記録が無い旧来の抽選だけに使う）。"""
    blob = " ".join(str(t or "") for t in texts).lower()
    for key, words in _TEXT_HINTS:
        if any(w in blob for w in words):
            return key
    return "other"


def valid(key) -> str:
    """URL の category= の値を検証する（知らない値は「すべて」）。"""
    k = str(key or "").strip().lower()
    return k if k in KEYS else ALL
