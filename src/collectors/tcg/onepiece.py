# -*- coding: utf-8 -*-
"""ONE PIECEカードゲーム関連コレクター（公式 / 公式ショップ / プレミアムバンダイ）。"""
from __future__ import annotations

from src.tcg.models import TCG_ONE_PIECE, CHANNEL_ONLINE

from .keyword_page import KeywordPageCollector

ONEPIECE_KEYWORDS: tuple[str, ...] = (
    "ONE PIECEカードゲーム", "ワンピースカード", "ブースターパック",
    "スタートデッキ", "プレミアムブースター", "OP-", "ST-", "EB-",
)


class OnePieceOfficialCollector(KeywordPageCollector):
    """ONE PIECEカードゲーム公式サイトのニュース欄。"""

    source_key = "ONEPIECE_CARD_OFFICIAL"
    source_name = "ONE PIECEカードゲーム公式（ニュース）"
    tcg = TCG_ONE_PIECE
    channel = CHANNEL_ONLINE
    urls = (
        "https://www.onepiece-cardgame.com/news/",
    )
    product_keywords = ONEPIECE_KEYWORDS
    block_lines = 3


class OnePieceProductsCollector(KeywordPageCollector):
    """ONE PIECEカードゲーム公式サイトの商品ラインナップ。

    「商品名 / 発売日 / メーカー希望小売価格」が数行に分かれて並ぶため、
    窓を広めに取る。
    """

    source_key = "ONEPIECE_CARD_OFFICIAL"
    source_name = "ONE PIECEカードゲーム公式（商品情報）"
    tcg = TCG_ONE_PIECE
    channel = CHANNEL_ONLINE
    urls = (
        "https://www.onepiece-cardgame.com/products/",
    )
    product_keywords = ONEPIECE_KEYWORDS
    block_lines = 6


# NOTE: ONE PIECE カードゲーム公式ショップ / BANDAI CARD GAMES 公式ショップは
#   2026-09-25 時点で URL を確認できなかった（DNS 解決に失敗）ため、
#   推測 URL でコレクターを実装していない。src/tcg/sources.py には
#   url_verified=False の監視登録だけを残してある。


class PremiumBandaiCollector(KeywordPageCollector):
    """プレミアムバンダイの ONE PIECE カード抽選・受注販売。"""

    source_key = "PREMIUM_BANDAI"
    source_name = "プレミアムバンダイ"
    tcg = TCG_ONE_PIECE
    channel = CHANNEL_ONLINE
    urls = (
        "https://p-bandai.jp/chara/onepiece/",
    )
    product_keywords = ONEPIECE_KEYWORDS
    block_lines = 4
