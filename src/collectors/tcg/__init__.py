# -*- coding: utf-8 -*-
"""TCG 販売情報コレクター群。"""
from .base import BaseTcgCollector
from .keyword_page import KeywordPageCollector, slugify
from .lawson import LawsonPokemonDiscoveryCollector
from .onepiece import (
    OnePieceOfficialCollector, OnePieceProductsCollector, PremiumBandaiCollector,
)
from .pokemon import (
    LawsonPokemonCollector, PokemonCardOfficialCollector,
    PokemonCenterOnlineCollector, PokemonProductsCollector,
)
from .pokemon_news import PokemonNewsCollector
from .pokemon_products import PokemonProductRegistryCollector

# Task23: 実 source から取得するコレクター（fixture ではない）
#
# ポケモン公式は次の2本で監視する:
#   - PokemonProductRegistryCollector: 公式商品 API（商品単位・発売日・価格）
#   - PokemonNewsCollector           : 公式ニュース（公式カテゴリで大会記事を除外）
# 以前使っていた PokemonProductsCollector（カテゴリトップ /products/index.html を
# Playwright で解析）は、カテゴリ紹介文しか無いページのため監視対象から外した。
# PokemonCardOfficialCollector / LawsonPokemonCollector は解析ロジック（parse）として
# 引き続き使うが、巡回は PokemonNewsCollector / LawsonPokemonDiscoveryCollector が行う。
ALL_COLLECTORS = (
    PokemonProductRegistryCollector,
    PokemonNewsCollector,
    PokemonCenterOnlineCollector,
    LawsonPokemonDiscoveryCollector,
    OnePieceOfficialCollector,
    OnePieceProductsCollector,
    PremiumBandaiCollector,
)

# ファネルで「商品ページの発見」を必須とするポケモン系コレクター
POKEMON_COLLECTORS = (
    PokemonProductRegistryCollector,
    PokemonNewsCollector,
    PokemonCenterOnlineCollector,
    LawsonPokemonDiscoveryCollector,
)

__all__ = [
    "BaseTcgCollector", "KeywordPageCollector", "slugify", "ALL_COLLECTORS",
    "POKEMON_COLLECTORS",
    "PokemonCenterOnlineCollector", "PokemonCardOfficialCollector",
    "PokemonProductsCollector", "PokemonProductRegistryCollector",
    "PokemonNewsCollector", "LawsonPokemonCollector",
    "LawsonPokemonDiscoveryCollector", "OnePieceOfficialCollector",
    "OnePieceProductsCollector", "PremiumBandaiCollector",
]
