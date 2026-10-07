# -*- coding: utf-8 -*-
"""抽選インテリジェンスのパイプライン。

collect（各 source の抽選コレクター + 未実装 source の到達確認）
  → 手動確認済みデータ → 商品の紐付け → 重複排除・矛盾検出
  → 状態・カウントダウン → 履歴 → 通知候補 → source 監視状態・カバレッジ
"""
from __future__ import annotations

import logging
from typing import Optional

from src.tcg.models import now_jst, parse_dt

from .history import frequency_by_retailer, notification_candidates, update_history
from .manual import is_official_url, load_manual_lotteries
from .merge import merge_lotteries
from .products import resolve_product
from .registry import (
    LOTTERY_SOURCES, STATE_LABELS, coverage_summary, source_state,
)
from .schema import (
    ACTIVE_STATUSES, L_UNKNOWN, LT_PREORDER, OFFICIAL_LOTTERY_SOURCES, SRC_MANUFACTURER,
    compute_lottery_status, countdown, lottery_id_of, sort_key,
)

logger = logging.getLogger(__name__)

# 告知のみ（日程未取得）を表示する期間（公開日からの日数）
ANNOUNCEMENT_DISPLAY_DAYS = 14


def _adapters():
    from src.collectors.tcg.lottery.geo import GeoLotteryAdapter
    from src.collectors.tcg.lottery.others import (
        LawsonLotteryAdapter, OnePieceNewsLotteryAdapter, PremiumBandaiLotteryAdapter,
    )
    from src.collectors.tcg.lottery.pokemon_official import (
        PcoLotteryAdapter, PokemonNewsLotteryAdapter,
    )
    return {
        "pco_lottery": PcoLotteryAdapter,
        "pokemon_news_lottery": PokemonNewsLotteryAdapter,
        "geo_lottery": GeoLotteryAdapter,
        "lawson_lottery": LawsonLotteryAdapter,
        "onepiece_news_lottery": OnePieceNewsLotteryAdapter,
        "premium_bandai_lottery": PremiumBandaiLotteryAdapter,
    }


def collect_sources(sources: Optional[list[dict]] = None) -> tuple[list[dict], dict, list[dict]]:
    """全 source を取得する。(events, health_by_source, announcements) を返す。"""
    from src.collectors.tcg.lottery.base import LotteryAdapter
    from src.collectors.tcg.lottery.others import SourceProbe
    sources = sources if sources is not None else LOTTERY_SOURCES
    registry = _adapters()
    LotteryAdapter.clear_cache()
    events: list[dict] = []
    health: dict[str, dict] = {}
    announcements: list[dict] = []
    for src in sources:
        name = src.get("adapter")
        cls = registry.get(name) if name else None
        try:
            if cls is not None:
                a = cls()
            elif src.get("official_url"):
                a = SourceProbe(src)
            else:
                health[src["source_id"]] = {"probe": "no_url", "status": None}
                continue
            found = a.collect()
            events.extend(found)
            announcements.extend(a.announcements)
            health[src["source_id"]] = a.health
            print(f"  → [抽選] {src['retailer']}: status={a.health.get('status')}"
                  f" lotteries={len(found)} blocked={a.health.get('blocked')}"
                  f" unreachable={a.health.get('unreachable')}")
        except Exception as exc:  # noqa: BLE001 - 1 source の失敗で止めない
            logger.exception("抽選コレクター失敗: %s", src["source_id"])
            health[src["source_id"]] = {"status": "FAILED", "errors": 1,
                                        "error_messages": [f"{type(exc).__name__}: {exc}"]}
    return events, health, announcements


def _resolve_all(events: list[dict], pokemon_registry: list[dict],
                 onepiece_products: list[dict]) -> None:
    for ev in events:
        if ev.get("product_id"):
            continue
        reg = pokemon_registry if ev.get("tcg") == "POKEMON" else onepiece_products
        r = resolve_product(ev.get("product_name") or "", reg)
        ev["product_id"] = r["product_id"]
        ev["product_match"] = r["product_match"]
        ev["provisional_product"] = r["provisional_product"]
        if r.get("release_date") and not ev.get("release_date"):
            ev["release_date"] = r["release_date"]


def normalize_url(url: str) -> str:
    """URL 照合用の正規化（スキーム・ホストの大小、末尾スラッシュ、フラグメント）。"""
    from urllib.parse import urlsplit, urlunsplit
    if not url:
        return ""
    sp = urlsplit(url.strip())
    path = sp.path.rstrip("/") or "/"
    return urlunsplit((sp.scheme.lower(), sp.netloc.lower(), path, sp.query, ""))


