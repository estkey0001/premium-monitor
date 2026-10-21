#!/usr/bin/env python3
"""運営者向けの劣化アラート候補を作る（PRODUCTION_HEALTH_ALERT。商品の通知とは別・外部へは送らない）。

入力（読むだけ）: exports/collector_report/latest.json・failure_history.json・exports/official_recheck/history.json
出力: exports/ops/health_alert.json（今回の候補・復旧・有効なアラート）・exports/ops/health_alert_state.json（重複の抑制の状態）
      GitHub Actions の注記（::warning:: / ::error::）と Step Summary（新しい・重くなった・復旧だけ。同じ異常は出し直さない）
使い方: python scripts/operator_health_alert.py [--dry-run]（--dry-run は状態・記録を書かない）
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JST = timezone(timedelta(hours=9))
OUT = ROOT / "exports" / "ops"


def gather_inputs(root: Path = ROOT) -> dict:
    """運営者向けのアラートの入力（読むだけ。通知・Secrets・外部には触れない）。"""
    from scripts.check_collector_quality import OPTIONAL_SHOPS
    from src.market import official_registry as reg
    from src.market.price_quality import HARD_REJECT_REASONS
    from src.ops.health_alert import read_json
    rc = root / "exports" / "collector_report"
    history = (read_json(root / "exports" / "official_recheck" / "history.json", {}) or {}).get("results") or []
    return {"collector": read_json(rc / "latest.json", {}), "failure_history": read_json(rc / "failure_history.json", {}),
            "optional_shops": sorted(OPTIONAL_SHOPS), "hard_reject_reasons": sorted(HARD_REJECT_REASONS),
            "official_status": reg.verification_status(history)}


def run(root: Path = ROOT, now: datetime | None = None, dry_run: bool = False) -> dict:
    from src.ops import health_alert as ha
    from src.utils.atomic_write import write_json_atomic
    now = now or datetime.now(tz=JST)
    out = root / "exports" / "ops"
    inputs = gather_inputs(root)
    current = ha.evaluate(inputs, now)
    state, result = ha.reconcile(ha.read_json(out / "health_alert_state.json", {}), current, now,
                                 ha.unobservable_categories(inputs))
    record = ha.build_record(current, result, now)
    if not dry_run:
        out.mkdir(parents=True, exist_ok=True)
        write_json_atomic(out / "health_alert.json", record)
        write_json_atomic(out / "health_alert_state.json", state)
    return record


def _esc(text) -> str:
    """GitHub Actions のワークフローコマンド（::warning:: など）の本文に入れる文字列のエスケープ。
    レポート由来の文字列（店・理由・詳細）に改行や % が入っても、別のコマンドとして読まれないようにする。"""
    return str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _annotations(record: dict) -> list[str]:
    lines = []
    for c in record["candidates"]:
        level = "error" if c["severity"] == "HIGH" else "warning"
        lines.append(f"::{level}::" + _esc(f"[運営者向け・{c['event']}] {c['title']}（{c['key']}）— {c['details']}"))
    for r in record["recovered"]:
        lines.append("::notice::" + _esc(f"[運営者向け・復旧] {r['key']} は解消しました（{r.get('last_severity')}）"))
    return lines


def _summary(record: dict) -> str:
    rows = ["### 運営者向けの劣化アラート（商品の通知ではない・外部へは送らない）", "",
            f"有効 {record['active_count']} 件（HIGH {record['high']} / WARNING {record['warning']}）・"
            f"新しい・重くなった {len(record['candidates'])} 件・出し直さなかった {record['suppressed']} 件・"
            f"復旧 {len(record['recovered'])} 件", ""]
    if record["candidates"]:
        rows += ["| 重さ | 種類 | 内容 |", "|---|---|---|"]
        rows += [f"| {c['severity']} | {c['event']} {c['key']} | {c['title']} |" for c in record["candidates"]]
    return "\n".join(rows) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="状態・記録を書かない")
    args = ap.parse_args(argv)
    record = run(dry_run=args.dry_run)
    for line in _annotations(record):
        print(line)
    print(f"[operator_health_alert] active={record['active_count']} high={record['high']} warning={record['warning']} "
          f"new={len(record['candidates'])} suppressed={record['suppressed']} recovered={len(record['recovered'])} "
          f"product_notification_candidates=0 external_sends=0")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(_summary(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
