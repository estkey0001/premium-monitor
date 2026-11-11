"""手動 CSV の「値は同じなのに観測日時だけ新しくした」更新を Git の履歴から数える。

使い方:
  python scripts/audit_timestamp_only_updates.py            # 全履歴を監査（件数とコミットを表示）
  python scripts/audit_timestamp_only_updates.py --range HEAD~1..HEAD   # 直近のコミットだけ
  python scripts/audit_timestamp_only_updates.py --worktree # 作業ツリーと HEAD を比べる（コミット前の確認）
終了コード: 違反があれば 1。

手動 CSV に加えて、公式の登録簿 src/market/official_registry.py の VERIFIED_URLS の各商品の checked_on / stock_checked_at も見る。
同じ商品の中身（price・url・price_kind・stock など checked_on と stock_checked_at 以外）が同じなのに日付だけ進み、
差分に新しい確認日（YYYY-MM-DD）を含むコメント行が追加されていないものを TIMESTAMP_ONLY_REGISTRY として報告する。
（再確認 recheck の RECHECK_MATCHED による更新は、登録簿を書き換えず DB 側の値を進めるだけなので、この検査の対象外。）
"""
from __future__ import annotations

import argparse
import ast
import difflib
import fnmatch
import re
import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace
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


REGISTRY_PATH = "src/market/official_registry.py"
TIMESTAMP_ONLY_REGISTRY = "TIMESTAMP_ONLY_REGISTRY"
CHECKED_ON_REGRESSED = "CHECKED_ON_REGRESSED"
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATE_FIELDS = ("checked_on", "stock_checked_at")


def _registry_entries(text: str) -> dict[str, dict]:
    """登録簿のソースから VERIFIED_URLS を読む。{商品ID: {"data": 辞書, "first": 行, "last": 行}}。壊れていれば {}（例外にしない）。"""
    try:
        tree = ast.parse(text or "")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if not any(isinstance(t, ast.Name) and t.id == "VERIFIED_URLS" for t in targets):
            continue
        if not isinstance(node.value, ast.Dict):
            return {}
        out: dict[str, dict] = {}
        for k, v in zip(node.value.keys, node.value.values):
            try:
                key, data = ast.literal_eval(k), ast.literal_eval(v)
            except (ValueError, SyntaxError, TypeError, RecursionError, MemoryError):
                continue
            if isinstance(key, str) and isinstance(data, dict):
                out[key] = {"data": data, "first": k.lineno, "last": v.end_lineno or v.lineno}
        return out
    return {}


def _as_dt(value) -> datetime | None:
    """日付（YYYY-MM-DD）か ISO 日時を比べられる値にする。読めなければ None。"""
    if not isinstance(value, str) or not value.strip():
        return None
    t = value.strip()
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        m = _DATE_RE.match(t)
        if not m:
            return None
        try:
            d = datetime.fromisoformat(m.group(0))
        except ValueError:
            return None
    return d.replace(tzinfo=None) if d.tzinfo is not None else d      # 日付どうしの前後だけを見る（時差は無視）


def _added_comment_lines(old_text: str, new_text: str) -> dict[int, str]:
    """新しいソースで追加された行のうちコメントを含むもの {行番号(1 始まり): コメントの文字列}。"""
    old_lines, new_lines = (old_text or "").splitlines(), (new_text or "").splitlines()
    out: dict[int, str] = {}
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        if tag not in ("insert", "replace"):
            continue
        for j in range(j1, j2):
            line = new_lines[j]
            if line.lstrip().startswith("#"):
                out[j + 1] = line
            else:
                m = re.search(r"\s#", line)
                if m:
                    out[j + 1] = line[m.start():]
    return out


