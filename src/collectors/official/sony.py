"""SonyOfficialCollector — 公式ストア Collector（汎用SSR戦略）。

sony 公式ストアの公式定価を JSON-LD / meta / 価格パターンから取得する。
サイト固有セレクタに依存せず graceful degradation する（GenericOfficialCollector 継承）。
"""
from src.collectors.official._generic import GenericOfficialCollector


class SonyOfficialCollector(GenericOfficialCollector):
    LABEL = "sony_official"
    PRICE_MIN = 30000
    PRICE_MAX = 1500000
