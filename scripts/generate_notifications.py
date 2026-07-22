#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Notification Engine — 条件成立を検知して通知イベントを生成する。

前回スナップショット（ai_opportunities / health / profit）との差分から
NEW_MAIN / WATCH_TO_BUY / PRICE_DROP / PRICE_RISE / ROI_UP / ROI_DOWN /
HEALTH_ALERT / DATA_RECOVERED を検知。優先度付け・テンプレート整形・
抑制（同一通知24h再送禁止、ただしROI+5%以上改善で再送可）を行う。
利益判定ロジックは変更しない。Discord/Telegram をまず対象（拡張しやすい構造）。

出力:
  exports/notifications/latest.json
  exports/notifications/history/YYYY-MM-DD.json
  exports/notifications/prev_snapshot.json   （次回比較用・上書き）
  exports/notifications/suppression.json      （再送抑制の状態）
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "notifications"
HIST = OUT / "history"

CHANNELS = ["discord", "telegram"]  # 後から line / email / push を追加しやすい構造
PRICE_DROP_MIN = 3000        # 価格下落の検知しきい値
ROI_DELTA = 0.03             # ROI ±3% で検知
PROFIT_DELTA = 10000         # 利益 +¥10,000 で検知
HEALTH_DELTA = 10            # Health ±10点で検知
SUPPRESS_HOURS = 24          # 同一通知の再送禁止時間
RESEND_ROI_GAIN = 0.05       # ROI+5%以上改善なら抑制を無視して再送

PRIORITY = {
    "WATCH_TO_BUY": "Critical", "NEW_MAIN": "High", "PRICE_DROP": "High",
    "ROI_UP": "Medium", "PRICE_RISE": "Medium", "ROI_DOWN": "Low",
    "HEALTH_ALERT": "Critical", "DATA_RECOVERED": "Low",
}


