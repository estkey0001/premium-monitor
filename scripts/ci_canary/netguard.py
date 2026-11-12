"""CI canary 用の外部通信の遮断・記録（Python。標準ライブラリだけ・Secrets を読まない）。

`sys.addaudithook` で、ループバック（127.0.0.0/8・::1・localhost・UNIX ソケット）以外への
接続・名前解決・送信と、外部通信の道具（curl・wget・ssh など）・git の push / fetch / pull / clone の起動を
**実行前に止め**（例外を投げる）、違反を 1 行の JSON で記録する。
フックは取り外せない（プロセスの終わりまで有効）。

使い方: site-packages の `.pth` から `runpy.run_path` で読み込む（すべての Python プロセスに効く。
env を空にして起動した子プロセスにも効くよう、記録先は .pth に埋め込む）。
記録先が未設定のときは何もしない。

記録するもの: 違反の種別・イベント名・宛先のホスト（ポートと URL のパスは書かない）・pid。
通信の内容・認証情報は記録しない。
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import sys

_LOG_ENV = "CANARY_NETGUARD_LOG"

# 外部通信を行う道具（起動そのものを違反にする）
_NET_TOOLS = {"curl", "wget", "ssh", "scp", "sftp", "nc", "ncat", "netcat", "telnet", "ftp", "rsync"}
# シェル経由（`sh -c "curl …"`・os.system）のコマンド文字列に、外部通信の道具の名前が単語として含まれるか
# パスつき（/usr/bin/curl）も見る。`scurl`・`curlish`・`data/curl.txt` は見ない
_NET_TOOL_WORD = re.compile(r"(?<![\w.-])(?:\S*/)?(?:" + "|".join(sorted(_NET_TOOLS)) + r")(?![\w-]|\.[A-Za-z0-9])")
# シェル文字列の中の git の外部操作（URL 形式の宛先。file:// は許す）
_SHELL_GIT_URL = re.compile(r"\bgit\b[^;&|\n]*?\b(?:push|fetch|pull|clone|ls-remote|remote)\b[^;&|\n]*?"
                            r"(?:(?<![\w])(?!file:)[A-Za-z][A-Za-z0-9+.-]*://|[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:)")
# git の外部通信（ローカルの一時リポジトリへの clone / fetch / remote はテストが使うので許す。
# 宛先が URL 形式（https://・ssh://・user@host:path）のものだけを違反にする。URL を渡さない `git push origin` などは、
# verify.py の「HEAD が動かない・認証情報が無い」と、workflow の GIT_ALLOW_PROTOCOL=file が受け持つ）
_GIT_NET_SUBCOMMANDS = {"push", "fetch", "pull", "clone", "ls-remote", "remote"}
_URL_LIKE = re.compile(r"^(?:(?!file:)[A-Za-z][A-Za-z0-9+.-]*://|[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:)")
# git のオプションのうち、値を 1 つ取るもの（値をサブコマンドと取り違えない）
_GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"}
# 別のコマンドを包んで起動するもの（`env curl`・`timeout 5 curl`・`xargs curl`）
_WRAPPERS = {"env", "timeout", "nice", "nohup", "xargs", "sudo", "time", "command", "exec", "busybox", "stdbuf", "setsid"}
# シェルのフラグ。`-c` のほか `-lc`・`-ec`・`-xec` のような連結
_SHELL_C_FLAG = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")


class NetworkBlocked(OSError):
    """canary が外部通信を止めたことを示す（OSError なので、通信失敗として扱うコードは従来どおり動く。違反は記録される）。"""


def is_loopback_host(host) -> bool:
    """ホスト名・IP がループバックか（空・None は「ポートだけ」の指定で、外へ出ないので許す）。"""
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if not isinstance(host, str):
        return False
    h = host.strip().strip("[]").split("%")[0]
    if h in ("", "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool((mapped or ip).is_loopback)


def _first(x):
    return x[0] if isinstance(x, (tuple, list)) and x else x


def _write(path: str, rec: dict) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass  # 記録できないときも通信は止める（止めた事実のほうが重要）


def _violation(path: str, event: str, target) -> None:
    host = _first(target)
    # PYTEST_CURRENT_TEST（テストの ID。例 tests/test_x.py::test_y (call)）は、どのテストが外へ出ようとしたかを特定するために残す
    _write(path, {"kind": "violation", "event": event, "target": str(host)[:200], "pid": os.getpid(),
                  "test": os.environ.get("PYTEST_CURRENT_TEST", "")[:300]})
    raise NetworkBlocked(f"canary: 外部通信を遮断した（{event} → {str(host)[:80]}）")


def _check_shell_command(path: str, cmd: str) -> None:
    m = _NET_TOOL_WORD.search(cmd)
    if m:
        _violation(path, "subprocess.shell_net_tool", os.path.basename(m.group(0)))
    if _SHELL_GIT_URL.search(cmd):
        _violation(path, "subprocess.shell_git", "git (shell)")


def _check_git(path: str, rest: list[str]) -> None:
    """git の引数から、サブコマンドを（-C・-c などの値を飛ばして）取り、URL 形式の宛先を伴う外部操作を違反にする。"""
    i, sub = 0, None
    while i < len(rest):
        a = rest[i]
        if a in _GIT_OPTS_WITH_VALUE:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        sub = a
        break
    if sub in _GIT_NET_SUBCOMMANDS and any(_URL_LIKE.match(a) for a in rest[i + 1:]):
        _violation(path, "subprocess.git", "git " + sub)


def _check_exec(path: str, args) -> None:
    """subprocess.Popen の引数（executable, args, cwd, env）から、外部通信の道具・git の外部操作を見つける。"""
    try:
        argv = list(args[1]) if len(args) > 1 and args[1] else [args[0]]
    except Exception:  # noqa: BLE001
        return
    if not argv:
        return
    argv = [a.decode("utf-8", "replace") if isinstance(a, bytes) else str(a) for a in argv]
    name = os.path.basename(argv[0])
    if name in _NET_TOOLS:
        _violation(path, "subprocess.net_tool", name)
    if name in _WRAPPERS:  # `env curl …`・`timeout 5 curl …`
        for a in argv[1:]:
            if os.path.basename(a) in _NET_TOOLS:
                _violation(path, "subprocess.net_tool", os.path.basename(a))
    if name in ("sh", "bash", "dash", "zsh"):  # shell=True・`bash -c`・`bash -lc`・`sh -ec`（コマンドはフラグの後ろ）
        for i, a in enumerate(argv[1:], start=1):
            if _SHELL_C_FLAG.match(a):
                _check_shell_command(path, " ".join(argv[i + 1:]))
                break
    if name == "git":
        _check_git(path, argv[1:])


def install(log_path: str) -> None:
    """フックを入れる（プロセスごとに 1 回）。"""
    if getattr(sys, "_canary_netguard_installed", False):
        return
    sys._canary_netguard_installed = True  # type: ignore[attr-defined]
    # git の通信はローカル（file）だけ。env を空にして起動した子にも、この .pth のガードが効いて同じ設定が入る
    os.environ.setdefault("GIT_ALLOW_PROTOCOL", "file")
    _write(log_path, {"kind": "installed", "pid": os.getpid()})

    def hook(event: str, args):
        try:
            if event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
                addr = args[1] if len(args) > 1 else None
                # AF_INET / AF_INET6 の (host, port, ...)。str・bytes は UNIX ソケット、先頭が整数の tuple は
                # AF_NETLINK など IP ではないソケット（外へ出ない）なので許す
                if isinstance(addr, tuple) and addr and isinstance(addr[0], (str, bytes)):
                    if not is_loopback_host(addr[0]):
                        _violation(log_path, event, addr[0])
            elif event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr"):
                host = _first(args[0]) if args else None
                if not is_loopback_host(host):
                    _violation(log_path, event, host)
            elif event == "socket.getnameinfo":
                host = _first(args[0]) if args else None
                if not is_loopback_host(host):
                    _violation(log_path, event, host)
            elif event == "subprocess.Popen":
                _check_exec(log_path, args)
            elif event == "os.system":
                _check_shell_command(log_path, str(args[0]) if args else "")
            elif event in ("os.exec", "os.posix_spawn"):
                # (path, argv, env)。外部通信の道具・git の URL 宛先だけを見る（通常の起動は許す）
                _check_exec(log_path, (args[0], args[1] if len(args) > 1 else None))
            elif event == "os.spawn":
                # (mode, path, argv, env)
                _check_exec(log_path, (args[1], args[2] if len(args) > 2 else None))
        except NetworkBlocked:
            raise
        except Exception:  # noqa: BLE001 — フック自身の不具合でテストを壊さない（検知の漏れより実行の継続を優先しない: 記録する）
            _write(log_path, {"kind": "hook_error", "event": event, "pid": os.getpid()})

    sys.addaudithook(hook)


def _boot() -> None:
    path = os.environ.get(_LOG_ENV)
    if path:
        install(path)


_boot()
