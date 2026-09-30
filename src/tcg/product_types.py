# -*- coding: utf-8 -*-
"""Task5: ポケモンカード商品種別の分類 / Task18: 価格の区別。

公式商品 API の productType（拡張パック / 構築デッキ / その他の商品 / 周辺グッズ）
と商品名から種別を決める。判定できないものは OTHER（推測で BOX にしない）。

価格について:
  - 拡張パック系の「希望小売価格」は 1パック の価格。
    BOX 価格を「パック価格 × 入数」で自動算出しない（入数は公式に明示されない限り不明）。
  - パック以外の商品（スターターセット、プレミアム BOX 等）の希望小売価格は
    その商品1個の価格として扱う。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from .models import JST

# ── 種別 ────────────────────────────────────────────────────────────────
PT_BOOSTER_BOX = "BOOSTER_BOX"              # 拡張パック（パック / BOX で流通）
PT_ENHANCED_BOOSTER = "ENHANCED_BOOSTER"    # 強化拡張パック
PT_SPECIAL_SET = "SPECIAL_SET"              # ハイクラスパック / デラックス / カードセット等
PT_STARTER_DECK = "STARTER_DECK"            # スターターセット / スタートデッキ
PT_CONSTRUCTED_DECK = "CONSTRUCTED_DECK"    # 構築デッキ（プレミアムデッキセット等）
PT_PREMIUM_COLLECTION = "PREMIUM_COLLECTION"  # プレミアム BOX / コレクション系
PT_ACCESSORY = "ACCESSORY"                  # 周辺グッズ（スリーブ・デッキケース等）
PT_PROMO = "PROMO"                          # プロモカード
PT_OTHER = "OTHER"

PRODUCT_TYPES: tuple[str, ...] = (
    PT_BOOSTER_BOX, PT_ENHANCED_BOOSTER, PT_SPECIAL_SET, PT_STARTER_DECK,
    PT_CONSTRUCTED_DECK, PT_PREMIUM_COLLECTION, PT_ACCESSORY, PT_PROMO, PT_OTHER,
)

# BOX Opportunity（プレミア・BUY NOW）の対象にしてよい種別
BOX_OPPORTUNITY_TYPES: frozenset[str] = frozenset({
    PT_BOOSTER_BOX, PT_ENHANCED_BOOSTER, PT_SPECIAL_SET, PT_PREMIUM_COLLECTION,
})

# 希望小売価格が「1パックの価格」である種別
PACK_PRICED_TYPES: frozenset[str] = frozenset({
    PT_BOOSTER_BOX, PT_ENHANCED_BOOSTER,
})

# 公式 API の productType
API_TYPE_EXPANSION = "拡張パック"
API_TYPE_CONSTRUCTION = "構築デッキ"
API_TYPE_OTHERS = "その他の商品"
API_TYPE_PERIPHERAL = "周辺グッズ"

_ACCESSORY_WORDS = ("スリーブ", "デッキシールド", "デッキケース", "プレイマット",
                    "ダメカン", "コイン", "マーカー", "ストレージ", "バインダー",
                    "カードファイル", "ローダー", "ホルダー", "ショッピングバッグ",
                    "フィギュア")


def classify_pokemon_product_type(api_type: str, title: str) -> str:
    """公式 API の productType と商品名から種別を決める。"""
    t = title or ""
    at = (api_type or "").strip()

    if at == API_TYPE_PERIPHERAL:
        return PT_ACCESSORY
    if "プロモ" in t and "パック" not in t:
        return PT_PROMO

    if at == API_TYPE_EXPANSION:
        if "強化拡張パック" in t:
            return PT_ENHANCED_BOOSTER
        if "ハイクラスパック" in t or "デラックス" in t:
            return PT_SPECIAL_SET
        return PT_BOOSTER_BOX

    if at == API_TYPE_CONSTRUCTION:
        if "スターター" in t or "スタートデッキ" in t:
            return PT_STARTER_DECK
        return PT_CONSTRUCTED_DECK

    if at == API_TYPE_OTHERS:
        if any(w in t for w in _ACCESSORY_WORDS):
            # 「その他の商品」でもフィギュア等は TCG の販売監視対象ではない
            return PT_OTHER if "フィギュア" in t else PT_ACCESSORY
        if "カードセット" in t or "スペシャルセット" in t:
            return PT_SPECIAL_SET
        if re.search(r"BOX|ボックス|コレクション|プレミアム", t):
            return PT_PREMIUM_COLLECTION
        return PT_OTHER

    return PT_OTHER


def is_box_opportunity_eligible(product_type: str) -> bool:
    """BOX Opportunity（プレミア計算・BUY NOW）の対象か。アクセサリーは対象外。"""
    return product_type in BOX_OPPORTUNITY_TYPES


# ── 価格 ────────────────────────────────────────────────────────────────
_YEN_RE = re.compile(r"([0-9][0-9,]*)\s*円")


def parse_yen(text: str) -> Optional[int]:
    """「1,800円（税込）」→ 1800。読めなければ None。"""
    m = _YEN_RE.search(text or "")
    if not m:
        return None
    try:
        v = int(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if 0 < v < 10_000_000 else None


def is_pack_priced(product_type: str, api_type: str = "") -> bool:
    """希望小売価格が「1パックの価格」か。

    公式 API の productType が「拡張パック」のものは、ハイクラスパックや
    拡張パックデラックスも含めてすべて1パック単位の価格で掲載されている。
    """
    return product_type in PACK_PRICED_TYPES or (api_type or "").strip() == API_TYPE_EXPANSION


def split_prices(product_type: str, price_text: str, api_type: str = "") -> dict:
    """希望小売価格を「パック価格」と「商品単価」に振り分ける。

    - 拡張パック系: pack_price にだけ入れる（BOX 定価は不明 = None）
    - それ以外    : retail_price（その商品1個の希望小売価格）に入れる
    パック価格 × 入数 で BOX 価格を作ることはしない。
    """
    yen = parse_yen(price_text)
    out = {"pack_price": None, "retail_price": None,
           "retail_price_basis": None, "price_text": price_text or None}
    if yen is None:
        return out
    if is_pack_priced(product_type, api_type):
        out["pack_price"] = yen
        out["retail_price_basis"] = "pack"
    else:
        out["retail_price"] = yen
        out["retail_price_basis"] = "product_unit"
    return out


# ── 日付 ────────────────────────────────────────────────────────────────
_JP_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def parse_release_date(text: str) -> Optional[str]:
    """「2026年 7月31日（金）」→ ISO8601（JST 00:00）。読めなければ None。

    時刻は公式に記載されていないため 00:00 とし、販売開始時刻を推測しない。
    """
    m = _JP_DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        tzinfo=JST).isoformat()
    except ValueError:
        return None


_PACK_CONTENT_RE = re.compile(r"(?:カード|キラカード)\s*(\d+)\s*枚入り")
_PACKS_PER_BOX_RE = re.compile(r"(\d+)\s*パック入り")


def parse_contents(text: str) -> dict:
    """「内容物」の記述から、明示されている数量だけを抜き出す。"""
    t = text or ""
    cards = _PACK_CONTENT_RE.search(t)
    packs = _PACKS_PER_BOX_RE.search(t)
    return {
        "cards_per_pack": int(cards.group(1)) if cards else None,
        # 「30パック入り」のような明示がある場合だけ。無ければ None（推測しない）
        "packs_per_box": int(packs.group(1)) if packs else None,
    }
