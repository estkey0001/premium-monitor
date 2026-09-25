# -*- coding: utf-8 -*-
"""Task3: 販売方式の厳格分類 / Task5: 公式とSNSの分離 / Task22: 誤情報保護。

抽選・予約・先着・コンビニ販売を絶対に混同しない。
判定できないものは None を返し、呼び出し側が推測で埋めないようにする。
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from .models import (
    EVENT_LOTTERY, EVENT_PREORDER, EVENT_FIRST_COME, EVENT_CONVENIENCE_STORE,
    EVENT_RESTOCK, EVENT_GUERRILLA_SALE, EVENT_ONLINE_RESTOCK,
    EVENT_RESERVATION_REOPEN, EVENT_GENERAL_SALE, SRC_OFFICIAL, SRC_RETAILER_OFFICIAL, SRC_STORE_OFFICIAL,
    SRC_COMMUNITY_REPORT, SRC_SOCIAL_REPORT, SRC_UNVERIFIED,
    OFFICIAL_SOURCE_TYPES, CONF_HIGH, CONF_MEDIUM, CONF_LOW,
    VERIFY_CONFIRMED, VERIFY_LIKELY, VERIFY_REPORTED, VERIFY_UNVERIFIED,
    CHANNEL_ONLINE,
)
from .sources import SOURCES, CONVENIENCE_CHAINS

# ── 販売方式キーワード（上から順に優先度が高い） ─────────────────────────
_RULES: list[tuple[str, tuple[str, ...]]] = [
    # 予約キャンセル分の再開（「再販」より先に判定する）
    (EVENT_RESERVATION_REOPEN, ("キャンセル分", "予約再開", "予約受付を再開", "キャンセル発生分")),
    # 抽選（応募 → 当落 → 購入 のフロー）
    (EVENT_LOTTERY, ("抽選", "応募", "エントリー", "当選", "抽選販売", "lottery")),
    # 予約
    (EVENT_PREORDER, ("予約受付", "予約開始", "事前予約", "ご予約", "preorder", "pre-order")),
    # EC在庫復活
    (EVENT_ONLINE_RESTOCK, ("在庫復活", "オンライン再入荷", "カート復活", "販売再開（オンライン）")),
    # 再入荷・再販
    (EVENT_RESTOCK, ("再入荷", "再販", "入荷しました", "入荷情報", "restock")),
    # 時間非公開の突発販売
    (EVENT_GUERRILLA_SALE, ("ゲリラ", "突発販売", "неожид", "時間未定で販売")),
    # 店頭先着
    (EVENT_FIRST_COME, ("先着", "店頭販売", "並び", "開店同時", "数量限定販売", "first come")),
    # 通常販売
    (EVENT_GENERAL_SALE, ("発売日", "通常販売", "発売中", "販売中")),
]

_CONVENIENCE_WORDS = ("ローソン", "セブン", "ファミリーマート", "ファミマ", "ミニストップ",
                      "コンビニ", "lawson", "seven", "familymart", "ministop")

# ── 公式ドメイン（Task5: 公式とSNSを同一信頼度にしない） ────────────────
_OFFICIAL_DOMAINS: tuple[str, ...] = (
    "pokemon-card.com", "pokemoncenter-online.com", "pokemon.co.jp",
    "onepiece-cardgame.com", "onepiece-cardgame-officialshop.com",
    "bandai-cardgames-officialshop.com", "p-bandai.jp", "bandai.co.jp",
)
_RETAILER_DOMAINS: tuple[str, ...] = (
    "lawson.co.jp", "sej.co.jp", "family.co.jp", "ministop.co.jp",
    "yodobashi.com", "biccamera.com", "joshinweb.jp", "edion.com",
    "yamada-denkiweb.com", "toysrus.co.jp", "geo-online.co.jp",
    "tsite.jp", "amazon.co.jp", "rakuten.co.jp", "books.rakuten.co.jp",
    "shopping.yahoo.co.jp", "7net.omni7.jp", "bookoff.co.jp",
    "namco-parks.com",
)
_SOCIAL_DOMAINS: tuple[str, ...] = (
    "x.com", "twitter.com", "instagram.com", "tiktok.com",
    "youtube.com", "threads.net", "note.com", "ameblo.jp",
)


def classify_event_type(text: str, store: str = "", channel: str = "") -> Optional[str]:
    """本文テキストから販売方式を判定する。判定できなければ None（推測しない）。

    コンビニチェーンの店頭販売は CONVENIENCE_STORE を優先する
    （FIRST_COME と混同しない）。
    """
    t = (text or "").lower()
    raw = text or ""
    store_u = (store or "").upper()

    is_convenience = (store_u in CONVENIENCE_CHAINS
                      or any(w in raw or w in t for w in _CONVENIENCE_WORDS))

    hit: Optional[str] = None
    for event_type, words in _RULES:
        if any((w.lower() in t) or (w in raw) for w in words):
            hit = event_type
            break

    if hit is None:
        return None

    # 抽選・予約・キャンセル分はコンビニでもその方式のまま（混同しない）
    if hit in (EVENT_LOTTERY, EVENT_PREORDER, EVENT_RESERVATION_REOPEN):
        return hit

    # コンビニの店頭販売系は CONVENIENCE_STORE に寄せる
    if is_convenience and hit in (EVENT_FIRST_COME, EVENT_GENERAL_SALE):
        return EVENT_CONVENIENCE_STORE

    # 再入荷はチャネルで online/store を分ける
    if hit == EVENT_RESTOCK and (channel or "").upper() == CHANNEL_ONLINE:
        return EVENT_ONLINE_RESTOCK

    return hit


def classify_source_type(url: str = "", store_key: str = "",
                         declared: str = "") -> str:
    """URL / 店舗キーから source_type を判定する。

    公式ドメインでなければ OFFICIAL にはしない。SNS ドメインは SOCIAL_REPORT。
    """
    host = ""
    if url:
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            host = ""

    if host:
        if any(host == d or host.endswith("." + d) for d in _OFFICIAL_DOMAINS):
            return SRC_OFFICIAL
        if any(host == d or host.endswith("." + d) for d in _RETAILER_DOMAINS):
            return SRC_RETAILER_OFFICIAL
        if any(host == d or host.endswith("." + d) for d in _SOCIAL_DOMAINS):
            return SRC_SOCIAL_REPORT

    store_u = (store_key or "").upper()
    for s in SOURCES:
        if s["key"] == store_u:
            # URL が公式ドメインでない場合は registry の種別止まり
            return s["source_type"]

    if declared in (SRC_STORE_OFFICIAL, SRC_COMMUNITY_REPORT, SRC_SOCIAL_REPORT):
        return declared
    return SRC_UNVERIFIED


def confidence_for(source_type: str, corroborations: int = 1,
                   official_confirmation: bool = False,
                   stale: bool = False) -> str:
    """Task5: 信頼度を決める。

    corroborations: 同一内容を報告している独立ソース数（SNS等）。
    公式でない情報が single report だけで high になることはない。
    """
    if stale:
        return CONF_LOW
    if source_type in OFFICIAL_SOURCE_TYPES:
        if source_type == SRC_STORE_OFFICIAL and not official_confirmation:
            return CONF_MEDIUM
        return CONF_HIGH
    if source_type == SRC_COMMUNITY_REPORT:
        return CONF_MEDIUM if corroborations >= 3 else CONF_LOW
    if source_type == SRC_SOCIAL_REPORT:
        # 単発SNSは low、複数一致で medium 止まり（high にはしない）
        return CONF_MEDIUM if corroborations >= 3 else CONF_LOW
    return CONF_LOW


def verification_label(source_type: str, confidence: str,
                       corroborations: int = 1,
                       official_confirmation: bool = False) -> str:
    """Task22: Confirmed / Likely / Reported / Unverified の表記を決める。

    SNS 1件だけで Confirmed にはしない。
    """
    if source_type in OFFICIAL_SOURCE_TYPES and (
            source_type != SRC_STORE_OFFICIAL or official_confirmation):
        return VERIFY_CONFIRMED
    if source_type == SRC_STORE_OFFICIAL:
        return VERIFY_LIKELY
    if source_type in (SRC_COMMUNITY_REPORT, SRC_SOCIAL_REPORT):
        return VERIFY_LIKELY if corroborations >= 3 else VERIFY_REPORTED
    return VERIFY_UNVERIFIED


def scope_label(source_type: str, corroborations: int, store_count: int) -> str:
    """報告の適用範囲を表す文言。SNS単発で「全国販売中」と書かせないための安全弁。"""
    if source_type in OFFICIAL_SOURCE_TYPES:
        return "公式告知の範囲"
    if corroborations >= 3 and store_count >= 3:
        return "複数店舗からの報告（在庫保証ではありません）"
    if corroborations >= 2:
        return "複数報告（在庫保証ではありません）"
    return "単一店舗の報告（在庫保証ではありません）"
