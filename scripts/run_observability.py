"""実行（run）の観測性: 予定からの開始の遅れ・所要時間を記録する（Wave 7e-1）。

GitHub Actions の定時（schedule）の実行は、予定の時刻より数時間遅れて始まる（実測 4〜8 時間）。その遅れと所要時間を、実行ごとに記録する。

- `start`（実行の最初の step）: 予定の時刻・開始の時刻・きっかけ・試行回数・lane を非公開の `.private/ops/run_timing_<lane>.json` に書く
- `finish`（公開の前の step）: 所要時間を計算し、**公開してよい項目だけ**を `exports/ops/run_timing_<lane>.json` に書く

公開してよいのは last_run_at・runtime_seconds・schedule_delay_seconds・trigger・lane だけ（固定の語彙・数値・時刻）。
例外の文面・URL・取得元の詳細・候補の詳細は書かない。

schedule_delay_seconds = started_at - scheduled_for。**手動の実行（workflow_dispatch）と再実行（run_attempt が 2 以上）は null**
（予定がない・再実行は元の予定からの遅れではない）。scheduled_for は `github.event.schedule`（cron の文字列）から、開始の時刻より前の最後の
予定の時刻を計算する（単純な「分 時 * * *」の cron だけ。読めなければ null）。将来の Fast Lane の run（別の cron・別の lane）からも
同じ形で記録できるように、lane ごとにファイルを分ける。

この script は失敗しても実行を止めない（常に終了コード 0。例外は型名だけを出す）。通信しない。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
PUBLIC_KEYS = ("last_run_at", "runtime_seconds", "schedule_delay_seconds", "trigger", "lane")
TRIGGERS = ("schedule", "manual", "other")
_LANE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,15}$")
MAX_RUNTIME_SECONDS = 2 * 86400              # これを超える所要時間は壊れた値として捨てる（null）


def lane_ok(lane) -> str | None:
    return lane if isinstance(lane, str) and _LANE_RE.match(lane) else None


def parse_daily_cron(expr) -> tuple[int, int] | None:
    """「M H * * *」（毎日 1 回。数字だけ）の (分, 時)。それ以外の cron（複数・間隔・曜日つき）は None。"""
    parts = str(expr or "").split()
    if len(parts) != 5 or parts[2:] != ["*", "*", "*"]:
        return None
    if not (parts[0].isascii() and parts[0].isdigit() and parts[1].isascii() and parts[1].isdigit()):
        return None
    m, h = int(parts[0]), int(parts[1])
    return (m, h) if 0 <= m <= 59 and 0 <= h <= 23 else None


def scheduled_for(cron, started_at: datetime | None) -> datetime | None:
    """開始の時刻より前の最後の予定の時刻（UTC）。cron が読めない・開始の時刻が無いなら None。"""
    mh = parse_daily_cron(cron)
    if mh is None or not isinstance(started_at, datetime):
        return None
    s = started_at if started_at.tzinfo else started_at.replace(tzinfo=UTC)
    s = s.astimezone(UTC)
    cand = s.replace(hour=mh[1], minute=mh[0], second=0, microsecond=0)
    return cand - timedelta(days=1) if cand > s else cand


def trigger_of(event_name) -> str:
    return {"schedule": "schedule", "workflow_dispatch": "manual"}.get(str(event_name or ""), "other")


def run_attempt_of(value) -> int | None:
    s = str(value or "").strip()
    return int(s) if s.isascii() and s.isdigit() and 1 <= int(s) <= 1000 else None


def schedule_delay_seconds(*, trigger: str, run_attempt, scheduled_for_: datetime | None, started_at: datetime | None):
    """予定からの開始の遅れ（秒）。schedule の最初の試行だけ。手動・再実行・予定が読めない・開始が予定より前は None。"""
    if trigger != "schedule" or run_attempt != 1 or scheduled_for_ is None or started_at is None:
        return None
    d = int((started_at.astimezone(UTC) - scheduled_for_.astimezone(UTC)).total_seconds())
    return d if d >= 0 else None


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(dt, datetime) else None


def _parse(value) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def start_record(env: dict, now: datetime, lane: str) -> dict:
    """実行の最初の記録（非公開）。env は GITHUB_EVENT_NAME・GITHUB_RUN_ATTEMPT・SCHEDULE_CRON。"""
    trig = trigger_of(env.get("GITHUB_EVENT_NAME"))
    attempt = run_attempt_of(env.get("GITHUB_RUN_ATTEMPT"))
    sched = scheduled_for(env.get("SCHEDULE_CRON"), now) if trig == "schedule" else None
    return {"schema": 1, "lane": lane, "trigger": trig, "run_attempt": attempt,
            "scheduled_for": _iso(sched), "started_at": _iso(now),
            "schedule_delay_seconds": schedule_delay_seconds(trigger=trig, run_attempt=attempt, scheduled_for_=sched, started_at=now)}


def public_record(start: dict | None, finished_at: datetime, lane: str) -> dict:
    """公開してよい項目だけ（許可リスト）。start が無い・壊れていれば、所要時間と遅れは null。"""
    st = start if isinstance(start, dict) else {}
    began = _parse(st.get("started_at"))
    runtime = int((finished_at - began).total_seconds()) if began is not None else None
    if runtime is not None and not (0 <= runtime <= MAX_RUNTIME_SECONDS):
        runtime = None
    delay = st.get("schedule_delay_seconds")
    out = {"last_run_at": _iso(finished_at), "runtime_seconds": runtime,
           "schedule_delay_seconds": delay if isinstance(delay, int) and not isinstance(delay, bool) and delay >= 0 else None,
           "trigger": st.get("trigger") if st.get("trigger") in TRIGGERS else "other", "lane": lane}
    return {k: out[k] for k in PUBLIC_KEYS}


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def cmd_start(root: Path, env: dict, now: datetime, lane: str) -> dict:
    rec = start_record(env, now, lane)
    _write(root / ".private" / "ops" / f"run_timing_{lane}.json", rec)
    return rec


def cmd_finish(root: Path, now: datetime, lane: str) -> dict:
    try:
        st = json.loads((root / ".private" / "ops" / f"run_timing_{lane}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = None
    pub = public_record(st, now, lane)
    _write(root / "exports" / "ops" / f"run_timing_{lane}.json",
           {"schema": 1, "type": "RUN_TIMING", "audience": "public_aggregate", **pub})
    return pub


def main(argv=None, root: Path = ROOT, env: dict | None = None, now: datetime | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    try:
        cmd = args[0] if args else ""
        lane = lane_ok(args[args.index("--lane") + 1]) if "--lane" in args and args.index("--lane") + 1 < len(args) else "daily"
        if cmd not in ("start", "finish") or lane is None:
            print("[run-timing] 使い方: start|finish --lane <name>")
            return 0
        now = now or datetime.now(tz=UTC)
        if cmd == "start":
            r = cmd_start(root, env if env is not None else dict(os.environ), now, lane)
            print(f"[run-timing] start lane={lane} trigger={r['trigger']} schedule_delay_seconds={r['schedule_delay_seconds']}")
        else:
            r = cmd_finish(root, now, lane)
            print(f"[run-timing] finish lane={lane} runtime_seconds={r['runtime_seconds']} schedule_delay_seconds={r['schedule_delay_seconds']}")
    except Exception as exc:  # noqa: BLE001 - 観測は付加の情報。失敗しても実行を止めない（型名だけ出す）
        print(f"[run-timing] 記録に失敗（続行）: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
