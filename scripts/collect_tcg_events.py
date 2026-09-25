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

from src.collectors.tcg import ALL_COLLECTORS                      # noqa: E402
from src.tcg.alerts import (                                        # noqa: E402
    build_premium_message, build_restock_signal_message,
    instant_sale_alerts, lottery_deadline_alerts,
)
from src.tcg.classify import confidence_for, verification_label     # noqa: E402
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


def collect() -> tuple[list[dict], list[dict]]:
    """全コレクターを実行し、(events, health) を返す。"""
    events: list[dict] = []
    health: list[dict] = []
    for cls in ALL_COLLECTORS:
        collector = cls()
        print(f"  → {collector.source_name} ({collector.source_key})")
        try:
            found = collector.collect()
        except Exception as exc:  # noqa: BLE001 - 1コレクターの失敗で止めない
            collector.health["errors"] += 1
            collector.health["error_messages"].append(str(exc))
            found = []
        events.extend(found)
        health.append(collector.health)
        print(f"     events={len(found)} errors={collector.health['errors']}"
              f" blocked={collector.health['blocked']}")
    return events, health


def enrich(events: list[dict], retail_prices: dict[str, int]) -> tuple[list[dict], list[dict]]:
    """重複排除・鮮度・信頼度・プレミア・スコアを付与し、(events, signals) を返す。"""
    now = now_jst()
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
        retail = retail_prices.get(ev.get("product_id", ""))
        ev["premium"] = premium_for_product(ev.get("product_id", ""), retail,
                                            observations)

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
    return merged, signals


def build_exports(events: list[dict], signals: list[dict],
                  health: list[dict]) -> dict:
    """Task28: exports を生成する。"""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = now_jst()

    lotteries = [e for e in events if e.get("event_type") == EVENT_LOTTERY]
    restocks = [e for e in events if e.get("event_type") in INSTANT_SALE_EVENTS]
    available = [e for e in events
                 if e.get("status") == ST_AVAILABLE_NOW and not e.get("stale")]
    opportunities = sorted(
        [e for e in events if e.get("opportunity_score") is not None],
        key=lambda e: e["opportunity_score"], reverse=True)

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
        },
        "events": events,
        "signals": signals,
        "notifications": notifications,
        "premium_alerts": premium_alerts,
        "signal_messages": signal_messages,
        "source_health": health,
        "source_registry_count": len(SOURCES),
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
    (EXPORT_DIR / "lotteries.json").write_text(
        json.dumps({"generated_at": now.isoformat(), "items": lotteries},
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

    L.append("## Source Health（各監視元の取得状況）")
    L.append("")
    L.append("| Source | TCG | Last checked | Last success | Events | Errors | Blocked |")
    L.append("|---|---|---|---|---|---|---|")
    for h in payload["source_health"]:
        L.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            h.get("source_name") or h.get("source"), h.get("tcg", "—"),
            (h.get("last_checked") or "—")[:16].replace("T", " "),
            (h.get("last_success") or "—")[:16].replace("T", " "),
            h.get("events_found", 0), h.get("errors", 0),
            "YES" if h.get("blocked") else "no"))
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
        "error": reason,
    }
    (EXPORT_DIR / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPORT_DIR / "latest.md").write_text(
        f"# TCG 入荷・抽選・プレミア レポート\n\n収集に失敗しました: {reason}\n",
        encoding="utf-8")
    for name in ("opportunities.json", "restocks.json", "lotteries.json"):
        body = {"generated_at": now.isoformat(), "items": []}
        if name == "restocks.json":
            body["signals"] = []      # 正常系と同じスキーマにそろえる
        (EXPORT_DIR / name).write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


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
    raw, health = collect()
    # Task6: 入荷報告（コミュニティ / SNS）を CSV 経由で取り込む
    reports = load_reports()
    print(f"  入荷報告の取り込み: {len(reports)}件")
    raw = raw + reports
    print(f"  収集イベント（重複排除前）: {len(raw)}件")
    events, signals = enrich(raw, retail_prices)
    print(f"  重複排除後: {len(events)}件 / シグナル: {len(signals)}件")
    payload = build_exports(events, signals, health)
    print(f"  ✅ exports/tcg/ へ出力: {payload['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
