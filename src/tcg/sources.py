# -*- coding: utf-8 -*-
"""Task1: TCG 監視 Source Registry / Task20: Source Priority。

ここは「どこを見るか」の定義のみ。実際の取得は src/collectors/tcg/ が行う。
tcg_type は POKEMON / ONE_PIECE の2種だが、SOURCES への追記だけで拡張できる。
"""
from __future__ import annotations

from .models import (
    SRC_OFFICIAL, SRC_RETAILER_OFFICIAL, SRC_STORE_OFFICIAL,
    SOURCE_PRIORITY, TCG_POKEMON, TCG_ONE_PIECE,
)

# 小売チェーンの正規化キー（コンビニは Task4 で独立監視）
CONVENIENCE_CHAINS: tuple[str, ...] = ("LAWSON", "7-ELEVEN", "FAMILY_MART", "MINISTOP")


def _s(key, name, tcg, url, source_type, category, chain=None, collector=None,
       url_verified=False):
    return {
        "key": key,
        "name": name,
        "tcg": list(tcg),
        "url": url,
        "source_type": source_type,
        "category": category,          # official / retailer / ec / convenience / cardshop
        "store_chain": chain or key,
        "collector": collector,        # 実装済みコレクター名（None は監視登録のみ）
        # url_verified: 実際に HTTP 200 を確認済みか。未確認の URL は
        #   推測 URL を「検証済み」として扱わないため False のままにする。
        "url_verified": url_verified,
        "priority": SOURCE_PRIORITY[source_type],
    }


_BOTH = (TCG_POKEMON, TCG_ONE_PIECE)