def _announcement_events(announcements: list[dict], covered_urls: set[str], now,
                         rejected: Optional[dict] = None) -> list[dict]:
    """日程未取得の公式告知を「抽選告知あり」として残す（手動確認で補えていないもの）。

    残さなかった告知は rejected に理由別で数える。
    """
    from src.collectors.tcg.lottery.base import LotteryAdapter
    screen = LotteryAdapter()
    covered = {normalize_url(u) for u in covered_urls}
    rejected = rejected if rejected is not None else {}

    def _rej(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    out: list[dict] = []
    for an in announcements:
        url = an.get("source_url") or ""
        if not url or not is_official_url(url):
            _rej("announcement_not_official")
            continue
        if normalize_url(url) in covered:
            continue   # 手動確認済みデータ等で日程が補えている
        reason = screen.screen_announcement_title(an.get("title") or "")
        if reason:
            _rej("announcement_" + reason)
            continue   # 大会・キャンペーン・プレゼント抽選の告知は残さない
        pub = parse_dt(an.get("published_at"))
        if pub is None or (now - pub).days > ANNOUNCEMENT_DISPLAY_DAYS:
            _rej("announcement_too_old_or_undated")
            continue
        d = {
            "tcg": an.get("tcg") or "POKEMON", "product_name": an.get("title") or "",
            "retailer": an.get("retailer"), "retailer_name": an.get("retailer_name"),
            "event_type": "LOTTERY", "store_specific": False,
            "application_start": None, "application_end": None,
            "source_url": url, "source_urls": [u for u in (url, an.get("listed_on")) if u],
            "source_type": SRC_MANUFACTURER, "confidence": "medium", "verified": False,
            "published_at": an.get("published_at"), "announcement_only": True,
            "provisional_product": True, "product_match": "none",
            "entry_url": None, "status": L_UNKNOWN,
            "notes": [an.get("reason") or "日程は公式ページでご確認ください"],
        }
        d["lottery_id"] = lottery_id_of(d)
        out.append(d)
    return out


_LEGACY_SOURCE_MAP = {
    "OFFICIAL": "MANUFACTURER_OFFICIAL", "RETAILER_OFFICIAL": "RETAILER_OFFICIAL",
    "STORE_OFFICIAL": "STORE_OFFICIAL",
}


def from_tcg_events(events: list[dict]) -> list[dict]:
    """既存コレクター（TcgEvent）の抽選・予約のイベントを抽選パイプラインの入力に変換する。

    新しい抽選コレクターが監視していない source の抽選・予約も、抽選・予約のページに統合して
    表示するため（二重表示も表示漏れも起こさない）。
    ページ内の最初の金額はパック価格か BOX 価格か分からないので定価にはしない。

    予約（PREORDER。Phase 11）は抽選と混ぜない（event_type=PREORDER のまま）。期間は予約の受付期間
    （application_start / application_end）だけを使い、発売日（sale_start）を受付期間とみなさない。
    受付期間が無ければ日程不明のまま（受付中とは言わない）。在庫・在庫再開には入れない。
    """
    from .schema import LT_LOTTERY, LT_PREORDER, LotteryEvent, SRC_COMMUNITY

    def _split(value):
        """既存パーサーは時刻が無い日付を 00:00 にしている。00:00 は「日付のみ」に戻す。

        戻り値は (時刻付き ISO または None, 日付のみ YYYY-MM-DD または None)。
        """
        if not value:
            return None, None
        v = str(value)
        if "T00:00:00" in v:
            return None, v[:10]
        return v, None

    out: list[dict] = []
    for e in events or []:
        etype = e.get("event_type")
        if etype not in (LT_LOTTERY, LT_PREORDER):
            continue
        st = _LEGACY_SOURCE_MAP.get(e.get("source_type") or "", SRC_COMMUNITY)
        a_s, a_s_d = _split(e.get("application_start"))
        a_e, a_e_d = _split(e.get("application_end"))
        w, w_d = _split(e.get("result_date"))
        p_s, p_s_d = _split(e.get("purchase_start"))
        p_e, p_e_d = _split(e.get("purchase_end"))
        try:
            ev = LotteryEvent(
                tcg=e.get("tcg") or "POKEMON", product_name=e.get("product_name") or "",
                retailer=(e.get("store") or "").upper(), retailer_name=e.get("store"),
                event_type=etype,
                application_start=a_s, application_start_date=a_s_d,
                application_end=a_e, application_end_date=a_e_d,
                winner_announcement_at=w, winner_announcement_date=w_d,
                purchase_start=p_s, purchase_start_date=p_s_d,
                purchase_end=p_e, purchase_end_date=p_e_d,
                price_text=(f"ページ記載 {e['price']}円" if e.get("price") else None),
                source_url=e.get("source_url") or "", source_type=st,
                confidence=e.get("confidence") or "low",
                verified=st != SRC_COMMUNITY, published_at=e.get("published_at"),
                observed_at=e.get("observed_at"), collection_method="LEGACY_TCG_EVENT",
                notes=[("既存の TCG 監視（ニュース解析）から取得した予約です" if etype == LT_PREORDER
                        else "既存の TCG 監視（ニュース解析）から取得した抽選です")],
            )
        except ValueError:
            continue
        out.append(ev.to_dict())
    return out


def run_lottery_pipeline(pokemon_registry: list[dict], onepiece_products: list[dict],
                         now=None, legacy_events: Optional[list[dict]] = None) -> dict:
    raw, health, announcements = collect_sources()
    raw = raw + from_tcg_events(legacy_events or [])
    # 状態は「収集が終わった時点」の1つの時刻で判定し、その時刻を出力にも残す
    # （収集中に締切・開始の境界をまたいでも、出力と検証の時刻がずれないように）
    now = now or now_jst()
    manual, manual_errors = load_manual_lotteries()
    print(f"  手動確認済みの抽選: {len(manual)}件（エラー {len(manual_errors)}件）")
    events = raw + manual
    _resolve_all(events, pokemon_registry, onepiece_products)
    merged = merge_lotteries(events)

    for ev in merged:
        ev["status"] = compute_lottery_status(ev, now)
        # Task27: 応募ボタンは公式の応募 URL のみ。公式確認でない情報には付けない
        for key in ("entry_url", "result_url", "purchase_url"):
            if (not ev.get(key) or not is_official_url(ev[key])
                    or ev.get("source_type") not in OFFICIAL_LOTTERY_SOURCES):
                ev[key] = None
        ev["deadline_countdown"] = countdown(ev.get("application_end"), now)
        ev["start_countdown"] = countdown(ev.get("application_start"), now)
        ev["purchase_countdown"] = countdown(ev.get("purchase_end"), now)

    covered = {u for ev in merged for u in (ev.get("source_urls") or [])}
    placeholder_rejected: dict[str, int] = {}
    placeholders = _announcement_events(announcements, covered, now, placeholder_rejected)
    lotteries = sorted(merged + placeholders, key=sort_key)

    # 抽選の履歴・店ごとの頻度には予約（PREORDER）を入れない（予約を抽選の回数に数えない。Phase 11）
    history = update_history([e for e in merged if e.get("event_type") != LT_PREORDER], now)
    frequency = frequency_by_retailer(history, now)
    # 抽選の通知（抽選開始・締切・当選発表）にも予約を入れない（予約に当選発表は無い。Phase 11）
    notifications, ledger = notification_candidates(
        [e for e in merged if e.get("event_type") != LT_PREORDER], now)

    rows: list[dict] = []
    for src in LOTTERY_SOURCES:
        h = health.get(src["source_id"]) or {}
        f = h.get("funnel") or {}
        _act = [ev for ev in lotteries if ev.get("retailer") == src["source_id"]
                and ev.get("status") in ACTIVE_STATUSES]
        # 取得元の状態の判定には抽選・予約の両方を数える（予約だけの取得元も「動いている」）。
        # 報告の件数は抽選と予約を分ける（予約を抽選の件数に数えない。Phase 12）
        active = len(_act)
        active_preorders = sum(1 for ev in _act if ev.get("event_type") == LT_PREORDER)
        seen = [hst.get("first_seen_at") for hst in history
                if hst.get("retailer") == src["source_id"] and hst.get("first_seen_at")]
        state = source_state(src, h, active)
        rows.append({
            **{k: src[k] for k in ("source_id", "retailer", "brand", "priority",
                                   "official_url", "lottery_url", "news_url", "channel",
                                   "collection_method", "adapter", "verified", "note")},
            "state": state, "state_label": STATE_LABELS.get(state, state),
            "reachable": bool(f.get("pages_loaded")) if h else None,
            "last_checked": h.get("last_checked"), "last_success": h.get("last_success"),
            "last_event_found": max(seen) if seen else None,
            "candidate_articles": f.get("product_links_discovered", 0),
            "accepted_lotteries": f.get("accepted_sales_events", 0),
            "rejected": f.get("rejected_events", 0),
            "rejection_reasons": f.get("rejection_reasons", {}),
            "blocked": bool(h.get("blocked")), "unreachable": bool(h.get("unreachable")),
            # robots.txt の理由（robots_disallowed: 禁止 / robots_unreachable: 到達できない。混ぜない。Phase 13）
            "robots": h.get("robots"),
            "error": (h.get("error_messages") or [None])[0],
            "health": h.get("status"), "active_lotteries": active - active_preorders,
            "active_preorders": active_preorders,
            "announcements": len(h.get("announcements") or []),
            "pages": f.get("pages", []),
        })
    coverage = coverage_summary(rows)
    rejection: dict[str, int] = dict(placeholder_rejected)
    for r in rows:
        for k, v in (r.get("rejection_reasons") or {}).items():
            rejection[k] = rejection.get(k, 0) + int(v)
    return {
        "lotteries": lotteries, "sources": rows, "coverage": coverage,
        "history": history, "frequency": frequency,
        "notifications": notifications, "ledger": ledger,
        "manual_errors": manual_errors, "rejection_reasons": rejection,
        "announcements": announcements,
        "evaluated_at": now.isoformat(),
        "pipeline_ok": True,
    }
