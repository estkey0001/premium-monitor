# -*- coding: utf-8 -*-
"""Task1 / Task2 / Task32 / Task33 / Task34: 抽選 source の registry とカバレッジ。

「抽選0件」と表示するときに、それが
  - 本当に抽選が無い（NO_ACTIVE_LOTTERY）
  - そもそも監視していない（SOURCE_NOT_MONITORED）
  - アクセスを拒否されている（SOURCE_BLOCKED）
  - 到達できない（SOURCE_UNREACHABLE）
のどれなのかを必ず区別する。
"""
from __future__ import annotations

from typing import Optional

# ── 収集方法（Task1） ────────────────────────────────────────────────────
CM_API = "API"
CM_HTML = "HTML"
CM_PLAYWRIGHT = "PLAYWRIGHT"
CM_RSS = "RSS"
CM_OFFICIAL_NEWS = "OFFICIAL_NEWS"
CM_MANUAL_VERIFIED = "MANUAL_VERIFIED"
CM_UNAVAILABLE = "UNAVAILABLE"
COLLECTION_METHODS = (CM_API, CM_HTML, CM_PLAYWRIGHT, CM_RSS, CM_OFFICIAL_NEWS,
                      CM_MANUAL_VERIFIED, CM_UNAVAILABLE)

# ── 監視状態（Task34） ───────────────────────────────────────────────────
ST_ACTIVE_LOTTERY = "ACTIVE_LOTTERY"            # 実装済み・取得成功・抽選あり
ST_NO_ACTIVE_LOTTERY = "NO_ACTIVE_LOTTERY"      # 実装済み・取得成功・現在の抽選なし
ST_SOURCE_BLOCKED = "SOURCE_BLOCKED"            # HTTP 403 / bot チャレンジ等
ST_SOURCE_UNREACHABLE = "SOURCE_UNREACHABLE"    # タイムアウト・接続失敗
ST_SOURCE_NOT_MONITORED = "SOURCE_NOT_MONITORED"  # 収集処理が未実装
ST_SOURCE_DEGRADED = "SOURCE_DEGRADED"          # 取得できたが告知一覧を発見できない
ST_SOURCE_FAILED = "SOURCE_FAILED"              # 実装済みだが取得に失敗
SOURCE_STATES = (ST_ACTIVE_LOTTERY, ST_NO_ACTIVE_LOTTERY, ST_SOURCE_BLOCKED,
                 ST_SOURCE_UNREACHABLE, ST_SOURCE_NOT_MONITORED, ST_SOURCE_DEGRADED,
                 ST_SOURCE_FAILED)
STATE_LABELS = {
    ST_ACTIVE_LOTTERY: "抽選あり", ST_NO_ACTIVE_LOTTERY: "現在の抽選なし",
    ST_SOURCE_BLOCKED: "アクセス拒否", ST_SOURCE_UNREACHABLE: "接続できない",
    ST_SOURCE_NOT_MONITORED: "未監視（未実装）", ST_SOURCE_DEGRADED: "要確認",
    ST_SOURCE_FAILED: "取得失敗",
}

POKEMON = "POKEMON"
ONE_PIECE = "ONE_PIECE"


def _src(source_id, retailer, brands, priority, official_url, method, *,
         lottery_url=None, news_url=None, channel="ONLINE", adapter=None,
         verified=False, note=None):
    return {
        "source_id": source_id,
        "retailer": retailer,
        "brand": list(brands),
        "priority": priority,                 # P0 / P1 / P2
        "official_url": official_url,
        "lottery_url": lottery_url,
        "news_url": news_url,
        "channel": channel,
        "collection_method": method,
        # adapter: 実装済みの抽選コレクター名。None は「監視対象として登録のみ」
        "adapter": adapter,
        # verified: URL の到達性・内容を実際に確認済みか（推測 URL を検証済みにしない）
        "verified": verified,
        "note": note,
    }


_BOTH = (POKEMON, ONE_PIECE)

