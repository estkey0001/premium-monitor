# -*- coding: utf-8 -*-
"""Task30 / Task31 / Task8: 抽選の履歴保存・頻度集計・通知の重複防止。

- 終了した抽選も削除せず履歴（exports/tcg/lottery_history.json）に残す。
- 小売ごとの抽選頻度（直近30日 / 90日・平均リードタイム・平均応募期間）を算出できる
  構造にする（予測モデルは作らない）。
- 通知候補は (lottery_id, milestone) ごとに1回だけ出す（ledger で管理）。
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from statistics import mean
from typing import Optional

from src.tcg.models import now_jst, parse_dt

from .schema import L_ENDED

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HISTORY_PATH = PROJECT_ROOT / "exports" / "tcg" / "lottery_history.json"
LEDGER_PATH = PROJECT_ROOT / "exports" / "tcg" / "lottery_notifications.json"

_KEEP_FIELDS = ("lottery_id", "tcg", "product_name", "product_id", "retailer",
                "retailer_name", "store_name", "store_specific", "event_type",
                "application_start", "application_end", "winner_announcement_at",
                "purchase_start", "purchase_end", "application_start_date",
                "application_end_date", "winner_announcement_date", "purchase_start_date",
                "purchase_end_date", "retail_price", "source_url",
                "source_type", "confidence", "published_at")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def update_history(events: list[dict], now=None,
                   path: Optional[Path] = None) -> list[dict]:
    """抽選の履歴を更新して返す。既存の記録は消さない。

    first_seen_at は初めて観測した時刻のまま、last_seen_at は今回観測した時刻。
    今回観測されなかった記録も残し、状態は日程から再計算する。
    """
    from .schema import compute_lottery_status
    now = now or now_jst()
    path = path or HISTORY_PATH
    data = _load_json(path, {"items": []})
    by_id = {it["lottery_id"]: it for it in data.get("items", []) if it.get("lottery_id")}
    for ev in events:
        lid = ev.get("lottery_id")
        if not lid:
            continue
        rec = by_id.get(lid, {"first_seen_at": now.isoformat()})
        rec.update({k: ev.get(k) for k in _KEEP_FIELDS})
        rec["last_seen_at"] = now.isoformat()
        by_id[lid] = rec
    for rec in by_id.values():
        rec["status"] = compute_lottery_status(rec, now)
    items = sorted(by_id.values(), key=lambda r: r.get("application_start") or "",
                   reverse=True)
    return items


def frequency_by_retailer(history: list[dict], now=None) -> dict:
    """Task31: 小売ごとの抽選頻度。将来の分析用（予測はしない）。"""
    now = now or now_jst()
    out: dict[str, dict] = {}
    for rec in history:
        r = rec.get("retailer") or "UNKNOWN"
        s = out.setdefault(r, {"events_total": 0, "events_last_30d": 0,
                               "events_last_90d": 0, "_lead": [], "_window": []})
        s["events_total"] += 1
        start = parse_dt(rec.get("application_start") or rec.get("application_start_date"))
        end = parse_dt(rec.get("application_end") or rec.get("application_end_date"))
        pub = parse_dt(rec.get("published_at") or rec.get("first_seen_at"))
        if start:
            if now - start <= timedelta(days=30):
                s["events_last_30d"] += 1
            if now - start <= timedelta(days=90):
                s["events_last_90d"] += 1
            if pub and start >= pub:
                s["_lead"].append((start - pub).total_seconds() / 3600)
        if start and end and end > start:
            s["_window"].append((end - start).total_seconds() / 3600)
    for s in out.values():
        lead, win = s.pop("_lead"), s.pop("_window")
        s["average_lead_time_hours"] = round(mean(lead), 1) if lead else None
        s["average_application_window_hours"] = round(mean(win), 1) if win else None
    return out


# ── Task8: 通知タイミング ────────────────────────────────────────────────
MILESTONES: tuple[tuple[str, str], ...] = (
    ("lottery_open", "抽選開始"),
    ("deadline_24h", "締切24時間前"),
    ("deadline_6h", "締切6時間前"),
    ("deadline_1h", "締切1時間前"),
    ("winner_announcement", "当選発表"),
    ("purchase_deadline_24h", "購入期限24時間前"),
)


def _milestone_times(ev: dict) -> dict:
    """各通知の (発火時刻, 有効期限)。有効期限を過ぎた通知は出さない。

    例: 「締切1時間前」は締切を過ぎたら意味が無いので、締切が有効期限。
    """
    start = parse_dt(ev.get("application_start"))
    end = parse_dt(ev.get("application_end"))
    result = parse_dt(ev.get("winner_announcement_at"))
    p_end = parse_dt(ev.get("purchase_end"))
    return {
        "lottery_open": (start, end),
        "deadline_24h": (end - timedelta(hours=24) if end else None, end),
        "deadline_6h": (end - timedelta(hours=6) if end else None, end),
        "deadline_1h": (end - timedelta(hours=1) if end else None, end),
        "winner_announcement": (result, p_end or (result + timedelta(hours=24) if result else None)),
        "purchase_deadline_24h": (p_end - timedelta(hours=24) if p_end else None, p_end),
    }


def notification_candidates(events: list[dict], now=None,
                            ledger_path: Optional[Path] = None,
                            grace: timedelta = timedelta(hours=24)) -> tuple[list[dict], dict]:
    """発火時刻を過ぎ、まだ出していない通知だけを候補にする。

    - 発火時刻から grace を過ぎたもの（古い通知）は出さない。
    - 一度出した (lottery_id, milestone) は ledger に記録し、二度と出さない。
    - 公式確認のもの（MANUFACTURER / RETAILER / STORE / MANUAL_VERIFIED_OFFICIAL）だけ。
    """
    from .schema import OFFICIAL_LOTTERY_SOURCES
    now = now or now_jst()
    ledger_path = ledger_path or LEDGER_PATH
    ledger = _load_json(ledger_path, {"sent": {}})
    sent: dict = ledger.get("sent", {})
    labels = dict(MILESTONES)
    out: list[dict] = []
    for ev in events:
        if ev.get("source_type") not in OFFICIAL_LOTTERY_SOURCES or ev.get("conflict"):
            continue
        # 人による確認が済んでいない手動データは通知しない
        if ev.get("collection_method") == "MANUAL_VERIFIED" and not ev.get("verified"):
            continue
        lid = ev.get("lottery_id")
        due: list[tuple[str, object]] = []
        for key, (at, expires) in _milestone_times(ev).items():
            if at is None:
                continue
            if f"{lid}:{key}" in sent:
                continue
            # 発火時刻を過ぎ、かつ有効期限（締切・購入期限）前のものだけ
            limit = min(x for x in (at + grace, expires) if x is not None)
            if at <= now < limit:
                due.append((key, at))
        # 締切前の通知（24h / 6h / 1h）が同時に該当する場合は、最も直近の1件だけ出す。
        # 古いほうは送信済みとして記録し、後から出さない。
        deadline_due = [d for d in due if d[0].startswith("deadline_")]
        if len(deadline_due) > 1:
            latest = max(deadline_due, key=lambda d: d[1])
            for key, _at in deadline_due:
                if key != latest[0]:
                    sent[f"{lid}:{key}"] = "suppressed:" + now.isoformat()
            due = [d for d in due if not d[0].startswith("deadline_") or d[0] == latest[0]]
        retailer = ev.get("retailer_name") or ev.get("retailer")
        for key, at in due:
            out.append({"lottery_id": lid, "milestone": key, "label": labels[key],
                        "fires_at": at.isoformat(), "tcg": ev.get("tcg"),
                        "product_name": ev.get("product_name"), "retailer": retailer,
                        "entry_url": ev.get("entry_url"), "source_url": ev.get("source_url"),
                        "message": f"{ev.get('product_name')}（{retailer}） {labels[key]}"})
            sent[f"{lid}:{key}"] = now.isoformat()
    ledger["sent"] = sent
    return out, ledger


def archive_counts(history: list[dict]) -> dict:
    return {"total": len(history),
            "ended": sum(1 for h in history if h.get("status") == L_ENDED)}