SOURCES: list[dict] = [
    # ── Pokemon 公式系 ────────────────────────────────────────────────
    _s("POKEMON_CENTER_ONLINE", "ポケモンセンターオンライン", (TCG_POKEMON,),
       "https://www.pokemoncenter-online.com/", SRC_OFFICIAL, "official",
       collector="pokemon_center", url_verified=True),
    _s("POKEMON_CARD_OFFICIAL", "ポケモンカードゲーム公式", (TCG_POKEMON,),
       "https://www.pokemon-card.com/", SRC_OFFICIAL, "official",
       collector="pokemon_card_official", url_verified=True),
    _s("POKEMON_CENTER_STORE", "ポケモンセンター店舗告知", (TCG_POKEMON,),
       "https://www.pokemon.co.jp/shop/", SRC_OFFICIAL, "official"),

    # ── ONE PIECE 公式系 ──────────────────────────────────────────────
    _s("ONEPIECE_CARD_OFFICIAL", "ONE PIECEカードゲーム公式", (TCG_ONE_PIECE,),
       "https://www.onepiece-cardgame.com/", SRC_OFFICIAL, "official",
       collector="onepiece_official", url_verified=True),
    # 公式ショップ2件は DNS 解決に失敗したため URL 未確定。
    # 推測 URL を「検証済み」として登録しない（url_verified=False のまま）。
    _s("ONEPIECE_CARD_OFFICIAL_SHOP", "ONE PIECEカードゲーム公式ショップ", (TCG_ONE_PIECE,),
       "", SRC_OFFICIAL, "official"),
    _s("BANDAI_CARD_GAMES_SHOP", "BANDAI CARD GAMES公式ショップ", (TCG_ONE_PIECE,),
       "", SRC_OFFICIAL, "official"),
    _s("PREMIUM_BANDAI", "プレミアムバンダイ", (TCG_ONE_PIECE,),
       "https://p-bandai.jp/chara/onepiece/", SRC_OFFICIAL, "official",
       collector="premium_bandai", url_verified=True),
    _s("NAMCO_PARKS", "ナムコパークス", (TCG_ONE_PIECE,),
       "https://namco-parks.com/", SRC_RETAILER_OFFICIAL, "ec"),

    # ── 量販店（両TCG） ───────────────────────────────────────────────
    _s("YODOBASHI", "ヨドバシカメラ", _BOTH, "https://www.yodobashi.com/", SRC_RETAILER_OFFICIAL, "retailer"),
    _s("BICCAMERA", "ビックカメラ", _BOTH, "https://www.biccamera.com/", SRC_RETAILER_OFFICIAL, "retailer"),
    _s("JOSHIN", "Joshin", _BOTH, "https://joshinweb.jp/", SRC_RETAILER_OFFICIAL, "retailer"),
    _s("EDION", "エディオン", _BOTH, "https://www.edion.com/", SRC_RETAILER_OFFICIAL, "retailer"),
    _s("YAMADA", "ヤマダデンキ", _BOTH, "https://www.yamada-denkiweb.com/", SRC_RETAILER_OFFICIAL, "retailer"),
    _s("TOYSRUS", "トイザらス", _BOTH, "https://www.toysrus.co.jp/", SRC_RETAILER_OFFICIAL, "retailer"),
    _s("GEO", "GEO", _BOTH, "https://geo-online.co.jp/", SRC_RETAILER_OFFICIAL, "retailer"),
    _s("TSUTAYA", "TSUTAYA", _BOTH, "https://store-tsutaya.tsite.jp/", SRC_RETAILER_OFFICIAL, "retailer"),

    # ── EC（両TCG） ───────────────────────────────────────────────────
    _s("AMAZON", "Amazon", _BOTH, "https://www.amazon.co.jp/", SRC_RETAILER_OFFICIAL, "ec"),
    _s("RAKUTEN_BOOKS", "楽天ブックス", _BOTH, "https://books.rakuten.co.jp/", SRC_RETAILER_OFFICIAL, "ec"),
    _s("RAKUTEN_ICHIBA", "楽天市場", _BOTH, "https://www.rakuten.co.jp/", SRC_RETAILER_OFFICIAL, "ec"),
    _s("YAHOO_SHOPPING", "Yahoo!ショッピング", _BOTH, "https://shopping.yahoo.co.jp/", SRC_RETAILER_OFFICIAL, "ec"),
    _s("SEVEN_NET", "セブンネットショッピング", _BOTH, "https://7net.omni7.jp/", SRC_RETAILER_OFFICIAL, "ec"),

    # ── コンビニ（Task4: 最重要・独立監視） ───────────────────────────
    _s("LAWSON", "ローソン", _BOTH, "https://www.lawson.co.jp/", SRC_RETAILER_OFFICIAL,
       "convenience", collector="lawson", url_verified=True),
    _s("7-ELEVEN", "セブン-イレブン", _BOTH, "https://www.sej.co.jp/", SRC_RETAILER_OFFICIAL, "convenience"),
    _s("FAMILY_MART", "ファミリーマート", _BOTH, "https://www.family.co.jp/", SRC_RETAILER_OFFICIAL, "convenience"),
    _s("MINISTOP", "ミニストップ", _BOTH, "https://www.ministop.co.jp/", SRC_RETAILER_OFFICIAL, "convenience"),

    # ── カードショップ ────────────────────────────────────────────────
    _s("BOOKOFF", "BOOKOFF", _BOTH, "https://www.bookoff.co.jp/", SRC_RETAILER_OFFICIAL, "cardshop"),
    _s("CARDSHOP_OFFICIAL", "カードショップ公式", _BOTH, "", SRC_STORE_OFFICIAL, "cardshop"),
]

SOURCE_BY_KEY: dict[str, dict] = {s["key"]: s for s in SOURCES}


def sources_for(tcg: str) -> list[dict]:
    """対象TCGの監視 source を優先度順に返す。"""
    return sorted((s for s in SOURCES if tcg in s["tcg"]), key=lambda s: s["priority"])


def convenience_sources(tcg: str | None = None) -> list[dict]:
    """Task4: コンビニ source のみ。"""
    return [s for s in SOURCES
            if s["category"] == "convenience" and (tcg is None or tcg in s["tcg"])]


def verified_sources() -> list[dict]:
    """URL の到達性を実確認済みの source のみ。"""
    return [s for s in SOURCES if s["url_verified"]]


def implemented_sources() -> list[dict]:
    """実コレクターが実装済みの source。"""
    return [s for s in SOURCES if s["collector"]]


def source_type_of(store_key: str, default: str = "UNVERIFIED") -> str:
    """店舗キーから source_type を引く（未登録は default）。"""
    s = SOURCE_BY_KEY.get((store_key or "").upper())
    return s["source_type"] if s else default


def is_higher_priority(a_source_type: str, b_source_type: str) -> bool:
    """Task20: a が b より上位 source なら True（下位は上位を上書きしない）。"""
    return SOURCE_PRIORITY.get(a_source_type, 99) < SOURCE_PRIORITY.get(b_source_type, 99)
