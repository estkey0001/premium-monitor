"""NikonOfficialCollector — 公式ストア Collector（汎用SSR戦略）。

nikon 公式ストアの公式定価を JSON-LD / meta / 価格パターンから取得する。
サイト固有セレクタに依存せず graceful degradation する（GenericOfficialCollector 継承）。
"""
from src.collectors.official._generic import GenericOfficialCollector


class NikonOfficialCollector(GenericOfficialCollector):
    LABEL = "nikon_official"
    PRICE_MIN = 60000
    PRICE_MAX = 1500000
