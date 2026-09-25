# -*- coding: utf-8 -*-
"""販売文脈フィルタ — 「大会・イベント告知」を「商品の販売情報」と誤認しないための層。

公式サイトのニュース欄には
  「ジムエントリーキャンペーン」「体験会」「チャンピオンズリーグ」
のような、商品の販売とは無関係な "エントリー / 応募" 告知が多数含まれる。
これらを LOTTERY（抽選販売）として取り込むと誤情報になるため、
販売文脈が確認できないブロックは最初から除外する。
"""
from __future__ import annotations

import re

# 販売と無関係な告知（1つでも含まれたら除外）
NON_SALE_TERMS: tuple[str, ...] = (
    "大会", "トーナメント", "チャンピオンズリーグ", "シティリーグ", "ジムイベント",
    "ジムエントリー", "体験会", "入門バトル", "学園祭", "教室", "ポケカジム",
    "プレイヤーズクラブ", "二要素認証", "チャンネル", "デッキ紹介", "対戦",
    "公式大会", "エントリーキャンペーン", "スタンプラリー", "イベント開催",
    "ランキング", "レギュレーション", "アプリ", "新店登場",
)

# 販売文脈を示す語（1つ以上必須）
SALE_TERMS: tuple[str, ...] = (
    "販売", "発売", "予約", "購入", "入荷", "再販", "在庫", "受注",
    "価格", "円", "税込", "抽選販売", "お届け", "カート",
)

# 商品らしさを示す語（1つ以上必須。「ポケモンカード」だけでは不十分）
PRODUCT_TERMS: tuple[str, ...] = (
    "拡張パック", "強化拡張パック", "ハイクラスパック", "スターターセット",
    "スタートデッキ", "プレミアムトレーナーボックス", "トレーナーボックス",
    "ブースターパック", "プレミアムブースター", "BOX", "ボックス", "パック",
    "セット", "デッキ", "バインダー", "カードケース", "スリーブ",
    "OP-", "ST-", "EB-", "PRB", "コレクション",
)

_CODE_RE = re.compile(r"\b(OP|ST|EB|PRB)-?\d{2}\b")


def has_sale_context(block: str) -> bool:
    """販売に関する記述が含まれているか。"""
    return any(w in block for w in SALE_TERMS)


def has_product_context(block: str) -> bool:
    """具体的な商品への言及があるか。"""
    return any(w in block for w in PRODUCT_TERMS) or bool(_CODE_RE.search(block))


def is_non_sale_announcement(block: str) -> bool:
    """大会・イベント等、販売と無関係な告知か。"""
    return any(w in block for w in NON_SALE_TERMS)


def is_sales_block(block: str) -> bool:
    """このブロックを販売イベントとして扱ってよいか。

    判定できない／販売と無関係なものは False（推測でイベント化しない）。
    """
    if not block:
        return False
    if is_non_sale_announcement(block):
        return False
    return has_sale_context(block) and has_product_context(block)


def is_product_lottery(block: str) -> bool:
    """「商品の抽選販売」と確認できるか。

    単なる「エントリー」「応募」は抽選販売の根拠にしない。
    """
    if "抽選販売" in block:
        return True
    if "抽選" not in block:
        return False
    return any(w in block for w in ("販売", "購入", "申込", "受注", "お届け"))
