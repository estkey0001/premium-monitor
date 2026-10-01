#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCG（ポケモンカード / ONE PIECEカードゲーム）入荷・抽選・プレミア監視パイプライン。

処理: collect → normalize → event build → dedupe → freshness → premium
      → clustering → scoring → notification candidates → exports

既存の Profit / AI / Opportunity / Notification / Capital / Execution / API /
Source Matching には一切触れない追加レイヤー。

出力:
  exports/tcg/latest.json / latest.md
  exports/tcg/opportunities.json / restocks.json / lotteries.json

Exit code は常に 0（取得失敗は health に記録し、パイプラインは止めない）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.tcg import ALL_COLLECTORS, POKEMON_COLLECTORS  # noqa: E402
from src.collectors.tcg.pokemon_products import secondary_mapping    # noqa: E402
from src.tcg.alerts import (                                        # noqa: E402
    build_premium_message, build_restock_signal_message,
    instant_sale_alerts, lottery_deadline_alerts,
)
from src.tcg.alerts import notification_kind                         # noqa: E402
from src.tcg.classify import (                                       # noqa: E402
    confidence_for, restock_class, verification_label,
)
from src.tcg.funnel import HEALTH_FAILED                             # noqa: E402
from src.tcg.product_types import PT_ACCESSORY                       # noqa: E402
from src.tcg.cluster import detect_restock_signals                  # noqa: E402
from src.tcg.dedupe import dedupe_events                            # noqa: E402
from src.tcg.freshness import compute_status, is_stale, ttl_for     # noqa: E402
from src.tcg.models import (                                        # noqa: E402
    EVENT_LOTTERY, INSTANT_SALE_EVENTS,
    ST_AVAILABLE_NOW, TCG_POKEMON, TCG_ONE_PIECE, now_jst,
)
from src.tcg.scoring import buy_now_signal, opportunity_score, notification_priority  # noqa: E402
from src.tcg.reports import load_reports                         # noqa: E402
from src.tcg.secondary import (                                  # noqa: E402
    ebay_enabled, fetch_ebay_observations, load_secondary_observations,
    premium_for_product,
)
from src.tcg.sources import SOURCES                                 # noqa: E402

EXPORT_DIR = PROJECT_ROOT / "exports" / "tcg"
RETAIL_CONFIG = PROJECT_ROOT / "config" / "tcg_retail_prices.yaml"

_TCG_LABEL = {TCG_POKEMON: "ポケモンカード", TCG_ONE_PIECE: "ONE PIECEカードゲーム"}
_ET_LABEL = {
    "LOTTERY": "抽選", "PREORDER": "予約", "FIRST_COME": "店頭先着",
    "CONVENIENCE_STORE": "コンビニ販売", "RESTOCK": "再入荷",
    "GUERRILLA_SALE": "突発店頭販売", "ONLINE_RESTOCK": "EC在庫復活",
    "RESERVATION_REOPEN": "予約キャンセル分", "GENERAL_SALE": "通常販売",
    "OFFICIAL_STORE": "公式ストア販売", "SECONDARY_MARKET": "二次流通",
}


