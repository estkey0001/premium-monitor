"""CanonOfficialCollector — 公式ストア Collector（汎用SSR戦略）。

canon 公式ストアの公式定価を JSON-LD / meta / 価格パターンから取得する。
サイト固有セレクタに依存せず graceful degradation する（GenericOfficialCollector 継承）。
"""
from src.collectors.official._generic import GenericOfficialCollector


class CanonOfficialCollector(GenericOfficialCollector):
    LABEL = "canon_official"
    PRICE_MIN = 80000
    PRICE_MAX = 1500000
