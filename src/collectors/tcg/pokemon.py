# -*- coding: utf-8 -*-
"""ポケモンカード関連コレクター（公式 / ポケモンセンターオンライン / ローソン）。"""
from __future__ import annotations

from src.tcg.models import TCG_POKEMON, CHANNEL_ONLINE, CHANNEL_STORE

from .keyword_page import KeywordPageCollector

# ポケモンカードの監視キーワード（拡張パック・BOX・限定セット）
POKEMON_KEYWORDS: tuple[str, ...] = (
    "ポケモンカード", "ポケカ", "拡張パック", "強化拡張パック",
    "スターターセット", "ハイクラスパック", "プレミアムトレーナーボックス",
    "30th", "CELEBRATION", "ポケモンカードゲーム",
)


class PokemonCardOfficialCollector(KeywordPageCollector):
    """ポケモンカードゲーム公式サイトの商品・販売告知。"""

    source_key = "POKEMON_CARD_OFFICIAL"
    source_name = "ポケモンカードゲーム公式"
    tcg = TCG_POKEMON
    channel = CHANNEL_ONLINE
    # NOTE: /products/ は JavaScript で商品一覧を描画するため静的取得では
    #   本文が取れない。ニュース欄（/info/）のみを監視対象にしている。
    urls = (
        "https://www.pokemon-card.com/info/",
    )
    product_keywords = POKEMON_KEYWORDS
    block_lines = 3


class PokemonProductsCollector(KeywordPageCollector):
    """ポケモンカードゲーム公式の商品情報（JavaScript 描画ページ）。

    静的取得では本文が得られないため Playwright で描画してから解析する。
    """

    source_key = "POKEMON_CARD_OFFICIAL"
    source_name = "ポケモンカードゲーム公式（商品情報）"
    tcg = TCG_POKEMON
    channel = CHANNEL_ONLINE
    urls = (
        "https://www.pokemon-card.com/products/index.html",
    )
    product_keywords = POKEMON_KEYWORDS
    block_lines = 6
    requires_js = True


class PokemonCenterOnlineCollector(KeywordPageCollector):
    """ポケモンセンターオンラインの抽選・販売告知。"""

    source_key = "POKEMON_CENTER_ONLINE"
    source_name = "ポケモンセンターオンライン"
    tcg = TCG_POKEMON
    channel = CHANNEL_ONLINE
    urls = (
        "https://www.pokemoncenter-online.com/",
    )
    product_keywords = POKEMON_KEYWORDS
    block_lines = 3


class LawsonPokemonCollector(KeywordPageCollector):
    """ローソン公式のポケモンカード販売告知（Task4: コンビニ独立監視）。"""

    source_key = "LAWSON"
    source_name = "ローソン"
    tcg = TCG_POKEMON
    channel = CHANNEL_STORE
    urls = (
        "https://www.lawson.co.jp/campaign/",
    )
    product_keywords = POKEMON_KEYWORDS
    block_lines = 3
