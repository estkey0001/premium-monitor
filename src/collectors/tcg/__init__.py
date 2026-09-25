# -*- coding: utf-8 -*-
"""TCG 販売情報コレクター群。"""
from .base import BaseTcgCollector
from .keyword_page import KeywordPageCollector, slugify
from .onepiece import (
    OnePieceOfficialCollector, OnePieceProductsCollector, PremiumBandaiCollector,
)
from .pokemon import (
    LawsonPokemonCollector, PokemonCardOfficialCollector,
    PokemonCenterOnlineCollector, PokemonProductsCollector,
)

# Task23: 実 source から取得するコレクター（fixture ではない）
ALL_COLLECTORS = (
    PokemonCenterOnlineCollector,
    PokemonCardOfficialCollector,
    PokemonProductsCollector,
    LawsonPokemonCollector,
    OnePieceOfficialCollector,
    OnePieceProductsCollector,
    PremiumBandaiCollector,
)

__all__ = [
    "BaseTcgCollector", "KeywordPageCollector", "slugify", "ALL_COLLECTORS",
    "PokemonCenterOnlineCollector", "PokemonCardOfficialCollector",
    "PokemonProductsCollector",
    "LawsonPokemonCollector", "OnePieceOfficialCollector",
    "OnePieceProductsCollector", "PremiumBandaiCollector",
]
