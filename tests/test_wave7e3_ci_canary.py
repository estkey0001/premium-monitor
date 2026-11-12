"""Wave 7e-3: CI canary（.github/workflows/ci_canary.yml・scripts/ci_canary/）のテスト。

canary は「外部へ出ない・Secrets を使わない・commit も push もしない」を守る仕組みなので、
(1) workflow の定義がその条件を満たすこと、(2) 通信ガードが実際に止める（許すものは許す）こと、
(3) 合否の判定が違反を見逃さないこと、を確かめる。ネットワークには出ない（遮断は宛先に届く前に起きる）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows" / "ci_canary.yml"
DIR = ROOT / "scripts" / "ci_canary"
GUARD = DIR / "netguard.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def wf_text() -> str:
    return WF.read_text(encoding="utf-8")


# ── workflow の定義 ───────────────────────────────────────────────────

def test_workflow_dispatch_only(wf):
    # YAML 1.1 では `on` が True になる
    on = wf.get("on", wf.get(True))
    assert set(on) == {"workflow_dispatch"}


def test_workflow_read_only_no_secrets_single_job(wf, wf_text):
    assert wf["permissions"] == {"contents": "read"}
    assert "secrets." not in wf_text and "secrets:" not in wf_text
    job = wf["jobs"]["canary"]
    assert set(wf["jobs"]) == {"canary"}
    assert job["timeout-minutes"] == 45
    assert job["env"] == {"TZ": "Asia/Tokyo"}
    assert "strategy" not in job and "matrix" not in wf_text


def test_workflow_python_311_and_checkout_without_credentials(wf):
    steps = wf["jobs"]["canary"]["steps"]
    py = [s for s in steps if str(s.get("uses", "")).startswith("actions/setup-python")]
    assert len(py) == 1 and str(py[0]["with"]["python-version"]) == "3.11"
    co = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(co) == 1 and co[0]["with"]["persist-credentials"] is False


def test_workflow_never_commits_pushes_or_installs_browsers(wf_text):
    code = "\n".join(ln for ln in wf_text.splitlines() if not ln.strip().startswith("#"))
    for bad in ("git commit", "git push", "git add", "git config", "playwright install", "gh ", "--with-deps"):
        assert bad not in code, bad


def test_workflow_guards_scoped_to_pytest_step(wf, wf_text):
    """NODE_OPTIONS・CHROME_BIN は pytest の step の env だけ（GITHUB_ENV に入れると actions の後処理まで遮断される）。"""
    steps = wf["jobs"]["canary"]["steps"]
    pytest_steps = [s for s in steps if "python -m pytest" in str(s.get("run", ""))]
    assert len(pytest_steps) == 1
    env = pytest_steps[0]["env"]
    assert "node_netguard.js" in env["NODE_OPTIONS"] and env["CHROME_BIN"].endswith("chrome_wrapper.sh")
    assert env["GIT_ALLOW_PROTOCOL"] == "file"
    for line in wf_text.splitlines():
        if ">> \"$GITHUB_ENV\"" in line:
            assert "NODE_OPTIONS" not in line and "CHROME_BIN" not in line


def test_workflow_guards_armed_after_dependencies_and_verify_always_runs(wf):
    steps = wf["jobs"]["canary"]["steps"]
    names = [s["name"] for s in steps]
    assert names.index("Install dependencies") < names.index("Arm network guards") < names.index("Run pytest (external requests blocked)")
    verify = steps[names.index("Verify canary conditions")]
    assert verify["if"] == "always()"
    assert steps[-1]["name"] == "Disarm Python guard" and steps[-1]["if"] == "always()"


def test_workflow_passes_pytest_env_keys_and_expects_chrome(wf_text):
    assert "pytest_env_keys.txt" in wf_text and "--pytest-env-keys" in wf_text
    assert "${CANARY_REAL_CHROME:+--expect-chrome}" in wf_text and "${CANARY_HAS_NODE:+--expect-node}" in wf_text
    # 環境変数名だけを記録する（値を出さない）
    assert "cut -d= -f1" in wf_text


def test_workflow_does_not_touch_daily_workflow():
    """本番の定時の workflow とは別ファイル・別の concurrency（定時の実行を待たせない・止めない）。"""
    daily = yaml.safe_load((ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8"))
    can = yaml.safe_load(WF.read_text(encoding="utf-8"))
    assert daily["concurrency"]["group"] != can["concurrency"]["group"]


# ── Python の通信ガード ───────────────────────────────────────────────

def _run_guarded(code: str, log: Path, *, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "CANARY_NETGUARD_LOG": str(log), **(env_extra or {})}
    prog = f"import runpy; runpy.run_path({str(GUARD)!r})\n" + textwrap.dedent(code)
    return subprocess.run([sys.executable, "-I", "-c", prog], capture_output=True, text=True, env=env, timeout=60)


def _records(log: Path) -> list[dict]:
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


@pytest.mark.parametrize("snippet,event", [
    ("socket.create_connection(('203.0.113.1', 80), timeout=1)", "socket.getaddrinfo"),
    ("socket.getaddrinfo('example.com', 443)", "socket.getaddrinfo"),
    ("socket.gethostbyname('example.com')", "socket.gethostbyname"),
    ("socket.socket().connect(('203.0.113.1', 80))", "socket.connect"),
    ("subprocess.run(['curl', '--version'])", "subprocess.net_tool"),
    ("subprocess.run(['git', 'clone', 'https://example.com/x.git', 'y'])", "subprocess.git"),
    ("subprocess.run(['git', 'push', 'git@example.com:x/y.git', 'main'])", "subprocess.git"),
    ("subprocess.run('curl https://example.com', shell=True)", "subprocess.shell_net_tool"),
    ("subprocess.run(['bash', '-c', 'echo a && wget http://example.com'])", "subprocess.shell_net_tool"),
    ("os.system('curl https://example.com')", "subprocess.shell_net_tool"),
    ("subprocess.run('/usr/bin/curl -V', shell=True)", "subprocess.shell_net_tool"),
    ("os.system('/usr/bin/wget http://example.com')", "subprocess.shell_net_tool"),
    ("subprocess.run(['bash', '-lc', 'curl -V'])", "subprocess.shell_net_tool"),
    ("subprocess.run(['sh', '-ec', 'wget http://example.com'])", "subprocess.shell_net_tool"),
    ("subprocess.run(['bash', '-e', '-c', 'echo a; /usr/bin/nc -z 203.0.113.1 80'])", "subprocess.shell_net_tool"),
    ("subprocess.run('git push https://203.0.113.1/x.git', shell=True)", "subprocess.shell_git"),
    ("subprocess.run(['env', 'curl', '-V'])", "subprocess.net_tool"),
    ("subprocess.run(['timeout', '5', 'curl', '-V'])", "subprocess.net_tool"),
    ("subprocess.run([b'curl', b'-V'])", "subprocess.net_tool"),
    ("subprocess.run(['git', '-C', '.', 'push', 'https://203.0.113.1/x.git', 'main'])", "subprocess.git"),
    ("subprocess.run(['git', '-c', 'user.name=x', 'clone', 'ssh://git@203.0.113.1/x.git', 'y'])", "subprocess.git"),
    ("os.posix_spawn('/usr/bin/curl', ['curl', 'x'], {})", "subprocess.net_tool"),
    ("os.execv('/usr/bin/curl', ['curl', 'x'])", "subprocess.net_tool"),
    ("socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendmsg([b'x'], [], 0, ('203.0.113.1', 9))", "socket.sendmsg"),
])
def test_guard_blocks_and_records(tmp_path, snippet, event):
    log = tmp_path / "g.jsonl"
    r = _run_guarded(f"import os, socket, subprocess\ntry:\n    {snippet}\n    print('PASSED_THROUGH')\nexcept OSError as e:\n    print('BLOCKED', 'canary' in str(e))\n", log)
    assert "BLOCKED True" in r.stdout and "PASSED_THROUGH" not in r.stdout, r.stdout + r.stderr
    rec = [x for x in _records(log) if x["kind"] == "violation"]
    assert rec and rec[0]["event"] == event
    assert rec[0]["target"] and "test" in rec[0]


def test_guard_allows_loopback_unix_socket_and_local_git(tmp_path):
    log = tmp_path / "g.jsonl"
    repo = tmp_path / "src"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a").write_text("x")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "add", "a"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "m"], check=True)
    import tempfile
    sock_dir = tempfile.mkdtemp(prefix="cn", dir="/tmp")
    sock_path = Path(sock_dir) / "s"
    r = _run_guarded(f"""
        import socket, subprocess, threading
        srv = socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(1)
        threading.Thread(target=srv.accept, daemon=True).start()
        socket.create_connection(('127.0.0.1', srv.getsockname()[1]), timeout=2).close()
        socket.getaddrinfo('localhost', 80)
        us = socket.socket(socket.AF_UNIX); us.bind({str(sock_path)!r}); us.listen(1)
        c = socket.socket(socket.AF_UNIX); c.connect({str(sock_path)!r})
        assert subprocess.run(['git', 'clone', '-q', {str(repo)!r}, {str(tmp_path / 'dst')!r}]).returncode == 0
        assert subprocess.run(['git', '-C', {str(tmp_path / 'dst')!r}, 'fetch', '-q']).returncode == 0
        # file:// 形式の宛先も許す（ローカルのリポジトリ。GIT_ALLOW_PROTOCOL=file の対象）
        assert subprocess.run(['git', 'clone', '-q', 'file://' + {str(repo)!r}, {str(tmp_path / 'dst2')!r}]).returncode == 0
        assert subprocess.run(['git', '-c', 'core.quotepath=off', '-C', {str(tmp_path / 'dst2')!r}, 'pull', '-q', 'file://' + {str(repo)!r}]).returncode == 0
        print('ALL_ALLOWED')
    """, log)
    assert "ALL_ALLOWED" in r.stdout, r.stdout + r.stderr
    assert [x for x in _records(log) if x["kind"] == "violation"] == []
    assert any(x["kind"] == "installed" for x in _records(log))


def test_guard_allows_ordinary_shell_and_exec(tmp_path):
    """外部通信の道具を含まないシェル・exec・spawn は止めない（テストが普通に使う）。"""
    log = tmp_path / "g.jsonl"
    r = _run_guarded("""
        import os, subprocess
        assert subprocess.run('echo curlish-but-not-curl && echo "scurl"', shell=True, capture_output=True).returncode == 0
        assert os.system('echo hello > /dev/null') == 0
        assert subprocess.run(['bash', '-c', 'echo ok'], capture_output=True).returncode == 0
        assert os.spawnv(os.P_WAIT, '/bin/echo', ['echo', 'x']) == 0
        # 名前に道具の文字を含むだけのもの（ファイル名・単語の一部）は止めない
        assert subprocess.run('cat /dev/null; echo data/curl.txt; echo ncurses wgetter', shell=True, capture_output=True).returncode == 0
        assert subprocess.run(['bash', '-lc', 'echo ok'], capture_output=True).returncode == 0
        assert subprocess.run(['env', 'echo', 'x'], capture_output=True).returncode == 0
        assert subprocess.run(['git', '-C', '.', 'status', '--short'], capture_output=True).returncode in (0, 128)
        assert subprocess.run('git log --oneline -1 || true', shell=True, capture_output=True).returncode == 0
        print('ALL_ALLOWED')
    """, log)
    assert "ALL_ALLOWED" in r.stdout, r.stdout + r.stderr
    assert [x for x in _records(log) if x["kind"] == "violation"] == []


def test_guard_blocks_spawn_of_net_tool_in_the_child(tmp_path):
    """os.spawnv は fork した子で exec する。子が遮断されて 127 で終わり（親に例外は出ない）、違反は記録される。"""
    log = tmp_path / "g.jsonl"
    r = _run_guarded("import os\nprint('RC', os.spawnv(os.P_WAIT, '/usr/bin/curl', ['curl', '--version']))\n", log)
    assert "RC 127" in r.stdout, r.stdout + r.stderr
    assert any(x["kind"] == "violation" and x["event"] == "subprocess.net_tool" for x in _records(log))


@pytest.mark.skipif(not hasattr(socket, "AF_NETLINK"), reason="AF_NETLINK は Linux だけ（CI の ubuntu で動く）")
def test_guard_allows_non_ip_socket_address_tuple(tmp_path):
    """アドレスが整数の tuple の非 IP ソケット（netlink）を、外部通信として誤って違反にしない。"""
    log = tmp_path / "g.jsonl"
    r = _run_guarded("""
        import socket
        s = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 0)
        try:
            s.connect((0, 0))
        except OSError as e:
            assert 'canary' not in str(e), e
        print('NOT_BLOCKED')
    """, log)
    assert "NOT_BLOCKED" in r.stdout, r.stdout + r.stderr
    assert [x for x in _records(log) if x["kind"] == "violation"] == []


def test_guard_sets_git_allow_protocol_file(tmp_path):
    """env を空にした子にもガード（.pth）が入って、git の通信は file だけになる。"""
    log = tmp_path / "g.jsonl"
    env = {k: v for k, v in os.environ.items() if k != "GIT_ALLOW_PROTOCOL"}
    r = _run_guarded("import os; print(os.environ.get('GIT_ALLOW_PROTOCOL'))", log, env_extra=env)
    assert r.stdout.strip() == "file"


def test_guard_records_current_test_id_and_no_secrets(tmp_path):
    log = tmp_path / "g.jsonl"
    _run_guarded("import socket\ntry:\n    socket.getaddrinfo('example.com', 443)\nexcept OSError:\n    pass\n", log,
                 env_extra={"PYTEST_CURRENT_TEST": "tests/x.py::t (call)", "SOME_TOKEN": "s3cr3t-value"})
    text = log.read_text(encoding="utf-8")
    assert "tests/x.py::t" in text and "s3cr3t-value" not in text


def test_guard_is_noop_without_log_env(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "CANARY_NETGUARD_LOG"}
    prog = f"import runpy, sys; runpy.run_path({str(GUARD)!r}); print(getattr(sys, '_canary_netguard_installed', False))"
    r = subprocess.run([sys.executable, "-S", "-I", "-c", prog], capture_output=True, text=True, env=env, timeout=30)
    assert r.stdout.strip() == "False"


def test_pth_style_boot_applies_to_child_python_with_empty_env(tmp_path):
    """.pth で埋め込んだ記録先は、env を空にして起動した子プロセスにも効く（env に頼らない）。"""
    log = tmp_path / "g.jsonl"
    child = tmp_path / "child.py"
    child.write_text(
        f"import os; os.environ.setdefault('CANARY_NETGUARD_LOG', {str(log)!r}); import runpy; runpy.run_path({str(GUARD)!r})\n"
        "import socket\n"
        "try:\n    socket.getaddrinfo('example.com', 1)\nexcept OSError:\n    print('BLOCKED')\n")
    # -S: site（.pth）を読まない。CI の canary 本体のガード（.pth）が先に入ると、この自己テストの違反が CI 全体の記録に混ざるため
    r = subprocess.run([sys.executable, "-S", "-I", str(child)], capture_output=True, text=True, env={}, timeout=60)
    assert "BLOCKED" in r.stdout, r.stdout + r.stderr
    assert any(x["kind"] == "violation" for x in _records(log))


def test_guard_installs_once_per_process(tmp_path):
    log = tmp_path / "g.jsonl"
    _run_guarded(f"import runpy; runpy.run_path({str(GUARD)!r}); runpy.run_path({str(GUARD)!r})\n", log)
    assert len([x for x in _records(log) if x["kind"] == "installed"]) == 1


def test_loopback_host_classification():
    g = _load("canary_netguard_unit", GUARD)
    for h in (None, "", "localhost", "127.0.0.1", "127.9.9.9", "::1", "[::1]", "::ffff:127.0.0.1", b"localhost"):
        assert g.is_loopback_host(h), h
    for h in ("example.com", "203.0.113.1", "10.0.0.1", "0.0.0.0", "192.168.1.1", "::ffff:8.8.8.8", "localhost.example.com", "evillocalhost", "foo.localhost", "notlocalhost", 80):
        assert not g.is_loopback_host(h), h


# ── Node の通信ガード ─────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い")
def test_node_guard_blocks_external_allows_loopback(tmp_path):
    log = tmp_path / "n.jsonl"
    code = """
    const net=require('net'),dns=require('dns');
    const srv=net.createServer(s=>s.on('error',()=>{})).listen(0,'127.0.0.1',()=>{
      const c=net.connect(srv.address().port,'127.0.0.1');
      c.on('connect',()=>{
        c.destroy(); srv.close(); const out=[];
        for (const f of [()=>net.connect(80,'203.0.113.1'),()=>net.connect({host:'203.0.113.1',port:80}),()=>dns.lookup('example.com',()=>{})]) {
          try { f(); out.push('PASSED_THROUGH'); } catch(e) { out.push(e.code); }
        }
        console.log(out.join(','));
        setTimeout(()=>process.exit(0),100);
      });
    });
    """
    env = {**os.environ, "CANARY_NODE_LOG": str(log)}
    r = subprocess.run(["node", f"--require={DIR / 'node_netguard.js'}", "-e", code], capture_output=True, text=True, env=env, timeout=60)
    assert r.stdout.strip() == "ECANARYBLOCKED,ECANARYBLOCKED,ECANARYBLOCKED", r.stdout + r.stderr
    assert len([x for x in _records(log) if x["kind"] == "violation"]) == 3


@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い")
def test_node_guard_noop_without_log_env():
    env = {k: v for k, v in os.environ.items() if k != "CANARY_NODE_LOG"}
    r = subprocess.run(["node", f"--require={DIR / 'node_netguard.js'}", "-e", "console.log(typeof require('net').connect)"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.stdout.strip() == "function"


# ── Chrome の hermetic wrapper ────────────────────────────────────────

def test_chrome_wrapper_forces_resolver_rules_after_callers_args_and_fails_closed(tmp_path):
    text = (DIR / "chrome_wrapper.sh").read_text(encoding="utf-8")
    exec_line = text[text.index("exec "):]
    # 呼び出し側の引数（"$@"）より後ろに付ける = テストが別の規則を渡しても上書きできない
    assert exec_line.index('"$@"') < exec_line.index("--host-resolver-rules") < exec_line.index("--proxy-server")
    assert "MAP * ~NOTFOUND" in exec_line
    # IP リテラルは名前解決の規則を通らないので、プロキシも死んだローカルのポートへ向ける（--no-proxy-server にしない）
    assert 'socks5://127.0.0.1:9' in exec_line and "--no-proxy-server" not in exec_line
    r = subprocess.run(["bash", str(DIR / "chrome_wrapper.sh"), "--version"], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"]}, timeout=30)
    assert r.returncode == 127  # 本物の Chrome が無いときは起動しない（素のブラウザへ落ちない）


def test_chrome_wrapper_refuses_non_executable_real_chrome(tmp_path):
    f = tmp_path / "not_exec"
    f.write_text("#!/usr/bin/env bash\necho RAN\n")
    f.chmod(0o644)
    r = subprocess.run(["bash", str(DIR / "chrome_wrapper.sh")], capture_output=True, text=True, timeout=30,
                       env={"PATH": os.environ["PATH"], "CANARY_REAL_CHROME": str(f)})
    assert r.returncode == 127 and "RAN" not in r.stdout


def test_chrome_wrapper_is_executable_in_repo():
    """Linux の CI で chmod +x が mode の変更として git status に出ると repository_mutation_zero が誤って FAIL する。"""
    assert os.access(DIR / "chrome_wrapper.sh", os.X_OK)


def test_chrome_wrapper_passes_args_and_logs_launch(tmp_path):
    fake = tmp_path / "fakechrome"
    fake.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n")
    fake.chmod(0o755)
    log = tmp_path / "c.jsonl"
    r = subprocess.run(["bash", str(DIR / "chrome_wrapper.sh"), "--headless=new", "--host-resolver-rules=MAP a 127.0.0.1"],
                       capture_output=True, text=True, timeout=30,
                       env={"PATH": os.environ["PATH"], "CANARY_REAL_CHROME": str(fake), "CANARY_CHROME_LOG": str(log)})
    args = r.stdout.splitlines()
    assert args[0] == "--headless=new"
    assert args.index("--host-resolver-rules=MAP a 127.0.0.1") < [i for i, a in enumerate(args) if a.startswith("--host-resolver-rules=MAP *")][0]
    last_rule = [a for a in args if a.startswith("--host-resolver-rules")][-1]
    assert last_rule.startswith("--host-resolver-rules=MAP * ~NOTFOUND")  # 最後の指定が勝つ
    assert json.loads(log.read_text().splitlines()[0])["kind"] == "chrome_launch"


# ── 合否の判定（verify.py）────────────────────────────────────────────

@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    def g(*a):
        return subprocess.run(["git", *a], cwd=r, capture_output=True, text=True, env=env, check=True).stdout.strip()
    g("init", "-q")
    (r / "src.py").write_text("x = 1\n")
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / ".github" / "workflows" / "daily_lp.yml").write_text("env:\n  K: ${{ secrets.MY_SECRET_KEY }}\n")
    g("add", "-A")
    g("commit", "-qm", "init")
    _GIT[str(r)] = g
    return r


_GIT: dict = {}


def _g(repo, *a):
    return _GIT[str(repo)](*a)


def _eval(V, repo, tmp_path, *, py=None, node=None, env=None, allow=(), head=None):
    gl = tmp_path / "py.jsonl"
    nl = tmp_path / "node.jsonl"
    gl.write_text("\n".join(json.dumps(x) for x in (py if py is not None else [{"kind": "installed", "pid": 1}])) + "\n")
    nl.write_text("\n".join(json.dumps(x) for x in (node or [])) + ("\n" if node else ""))
    return V.evaluate(repo, start_head=head or _g(repo, "rev-parse", "HEAD"), guard_log=str(gl), node_log=str(nl),
                      chrome_log=None, allow=list(allow), env=env or {})


def _failed(res):
    return {c["check"] for c in res["checks"] if not c["ok"]}


def test_verify_passes_on_clean_run(repo, tmp_path):
    V = _load("canary_verify_unit", DIR / "verify.py")
    res = _eval(V, repo, tmp_path)
    assert res["ok"], res


def test_verify_fails_on_each_violation(repo, tmp_path):
    V = _load("canary_verify_unit2", DIR / "verify.py")
    base = lambda **kw: _failed(_eval(V, repo, tmp_path, **kw))  # noqa: E731

    assert base(py=[{"kind": "installed", "pid": 1}, {"kind": "violation", "event": "socket.getaddrinfo", "target": "x.com"}]) == {"python_external_requests_zero"}
    assert base(py=[]) == {"python_guard_active"}                       # ガードが入っていなければ通さない（空の記録を成功にしない）
    assert base(py=[{"kind": "installed"}, {"kind": "hook_error", "event": "e"}]) == {"python_external_requests_zero"}
    assert base(node=[{"kind": "violation", "event": "net.connect", "target": "x.com"}]) == {"node_external_requests_zero"}
    assert base(env={"MY_SECRET_KEY": "v"}) == {"secrets_access_zero"}   # daily_lp.yml が参照する Secrets 名が環境にあれば違反
    assert base(head="0" * 40) == {"git_commit_zero"}

    (repo / "src.py").write_text("x = 2\n")                              # ソースの変更
    assert base() == {"repository_mutation_zero"}
    assert base(allow=["src.py"]) == set()                               # 許可リストにあるものだけ通る
    _g(repo, "checkout", "--", "src.py")
    (repo / "new_generated.txt").write_text("x")                         # 想定外の生成物
    assert base() == {"repository_mutation_zero"}
    (repo / "new_generated.txt").unlink()

    _g(repo, "config", "http.https://github.com/.extraheader", "AUTHORIZATION: basic x")
    assert base() == {"git_no_credentials_for_push"}
    _g(repo, "config", "--unset", "http.https://github.com/.extraheader")


def test_verify_main_exit_code_reflects_result(repo, tmp_path, monkeypatch):
    # CI の pytest の step には GITHUB_STEP_SUMMARY がある。main() が追記すると、本物のジョブサマリーに偽の PASS / FAIL が残る
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    V = _load("canary_verify_unit_main", DIR / "verify.py")
    head = _g(repo, "rev-parse", "HEAD")
    gl = tmp_path / "py.jsonl"
    gl.write_text(json.dumps({"kind": "installed"}) + "\n")
    args = ["--root", str(repo), "--start-head", head, "--guard-log", str(gl)]
    assert V.main(args) == 0
    (repo / "src.py").write_text("x = 99\n")
    assert V.main(args) == 1


def test_verify_does_not_count_its_own_guard_install(repo, tmp_path):
    """verify 自身も .pth のガードを読んで installed を書く。それを pytest 側のガードの証拠にしない。"""
    V = _load("canary_verify_unit_self", DIR / "verify.py")
    only_self = [{"kind": "installed", "pid": os.getpid()}]
    assert _failed(_eval(V, repo, tmp_path, py=only_self)) == {"python_guard_active"}
    assert _eval(V, repo, tmp_path, py=only_self + [{"kind": "installed", "pid": os.getpid() + 1}])["ok"]


def test_verify_chrome_launches_required_only_when_chrome_exists(repo, tmp_path):
    V = _load("canary_verify_unit_chrome", DIR / "verify.py")
    gl = tmp_path / "py.jsonl"
    gl.write_text(json.dumps({"kind": "installed", "pid": 1}) + "\n")
    cl = tmp_path / "chrome.jsonl"
    cl.write_text("")
    head = _g(repo, "rev-parse", "HEAD")
    kw = dict(start_head=head, guard_log=str(gl), node_log=None, chrome_log=str(cl), allow=[], env={})
    assert V.evaluate(repo, **kw)["ok"]                                              # Chrome が無い実行は情報だけ
    assert _failed(V.evaluate(repo, expect_chrome=True, **kw)) == {"chrome_hermetic_launches"}
    cl.write_text(json.dumps({"kind": "chrome_launch", "pid": 2}) + "\n")
    assert V.evaluate(repo, expect_chrome=True, **kw)["ok"]


def test_verify_checks_secret_names_in_pytest_step_env(repo, tmp_path):
    V = _load("canary_verify_unit_envkeys", DIR / "verify.py")
    gl = tmp_path / "py.jsonl"
    gl.write_text(json.dumps({"kind": "installed", "pid": 1}) + "\n")
    head = _g(repo, "rev-parse", "HEAD")
    kw = dict(start_head=head, guard_log=str(gl), node_log=None, chrome_log=None, allow=[])
    # verify の step の環境が空でも、pytest の step の環境に Secrets 名があれば違反（verify の環境だけを見ない）
    assert _failed(V.evaluate(repo, env={}, pytest_env_keys=["PATH", "MY_SECRET_KEY"], **kw)) == {"secrets_access_zero"}
    assert V.evaluate(repo, env={"MY_SECRET_KEY": "v"}, pytest_env_keys=["PATH"], **kw)["ok"]


def test_verify_node_guard_required_only_when_node_exists(repo, tmp_path):
    V = _load("canary_verify_unit_node", DIR / "verify.py")
    gl = tmp_path / "py.jsonl"
    gl.write_text(json.dumps({"kind": "installed", "pid": 1}) + "\n")
    nl = tmp_path / "node.jsonl"
    nl.write_text("")
    head = _g(repo, "rev-parse", "HEAD")
    kw = dict(start_head=head, guard_log=str(gl), node_log=str(nl), chrome_log=None, allow=[], env={})
    assert V.evaluate(repo, **kw)["ok"]                                                  # node が無い実行は要求しない
    assert _failed(V.evaluate(repo, expect_node=True, **kw)) == {"node_external_requests_zero"}  # 記録が空は通さない
    nl.write_text(json.dumps({"kind": "installed", "pid": 2}) + "\n")
    assert V.evaluate(repo, expect_node=True, **kw)["ok"]


def test_verify_known_test_write_is_allowed_only_for_that_file(repo, tmp_path):
    V = _load("canary_verify_unit3", DIR / "verify.py")
    p = repo / "exports" / "api_automation"
    p.mkdir(parents=True)
    (p / "collection.json").write_text("{}")
    assert _eval(V, repo, tmp_path)["ok"]
    (p / "other.json").write_text("{}")
    assert _failed(_eval(V, repo, tmp_path)) == {"repository_mutation_zero"}


def test_verify_flags_secrets_reference_in_canary_workflow(repo, tmp_path):
    V = _load("canary_verify_unit4", DIR / "verify.py")
    (repo / ".github" / "workflows" / "ci_canary.yml").write_text("steps:\n  - run: echo ${{ secrets.X }}\n")
    _g(repo, "add", "-A")
    _g(repo, "commit", "-qm", "wf")
    assert _failed(_eval(V, repo, tmp_path)) == {"canary_workflow_no_secrets_reference"}


def test_verify_main_appends_summary_only_when_env_set(repo, tmp_path, monkeypatch):
    V = _load("canary_verify_unit_summary", DIR / "verify.py")
    head = _g(repo, "rev-parse", "HEAD")
    gl = tmp_path / "py.jsonl"
    gl.write_text(json.dumps({"kind": "installed", "pid": 1}) + "\n")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert V.main(["--root", str(repo), "--start-head", head, "--guard-log", str(gl)]) == 0
    assert "## CI Canary: PASS" in summary.read_text(encoding="utf-8")


def test_verify_output_has_no_secret_values(repo, tmp_path, capsys):
    V = _load("canary_verify_unit5", DIR / "verify.py")
    res = _eval(V, repo, tmp_path, env={"MY_SECRET_KEY": "s3cr3t-value"})
    assert "s3cr3t-value" not in json.dumps(res, ensure_ascii=False)


def test_canary_adds_no_secret_names_or_personal_paths():
    """公開リポジトリなので、canary の一式に絶対パス・個人名を残さない。"""
    blob = "\n".join(p.read_text(encoding="utf-8") for p in list(DIR.iterdir()) + [WF] if p.is_file())
    assert not re.search(r"/Users/[A-Za-z0-9_.-]+", blob)