def _load(p, default=None):
    try:
        return json.loads((ROOT / p).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _snapshot(ai, health, pr) -> dict:
    ops = {o["product_id"]: o for o in ai.get("todays_opportunities", [])}
    return {
        "date": NOW.strftime("%Y-%m-%d"),
        "health_score": (health.get("health_score", {}) or {}).get("total"),
        "stale_rate": (health.get("data_quality", {}) or {}).get("stale_rate"),
        "main_products": sorted({r["product_id"] for r in pr.get("main_routes", [])}),
        "reference_products": sorted({r["product_id"] for r in pr.get("reference_routes", [])}),
        "ops": {pid: {"action": o.get("action"), "buy_now": o.get("buy_now"),
                      "roi": o.get("roi"), "net_profit": o.get("net_profit"),
                      "buy_price": o.get("buy_price"), "product": o.get("product"),
                      "buy_source": o.get("buy_source"), "kind": o.get("kind")}
                for pid, o in ops.items()},
    }


def _template(ev: dict) -> str:
    t = ev["type"]; d = ev["data"]
    p = d.get("product", "")
    if t == "WATCH_TO_BUY":
        return (f"🎉 BUYチャンス\n{p}\n現在価格 ¥{d.get('buy_price',0):,}\n"
                f"利益 ¥{d.get('net_profit',0):,}\nROI {d.get('roi',0)*100:.0f}%\n今すぐ確認")
    if t == "NEW_MAIN":
        return (f"🆕 新しい利益ルート成立\n{p}\n利益 ¥{d.get('net_profit',0):,} / "
                f"ROI {d.get('roi',0)*100:.0f}%")
    if t == "PRICE_DROP":
        return (f"📉 価格下落\n{p}\n{d.get('buy_source','')} ¥{d.get('prev_price',0):,} → "
                f"¥{d.get('buy_price',0):,}（-¥{d.get('delta',0):,}）")
    if t == "PRICE_RISE":
        return (f"📈 価格上昇\n{p}\n{d.get('buy_source','')} ¥{d.get('prev_price',0):,} → "
                f"¥{d.get('buy_price',0):,}（+¥{d.get('delta',0):,}）")
    if t == "ROI_UP":
        return f"⬆️ ROI改善\n{p}\nROI {d.get('prev_roi',0)*100:.0f}% → {d.get('roi',0)*100:.0f}%"
    if t == "ROI_DOWN":
        return f"⬇️ ROI低下\n{p}\nROI {d.get('prev_roi',0)*100:.0f}% → {d.get('roi',0)*100:.0f}%"
    if t == "HEALTH_ALERT":
        return f"⚠️ データ品質低下\nHealth Score {d.get('prev',0)} → {d.get('cur',0)}"
    if t == "DATA_RECOVERED":
        return f"✅ データ品質回復\nHealth Score {d.get('prev',0)} → {d.get('cur',0)}"
    return f"{t}: {p}"


def detect(prev: dict, cur: dict) -> list[dict]:
    events = []
    if not prev:
        return events  # 初回は基準日（差分なし）
    pops = prev.get("ops", {}); cops = cur.get("ops", {})
    # main/reference 追加
    for pid in cur["main_products"]:
        if pid not in prev.get("main_products", []):
            o = cops.get(pid, {})
            events.append({"type": "NEW_MAIN", "product_id": pid,
                           "data": {"product": o.get("product", pid), "net_profit": o.get("net_profit", 0),
                                    "roi": o.get("roi", 0)}})
    # 商品ごとの状態遷移
    for pid, co in cops.items():
        po = pops.get(pid)
        if not po:
            continue
        # WATCH/ALERT/WAIT → BUY
        if po.get("buy_now") != "BUY" and co.get("buy_now") == "BUY":
            events.append({"type": "WATCH_TO_BUY", "product_id": pid,
                           "data": {"product": co.get("product", pid), "buy_price": co.get("buy_price", 0),
                                    "net_profit": co.get("net_profit", 0), "roi": co.get("roi", 0)}})
        # 価格変動
        pbp = po.get("buy_price") or 0; cbp = co.get("buy_price") or 0
        if pbp and cbp and abs(cbp - pbp) >= PRICE_DROP_MIN:
            typ = "PRICE_DROP" if cbp < pbp else "PRICE_RISE"
            events.append({"type": typ, "product_id": pid,
                           "data": {"product": co.get("product", pid), "buy_source": co.get("buy_source", ""),
                                    "prev_price": pbp, "buy_price": cbp, "delta": abs(cbp - pbp)}})
        # ROI 変動
        proi = po.get("roi") or 0; croi = co.get("roi") or 0
        if croi - proi >= ROI_DELTA:
            events.append({"type": "ROI_UP", "product_id": pid,
                           "data": {"product": co.get("product", pid), "prev_roi": proi, "roi": croi}})
        elif proi - croi >= ROI_DELTA:
            events.append({"type": "ROI_DOWN", "product_id": pid,
                           "data": {"product": co.get("product", pid), "prev_roi": proi, "roi": croi}})
    # Health
    ph = prev.get("health_score"); ch = cur.get("health_score")
    if ph is not None and ch is not None:
        if ph >= 60 and ch < 60:
            events.append({"type": "HEALTH_ALERT", "product_id": "_health",
                           "data": {"prev": ph, "cur": ch}})
        elif ph < 80 <= ch or (ch - ph >= HEALTH_DELTA and ch >= 80):
            events.append({"type": "DATA_RECOVERED", "product_id": "_health",
                           "data": {"prev": ph, "cur": ch}})
    return events


def apply_suppression(events: list[dict], supp: dict) -> tuple[list[dict], dict]:
    """同一通知(type+product)を24h以内は抑制。ただしROI+5%以上改善なら再送可。"""
    out = []
    for ev in events:
        key = f"{ev['type']}::{ev['product_id']}"
        last = supp.get(key)
        roi = ev["data"].get("roi")
        suppressed = False
        if last:
            try:
                last_dt = datetime.fromisoformat(last["sent_at"])
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=JST)
                hours = (NOW - last_dt.astimezone(JST)).total_seconds() / 3600
                if hours < SUPPRESS_HOURS:
                    # ROI が前回通知比 +5% 以上改善していれば再送許可
                    if not (roi is not None and last.get("roi") is not None
                            and roi - last["roi"] >= RESEND_ROI_GAIN):
                        suppressed = True
            except Exception:
                pass
        ev["suppressed"] = suppressed
        if not suppressed:
            supp[key] = {"sent_at": NOW.isoformat(), "roi": roi}
            out.append(ev)
    return out, supp


