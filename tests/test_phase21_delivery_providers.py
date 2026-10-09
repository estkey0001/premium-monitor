"""Phase 21（配信先の部品・届いたか不明の人による解決・古い基準のファイル）のテスト。

外部への送信はしない（偽の transport だけ。値はすべてダミー）。各テストに否定の対照を付ける。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from _notify_helpers import CLOSED, NOW, OPEN, SONY, FixtureAdapter, SendFail, _diag, gr4, ps5, run
from src.notifiers import adapters as ad
from src.notifiers import outbox as ob

ROOT = Path(__file__).resolve().parent.parent
DUMMY_HOOK = "https://discord.com/api/webhooks/1234567890/dummy-token-for-tests_only"
DUMMY_TOKEN = "123456789:AAdummydummydummydummydummydummy00"


def _rows(d):
    return d["actionability"]["products"]


def _record(**kw):
    st = ob.empty_store()
    ob.observe(st, _rows(_diag(ps5("OUT_OF_STOCK"))), now=NOW, mode=ob.MODE_DRY)
    ob.observe(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_DRY)
    rec = next(iter(st["records"].values()))
    rec.update(kw)
    return rec


# ── 本文（Discord・Telegram） ────────────────────────────────────────────

def test_discord_payload_fields():
    p = ad.DiscordAdapter().build_payload(_record())
    c = p["content"]
    for part in ("購入可能になりました", "商品: PlayStation 5 Pro", "想定純利益: +¥54,870", "ROI: 39.6%", "状態: 購入可能",
                 "確認: ", f"購入する: {SONY}"):
        assert part in c, part
    assert p["allowed_mentions"] == {"parse": []}


def test_telegram_payload_same_meaning():
    rec = _record()
    d, t = ad.DiscordAdapter().build_payload(rec)["content"], ad.TelegramAdapter().build_payload(rec)
    assert t["text"] == d and "parse_mode" not in t and "chat_id" not in t


def test_lottery_payload_has_deadline():
    st = ob.empty_store()
    ob.observe(st, _rows(_diag(gr4(CLOSED))), now=NOW, mode=ob.MODE_DRY)
    ob.observe(st, _rows(_diag(gr4(OPEN))), now=NOW, mode=ob.MODE_DRY)
    rec = next(iter(st["records"].values()))
    c = ad.DiscordAdapter().build_payload(rec)["content"]
    assert "抽選受付が始まりました" in c and "締切: " in c and "抽選に申し込む: https://ricohimagingstore.com/" in c


def test_payload_uses_record_values_only():
    """本文の利益・ROI は記録の値そのまま（配信先の側で計算し直さない）。"""
    c = ad.DiscordAdapter().build_payload(_record(net_profit=12345, roi=0.5))["content"]
    assert "+¥12,345" in c and "ROI: 50.0%" in c


@pytest.mark.parametrize("cls,limit", [(ad.DiscordAdapter, 2000), (ad.TelegramAdapter, 4096)])
def test_payload_length_safe_shortening(cls, limit):
    rec = _record(product="とても長い商品名" * 800)
    a = cls()
    p = a.build_payload(rec)
    text = p[a._text_field()]
    assert len(text) <= limit and text.endswith(SONY) and "+¥54,870" in text and "…" in text
    assert "確認: " not in text                                        # 先に確認の時刻の行を削る
    assert a.validate_payload(p) == []
    short = a.build_payload(_record())[a._text_field()]                # 否定の対照: 短ければ削らない
    assert "確認: " in short and "…" not in short


def test_url_never_cut():
    rec = _record(action_url="https://pur.store.sony.jp/" + "a" * 5000)
    for cls in (ad.DiscordAdapter, ad.TelegramAdapter):
        a = cls()
        assert a.build_payload(rec)[a._text_field()] == ""             # 収まらなければ送らない（URL を切らない）
        assert "empty" in a.validate_payload(a.build_payload(rec))


def test_unicode_preserved():
    rec = _record(product="カメラ「GR Ⅳ」¥%＆😀")
    c = ad.DiscordAdapter().build_payload(rec)["content"]
    assert "カメラ「GR Ⅳ」¥%＆😀" in c and "¥54,870" in c and "39.6%" in c and SONY in c
    assert json.loads(json.dumps({"content": c}, ensure_ascii=False))["content"] == c


# ── 設定・秘密の値 ─────────────────────────────────────────────────────────

def test_validate_config_without_values():
    d, t = ad.DiscordAdapter(), ad.TelegramAdapter()
    assert d.validate_config({}) == ["DISCORD_WEBHOOK_URL:missing"]
    assert d.validate_config({"DISCORD_WEBHOOK_URL": DUMMY_HOOK}) == []
    assert d.validate_config({"DISCORD_WEBHOOK_URL": "http://example.com/x"}) == ["DISCORD_WEBHOOK_URL:invalid_format"]
    assert set(t.validate_config({})) == {"TELEGRAM_BOT_TOKEN:missing", "TELEGRAM_CHAT_ID:missing"}
    assert t.validate_config({"TELEGRAM_BOT_TOKEN": DUMMY_TOKEN, "TELEGRAM_CHAT_ID": "-1001234567890"}) == []
    problems = t.validate_config({"TELEGRAM_BOT_TOKEN": "bad", "TELEGRAM_CHAT_ID": "x"})
    assert all("bad" not in p and ":invalid_format" in p for p in problems)    # 値を返さない


def test_secret_redaction():
    text = f"failed {DUMMY_HOOK} and bot{DUMMY_TOKEN} Bearer abcdefghijklmnopqrstuvwxyz"
    r = ad.redact(text)
    assert "dummy-token" not in r and "AAdummy" not in r and "abcdefghijkl" not in r and "[REDACTED]" in r
    assert ad.redact("ふつうの文 https://pur.store.sony.jp/") == "ふつうの文 https://pur.store.sony.jp/"


def test_payload_with_secret_is_rejected():
    a = ad.DiscordAdapter()
    assert "secret_in_payload" in a.validate_payload({"content": f"x {DUMMY_HOOK}"})


def test_real_send_gate_closed_by_default():
    g = ad.real_send_gate({})
    assert not g["allowed"] and not any(g["checks"].values())
    full = {"NOTIFICATION_REAL_SEND": "true", "NOTIFICATION_DRY_RUN": "false", "NOTIFICATION_PROVIDERS": "discord,telegram",
            "DISCORD_WEBHOOK_URL": DUMMY_HOOK, "TELEGRAM_BOT_TOKEN": DUMMY_TOKEN, "TELEGRAM_CHAT_ID": "-100123"}
    g = ad.real_send_gate(full)
    assert not g["allowed"] and g["checks"]["implemented"] is False   # 商品の通知の送信は無効のまま（Phase 22）
    assert g["checks"]["provider_selected"] is False                  # Discord を含む選択は受け付けない（Phase 22）
    tg = dict(full, NOTIFICATION_PROVIDERS="telegram")
    g = ad.real_send_gate(tg)
    assert not g["allowed"] and all(v for k, v in g["checks"].items() if k != "implemented")
    assert DUMMY_HOOK not in json.dumps(g) and DUMMY_TOKEN not in json.dumps(g)


def test_gate_reports_config_problems_without_values():
    g = ad.real_send_gate({"NOTIFICATION_PROVIDERS": "telegram", "TELEGRAM_BOT_TOKEN": "xyz-secret"})
    assert "xyz-secret" not in json.dumps(g) and g["config_problems"]["telegram"]


# ── 応答の分類・配信先の ID ─────────────────────────────────────────────────

@pytest.mark.parametrize("status,kind", [(200, None), (204, None), (400, ad.FINAL), (401, ad.FINAL), (403, ad.FINAL),
                                         (404, ad.FINAL), (429, ad.RETRYABLE), (503, ad.RETRYABLE),
                                         (500, ad.AMBIGUOUS), (502, ad.AMBIGUOUS), (504, ad.AMBIGUOUS)])
def test_discord_response_classification(status, kind):
    e = ad.DiscordAdapter().classify_response(status, {"Retry-After": "12"} if status == 429 else {})
    assert (e.kind if e else None) == kind
    if status == 429:
        assert e.retry_after == 12


@pytest.mark.parametrize("status,body,kind", [
    (200, {"ok": True, "result": {"message_id": 7}}, None),
    (200, {"ok": False, "error_code": 400, "description": "Bad Request"}, ad.FINAL),
    (403, {"ok": False, "error_code": 403}, ad.FINAL),
    (429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 30}}, ad.RETRYABLE),
    (502, {}, ad.AMBIGUOUS),
    (200, {}, ad.AMBIGUOUS),                                           # 成功の形でない 2xx は届いたか不明
])
def test_telegram_response_classification(status, body, kind):
    e = ad.TelegramAdapter().classify_response(status, {}, body)
    assert (e.kind if e else None) == kind
    if kind == ad.RETRYABLE:
        assert e.retry_after == 30


def test_delivery_ids():
    assert ad.TelegramAdapter().extract_delivery_id(200, {}, {"ok": True, "result": {"message_id": 99}}) == "99"
    assert ad.DiscordAdapter().extract_delivery_id(200, {}, {"id": "112233"}) == "112233"
    assert ad.DiscordAdapter().extract_delivery_id(204, {}, None) == ""     # wait なしの 204 は ID なし


@pytest.mark.parametrize("stage,kind", [("connect", ad.RETRYABLE), ("read", ad.AMBIGUOUS), ("other", ad.AMBIGUOUS)])
def test_timeout_classification(stage, kind):
    def tr(payload, key):
        raise ad.TransportError(stage)
    with pytest.raises(ad.ProviderError) as e:
        ad.DiscordAdapter(tr).send(_record(), "k")
    assert e.value.kind == kind


def test_provider_send_records_delivery_id_through_outbox():
    sent = []

    def tg(payload, key):
        sent.append(payload)
        return 200, {}, {"ok": True, "result": {"message_id": 555}}
    st = ob.empty_store()
    ob.observe(st, _rows(_diag(ps5("OUT_OF_STOCK"))), now=NOW, mode=ob.MODE_LIVE)
    ob.cycle(st, _diag(ps5()), now=NOW, mode=ob.MODE_LIVE, attempt_id="a", channels=["telegram"],
             adapters={"telegram": ad.TelegramAdapter(tg)})
    ch = next(iter(st["records"].values()))["channels"]["telegram"]
    assert ch["status"] == ob.DELIVERED and ch["provider_delivery_id"] == "555" and len(sent) == 1
    assert "chat_id" not in sent[0]


# ── 複数の配信先 ─────────────────────────────────────────────────────────

def test_multi_channel_partial_success():
    calls = {"discord": 0, "telegram": 0}

    def dsc(p, k):
        calls["discord"] += 1
        return 200, {}, {"id": "d1"}

    def tg_fail(p, k):
        calls["telegram"] += 1
        return 503, {}, {"ok": False, "error_code": 503}
    adapters = {"discord": ad.DiscordAdapter(dsc), "telegram": ad.TelegramAdapter(tg_fail)}
    st = ob.empty_store()
    ob.observe(st, _rows(_diag(ps5("OUT_OF_STOCK"))), now=NOW, mode=ob.MODE_LIVE)
    ob.cycle(st, _diag(ps5()), now=NOW, mode=ob.MODE_LIVE, attempt_id="a", channels=["discord", "telegram"],
             adapters=adapters)
    rec = next(iter(st["records"].values()))
    assert rec["channels"]["discord"]["status"] == ob.DELIVERED
    assert rec["channels"]["telegram"]["status"] == ob.FAILED_RETRYABLE
    later = NOW + timedelta(minutes=10)
    adapters["telegram"] = ad.TelegramAdapter(lambda p, k: (calls.__setitem__("telegram", calls["telegram"] + 1),
                                                            (200, {}, {"ok": True, "result": {"message_id": 3}}))[1])
    ob.cycle(st, _diag(ps5(checked=later - timedelta(minutes=5), now=later)), now=later, mode=ob.MODE_LIVE,
             attempt_id="b", channels=["discord", "telegram"], adapters=adapters)
    assert calls == {"discord": 1, "telegram": 2}                       # 届いた Discord は送り直さない
    assert rec["channels"]["telegram"]["status"] == ob.DELIVERED and rec["status"] == ob.DELIVERED


# ── 送る直前の確かめ直し ────────────────────────────────────────────────────

def test_send_revalidates_right_before_payload():
    """SENDING を保存した後、送る直前に期限が過ぎていたら送らない（EXPIRED）。"""
    calls = []
    fx = {"fixture": FixtureAdapter(lambda c, k: calls.append(k))}
    st = ob.empty_store()
    ob.observe(st, _rows(_diag(ps5("OUT_OF_STOCK"))), now=NOW, mode=ob.MODE_LIVE)
    ob.observe(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_LIVE, channels=["fixture"])
    ob.prepare(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_LIVE, attempt_id="a", adapters=fx)
    out = ob.send(st, now=NOW + timedelta(hours=4), attempt_id="a", adapters=fx)
    assert calls == [] and out["expired"] == 1 and ob.counts(st)["expired"] == 1


# ── 届いたか不明の解決 ────────────────────────────────────────────────────

def _unknown_store(sender_status="read"):
    def snd(c, k):
        raise SendFail(sender_status)
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, dry_run=False, sender=snd)
    _r, st = run(_diag(ps5()), st, dry_run=False, sender=snd)
    nid = next(iter(st["records"]))
    assert st["records"][nid]["status"] == ob.UNKNOWN_DELIVERY
    return st, nid


def test_unknown_is_listed_without_secrets():
    st, nid = _unknown_store()
    rows = ob.list_unknown(st)
    assert len(rows) == 1 and rows[0]["notification_id"] == nid and rows[0]["provider"] == "fixture"
    assert rows[0]["attempted_at"] and rows[0]["reason"] == "response_lost"
    assert "webhook" not in json.dumps(rows) and "token" not in json.dumps(rows).lower()


def test_unknown_not_auto_retried():
    calls = []
    st, nid = _unknown_store()
    for i in range(3):
        later = NOW + timedelta(minutes=10 * (i + 1))
        run(_diag(ps5(checked=later - timedelta(minutes=5), now=later)), st, now=later, dry_run=False,
            sender=lambda c, k: calls.append(k))
    assert calls == [] and st["records"][nid]["status"] == ob.UNKNOWN_DELIVERY


def test_mark_delivered_never_resent():
    calls = []
    st, nid = _unknown_store()
    res = ob.resolve(st, nid, ob.MARK_DELIVERED, rows=_rows(_diag(ps5())), now=NOW)
    assert res["channels"] == {"fixture": ob.DELIVERED}
    later = NOW + timedelta(minutes=10)
    run(_diag(ps5(checked=later - timedelta(minutes=5), now=later)), st, now=later, dry_run=False,
        sender=lambda c, k: calls.append(k))
    assert calls == [] and st["records"][nid]["status"] == ob.DELIVERED
    audit = st["records"][nid]["channels"]["fixture"]["resolutions"][-1]
    assert audit["resolution"] == "delivered" and audit["resolver_type"] == "operator_cli" and audit["resolved_at"]
    assert set(audit) == {"resolved_at", "resolution", "resolver_type", "previous_status", "result_status"}


def test_mark_not_delivered_returns_to_retry_with_same_key():
    calls = []
    st, nid = _unknown_store()
    key = st["records"][nid]["idempotency_key"]
    n = len(st["records"])
    later = NOW + timedelta(minutes=10)
    rows = _rows(_diag(ps5(checked=later - timedelta(minutes=5), now=later)))
    ob.resolve(st, nid, ob.MARK_NOT_DELIVERED, rows=rows, now=later)
    assert st["records"][nid]["status"] == ob.FAILED_RETRYABLE and len(st["records"]) == n
    run(_diag(ps5(checked=later - timedelta(minutes=5), now=later)), st, now=later, dry_run=False,
        sender=lambda c, k: calls.append(k))
    assert calls == [key]                                              # 同じ冪等性のキーで1回だけ
    run(_diag(ps5(checked=later - timedelta(minutes=5), now=later)), st, now=later, dry_run=False,
        sender=lambda c, k: calls.append(k))
    assert calls == [key]


def test_expired_unknown_not_retried():
    st, nid = _unknown_store()
    late = NOW + timedelta(hours=6)
    rows = _rows(_diag(ps5(checked=NOW - timedelta(minutes=30), now=late)))   # 今は更新待ち（期限切れ）
    ob.resolve(st, nid, ob.MARK_NOT_DELIVERED, rows=rows, now=late)
    assert st["records"][nid]["status"] in (ob.EXPIRED, ob.CANCELLED)
    st2, nid2 = _unknown_store()
    rec = st2["records"][nid2]
    ob.resolve(st2, nid2, ob.MARK_NOT_DELIVERED,
               rows=[dict(_rows(_diag(ps5()))[0], until_ms=int(NOW.timestamp() * 1000) - 1)], now=NOW)
    assert rec["status"] == ob.EXPIRED


def test_profit_lost_unknown_cancelled():
    st, nid = _unknown_store()
    ob.resolve(st, nid, ob.MARK_NOT_DELIVERED, rows=_rows(_diag(ps5(profitable=False))), now=NOW)
    assert st["records"][nid]["status"] == ob.CANCELLED


def test_cancel_and_keep_unknown():
    st, nid = _unknown_store()
    ob.resolve(st, nid, ob.KEEP_UNKNOWN, rows=[], now=NOW)
    assert st["records"][nid]["status"] == ob.UNKNOWN_DELIVERY
    assert st["records"][nid]["channels"]["fixture"]["resolutions"][-1]["resolution"] == "keep-unknown"
    ob.resolve(st, nid, ob.CANCEL, rows=[], now=NOW)
    assert st["records"][nid]["status"] == ob.CANCELLED
    with pytest.raises(LookupError):                                   # 不明でなくなったものは解決できない
        ob.resolve(st, nid, ob.CANCEL, rows=[], now=NOW)


def test_resolution_does_not_create_new_keys():
    st, nid = _unknown_store()
    keys = {r["idempotency_key"] for r in st["records"].values()}
    ob.resolve(st, nid, ob.MARK_DELIVERED, rows=[], now=NOW)
    run(_diag(ps5()), st, dry_run=False, sender=lambda c, k: None)
    assert {r["idempotency_key"] for r in st["records"].values()} == keys


# ── CLI ────────────────────────────────────────────────────────────────────

def _cli_env(tmp_path, monkeypatch, store, diag):
    out, dd = tmp_path / "out", tmp_path / "diag"
    out.mkdir()
    dd.mkdir()
    (out / ob.STORE_NAME).write_text(ob.dumps(store), encoding="utf-8")
    (dd / "latest.json").write_text(json.dumps(diag), encoding="utf-8")
    monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(out))
    monkeypatch.setenv("OPPORTUNITY_DIAGNOSTICS_DIR", str(dd))
    return out


def test_cli_list_and_resolve_requires_confirm(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from src import cli
    st, nid = _unknown_store()
    out = _cli_env(tmp_path, monkeypatch, st, _diag(ps5()))
    r = CliRunner().invoke(cli.cli, ["notification", "list-unknown"])
    assert r.exit_code == 0 and nid in r.output
    before = (out / ob.STORE_NAME).read_text(encoding="utf-8")
    monkeypatch.setattr(ob, "main_ledger_matches", lambda p, r: (True, ""))
    r = CliRunner().invoke(cli.cli, ["notification", "resolve", nid, "delivered"])
    assert r.exit_code == 0 and "--confirm" in r.output
    assert (out / ob.STORE_NAME).read_text(encoding="utf-8") == before     # 確認なしでは書き換えない
    r = CliRunner().invoke(cli.cli, ["notification", "resolve", nid, "delivered", "--confirm"])
    assert r.exit_code == 0
    st2, _b = ob.load(out / ob.STORE_NAME)
    assert st2["records"][nid]["status"] == ob.DELIVERED


def test_cli_resolve_refuses_when_main_differs(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from src import cli
    st, nid = _unknown_store()
    out = _cli_env(tmp_path, monkeypatch, st, _diag(ps5()))
    monkeypatch.setattr(ob, "main_ledger_matches", lambda p, r: (False, "手元の台帳が main の台帳と違います"))
    before = (out / ob.STORE_NAME).read_text(encoding="utf-8")
    r = CliRunner().invoke(cli.cli, ["notification", "resolve", nid, "delivered", "--confirm"])
    assert r.exit_code == 1 and (out / ob.STORE_NAME).read_text(encoding="utf-8") == before


def test_cli_gate_shows_no_values(monkeypatch):
    from click.testing import CliRunner
    from src import cli
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", DUMMY_HOOK)
    monkeypatch.setenv("NOTIFICATION_PROVIDERS", "discord")
    r = CliRunner().invoke(cli.cli, ["notification", "gate"])
    assert r.exit_code == 0 and "無効" in r.output and DUMMY_HOOK not in r.output


def test_cli_dispatch_forces_dry_run_when_gate_closed(tmp_path, monkeypatch):
    """dry-run を外す設定にしても、最終の関門が閉じていれば送らない（dry-run と同じ）。"""
    from click.testing import CliRunner
    from src import cli
    d = dict(_diag(ps5()), generated_at=NOW.isoformat())
    out = tmp_path / "out"
    ob.run_observe(out, dict(_diag(ps5("OUT_OF_STOCK")), generated_at="x"), now=NOW, dry_run=False)
    ob.run_observe(out, d, now=NOW, dry_run=True)
    dd = tmp_path / "diag"
    dd.mkdir()
    (dd / "latest.json").write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(out))
    monkeypatch.setenv("OPPORTUNITY_DIAGNOSTICS_DIR", str(dd))
    monkeypatch.setenv("NOTIFICATION_DRY_RUN", "false")
    monkeypatch.setenv("NOTIFICATION_REAL_SEND", "true")
    r = CliRunner().invoke(cli.cli, ["dispatch-notifications", "--step", "send", "--persisted-sha", "x"])
    assert r.exit_code == 0 and '"skipped": "dry_run"' in r.output and '"implemented": false' in r.output


# ── 古い基準のファイル（一時の bare リポジトリ。ネットワークに出ない） ─────────────────

STATE_REL = "exports/notifications/actionable/state.json"


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=env, check=True,
                          encoding="utf-8", errors="replace").stdout


def _repo(tmp_path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    a = tmp_path / "a"
    _git(tmp_path, "clone", "-q", str(origin), str(a))
    (a / STATE_REL).parent.mkdir(parents=True)
    (a / STATE_REL).write_text('{"schema": 2, "products": {}, "records": {}}\n', encoding="utf-8")
    _git(a, "add", "-A")
    _git(a, "commit", "-q", "-m", "seed")
    _git(a, "push", "-q", "origin", "HEAD:main")
    return origin, a


def _sh(name, cwd, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_RUN", "RUNNER_TEMP",
                                                                    "NOTIFICATION_OUTBOX_BASE"))}
    env.update(env_extra or {})
    return subprocess.run(["bash", str(ROOT / "scripts" / name)], cwd=cwd, capture_output=True, env=env,
                          encoding="utf-8", errors="replace")


def test_default_base_file_is_not_shared_tmp(tmp_path):
    _origin, a = _repo(tmp_path)
    assert _sh("sync_notification_state.sh", a).returncode == 0
    base = Path(_git(a, "rev-parse", "--absolute-git-dir").strip()) / "notification_outbox_base"
    text = base.read_text()
    assert text.startswith("run=local-") and "\nmain=" in text and "\nblob=" in text and "\nsynced=" in text


def test_stale_base_from_other_run_rejected(tmp_path):
    _origin, a = _repo(tmp_path)
    base = tmp_path / "base"
    assert _sh("sync_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base),
                                                  "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"}).returncode == 0
    (a / STATE_REL).write_text('{"schema": 2, "products": {"x": {}}, "records": {}}\n', encoding="utf-8")
    r = _sh("persist_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base),
                                                  "GITHUB_RUN_ID": "2", "GITHUB_RUN_ATTEMPT": "1"})
    assert r.returncode == 1 and "別の実行" in r.stdout
    r = _sh("persist_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base),
                                                  "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"})
    assert r.returncode == 0, r.stdout + r.stderr                     # 否定の対照: 同じ実行なら保存する


def test_old_local_base_rejected(tmp_path):
    _origin, a = _repo(tmp_path)
    base = tmp_path / "base"
    assert _sh("sync_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base)}).returncode == 0
    text = base.read_text()
    base.write_text(text.replace([ln for ln in text.splitlines() if ln.startswith("synced=")][0], "synced=1000"))
    (a / STATE_REL).write_text('{"schema": 2, "products": {"y": {}}, "records": {}}\n', encoding="utf-8")
    r = _sh("persist_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base)})
    assert r.returncode == 1 and "古すぎます" in r.stdout


def test_tampered_base_blob_rejected(tmp_path):
    _origin, a = _repo(tmp_path)
    base = tmp_path / "base"
    assert _sh("sync_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base)}).returncode == 0
    text = base.read_text()
    blob = [ln for ln in text.splitlines() if ln.startswith("blob=")][0]
    base.write_text(text.replace(blob, "blob=" + "0" * 40))
    (a / STATE_REL).write_text('{"schema": 2, "products": {"z": {}}, "records": {}}\n', encoding="utf-8")
    r = _sh("persist_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base)})
    assert r.returncode == 1 and "基準の台帳" in r.stdout


def test_legacy_base_format_rejected(tmp_path):
    _origin, a = _repo(tmp_path)
    base = tmp_path / "base"
    base.write_text(_git(a, "rev-parse", f"origin/main:{STATE_REL}").strip())    # Phase 20 の形（blob だけ）
    (a / STATE_REL).write_text('{"schema": 2, "products": {"w": {}}, "records": {}}\n', encoding="utf-8")
    r = _sh("persist_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base)})
    assert r.returncode == 1


# ── ワークフロー・送信なし ────────────────────────────────────────────────

def _dc():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_check
    return deploy_check


def test_workflow_secrets_only_in_send_step():
    import re
    assert _dc()._notification_secret_exposure(ROOT) == []
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    assert not re.search(r"NOTIFICATION_REAL_SEND:\s*[\"']?true", wf, re.I)


@pytest.mark.parametrize("mutate,expect", [
    (lambda t: t.replace("permissions:\n", "env:\n  DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}\npermissions:\n", 1),
     "ワークフロー全体"),
    (lambda t: t.replace("      TZ: Asia/Tokyo\n", "      TZ: Asia/Tokyo\n      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}\n", 1),
     "ジョブ"),
    (lambda t: t.replace("    runs-on:", "    env:\n      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}\n    runs-on:", 1),
     "env の外"),                                                       # 重複したキー（構造では見えない）
    (lambda t: t.replace("NOTIFICATION_REAL_SEND: \"false\"\n", "NOTIFICATION_REAL_SEND: \"false\"\n          X: ${{ toJSON(secrets) }}\n", 1),
     "secrets 全体"),
    (lambda t: t.replace("NOTIFICATION_REAL_SEND: \"false\"\n", "NOTIFICATION_REAL_SEND: \"false\"\n          # c\n          D: ${{ secrets.DISCORD_WEBHOOK_URL }}\n", 1),
     "送信の手順でない"),
])
def test_secret_exposure_variants_detected(tmp_path, mutate, expect):
    """ジョブの env・secrets 全体・コメントを挟んだ参照も検出する（監査 M-1）。"""
    root = tmp_path
    (root / ".github" / "workflows").mkdir(parents=True)
    src = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    (root / ".github" / "workflows" / "daily_lp.yml").write_text(mutate(src), encoding="utf-8")
    probs = _dc()._notification_secret_exposure(root)
    assert any(expect in p for p in probs), probs


def test_dry_run_no_network(monkeypatch):
    import socket

    def no_net(*a, **k):
        raise AssertionError("network called")
    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(socket.socket, "connect", no_net)
    st = ob.empty_store()
    ob.cycle(st, _diag(ps5("OUT_OF_STOCK")), now=NOW, mode=ob.MODE_DRY)
    res = ob.cycle(st, _diag(ps5()), now=NOW, mode=ob.MODE_DRY, adapters=ad.default_adapters())
    assert res["counts"]["dry_run_planned"] == 1
    for a in ad.default_adapters().values():
        a.build_payload(next(iter(st["records"].values())))


def test_deploy_check_857_ok():
    res = _dc()._check_phase21_delivery_providers()[0]
    assert res["level"] == "ok", res["message"]


def test_admin_lists_unknown_read_only(tmp_path):
    from src.content.ui import admin
    st, nid = _unknown_store()
    rep = {"generated_at": NOW.isoformat(), "dry_run": False, "unknown": ob.list_unknown(st), "counts": ob.counts(st)}
    a = admin.build_actionable_notices(rep)
    html = admin._act_notices(a)
    assert nid in html and "fixture" in html and "届いたか不明" in html
    assert "notification resolve" in html and "見るだけ" in html               # 書き換えの画面を装わない
    assert "<form" not in html and "<button" not in html
    assert "webhook" not in html.lower() and "token" not in html.lower()


def test_persist_refuses_bare_telegram_token(tmp_path):
    _origin, a = _repo(tmp_path)
    base = tmp_path / "base"
    _sh("sync_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base)})
    (a / STATE_REL).write_text('{"t": "bot' + DUMMY_TOKEN.split(":")[0] + ":" + "A" * 35 + '"}', encoding="utf-8")
    r = _sh("persist_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base)})
    assert r.returncode == 1 and "トークン" in r.stdout


# ── レビュー・監査の指摘 ─────────────────────────────────────────────────

def test_cancelled_unknown_is_not_revived():
    """人が cancel で解決した届いたか不明は、同じキーで行動できるままでも配信待ちに戻さない（H-1）。"""
    calls = []
    st, nid = _unknown_store()
    ob.resolve(st, nid, ob.CANCEL, rows=[], now=NOW)
    for i in range(3):
        later = NOW + timedelta(minutes=30 * (i + 1))
        run(_diag(ps5(checked=later - timedelta(minutes=5), now=later)), st, now=later, dry_run=False,
            sender=lambda c, k: calls.append(k))
    assert calls == [] and st["records"][nid]["status"] == ob.CANCELLED
    st2, nid2 = _unknown_store()                                       # 否定の対照: not-delivered は出し直す
    later = NOW + timedelta(minutes=30)
    ob.resolve(st2, nid2, ob.MARK_NOT_DELIVERED,
               rows=_rows(_diag(ps5(checked=later - timedelta(minutes=5), now=later))), now=later)
    run(_diag(ps5(checked=later - timedelta(minutes=5), now=later)), st2, now=later, dry_run=False,
        sender=lambda c, k: calls.append(k))
    assert len(calls) == 1


@pytest.mark.parametrize("body", [{"ok": False, "error_code": "Bad"},
                                  {"ok": False, "error_code": 429, "parameters": {"retry_after": "5s"}},
                                  {"ok": False, "error_code": 429, "parameters": "x"}])
def test_malformed_telegram_body_does_not_crash(body):
    """形の崩れた応答でも send 全体を止めない（M-1）。ほかの配信先も送る。"""
    calls = {"discord": 0}

    def dsc(p, k):
        calls["discord"] += 1
        return 200, {}, {"id": "d"}
    adapters = {"telegram": ad.TelegramAdapter(lambda p, k: (429, {}, body)), "discord": ad.DiscordAdapter(dsc)}
    st = ob.empty_store()
    ob.observe(st, _rows(_diag(ps5("OUT_OF_STOCK"))), now=NOW, mode=ob.MODE_LIVE)
    ob.cycle(st, _diag(ps5()), now=NOW, mode=ob.MODE_LIVE, attempt_id="a", channels=["telegram", "discord"],
             adapters=adapters)
    rec = next(iter(st["records"].values()))
    assert calls["discord"] == 1 and rec["channels"]["telegram"]["status"] in (ob.FAILED_RETRYABLE, ob.FAILED_FINAL,
                                                                                ob.UNKNOWN_DELIVERY)


def test_observe_mode_matches_dispatch(tmp_path, monkeypatch):
    """dry-run を外しても関門が閉じていれば、LP の生成も dry-run の記録を作る（方式の食い違いをなくす。L-1）。"""
    from src.content.daily_lp_generator import DailyLPGenerator
    monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(tmp_path))
    monkeypatch.setenv("NOTIFICATION_DRY_RUN", "false")
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g._write_actionable_notifications(_diag(ps5("OUT_OF_STOCK")), NOW)
    rep = g._write_actionable_notifications(_diag(ps5()), NOW)
    assert rep["dry_run"] is True
    st, _b = ob.load(tmp_path / ob.STORE_NAME)
    assert {r["mode"] for r in st["records"].values()} == {ob.MODE_DRY}


@pytest.mark.parametrize("value", ["", "maybe", "TRUE", "1"])
def test_gate_dry_run_matches_is_dry_run(value):
    from src.notifiers import actionable as an
    g = ad.real_send_gate({"NOTIFICATION_DRY_RUN": value})
    assert g["checks"]["dry_run_off"] == (not an.is_dry_run({"NOTIFICATION_DRY_RUN": value}))


@pytest.mark.parametrize("synced", ["1e5", "abc", "99999999999"])
def test_bad_or_future_base_time_rejected(tmp_path, synced):
    _origin, a = _repo(tmp_path)
    base = tmp_path / "base"
    assert _sh("sync_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base)}).returncode == 0
    text = base.read_text()
    base.write_text(text.replace([ln for ln in text.splitlines() if ln.startswith("synced=")][0], f"synced={synced}"))
    (a / STATE_REL).write_text('{"schema": 2, "products": {"q": {}}, "records": {}}\n', encoding="utf-8")
    assert _sh("persist_notification_state.sh", a, {"NOTIFICATION_OUTBOX_BASE_FILE": str(base)}).returncode == 1


def test_cli_has_no_skip_main_check_and_commits_only_ledger(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from src import cli
    st, nid = _unknown_store()
    _cli_env(tmp_path, monkeypatch, st, _diag(ps5()))
    r = CliRunner().invoke(cli.cli, ["notification", "resolve", nid, "delivered", "--skip-main-check"])
    assert r.exit_code != 0                                            # 照合を省くオプションは無い
    monkeypatch.setattr(ob, "main_ledger_matches", lambda p, r: (True, ""))
    r = CliRunner().invoke(cli.cli, ["notification", "resolve", nid, "delivered", "--confirm"])
    assert r.exit_code == 0 and " -- " in r.output and "state.json" in r.output


def test_discord_escapes_markdown_in_product_name():
    c = ad.DiscordAdapter().build_payload(_record(product="PS5 **限定** ~~旧~~ ||秘|| `x`"))["content"]
    assert "\\*\\*限定\\*\\*" in c and "\\~\\~" in c and "\\|\\|" in c and "\\`x\\`" in c
    assert SONY in c and "\\" not in c.splitlines()[-1]                # URL の行は変えない
    t = ad.TelegramAdapter().build_payload(_record(product="PS5 **限定**"))["text"]
    assert "**限定**" in t                                             # Telegram はそのままの文字


@pytest.mark.parametrize("leak", ["12345678901:" + "A" * 35, "1234567:" + "B" * 32,
                                  "discord.com/api/webhooks/123/abc"])
def test_redact_matches_accepted_formats(leak):
    assert "[REDACTED]" in ad.redact(f"x {leak} y")


def test_deploy_check_857_detects_exposed_secret(tmp_path):
    """#857 が、送信の手順でない手順の通知の Secrets をエラーにする（否定の対照: 今のワークフローは ok）。"""
    import shutil
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "persist_notification_state.sh", tmp_path / "scripts")
    src = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    (tmp_path / ".github" / "workflows" / "daily_lp.yml").write_text(src, encoding="utf-8")
    assert _dc()._check_phase21_delivery_providers(tmp_path)[0]["level"] == "ok"
    bad = src.replace("      TZ: Asia/Tokyo\n", "      TZ: Asia/Tokyo\n      DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}\n", 1)
    (tmp_path / ".github" / "workflows" / "daily_lp.yml").write_text(bad, encoding="utf-8")
    assert _dc()._check_phase21_delivery_providers(tmp_path)[0]["level"] == "error"