# 2026-10-01 に各サイトのトップ・一覧を実際に取得して確認した結果に基づく
LOTTERY_SOURCES: list[dict] = [
    # ── Pokemon P0 ───────────────────────────────────────────────────
    _src("POKEMON_CENTER_ONLINE", "ポケモンセンターオンライン", (POKEMON,), "P0",
         "https://www.pokemoncenter-online.com/", CM_OFFICIAL_NEWS,
         news_url="https://www.pokemon-card.com/info/", adapter="pco_lottery",
         verified=True,
         note="抽選告知は公式ニュース一覧のリンクから発見。PCO 本体は CI から HTTP 403 "
              "のため、本文が取れない場合は手動確認済みデータで補う（bot 対策は回避しない）"),
    _src("POKEMON_CARD_OFFICIAL", "ポケモンカードゲーム公式（ニュース）", (POKEMON,), "P0",
         "https://www.pokemon-card.com/", CM_OFFICIAL_NEWS,
         news_url="https://www.pokemon-card.com/info/", adapter="pokemon_news_lottery",
         verified=True),
    # ── Pokemon / ONE PIECE P1（量販店） ─────────────────────────────
    _src("GEO", "ゲオ", _BOTH, "P1", "https://geo-online.co.jp/", CM_HTML,
         news_url="https://geo-online.co.jp/news/",
         lottery_url="https://draw.geo-online.co.jp/lottery/", channel="STORE",
         adapter="geo_lottery", verified=True),
    _src("TOYSRUS", "トイザらス", _BOTH, "P1", "https://www.toysrus.co.jp/", CM_HTML,
         note="2026-10-01 時点でトップページが HTTP 403（ローカル・CI とも）。解析器は未実装"),
    _src("JOSHIN", "Joshin", _BOTH, "P1", "https://joshinweb.jp/", CM_HTML,
         note="2026-10-01 時点でトップページが HTTP 403。解析器は未実装"),
    _src("EDION", "エディオン", _BOTH, "P1", "https://www.edion.com/", CM_HTML,
         note="到達可。トップから TCG の抽選告知一覧を発見できず、解析器は未実装"),
    _src("YAMADA", "ヤマダデンキ", _BOTH, "P1", "https://www.yamada-denkiweb.com/", CM_HTML,
         note="2026-10-01 時点で応答タイムアウト。解析器は未実装"),
    _src("TSUTAYA", "TSUTAYA", _BOTH, "P1", "https://store-tsutaya.tsite.jp/", CM_HTML,
         note="到達可。トップから TCG の抽選告知一覧を発見できず、解析器は未実装"),
    _src("BICCAMERA", "ビックカメラ", _BOTH, "P1", "https://www.biccamera.com/", CM_HTML,
         note="2026-10-01 時点で応答タイムアウト。解析器は未実装"),
    _src("YODOBASHI", "ヨドバシカメラ", _BOTH, "P1", "https://www.yodobashi.com/", CM_HTML,
         note="2026-10-01 時点で応答タイムアウト。解析器は未実装"),
    # ── P2（EC・コンビニ） ───────────────────────────────────────────
    _src("AMAZON", "Amazon", _BOTH, "P2", "https://www.amazon.co.jp/", CM_HTML,
         note="自動アクセスに応答本文を返さない（HTTP 202）。解析器は未実装"),
    _src("RAKUTEN_BOOKS", "楽天ブックス", _BOTH, "P2", "https://books.rakuten.co.jp/", CM_HTML,
         note="到達可。TCG 抽選の告知一覧を発見できず、解析器は未実装"),
    _src("SEVEN_NET", "セブンネットショッピング", _BOTH, "P2", "https://7net.omni7.jp/", CM_HTML,
         note="到達可。TCG 抽選の告知一覧を発見できず、解析器は未実装"),
    _src("LAWSON", "ローソン", _BOTH, "P2", "https://www.lawson.co.jp/", CM_HTML,
         news_url="https://www.lawson.co.jp/campaign/", channel="STORE",
         adapter="lawson_lottery", verified=True),
    # ── ONE PIECE P0 ─────────────────────────────────────────────────
    _src("ONEPIECE_CARD_OFFICIAL", "ONE PIECEカードゲーム公式", (ONE_PIECE,), "P0",
         "https://www.onepiece-cardgame.com/", CM_OFFICIAL_NEWS,
         news_url="https://www.onepiece-cardgame.com/news/", adapter="onepiece_news_lottery",
         verified=True),
    _src("ONEPIECE_CARD_OFFICIAL_SHOP", "ONE PIECEカードゲーム公式ショップ", (ONE_PIECE,), "P0",
         "", CM_UNAVAILABLE,
         note="公式ショップの URL を確認できていない（DNS 解決不可）。推測 URL で監視しない"),
    _src("PREMIUM_BANDAI", "プレミアムバンダイ", (ONE_PIECE,), "P0",
         "https://p-bandai.jp/", CM_HTML,
         news_url="https://p-bandai.jp/chara/onepiece/", adapter="premium_bandai_lottery",
         verified=True),
]
SOURCE_BY_ID: dict[str, dict] = {s["source_id"]: s for s in LOTTERY_SOURCES}


def source_state(source: dict, health: Optional[dict], active_lotteries: int) -> str:
    """source の監視状態を決める（Task34）。"""
    if not source.get("adapter"):
        if health and health.get("blocked"):
            return ST_SOURCE_BLOCKED
        if health and health.get("unreachable"):
            return ST_SOURCE_UNREACHABLE
        return ST_SOURCE_NOT_MONITORED
    if not health:
        return ST_SOURCE_FAILED
    if health.get("blocked"):
        return ST_SOURCE_BLOCKED
    if health.get("unreachable"):
        return ST_SOURCE_UNREACHABLE
    status = health.get("status")
    if status == "FAILED":
        return ST_SOURCE_FAILED
    if status == "DEGRADED":
        return ST_SOURCE_DEGRADED
    return ST_ACTIVE_LOTTERY if active_lotteries > 0 else ST_NO_ACTIVE_LOTTERY


def coverage_summary(rows: list[dict]) -> dict:
    """Task33: Lottery Source Coverage。"""
    def _n(cond):
        return sum(1 for r in rows if cond(r))
    return {
        "configured_sources": len(rows),
        "implemented_collectors": _n(lambda r: bool(r.get("adapter"))),
        "reachable_sources": _n(lambda r: r.get("reachable") is True),
        "healthy_sources": _n(lambda r: r.get("state") in (ST_ACTIVE_LOTTERY,
                                                           ST_NO_ACTIVE_LOTTERY)),
        "blocked_sources": _n(lambda r: r.get("state") == ST_SOURCE_BLOCKED),
        "unreachable_sources": _n(lambda r: r.get("state") == ST_SOURCE_UNREACHABLE),
        "not_implemented_sources": _n(lambda r: not r.get("adapter")),
        "sources_with_active_lottery": _n(lambda r: r.get("state") == ST_ACTIVE_LOTTERY),
        "lottery_events_found": sum(int(r.get("active_lotteries") or 0) for r in rows),
    }