def _deliver(events: list[dict]) -> dict:
    """通知配信（Discord/Telegram）。webhook 未設定時は pending。拡張しやすい channel 構造。"""
    configured = {
        "discord": bool(os.environ.get("DISCORD_WEBHOOK_URL")),
        "telegram": bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")),
    }
    status = {}
    for ch in CHANNELS:
        if not events:
            status[ch] = "no_events"
        elif configured.get(ch):
            status[ch] = "ready"   # 実送信は notify スクリプト/CIに委譲（本ジョブは生成のみ）
        else:
            status[ch] = "pending(未設定)"
    return status


def main() -> int:
    print(f"[generate_notifications] 開始: {NOW.strftime('%Y-%m-%d %H:%M')} JST")
    ai = _load("exports/ai_opportunities/latest.json")
    health = _load("audit_health/health_report.json")
    pr = _load("exports/profit_routes/latest.json")

    cur_snap = _snapshot(ai, health, pr)
    prev_snap = _load("exports/notifications/prev_snapshot.json", default={})
    supp = _load("exports/notifications/suppression.json", default={})

    raw_events = detect(prev_snap, cur_snap)
    for ev in raw_events:
        ev["priority"] = PRIORITY.get(ev["type"], "Low")
        ev["message"] = _template(ev)
        ev["channels"] = CHANNELS
        ev["created_at"] = NOW.strftime("%Y-%m-%d %H:%M JST")
    sent, supp = apply_suppression(raw_events, supp)
    # 優先度順（Critical>High>Medium>Low）
    _prank = {"Critical": 3, "High": 2, "Medium": 1, "Low": 0}
    sent.sort(key=lambda e: _prank.get(e["priority"], 0), reverse=True)
    delivery = _deliver(sent)

    OUT.mkdir(parents=True, exist_ok=True)
    HIST.mkdir(exist_ok=True)
    payload = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "date": cur_snap["date"],
        "is_baseline": (not prev_snap),
        "channels": CHANNELS,
        "delivery_status": delivery,
        "event_count": len(sent),
        "suppressed_count": sum(1 for e in raw_events if e.get("suppressed")),
        "events": sent,
    }
    (OUT / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (HIST / f"{cur_snap['date']}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "prev_snapshot.json").write_text(json.dumps(cur_snap, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "suppression.json").write_text(json.dumps(supp, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(payload)
    print(f"  通知イベント: {len(sent)}件（抑制 {payload['suppressed_count']}）"
          f"{' / 基準日（初回）' if payload['is_baseline'] else ''}")
    print(f"  配信: {delivery}")
    return 0


def _write_md(p):
    o = ["# AI Notification Engine", "", f"生成: {p['generated_at']}",
         f"イベント {p['event_count']}件 / 抑制 {p['suppressed_count']}件"
         + ("（基準日・初回のため差分なし）" if p["is_baseline"] else ""),
         f"配信チャネル: {p['channels']} / 状態: {p['delivery_status']}", "",
         "## 通知イベント（優先度順）", ""]
    if not p["events"]:
        o.append("（本日は新規通知なし）")
    for e in p["events"]:
        o += [f"### [{e['priority']}] {e['type']}",
              "```", e["message"], "```", ""]
    (OUT / "latest.md").write_text("\n".join(o) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