def registry_timestamp_findings(old_text: str, new_text: str) -> list[dict]:
    """登録簿 official_registry.py の旧・新ソースを比べ、根拠の無い「確認日だけの前進」を返す（純関数。壊れたソース・空文字でも例外にしない）。

    商品ごとに checked_on / stock_checked_at を比べる。
    - 前進したのに、他の項目（price・url・price_kind・stock など）が同じで、その商品の範囲（直前の商品の終わりから、その商品の終わりまで）に
      新しい確認日（checked_on または stock_checked_at の日付）を含むコメント行が追加されていない → kind=TIMESTAMP_ONLY_REGISTRY
    - 過去へ戻った（checked_on）→ kind=CHECKED_ON_REGRESSED
    - 価格・URL などが変わった／新しい確認日のコメントが追加された（HUMAN_VERIFIED）／商品が新規追加された → 許す
    再確認（recheck の RECHECK_MATCHED）は登録簿を書き換えず DB 側の値を進めるだけなので、この検査の対象外。
    """
    try:
        old, new = _registry_entries(old_text), _registry_entries(new_text)
        if not old or not new:
            return []
        added = _added_comment_lines(old_text, new_text)
        ordered = sorted(new.items(), key=lambda kv: kv[1]["first"])
        findings: list[dict] = []
        prev_last = 0
        for pid, ent in ordered:
            lo, hi = prev_last + 1, ent["last"]
            prev_last = hi
            if pid not in old:
                continue                                              # 新規追加は許す
            od, nd = old[pid]["data"], ent["data"]
            same_content = ({k: v for k, v in od.items() if k not in _DATE_FIELDS} == {k: v for k, v in nd.items() if k not in _DATE_FIELDS})
            new_dates = {str(nd.get(f))[:10] for f in _DATE_FIELDS
                         if nd.get(f) != od.get(f) and _DATE_RE.match(str(nd.get(f) or ""))}       # 変わった日付だけが根拠の対象
            has_evidence = any(lo <= ln <= hi and any(d in text for d in new_dates) for ln, text in added.items())
            for f in _DATE_FIELDS:
                o_dt, n_dt = _as_dt(od.get(f)), _as_dt(nd.get(f))
                if o_dt is None or n_dt is None or o_dt == n_dt:
                    continue
                if n_dt < o_dt:
                    if f == "checked_on":
                        findings.append({"kind": CHECKED_ON_REGRESSED, "product_id": pid, "field": f, "old": od.get(f), "new": nd.get(f)})
                    continue
                if same_content and not has_evidence:
                    findings.append({"kind": TIMESTAMP_ONLY_REGISTRY, "product_id": pid, "field": f, "old": od.get(f), "new": nd.get(f)})
        return findings
    except Exception:  # noqa: BLE001 - 監査は壊れた入力で落ちない（空として扱う）
        return []


def _registry_violations(old_text: str, new_text: str) -> list:
    """CLI の表示用（key / old_ts / new_ts を持つ）に包む。"""
    return [SimpleNamespace(key=f"{x['kind']} {x['product_id']}.{x['field']}", old_ts=x["old"], new_ts=x["new"])
            for x in registry_timestamp_findings(old_text, new_text)]


def audit_commits(rev_range: str | None) -> list[tuple[str, str, int, list]]:
    args = ["rev-list", "--reverse", "--no-merges"]
    args.append(rev_range or "HEAD")
    out = []
    for c in _git(*args).split():
        parent = _git("rev-parse", f"{c}^").strip()
        if not parent or parent.startswith(c):
            continue
        for path in _git("diff", "--name-only", parent, c).split():
            if path == REGISTRY_PATH:
                v = _registry_violations(_show(parent, path), _show(c, path))
                if v:
                    out.append((c[:8], path, len(v), v))
                continue
            if not _is_manual(path):
                continue
            v = timestamp_only_updates(_show(parent, path), _show(c, path), path)
            if v:
                out.append((c[:8], path, len(v), v))
    return out


def audit_worktree() -> list[tuple[str, str, int, list]]:
    out = []
    for path in _git("diff", "--name-only", "HEAD").split():
        if path != REGISTRY_PATH and not _is_manual(path):
            continue
        new = (ROOT / path).read_text(encoding="utf-8") if (ROOT / path).exists() else ""
        v = _registry_violations(_show("HEAD", path), new) if path == REGISTRY_PATH else timestamp_only_updates(_show("HEAD", path), new, path)
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