def _load_retail_prices() -> dict[str, int]:
    """手動で検証済みの定価（config/tcg_retail_prices.yaml）。無ければ空。"""
    if not RETAIL_CONFIG.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(RETAIL_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ 定価設定の読み込みに失敗: {exc}")
        return {}
    out: dict[str, int] = {}
    for pid, entry in (data.get("products") or {}).items():
        if isinstance(entry, dict):
            price = entry.get("retail_price")
            # 検証済みフラグが無い定価は採用しない（推測値を混ぜない）
            if price and entry.get("verified") is True:
                out[str(pid)] = int(price)
    return out


def collect() -> tuple[list[dict], list[dict], list[dict]]:
    """全コレクターを実行し、(events, health, pokemon_registry) を返す。"""
    events: list[dict] = []
    health: list[dict] = []
    registry: list[dict] = []
    pokemon_classes = set(POKEMON_COLLECTORS)
    for cls in ALL_COLLECTORS:
        collector = cls()
        print(f"  → {collector.source_name} ({collector.source_key})")
        try:
            found = collector.collect()
        except Exception as exc:  # noqa: BLE001 - 1コレクターの失敗で止めない
            collector.health["errors"] += 1
            collector.health["error_messages"].append(str(exc))
            collector.funnel.errors += 1
            found = collector._finish([])
            # 例外で中断したものは取得状況に関わらず FAILED と明示する
            collector.health["status"] = HEALTH_FAILED
            collector.health["status_reason"] = f"コレクター例外: {type(exc).__name__}"
        collector.health["collector"] = cls.__name__
        collector.health["is_pokemon"] = cls in pokemon_classes
        events.extend(found)
        health.append(collector.health)
        registry.extend(getattr(collector, "registry", []) or [])
        f = collector.health.get("funnel") or {}
        print(f"     status={collector.health.get('status')} events={len(found)}"
              f" pages={f.get('pages_loaded', 0)}/{f.get('pages_requested', 0)}"
              f" product_pages={f.get('product_pages_discovered', 0)}"
              f" rejected={f.get('rejected_events', 0)}"
              f" errors={collector.health['errors']} blocked={collector.health['blocked']}")
    return events, health, registry


def registry_retail_prices(registry: list[dict]) -> dict[str, int]:
    """公式商品 API で「商品1個の希望小売価格」と明示されたものだけを定価候補にする。

    拡張パック系の「1パック価格」は含めない（パック価格 × 入数で BOX 価格を作らない）。
    BOX Opportunity の対象外（アクセサリー・デッキ等）も含めない。
    """
    out: dict[str, int] = {}
    for rec in registry or []:
        if (rec.get("box_opportunity_eligible") and rec.get("retail_price")
                and rec.get("retail_price_basis") == "product_unit"):
            out[rec["product_id"]] = int(rec["retail_price"])
    return out


def enrich(events: list[dict], retail_prices: dict[str, int],
           registry_prices: dict[str, int] | None = None) -> tuple[list[dict], list[dict]]:
    """重複排除・鮮度・信頼度・プレミア・スコアを付与し、(events, signals) を返す。"""
    now = now_jst()
    registry_prices = registry_prices or {}
    observations = load_secondary_observations()
    merged = dedupe_events(events)

    # eBay 経由の二次流通価格（kill-switch と dry-run が解除されている間だけ）
    if ebay_enabled():
        for pid, name in {(e.get("product_id"), e.get("product_name"))
                          for e in merged if e.get("product_id")}:
            observations.extend(fetch_ebay_observations(pid, name or ""))
        print(f"  eBay 由来の二次流通観測: "
              f"{sum(1 for o in observations if o.get('source') == 'ebay')}件")

    for ev in merged:
        corroborations = ev.get("corroborations", 1)
        ev["stale"] = is_stale(ev, now)
        ev["ttl_sec"] = ttl_for(ev.get("event_type", ""))
        ev["confidence"] = confidence_for(
            ev.get("source_type", ""), corroborations,
            official_confirmation=ev.get("official_confirmation", False),
            stale=ev["stale"])
        ev["verification"] = verification_label(
            ev.get("source_type", ""), ev["confidence"], corroborations,
            official_confirmation=ev.get("official_confirmation", False))
        ev["status"] = compute_status(ev, now)

        # 定価は config/tcg_retail_prices.yaml で verified: true のものだけを採用する。
        # ページ内の最初の金額はパック単価と BOX 価格の区別がつかないため、
        # 定価として扱わない（ev["price"] は「ページ記載の参考価格」のまま）。
        # 優先順: config の手動検証済み定価 > 公式 API の商品単価（BOX 対象種別のみ）
        pid = ev.get("product_id", "")
        retail = retail_prices.get(pid)
        if retail is None:
            retail = registry_prices.get(pid)
        if ev.get("product_type") == PT_ACCESSORY:
            retail = None   # アクセサリーは BOX Opportunity に入れない
        ev["premium"] = premium_for_product(pid, retail, observations)
        # Task15: 再販の出どころ
        ev["restock_class"] = restock_class(ev.get("event_type", ""),
                                            ev.get("source_type", ""))

    signals = detect_restock_signals(merged, now)
    chains = {s.get("chain") for s in signals}

    for ev in merged:
        sig = 1 if (ev.get("store_chain") or ev.get("store") or "").upper() in chains else 0
        score = opportunity_score(ev, ev["premium"], signals=sig)
        ev["opportunity_score"] = score["score"]
        ev["score_breakdown"] = score["breakdown"]
        buy = buy_now_signal(ev, ev["premium"])
        ev["buy_now"] = buy["buy_now"]
        ev["buy_now_blocked_reasons"] = buy["blocked_reasons"]
        ev["buy_now_notes"] = buy["notes"]
        ev["priority"] = notification_priority(ev, signals=sig)
        # Task24: 通知候補の種類（候補にしないものは None）
        ev["notification_kind"] = notification_kind(ev)
    return merged, signals


def empty_lottery_payload(error: str | None = None) -> dict:
    """抽選パイプラインが動かなかった場合の空ペイロード（正常系と同じキー）。"""
    from src.tcg.lottery.registry import coverage_summary
    return {"lotteries": [], "sources": [], "coverage": coverage_summary([]),
            "history": [], "frequency": {}, "notifications": [],
            "ledger": {"sent": {}}, "manual_errors": [error] if error else [],
            "rejection_reasons": {}, "announcements": [], "pipeline_ok": False}


def run_lottery(registry: list[dict], events: list[dict]) -> dict:
    """抽選インテリジェンスを実行する。失敗しても TCG 全体は止めない。"""
    from src.tcg.lottery.pipeline import run_lottery_pipeline
    onepiece = [{"product_id": e.get("product_id"), "name": e.get("product_name")}
                for e in events if e.get("tcg") == TCG_ONE_PIECE and e.get("product_id")]
    try:
        # 既存コレクターの抽選（TcgEvent）も抽選セクションに統合する
        return run_lottery_pipeline(registry, onepiece, legacy_events=events)
    except Exception as exc:  # noqa: BLE001 - 既存の TCG 出力を止めない
        print(f"  ❌ 抽選パイプラインに失敗: {type(exc).__name__}: {exc}")
        return empty_lottery_payload(f"{type(exc).__name__}: {exc}")


def pokemon_funnel_summary(health: list[dict], events: list[dict]) -> dict:
    """Task17 / Task32: ポケモン系コレクターのファネルを集計する。"""
    rows = []
    total = {k: 0 for k in (
        "pages_discovered", "pages_requested", "pages_loaded",
        "product_links_discovered", "product_pages_discovered",
        "product_pages_loaded", "news_pages_discovered", "news_pages_loaded",
        "candidate_events", "accepted_sales_events", "rejected_events", "errors")}
    reasons: dict[str, int] = {}
    for h in health:
        if not h.get("is_pokemon"):
            continue
        f = h.get("funnel") or {}
        rows.append({"source": h.get("source_name") or h.get("source"),
                     "collector": h.get("collector"),
                     "status": h.get("status"),
                     "status_reason": h.get("status_reason"),
                     **{k: f.get(k, 0) for k in total},
                     "rejection_reasons": f.get("rejection_reasons", {}),
                     "notes": f.get("notes", [])})
        for k in total:
            total[k] += int(f.get(k, 0) or 0)
        for r, n in (f.get("rejection_reasons") or {}).items():
            reasons[r] = reasons.get(r, 0) + int(n)
    current = [e for e in events if e.get("tcg") == TCG_POKEMON
               and e.get("status") != "ENDED"]
    return {"sources": rows, "total": total, "rejection_reasons": reasons,
            "current_events": len(current)}


def build_exports(events: list[dict], signals: list[dict],
                  health: list[dict], registry: list[dict] | None = None,
                  lottery: dict | None = None) -> dict:
    """Task28: exports を生成する。"""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = now_jst()
    registry = registry or []
    funnel = pokemon_funnel_summary(health, events)
    lottery = lottery or empty_lottery_payload()

    lotteries = [e for e in events if e.get("event_type") == EVENT_LOTTERY]
    restocks = [e for e in events if e.get("event_type") in INSTANT_SALE_EVENTS]
    available = [e for e in events
                 if e.get("status") == ST_AVAILABLE_NOW and not e.get("stale")]
    # アクセサリーは BOX Opportunity に入れない（Task5）
    opportunities = sorted(
        [e for e in events if e.get("opportunity_score") is not None
         and e.get("product_type") != PT_ACCESSORY],
        key=lambda e: e["opportunity_score"], reverse=True)
    coming_soon = [e for e in events if e.get("status") == "COMING_SOON"]

    notifications = instant_sale_alerts(events, signals, now)
    for ev in lotteries:
        for alert in lottery_deadline_alerts(ev, now):
            notifications.append(alert)
    premium_alerts = [m for m in (build_premium_message(e) for e in events) if m]
    signal_messages = [build_restock_signal_message(s) for s in signals]

    payload = {
        "generated_at": now.isoformat(),
        "tcg_types": [TCG_POKEMON, TCG_ONE_PIECE],
        "counts": {
            "events": len(events),
            "lotteries": len(lotteries),
            "restocks": len(restocks),
            "available_now": len(available),
            "signals": len(signals),
            "notifications": len(notifications),
            "coming_soon": len(coming_soon),
            # 抽選インテリジェンスの件数（counts.lotteries は従来の TcgEvent の抽選件数）
            "lottery_intel": len(lottery["lotteries"]),
            "pokemon_events": sum(1 for e in events if e.get("tcg") == TCG_POKEMON),
            "pokemon_registry": len(registry),
        },
        "events": events,
        "signals": signals,
        "notifications": notifications,
        "premium_alerts": premium_alerts,
        "signal_messages": signal_messages,
        "source_health": health,
        "source_registry_count": len(SOURCES),
        "pokemon_funnel": funnel,
        "lotteries": lottery["lotteries"],
        "lottery_sources": lottery["sources"],
        "lottery_coverage": lottery["coverage"],
        "lottery_notifications": lottery["notifications"],
        "lottery_rejection_reasons": lottery["rejection_reasons"],
        "lottery_manual_errors": lottery["manual_errors"],
        # 抽選の状態を判定した時刻（deploy-check はこの時刻で整合を検証する）
        "lottery_evaluated_at": lottery.get("evaluated_at"),
    }

    (EXPORT_DIR / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPORT_DIR / "opportunities.json").write_text(
        json.dumps({"generated_at": now.isoformat(), "items": opportunities},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPORT_DIR / "restocks.json").write_text(
        json.dumps({"generated_at": now.isoformat(), "items": restocks,
                    "signals": signals}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    # 抽選インテリジェンス（抽選・予約・購入権の横断監視）
    (EXPORT_DIR / "lotteries.json").write_text(
        json.dumps({"generated_at": now.isoformat(),
                    "evaluated_at": lottery.get("evaluated_at"),
                    "items": lottery["lotteries"],
                    "coverage": lottery["coverage"],
                    "announcements": lottery["announcements"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPORT_DIR / "lottery_sources.json").write_text(
        json.dumps({"generated_at": now.isoformat(), "sources": lottery["sources"],
                    "coverage": lottery["coverage"],
                    "rejection_reasons": lottery["rejection_reasons"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    # 履歴と通知台帳は実行をまたいで蓄積する状態なので、抽選パイプラインが
    # 正常に終わった場合だけ書き込む（失敗時に空で上書きして履歴を消さない）
    if lottery.get("pipeline_ok"):
        (EXPORT_DIR / "lottery_history.json").write_text(
            json.dumps({"generated_at": now.isoformat(), "items": lottery["history"],
                        "frequency_by_retailer": lottery["frequency"]},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        (EXPORT_DIR / "lottery_notifications.json").write_text(
            json.dumps({"generated_at": now.isoformat(), **lottery["ledger"],
                        "candidates": lottery["notifications"]},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPORT_DIR / "pokemon_funnel.json").write_text(
        json.dumps({"generated_at": now.isoformat(), **funnel},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPORT_DIR / "pokemon_registry.json").write_text(
        json.dumps({"generated_at": now.isoformat(),
                    "source": "https://www.pokemon-card.com/products/resultAPI.php",
                    "products": registry,
                    # Task20: 二次流通価格を投入するための mapping（BOX 対象のみ）
                    "secondary_mapping": [m for m in (secondary_mapping(r) for r in registry) if m]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPORT_DIR / "latest.md").write_text(_render_md(payload, available,
                                                     opportunities),
                                          encoding="utf-8")
    return payload


def _fmt_dt(value) -> str:
    from src.tcg.models import parse_dt
    dt = parse_dt(value)
    return dt.strftime("%m/%d %H:%M") if dt else "—"


def _render_md(payload: dict, available: list[dict],
               opportunities: list[dict]) -> str:
    """Task32: 最終報告フォーマットの Markdown。"""
    now = payload["generated_at"][:16].replace("T", " ")
    L: list[str] = [f"# TCG 入荷・抽選・プレミア レポート（{now} JST）", ""]

    L.append("## Current Active")
    L.append("")
    L.append("| TCG | Product | Store | Method | Start/Deadline | Price | Premium | Confidence |")
    L.append("|---|---|---|---|---|---|---|---|")
    active = [e for e in payload["events"] if e.get("status") not in ("ENDED",)]
    if not active:
        L.append("| — | 取得できた販売情報はありません | — | — | — | — | — | — |")
    for e in active[:50]:
        prem = e.get("premium") or {}
        pct = prem.get("premium_percent")
        L.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            _TCG_LABEL.get(e.get("tcg"), e.get("tcg")),
            e.get("product_name", "—"),
            e.get("store", "—"),
            _ET_LABEL.get(e.get("event_type"), e.get("event_type")),
            _fmt_dt(e.get("sale_start") or e.get("application_end")),
            f"¥{e['price']:,}" if e.get("price") else "—",
            f"{pct:+.1f}%" if pct is not None else "—",
            f"{e.get('confidence')} / {e.get('verification')}",
        ))
    L.append("")

    L.append("## Lottery（受付中の抽選）")
    lot = [e for e in payload["events"]
           if e.get("event_type") == EVENT_LOTTERY
           and e.get("status") in ("OPEN", "ENDING_SOON", "STARTING_SOON")]
    L.extend([""] + ([f"- {e['product_name']}（{e.get('store')}）"
                      f" 締切 {_fmt_dt(e.get('application_end'))} / {e.get('status')}"
                      for e in lot] or ["- 受付中の抽選はありません"]) + [""])

    L.append("## Available / Restock（現在購入可能性があるもの）")
    L.extend([""] + ([f"- {e['product_name']}（{e.get('store')}）"
                      f" {_ET_LABEL.get(e.get('event_type'), '')} / {e.get('verification')}"
                      for e in available] or
                     ["- 現在「購入可能」と確認できた情報はありません"
                      "（古い入荷報告は表示しません）"]) + [""])

    L.append("## Convenience Store（コンビニ販売情報）")
    conv = [e for e in payload["events"]
            if e.get("event_type") == "CONVENIENCE_STORE"
            or (e.get("store") or "") in ("LAWSON", "7-ELEVEN", "FAMILY_MART", "MINISTOP")]
    L.extend([""] + ([f"- {e.get('store')}: {e['product_name']}"
                      f" {_fmt_dt(e.get('sale_start'))} / 制限 {e.get('purchase_limit') or '未公表'}"
                      f" / シュリンク {e.get('shrink_status')}"
                      for e in conv] or ["- コンビニ販売情報は取得できていません"]) + [""])

    L.append("## Premium（未開封BOXプレミア率）")
    prem_rows = [e for e in opportunities
                 if (e.get("premium") or {}).get("premium_percent") is not None]
    L.append("")
    if prem_rows:
        L.append("| Product | 定価 | シュリンク市場中央値 | Premium | サンプル数 |")
        L.append("|---|---|---|---|---|")
        for e in prem_rows[:30]:
            p = e["premium"]
            L.append("| {} | ¥{:,} | ¥{:,} | {:+.1f}% | {} |".format(
                e.get("product_name", "—"), p.get("retail_price") or 0,
                p.get("market_median") or 0, p["premium_percent"],
                p.get("sealed_sample_count", 0)))
    else:
        L.append("- 二次流通の実測サンプルが不足しているため、プレミア率は算出していません"
                 "（推定値は表示しません）")
    L.append("")

    # ── 抽選インテリジェンス（最上位） ─────────────────────────────────
    lots = payload.get("lotteries") or []
    L.append("## Lottery Sources")
    L.append("")
    L.append("| Retailer | Collector | Reachable | Health | Last Check | Active Lotteries |")
    L.append("|---|---|---|---|---|---|")
    for r in payload.get("lottery_sources") or []:
        L.append("| {} ({}) | {} | {} | {} | {} | {} |".format(
            r["retailer"], r["priority"], r.get("adapter") or "未実装",
            {True: "yes", False: "no", None: "—"}[r.get("reachable")],
            r.get("state_label"), (r.get("last_checked") or "—")[:16].replace("T", " "),
            r.get("active_lotteries", 0)))
    L.append("")

    def _lot_rows(items):
        rows = []
        for e in items:
            purchase = (f"{_fmt_dt(e.get('purchase_start'))}〜{_fmt_dt(e.get('purchase_end'))}"
                        if e.get("purchase_start") or e.get("purchase_end") else "—")
            rows.append("| {} | {} | {} | {} | {} | {} | {} |".format(
                _TCG_LABEL.get(e.get("tcg"), e.get("tcg")), e.get("product_name", "—"),
                e.get("retailer_name") or e.get("retailer"),
                _fmt_dt(e.get("application_start")), _fmt_dt(e.get("application_end")),
                purchase, f"{e.get('source_type')} / {e.get('confidence')}"))
        return rows or ["| — | 該当なし | — | — | — | — | — |"]

    head = ("| TCG | Product | Retailer | Start | Deadline | Purchase Period | Confidence |",
            "|---|---|---|---|---|---|---|")
    L.append("## Active（受付中・締切間近）")
    L.extend(["", *head, *_lot_rows([e for e in lots if e.get("status") in ("OPEN", "ENDING_SOON")]), ""])
    L.append("## Upcoming（まもなく抽選開始）")
    L.extend(["", *head, *_lot_rows([e for e in lots if e.get("status") == "UPCOMING"]), ""])
    L.append("## 結果発表待ち・当選者購入期間")
    L.extend(["", *head, *_lot_rows([e for e in lots if e.get("status") in (
        "CLOSED", "RESULT_PENDING", "WINNER_ANNOUNCED", "WINNER_PURCHASE_PERIOD")]), ""])
    ann = [e for e in lots if e.get("announcement_only")]
    if ann:
        L.append("### 抽選告知あり（日程未取得）")
        L.append("")
        for e in ann:
            L.append(f"- {e.get('product_name')}（{e.get('retailer_name')}）: {e.get('source_url')}")
        L.append("")
    L.append("## Blocked")
    L.append("")
    blocked = [r for r in payload.get("lottery_sources") or []
               if r.get("state") in ("SOURCE_BLOCKED", "SOURCE_UNREACHABLE")]
    for r in blocked:
        L.append(f"- {r['retailer']}: {r.get('state_label')}（{r.get('error') or r.get('note') or '—'}）")
    if not blocked:
        L.append("- なし")
    L.append("")
    cov = payload.get("lottery_coverage") or {}
    L.append("## Coverage")
    L.append("")
    L.append(f"- Configured: {cov.get('configured_sources', 0)} / Implemented: "
             f"{cov.get('implemented_collectors', 0)} / Healthy: {cov.get('healthy_sources', 0)}"
             f" / Blocked: {cov.get('blocked_sources', 0)} / Unreachable: "
             f"{cov.get('unreachable_sources', 0)} / Not Implemented: "
             f"{cov.get('not_implemented_sources', 0)} / Lottery events: "
             f"{cov.get('lottery_events_found', 0)}")
    L.append("")
    L.append("### Rejected（抽選・理由別件数）")
    L.append("")
    lrej = payload.get("lottery_rejection_reasons") or {}
    for k, v in sorted(lrej.items(), key=lambda kv: -kv[1]):
        L.append(f"- {k}: {v}")
    if not lrej:
        L.append("- なし")
    L.append("")

    # ── Task35: Pokemon Funnel ─────────────────────────────────────────
    pf = payload.get("pokemon_funnel") or {}
    L.append("## Pokemon Funnel")
    L.append("")
    L.append("| Source | Pages | Product Links | Products | Candidate Events | Accepted | Errors | Health |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in pf.get("sources", []):
        L.append("| {} | {}/{} | {} | {} | {} | {} | {} | {} |".format(
            r["source"], r["pages_loaded"], r["pages_requested"],
            r["product_links_discovered"], r["product_pages_discovered"],
            r["candidate_events"], r["accepted_sales_events"], r["errors"],
            r["status"]))
    L.append("")
    for r in pf.get("sources", []):
        L.append(f"- {r['source']}: {r['status_reason']}")
        for n in r.get("notes") or []:
            L.append(f"  - {n}")
    L.append("")
    L.append("### Active Pokemon Events")
    L.append("")
    L.append("| Product | Store | Method | Start/End | Price | Status | Confidence |")
    L.append("|---|---|---|---|---|---|---|")
    pk = [e for e in payload["events"] if e.get("tcg") == TCG_POKEMON
          and e.get("status") != "ENDED"]
    if not pk:
        L.append("| — | 現在のポケモン販売イベントはありません | — | — | — | — | — |")
    for e in pk[:50]:
        price = e.get("price")
        basis = "（1パック）" if e.get("retail_price_basis") == "pack" else ""
        L.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            e.get("product_name", "—"), e.get("store", "—"),
            _ET_LABEL.get(e.get("event_type"), e.get("event_type")),
            f"{_fmt_dt(e.get('sale_start') or e.get('application_start'))}"
            f" / {_fmt_dt(e.get('sale_end') or e.get('application_end'))}",
            f"¥{price:,}{basis}" if price else "—",
            e.get("status"), f"{e.get('confidence')} / {e.get('verification')}"))
    L.append("")
    L.append("### Rejected（理由別件数）")
    L.append("")
    reasons = pf.get("rejection_reasons") or {}
    if reasons:
        L.append("| 理由 | 件数 |")
        L.append("|---|---|")
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
            L.append(f"| {k} | {v} |")
    else:
        L.append("- 棄却なし")
    L.append("")

    L.append("## Source Health（各監視元の取得状況）")
    L.append("")
    L.append("| Source | TCG | Status | Last checked | Last success | Events | Errors | Blocked | robots |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for h in payload["source_health"]:
        pages = (h.get("funnel") or {}).get("pages") or []
        robots = sorted({p.get("robots_status") or "unknown" for p in pages}) or ["—"]
        L.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            h.get("source_name") or h.get("source"), h.get("tcg", "—"),
            h.get("status", "—"),
            (h.get("last_checked") or "—")[:16].replace("T", " "),
            (h.get("last_success") or "—")[:16].replace("T", " "),
            h.get("events_found", 0), h.get("errors", 0),
            "YES" if h.get("blocked") else "no", "/".join(robots)))
    L.append("")
    L.append(f"監視登録 source 数: {payload['source_registry_count']}")
    L.append("")
    L.append("> 入荷報告は在庫を保証するものではありません。"
             "販売条件・購入制限は必ず各公式サイトでご確認ください。")
    return "\n".join(L)


def _write_empty_payload(reason: str) -> None:
    """収集に失敗しても空のレポートを残し、後続ステップを止めない。"""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = now_jst()
    payload = {
        "generated_at": now.isoformat(),
        "tcg_types": [TCG_POKEMON, TCG_ONE_PIECE],
        "counts": {"events": 0, "lotteries": 0, "restocks": 0,
                   "available_now": 0, "signals": 0, "notifications": 0},
        "events": [], "signals": [], "notifications": [],
        "premium_alerts": [], "signal_messages": [],
        "source_health": [], "source_registry_count": len(SOURCES),
        "pokemon_funnel": pokemon_funnel_summary([], []),
        "lotteries": [], "lottery_sources": [],
        "lottery_coverage": empty_lottery_payload()["coverage"],
        "lottery_notifications": [], "lottery_rejection_reasons": {},
        "lottery_manual_errors": [],
        "error": reason,
    }
    (EXPORT_DIR / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPORT_DIR / "latest.md").write_text(
        f"# TCG 入荷・抽選・プレミア レポート\n\n収集に失敗しました: {reason}\n",
        encoding="utf-8")
    empty_funnel = pokemon_funnel_summary([], [])
    bodies = {
        "opportunities.json": {"items": []},
        "restocks.json": {"items": [], "signals": []},
        "lotteries.json": {"items": [], "coverage": empty_lottery_payload()["coverage"],
                           "announcements": []},
        "lottery_sources.json": {"sources": [], "coverage": empty_lottery_payload()["coverage"],
                                 "rejection_reasons": {}},
        # 正常系と同じキーを空の値で出す（読み手側で KeyError にしない）
        "pokemon_funnel.json": empty_funnel,
        "pokemon_registry.json": {
            "source": "https://www.pokemon-card.com/products/resultAPI.php",
            "products": [], "secondary_mapping": []},
    }
    for name, body in bodies.items():
        (EXPORT_DIR / name).write_text(
            json.dumps({"generated_at": now.isoformat(), **body},
                       ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    try:
        return _run()
    except Exception as exc:  # noqa: BLE001 - 既存パイプラインを止めない
        print(f"  ❌ TCG 収集に失敗: {type(exc).__name__}: {exc}")
        _write_empty_payload(f"{type(exc).__name__}: {exc}")
        return 0


def _run() -> int:
    print("=" * 60)
    print(" TCG 入荷・抽選・プレミア監視")
    print("=" * 60)
    retail_prices = _load_retail_prices()
    print(f"  検証済み定価: {len(retail_prices)}件")
    raw, health, registry = collect()
    # Task6: 入荷報告（コミュニティ / SNS）を CSV 経由で取り込む
    reports = load_reports()
    print(f"  入荷報告の取り込み: {len(reports)}件")
    raw = raw + reports
    print(f"  収集イベント（重複排除前）: {len(raw)}件")
    events, signals = enrich(raw, retail_prices, registry_retail_prices(registry))
    print(f"  重複排除後: {len(events)}件 / シグナル: {len(signals)}件")
    lottery = run_lottery(registry, events)
    lc = lottery["coverage"]
    print(f"  抽選: {len(lottery['lotteries'])}件 / sources configured={lc['configured_sources']}"
          f" implemented={lc['implemented_collectors']} healthy={lc['healthy_sources']}"
          f" blocked={lc['blocked_sources']} unreachable={lc['unreachable_sources']}")
    payload = build_exports(events, signals, health, registry, lottery)
    pf = payload["pokemon_funnel"]["total"]
    print(f"  Pokemon funnel: pages={pf['pages_loaded']}/{pf['pages_requested']}"
          f" product_links={pf['product_links_discovered']}"
          f" product_pages={pf['product_pages_discovered']}"
          f" candidate={pf['candidate_events']} accepted={pf['accepted_sales_events']}"
          f" rejected={pf['rejected_events']} errors={pf['errors']}")
    print(f"  ✅ exports/tcg/ へ出力: {payload['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
