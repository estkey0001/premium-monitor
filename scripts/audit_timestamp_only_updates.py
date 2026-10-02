"""手動 CSV の「値は同じなのに観測日時だけ新しくした」更新を Git の履歴から数える。

使い方:
  python scripts/audit_timestamp_only_updates.py            # 全履歴を監査（件数とコミットを表示）
  python scripts/audit_timestamp_only_updates.py --range HEAD~1..HEAD   # 直近のコミットだけ
  python scripts/audit_timestamp_only_updates.py --worktree # 作業ツリーと HEAD を比べる（コミット前の確認）
終了コード: 違反があれば 1。
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.market.freshness_guard import MANUAL_CSV_GLOBS, timestamp_only_updates  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def _show(rev: str, path: str) -> str:
    r = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _is_manual(path: str) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in MANUAL_CSV_GLOBS)


def audit_commits(rev_range: str | None) -> list[tuple[str, str, int, list]]:
    args = ["rev-list", "--reverse", "--no-merges"]
    args.append(rev_range or "HEAD")
    out = []
    for c in _git(*args).split():
        parent = _git("rev-parse", f"{c}^").strip()
        if not parent or parent.startswith(c):
            continue
        for path in _git("diff", "--name-only", parent, c).split():
            if not _is_manual(path):
                continue
            v = timestamp_only_updates(_show(parent, path), _show(c, path), path)
            if v:
                out.append((c[:8], path, len(v), v))
    return out


def audit_worktree() -> list[tuple[str, str, int, list]]:
    out = []
    for path in _git("diff", "--name-only", "HEAD").split():
        if not _is_manual(path):
            continue
        new = (ROOT / path).read_text(encoding="utf-8") if (ROOT / path).exists() else ""
        v = timestamp_only_updates(_show("HEAD", path), new, path)
        if v:
            out.append(("worktree", path, len(v), v))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--range", dest="rev_range", default=None)
    ap.add_argument("--worktree", action="store_true")
    a = ap.parse_args()
    found = audit_worktree() if a.worktree else audit_commits(a.rev_range)
    total = sum(n for _, _, n, _ in found)
    for commit, path, n, v in found:
        subj = _git("log", "-1", "--format=%ad %s", "--date=short", commit).strip() if commit != "worktree" else ""
        print(f"{commit} {path}: {n}行  {subj}")
        for x in v[:3]:
            print(f"    {x.key}  {x.old_ts} → {x.new_ts}")
    print(f"合計: {len(found)}件の変更 / {total}行")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
