"""CI canary の合否判定（標準ライブラリだけ。通信しない・Secrets を読まない）。

pytest の後に実行し、次を確かめる。1 つでも外れたら終了コード 1。
  1. Python の通信ガードが実際に入っていた（installed >= 1）かつ違反 0
  2. Node の通信ガードの違反 0
  3. HEAD が開始時から動いていない（commit 0）／認証情報（extraheader）が .git/config に残っていない（push できない）
  4. 作業ツリーの変更が、許可リスト（既知の書き込み）だけ（リポジトリのソースの変更 0・想定外の生成物 0）
  5. daily_lp.yml が参照する Secrets の名前が、環境変数に 1 つも無い／canary の workflow が secrets を参照しない
結果は標準出力と、あれば $GITHUB_STEP_SUMMARY に書く（宛先のホスト名だけ。内容・URL のパスは書かない）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# pytest が実行のたびに書き換える既知のファイル（tests/ が書く）。ここに無い変更はすべて違反として扱う。
KNOWN_TEST_WRITES = ("exports/api_automation/collection.json",)


def read_jsonl(path: str | None) -> list[dict]:
    rows: list[dict] = []
    if not path or not Path(path).exists():
        return rows
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            rows.append({"kind": "unparsable_log_line"})
    return rows


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False).stdout


def porcelain_paths(root: Path) -> list[str]:
    out = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    paths = []
    for line in out.splitlines():
        if len(line) > 3:
            p = line[3:]
            if " -> " in p:  # rename
                p = p.split(" -> ", 1)[1]
            paths.append(p.strip().strip('"'))
    return paths


def referenced_secret_names(root: Path) -> list[str]:
    names: set[str] = set()
    wf = root / ".github" / "workflows"
    if wf.is_dir():
        for f in wf.glob("*.yml"):
            if f.name == "ci_canary.yml":
                continue
            names.update(re.findall(r"secrets\.([A-Za-z0-9_]+)", f.read_text(encoding="utf-8")))
    names.discard("GITHUB_TOKEN")
    return sorted(names)


def evaluate(root: Path, *, start_head: str, guard_log: str | None, node_log: str | None,
             chrome_log: str | None, allow: list[str], env: dict[str, str],
             expect_chrome: bool = False, expect_node: bool = False, pytest_env_keys: list[str] | None = None) -> dict:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    py = read_jsonl(guard_log)
    # verify 自身も .pth のガードを読むので、自分の pid の installed は数えない（pytest 側のガードが入っていた証拠にならない）
    py_inst = sum(1 for r in py if r.get("kind") == "installed" and r.get("pid") != os.getpid())
    py_viol = [r for r in py if r.get("kind") in ("violation", "hook_error", "unparsable_log_line")]
    add("python_guard_active", py_inst >= 1, f"installed={py_inst}")
    add("python_external_requests_zero", not py_viol,
        "0" if not py_viol else "; ".join(sorted({f"{r.get('event', r.get('kind'))}→{r.get('target', '')}" for r in py_viol}))[:600])

    nd = read_jsonl(node_log)
    nd_viol = [r for r in nd if r.get("kind") in ("violation", "unparsable_log_line")]
    nd_inst = sum(1 for r in nd if r.get("kind") == "installed")
    # node がある実行（テストが node を使う）で、Node のガードが 1 度も入っていなければ、記録が空でも通さない
    add("node_external_requests_zero", not nd_viol and (nd_inst >= 1 if expect_node else True),
        f"installed={nd_inst} violations={len(nd_viol)}"
        + ("" if not nd_viol else " " + "; ".join(sorted({str(r.get('target', '')) for r in nd_viol}))[:400]))

    ch = read_jsonl(chrome_log)
    launches = sum(1 for r in ch if r.get("kind") == "chrome_launch")
    # 本物の Chrome がある実行で wrapper の起動が 0 なら、ブラウザのテストが走っていない（全 skip）か wrapper を通っていない
    add("chrome_hermetic_launches", (launches > 0) if expect_chrome else True,
        f"launches={launches}" + ("" if expect_chrome else "（Chrome が無い実行。情報）"))

    head = git(root, "rev-parse", "HEAD").strip()
    add("git_commit_zero", bool(start_head) and head == start_head, f"head_unchanged={head == start_head}")
    cred = git(root, "config", "--get-regexp", r"http\..*extraheader").strip()
    add("git_no_credentials_for_push", cred == "", "extraheader なし" if cred == "" else "認証ヘッダが .git/config に残っている")

    allowed = set(KNOWN_TEST_WRITES) | set(allow)
    changed = porcelain_paths(root)
    unexpected = [p for p in changed if p not in allowed]
    add("repository_mutation_zero", not unexpected,
        f"想定外 {len(unexpected)} 件" + ("" if not unexpected else ": " + ", ".join(unexpected[:10]))
        + f"／既知の書き込み {len([p for p in changed if p in allowed])} 件（{', '.join(sorted(allowed & set(changed))) or 'なし'}）")

    # pytest の step の環境変数名（値は記録しない）があればそれで、無ければ verify の step の環境で照合する
    present = set(pytest_env_keys) if pytest_env_keys is not None else {k for k, val in env.items() if val}
    leaked = [n for n in referenced_secret_names(root) if n in present]
    add("secrets_access_zero", not leaked, "環境変数に存在する Secrets 名: " + (", ".join(leaked) if leaked else "なし"))
    wf = root / ".github" / "workflows" / "ci_canary.yml"
    uses = wf.exists() and re.search(r"\bsecrets\.", wf.read_text(encoding="utf-8")) is not None
    add("canary_workflow_no_secrets_reference", not uses, "参照あり" if uses else "参照なし")

    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--start-head", required=True)
    ap.add_argument("--guard-log")
    ap.add_argument("--node-log")
    ap.add_argument("--chrome-log")
    ap.add_argument("--allow-modified", action="append", default=[])
    ap.add_argument("--expect-node", action="store_true", help="node がある実行（Node のガードが 1 回以上入っていること）")
    ap.add_argument("--expect-chrome", action="store_true", help="本物の Chrome がある実行（wrapper の起動が 1 回以上あること）")
    ap.add_argument("--pytest-env-keys", help="pytest の step の環境変数名の一覧（1 行 1 件。値は含まない）")
    a = ap.parse_args(argv)

    res = evaluate(Path(a.root).resolve(), start_head=a.start_head, guard_log=a.guard_log, node_log=a.node_log,
                   chrome_log=a.chrome_log, allow=a.allow_modified, env=dict(os.environ), expect_chrome=a.expect_chrome, expect_node=a.expect_node,
                   pytest_env_keys=(Path(a.pytest_env_keys).read_text(encoding="utf-8").split() if a.pytest_env_keys else None))
    lines = ["## CI Canary: " + ("PASS" if res["ok"] else "FAIL"), ""]
    lines += [f"- {'✅' if c['ok'] else '❌'} `{c['check']}` — {c['detail']}" for c in res["checks"]]
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