def test_unreadable_response_is_ambiguous():
    """応答の分類そのものが失敗しても、例外を漏らさず「届いたか不明」にする（ほかの配信先を止めない）。"""
    class Broken(ad.TelegramAdapter):
        def classify_response(self, status, headers=None, body=None):
            raise ValueError("unreadable")
    with pytest.raises(ad.ProviderError) as e:
        Broken(lambda p, k: (200, {}, {"ok": True})).send(_record(), "k")
    assert e.value.kind == ad.AMBIGUOUS and e.value.error_class == "classify_failed"


def test_secret_exposure_case_and_inherit(tmp_path):
    """Secrets の名前の大文字と小文字・secrets: inherit も検出する（レビュー L-A）。"""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    src = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    low = src.replace("      TZ: Asia/Tokyo\n", "      TZ: Asia/Tokyo\n      X: ${{ secrets.discord_webhook_url }}\n", 1)
    (tmp_path / ".github" / "workflows" / "daily_lp.yml").write_text(low, encoding="utf-8")
    assert _dc()._notification_secret_exposure(tmp_path)
    (tmp_path / ".github" / "workflows" / "daily_lp.yml").write_text(src, encoding="utf-8")
    (tmp_path / ".github" / "workflows" / "call.yml").write_text(
        "on: push\njobs:\n  c:\n    uses: ./.github/workflows/other.yml\n    secrets: inherit\n", encoding="utf-8")
    assert any("secrets" in p for p in _dc()._notification_secret_exposure(tmp_path))


def test_discord_shortening_does_not_split_escape():
    """エスケープの途中で切らない（末尾に対になっていない \\ を残さない。レビュー L-B）。"""
    c = ad.DiscordAdapter().build_payload(_record(product="*" * 3000))["content"]
    name_line = [ln for ln in c.splitlines() if ln.startswith("商品: ")][0]
    body = name_line[len("商品: "):-1]                                # 末尾の「…」を除く
    assert len(c) <= 2000 and name_line.endswith("…") and c.endswith(SONY)
    assert body == "\\*" * (len(body) // 2)                           # \* の組だけ


def test_secret_sender_step_is_unique_and_fixed(tmp_path):
    """同じ名前の手順を足しても・結果の通知のスクリプト以外を実行しても検出する（監査 L-b）。"""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    src = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    other = src.replace("        run: python scripts/notify_workflow_result.py",
                        "        run: env | base64", 1)
    (tmp_path / ".github" / "workflows" / "daily_lp.yml").write_text(other, encoding="utf-8")
    assert any("以外を実行" in p for p in _dc()._notification_secret_exposure(tmp_path))
