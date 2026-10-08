"""Phase 20（通知の outbox・冪等性・保存してから送る）のテスト。

外部への送信はしない（偽の配信先だけ）。各テストに否定の対照を付ける。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from _notify_helpers import (CLOSED, NOW, OPEN, SONY, FixtureAdapter, SendFail, _diag, gr4, lottery_event, ps5, run,
                             seq)
from _notify_helpers import stock_gr4
from src.notifiers import adapters as ad
from src.notifiers import outbox as ob

ROOT = Path(__file__).resolve().parent.parent


def _rows(d):
    return d["actionability"]["products"]


def _fresh_store():
    st = ob.empty_store()
    ob.observe(st, _rows(_diag(ps5("OUT_OF_STOCK"))), now=NOW, mode=ob.MODE_DRY)
    return st


# ── 候補 → outbox・冪等性のキー ─────────────────────────────────────────────

def test_candidate_goes_to_outbox_pending():
    st = _fresh_store()
    stats = ob.observe(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_DRY)
    assert stats["notification_candidates"] == 1 and len(st["records"]) == 1
    rec = next(iter(st["records"].values()))
    assert rec["status"] == ob.PENDING and rec["notification_type"] == "ACTIONABLE_NOW"
    for k in ("notification_id", "idempotency_key", "product_id", "state_transition", "availability_kind", "event_id",
              "deadline", "action_url", "net_profit", "roi", "created_at", "status"):
        assert k in rec
    assert rec["action_url"] == SONY and rec["net_profit"] == 54870 and rec["state_transition"] == "OUT_OF_STOCK→IN_STOCK"


def test_idempotency_key_is_stable_and_provider_independent():
    a, b = _fresh_store(), _fresh_store()
    ob.observe(a, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_DRY)
    ob.observe(b, _rows(_diag(ps5())), now=NOW + timedelta(minutes=5), mode=ob.MODE_DRY)
    ka = {r["idempotency_key"] for r in a["records"].values()}
    kb = {r["idempotency_key"] for r in b["records"].values()}
    assert ka == kb and len(ka) == 1
    key = ka.pop()
    assert "discord" not in key and "telegram" not in key and "dry" not in key
    assert ob.notification_id(key, ob.MODE_DRY) != ob.notification_id(key, ob.MODE_LIVE)


def test_same_candidate_no_duplicate_outbox():
    st = _fresh_store()
    for _ in range(3):
        ob.observe(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_DRY)
    assert len(st["records"]) == 1


def test_rearm_creates_new_transition_key():
    st = _fresh_store()
    for stock in ("IN_STOCK", "OUT_OF_STOCK", "IN_STOCK"):
        ob.observe(st, _rows(_diag(ps5(stock))), now=NOW, mode=ob.MODE_DRY)
    keys = sorted(r["idempotency_key"] for r in st["records"].values())
    assert len(keys) == 2 and keys[0] != keys[1]
    st2 = _fresh_store()                                     # 否定の対照: 更新待ちを挟んでも新しいキーにしない
    for stock, ck in (("IN_STOCK", None), ("IN_STOCK", NOW - timedelta(hours=4)), ("IN_STOCK", None)):
        ob.observe(st2, _rows(_diag(ps5(stock, checked=ck or NOW - timedelta(minutes=30)))), now=NOW, mode=ob.MODE_DRY)
    assert len(st2["records"]) == 1


def test_lottery_event_key_once_per_event():
    st = ob.empty_store()
    ob.observe(st, _rows(_diag(gr4(CLOSED))), now=NOW, mode=ob.MODE_DRY)
    ob.observe(st, _rows(_diag(gr4(OPEN))), now=NOW, mode=ob.MODE_DRY)
    ob.observe(st, _rows(_diag(gr4(OPEN))), now=NOW, mode=ob.MODE_DRY)
    nxt = lottery_event(NOW - timedelta(hours=1), NOW + timedelta(days=4))
    ob.observe(st, _rows(_diag(gr4(nxt))), now=NOW, mode=ob.MODE_DRY)
    ev = [r for r in st["records"].values() if r["kind"] == "event"]
    assert len(ev) == 2 and len({r["idempotency_key"] for r in ev}) == 2


def test_deadline_extension_is_same_event():
    """同じ受付（開始が同じ）の締切の延長だけでは新しい受付にしない（再通知しない）。"""
    ext = dict(OPEN, entry_end_at=(NOW + timedelta(days=6)).isoformat())
    reps, st = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)), _diag(gr4(ext)))
    assert [r["notification_candidates"] for r in reps] == [0, 1, 0]
    assert len(st["records"]) == 1
    moved = lottery_event(NOW - timedelta(hours=3), NOW + timedelta(days=6))   # 否定の対照: 開始が違えば別の受付
    r, _ = run(_diag(gr4(moved)), st)
    assert r["notification_candidates"] == 1


def test_date_only_and_midnight_start_are_same_event():
    """日付だけの開始と 0:00 の開始は同じ受付（どちらもその日の始まり）。"""
    d1 = dict(OPEN, entry_start_at=(NOW - timedelta(days=1)).strftime("%Y-%m-%d"))
    d2 = dict(OPEN, entry_start_at=(NOW - timedelta(days=1)).strftime("%Y-%m-%d 00:00"))
    rows1, rows2 = _rows(_diag(gr4(d1))), _rows(_diag(gr4(d2)))
    if rows1[0]["actionable"] and rows2[0]["actionable"]:
        assert ob.event_identity(rows1[0]) == ob.event_identity(rows2[0])
    assert ob.event_identity({"availability": "IN_STOCK", "event_key": "p|a|b"}) == ""


# ── dry-run ────────────────────────────────────────────────────────────────

def test_dry_run_is_not_delivered():
    reps, st = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()))
    c = ob.counts(st)
    assert c["dry_run_planned"] == 1 and c["delivered"] == 0
    assert all(ch["status"] == ob.DRY_RUN_PLANNED for r in st["records"].values() for ch in r["channels"].values())


def test_dry_run_history_does_not_block_first_real_send():
    """dry-run の記録は DELIVERED ではない。本番に切り替えた後の新しい変化は送る（dry-run の計画が止めない）。
    dry-run で計画した古い変化は、切り替えた時点では送らない（何日も前の「行動できるようになった」を送らない。監査 M-1）。"""
    sent = []
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, channels=["fixture"])
    _r, st = run(_diag(ps5()), st, channels=["fixture"])             # dry-run で計画
    r, st = run(_diag(ps5()), st, dry_run=False, sender=lambda c, k: sent.append(k))
    assert r["dispatch_sent"] == 0 and sent == []                      # 古い変化は送らない
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), st, dry_run=False, sender=lambda c, k: sent.append(k))
    r, st = run(_diag(ps5()), st, dry_run=False, sender=lambda c, k: sent.append(k))
    assert r["dispatch_sent"] == 1 and len(sent) == 1                  # 本番に切り替えた後の新しい変化は送る
    r, st = run(_diag(ps5()), st, dry_run=False, sender=lambda c, k: sent.append(k))
    assert len(sent) == 1


def test_pruned_record_is_not_resent():
    """記録が消えても（prune）、同じ変化（同じキー）は送り直さない（監査 H-3）。抽選なども同じ。"""
    sent = []
    snd = lambda c, k: sent.append(k)                                   # noqa: E731
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, dry_run=False, sender=snd)
    _r, st = run(_diag(ps5()), st, dry_run=False, sender=snd)
    _r, st = run(_diag(ps5(checked=NOW - timedelta(hours=4))), st, dry_run=False, sender=snd)   # 更新待ち
    assert ob.prune(st, NOW + timedelta(days=ob.RETENTION_DAYS + 2)) == 1
    _r, st = run(_diag(ps5()), st, dry_run=False, sender=snd)
    assert len(sent) == 1
    sent.clear()
    _r, st = run(_diag(gr4(CLOSED)), {}, dry_run=False, sender=snd)
    _r, st = run(_diag(gr4(OPEN)), st, dry_run=False, sender=snd)
    _r, st = run(_diag(gr4(dict(OPEN, status="closed"))), st, dry_run=False, sender=snd)
    ob.prune(st, NOW + timedelta(days=ob.RETENTION_DAYS + 2))
    _r, st = run(_diag(gr4(OPEN)), st, dry_run=False, sender=snd)
    assert len(sent) == 1


def test_mode_change_cancels_pending_of_other_mode():
    st = _fresh_store()
    ob.observe(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_DRY)
    out = ob.prepare(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_LIVE, attempt_id="a")
    assert out["cancelled"] == 1 and ob.counts(st)["cancelled"] == 1


# ── 送信（偽の配信先だけ）・再試行 ───────────────────────────────────────────

def _live(sender, *, stocks=("OUT_OF_STOCK", "IN_STOCK"), now=NOW):
    st = None
    reps = []
    for s in stocks:
        r, st = run(_diag(ps5(s, checked=now - timedelta(minutes=30), now=now)), st if st is not None else {},
                    now=now, dry_run=False, sender=sender)
        reps.append(r)
    return reps, st


def test_real_mode_fixture_only_sends_once():
    sent = []
    reps, st = _live(lambda c, k: sent.append(k))
    assert reps[-1]["dispatch_sent"] == 1 and len(sent) == 1
    rec = next(iter(st["records"].values()))
    ch = rec["channels"]["fixture"]
    assert rec["status"] == ob.DELIVERED and ch["provider_delivery_id"].startswith("fx-")
    assert ch["attempts"][-1]["status"] == ob.DELIVERED and ch["attempts"][-1]["provider"] == "fixture"


def test_retryable_failure_honors_retry_after():
    def sender(c, k):
        raise SendFail(429, {"Retry-After": "1800"})
    _reps, st = _live(sender)
    ch = next(iter(st["records"].values()))["channels"]["fixture"]
    assert ch["status"] == ob.FAILED_RETRYABLE and ch["error_class"] == "rate_limited"
    due = datetime.fromisoformat(ch["next_attempt_at"])
    assert due >= NOW + timedelta(seconds=1800)
    out = ob.prepare(st, _rows(_diag(ps5())), now=NOW + timedelta(minutes=10), mode=ob.MODE_LIVE, attempt_id="b",
                     adapters={"fixture": FixtureAdapter(lambda c, k: None)})
    assert out["sending"] == 0                                          # Retry-After の前は出し直さない


def test_non_retryable_failure_is_final():
    for status, cls in ((401, "auth"), (404, "invalid_destination"), (400, "malformed_payload")):
        _reps, st = _live(lambda c, k, s=status: (_ for _ in ()).throw(SendFail(s)))
        ch = next(iter(st["records"].values()))["channels"]["fixture"]
        assert ch["status"] == ob.FAILED_FINAL and ch["error_class"] == cls


def test_ambiguous_delivery_is_not_retried():
    calls = []

    def sender(c, k):
        calls.append(k)
        raise SendFail("read")
    reps, st = _live(sender, stocks=("OUT_OF_STOCK", "IN_STOCK", "IN_STOCK", "IN_STOCK"))
    assert len(calls) == 1 and ob.counts(st)["ambiguous_delivery"] == 1


def test_max_attempts_then_final():
    calls = []

    def sender(c, k):
        calls.append(k)
        raise SendFail(503)
    st = None
    t = NOW
    for i in range(ob.MAX_ATTEMPTS + 3):
        v = ps5("IN_STOCK" if i else "OUT_OF_STOCK", checked=t - timedelta(minutes=5), now=t)
        _r, st = run(_diag(v), st if st is not None else {}, now=t, dry_run=False, sender=sender)
        t += timedelta(hours=7)                                          # 再試行の間隔（上限6時間）より後
    ch = next(iter(st["records"].values()))["channels"]["fixture"]
    assert len(calls) == ob.MAX_ATTEMPTS and ch["status"] == ob.FAILED_FINAL


# ── 期限切れ・利益が消えた ─────────────────────────────────────────────────

def test_expired_before_dispatch_not_sent():
    sent = []
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, dry_run=False, sender=lambda c, k: sent.append(k))
    r, st = run(_diag(ps5()), st, dry_run=False, sender=lambda c, k: sent.append(k),
                dispatch_now=NOW + timedelta(hours=4))
    assert sent == [] and ob.counts(st)["expired"] == 1


def test_profit_lost_before_dispatch_cancelled():
    st = _fresh_store()
    ob.observe(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_LIVE, channels=["fixture"])
    sent = []
    lost = _rows(_diag(ps5(profitable=False)))                          # 配信の前に利益が確定でなくなった
    ob.prepare(st, lost, now=NOW, mode=ob.MODE_LIVE, attempt_id="a",
               adapters={"fixture": FixtureAdapter(lambda c, k: sent.append(k))})
    ob.send(st, now=NOW, attempt_id="a", adapters={"fixture": FixtureAdapter(lambda c, k: sent.append(k))})
    assert sent == [] and ob.counts(st)["cancelled"] == 1


def test_stale_pending_not_sent_next_run():
    """PENDING のまま次の実行になっても、行動できなければ送らない。"""
    st = _fresh_store()
    ob.observe(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_DRY)
    ob.observe(st, _rows(_diag(ps5("OUT_OF_STOCK"))), now=NOW, mode=ob.MODE_DRY)
    out = ob.prepare(st, _rows(_diag(ps5("OUT_OF_STOCK"))), now=NOW, mode=ob.MODE_DRY, attempt_id="a")
    assert out["planned"] == 0 and out["cancelled"] == 1


def test_profit_change_uses_latest_confirmed_value():
    st = _fresh_store()
    ob.observe(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_DRY)
    v = ps5()
    v.net_profit = 60000
    ob.prepare(st, _rows(_diag(v)), now=NOW, mode=ob.MODE_DRY, attempt_id="a")
    rec = next(iter(st["records"].values()))
    assert rec["net_profit"] == 60000 and "+¥60,000" in rec["message"]


# ── 保存・送った後の停止（crash window）・失敗の場面 ─────────────────────────

def test_crash_after_send_before_persist_does_not_resend():
    """送った後、DELIVERED を保存する前に止まった → 次の実行は SENDING を「届いたか不明」にして送り直さない。"""
    calls = []
    fx = {"fixture": FixtureAdapter(lambda c, k: calls.append(k))}
    st = _fresh_store()
    ob.observe(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_LIVE, channels=["fixture"])
    ob.prepare(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_LIVE, attempt_id="run1", adapters=fx)
    persisted = json.loads(ob.dumps(st))                                 # SENDING を保存した
    ob.send(st, now=NOW, attempt_id="run1", adapters=fx)                 # 送った（ここで止まって保存されない）
    assert len(calls) == 1
    st2 = ob.migrate(persisted)
    ob.cycle(st2, _diag(ps5()), now=NOW, mode=ob.MODE_LIVE, attempt_id="run2", adapters=fx, channels=["fixture"])
    assert len(calls) == 1 and ob.counts(st2)["ambiguous_delivery"] == 1


@pytest.mark.parametrize("failure", ["generated_commit", "deploy_check", "pages"])
def test_later_failures_do_not_cause_resend(failure):
    """送って DELIVERED を保存した後に、生成物のコミット・deploy-check・Pages が失敗しても、台帳は保存済みなので
    次の実行で送り直さない（台帳は手順ごとの保存で残る。生成物のコミットに頼らない）。"""
    calls = []
    fx = {"fixture": FixtureAdapter(lambda c, k: calls.append(k))}
    st = _fresh_store()
    ob.cycle(st, _diag(ps5()), now=NOW, mode=ob.MODE_LIVE, attempt_id="run1", adapters=fx, channels=["fixture"])
    persisted = json.loads(ob.dumps(st))                                 # 送った後の保存（手順の保存）
    # failure の手順は台帳を書き換えない（コミット・検査・Pages は台帳を読まない）
    st2 = ob.migrate(persisted)
    ob.cycle(st2, _diag(ps5()), now=NOW, mode=ob.MODE_LIVE, attempt_id="run2", adapters=fx, channels=["fixture"])
    assert len(calls) == 1 and ob.counts(st2)["delivered"] == 1


def test_send_requires_persisted_sha(tmp_path):
    calls = []
    fx = {"fixture": FixtureAdapter(lambda c, k: calls.append(k))}
    d = dict(_diag(ps5()), generated_at=NOW.isoformat())
    ob.run_observe(tmp_path, _diag(ps5("OUT_OF_STOCK")), now=NOW, dry_run=False)
    path = tmp_path / ob.STORE_NAME
    st, _b = ob.load(path)
    ob.observe(st, _rows(d), now=NOW, mode=ob.MODE_LIVE, channels=["fixture"])
    ob.save(path, st)
    (tmp_path / "latest.json").write_text(json.dumps({"step": "observe", "diagnostics_generated_at": d["generated_at"]}),
                                          encoding="utf-8")
    ob.run_prepare(tmp_path, d, now=NOW, dry_run=False, attempt_id="r1", adapters=fx)
    r = ob.run_send(tmp_path, now=NOW, dry_run=False, attempt_id="r1", persisted_sha="0" * 64, adapters=fx)
    assert r["skipped"] == "not_persisted" and calls == []
    r = ob.run_send(tmp_path, now=NOW, dry_run=False, attempt_id="r1", persisted_sha=ob.file_sha(path), adapters=fx)
    assert calls and r["dispatch_sent"] == 1                            # 否定の対照: 保存した内容と同じなら送る
    r = ob.run_send(tmp_path, now=NOW, dry_run=True, attempt_id="r1", persisted_sha=ob.file_sha(path), adapters=fx)
    assert r["skipped"] == "dry_run"


def test_atomic_save_keeps_old_file_on_failure(tmp_path, monkeypatch):
    path = tmp_path / ob.STORE_NAME
    st = _fresh_store()
    ob.save(path, st)
    before = path.read_text(encoding="utf-8")
    ob.observe(st, _rows(_diag(ps5())), now=NOW, mode=ob.MODE_DRY)

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        ob.save(path, st)
    assert path.read_text(encoding="utf-8") == before
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_save_only_when_changed(tmp_path):
    path = tmp_path / ob.STORE_NAME
    st = _fresh_store()
    assert ob.save(path, st) is True
    assert ob.save(path, json.loads(ob.dumps(st))) is False              # 時刻だけの書き換えをしない


def test_candidate_failure_leaves_no_partial_outbox(tmp_path, monkeypatch):
    ob.run_observe(tmp_path, _diag(ps5("OUT_OF_STOCK")), now=NOW, dry_run=True)
    before = (tmp_path / ob.STORE_NAME).read_text(encoding="utf-8")
    real = ob._record

    def half(*a, **k):
        raise RuntimeError("途中で失敗")
    monkeypatch.setattr(ob, "_record", half)
    with pytest.raises(RuntimeError):
        ob.run_observe(tmp_path, _diag(ps5()), now=NOW, dry_run=True)
    assert (tmp_path / ob.STORE_NAME).read_text(encoding="utf-8") == before
    monkeypatch.setattr(ob, "_record", real)


def test_zero_diagnostics_keeps_ledger():
    reps, st = seq(_diag(ps5("OUT_OF_STOCK")), _diag(), _diag(ps5()))
    assert [r["notification_candidates"] for r in reps] == [0, 0, 1]


def test_baseline_initialization_records_only():
    rep, st = run(_diag(ps5(), gr4(OPEN)), None)
    assert rep["is_baseline"] and rep["notification_candidates"] == 0 and rep["baseline_recorded"] == 2
    assert st["records"] == {}


def test_corrupt_store_is_baseline(tmp_path):
    p = tmp_path / ob.STORE_NAME
    p.write_text("{broken", encoding="utf-8")
    st, baseline = ob.load(p)
    assert baseline and st == ob.empty_store()


def test_legacy_production_ledger_migrates():
    """本番の Phase 19 の台帳（PS5 Pro 在庫切れ・GR IV HDF 抽選終了・通知なし）→ 次の行動できる変化は通知する。"""
    legacy = {"updated_at": "2026-10-09T00:19:40+09:00", "products": {
        "prod_gr4_hdf": {"availability": "LOTTERY_CLOSED", "actionable": False, "event_id": "", "notified_key": "",
                         "notified_at": "", "notified_events": []},
        "prod_ps5_pro": {"availability": "OUT_OF_STOCK", "actionable": False, "event_id": "", "notified_key": "",
                         "notified_at": "", "notified_events": []}}}
    st = ob.migrate(legacy)
    assert st["schema"] == ob.SCHEMA and st["records"] == {}
    reps = []
    for d in (_diag(ps5(), gr4(CLOSED)), _diag(ps5(), gr4(OPEN))):
        r, st = run(d, st)
        reps.append(r["notification_candidates"])
    assert reps == [1, 1]


def test_prune_keeps_current_key():
    st = _fresh_store()
    ob.cycle(st, _diag(ps5()), now=NOW, mode=ob.MODE_DRY)
    later = NOW + timedelta(days=ob.RETENTION_DAYS + 5)
    assert ob.prune(st, later) == 0                                     # 今の候補のキーは消さない
    ob.observe(st, _rows(_diag(ps5("OUT_OF_STOCK", now=later))), now=later, mode=ob.MODE_DRY)
    assert ob.prune(st, later) == 1


def test_lock_is_reentrant_free(tmp_path):
    with ob.locked(tmp_path / "x.json"):
        pass
    with ob.locked(tmp_path / "x.json"):
        pass


# ── 配信先の部品（通信なし） ─────────────────────────────────────────────────

def test_adapters_build_and_validate_without_network():
    rec = {"message": "🎯 購入可能になりました\nPS5"}
    d = ad.DiscordAdapter()
    p = d.build_payload(rec)
    assert p["allowed_mentions"] == {"parse": []} and d.validate(p) == []
    assert "too_long" in d.validate({"content": "x" * 2001})
    assert "mass_mention" in d.validate({"content": "@everyone hi"})
    t = ad.TelegramAdapter()
    assert t.validate(t.build_payload(rec)) == [] and "chat_id" not in t.build_payload(rec)
    assert not d.configured and not t.configured
    with pytest.raises(ad.ProviderError) as e:
        d.send(rec, "k")
    assert e.value.error_class == "not_configured"


def test_classify_http():
    assert ad.classify_http(204) is None
    assert ad.classify_http(429, {"Retry-After": "30"}).retry_after == 30
    assert ad.classify_http(503).kind == ad.RETRYABLE
    assert ad.classify_http(401).kind == ad.FINAL and ad.classify_http(404).error_class == "invalid_destination"


def test_adapters_module_has_no_http_imports():
    import re
    src = (ROOT / "src" / "notifiers" / "adapters.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+(requests|urllib|http\.client|httpx|aiohttp|socket)\b", src, re.M)
    src_ob = (ROOT / "src" / "notifiers" / "outbox.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+(requests|urllib|http\.client|httpx|aiohttp|socket)\b", src_ob, re.M)


def test_store_has_no_secrets(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/secret-token")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100999")
    reps, st = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()))
    text = ob.dumps(st)
    assert "secret-token" not in text and "ABCDEFGHIJ" not in text and "-100999" not in text


# ── CLI・保存のスクリプト・ワークフロー ─────────────────────────────────────

def test_cli_dispatch_dry_run(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from src import cli
    diag_dir = tmp_path / "diag"
    diag_dir.mkdir()
    (diag_dir / "latest.json").write_text(json.dumps(_diag(ps5())), encoding="utf-8")
    out = tmp_path / "out"
    ob.run_observe(out, _diag(ps5("OUT_OF_STOCK")), now=NOW, dry_run=True)
    monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(out))
    monkeypatch.setenv("OPPORTUNITY_DIAGNOSTICS_DIR", str(diag_dir))
    monkeypatch.delenv("NOTIFICATION_DRY_RUN", raising=False)
    r = CliRunner().invoke(cli.cli, ["dispatch-notifications", "--step", "prepare"])
    assert r.exit_code == 0 and '"step": "prepare"' in r.output
    r = CliRunner().invoke(cli.cli, ["dispatch-notifications", "--step", "send", "--persisted-sha", "x"])
    assert r.exit_code == 0 and '"skipped": "dry_run"' in r.output


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=env, check=True,
                          encoding="utf-8", errors="replace").stdout


STATE_REL = "exports/notifications/actionable/state.json"


def _repo(tmp_path):
    """手元の bare の origin と、その clone 2つ（ネットワークに出ない）。"""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    (seed / STATE_REL).parent.mkdir(parents=True)
    (seed / STATE_REL).write_text('{"schema": 2, "products": {}, "records": {}}\n', encoding="utf-8")
    (seed / "docs").mkdir()
    (seed / "docs" / "index.html").write_text("v0\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", "origin", "HEAD:main")
    a, b = tmp_path / "a", tmp_path / "b"
    _git(tmp_path, "clone", "-q", str(origin), str(a))
    _git(tmp_path, "clone", "-q", str(origin), str(b))
    return origin, a, b


def _sh(name, cwd, tmp_path, tag):
    env = {**os.environ, "NOTIFICATION_OUTBOX_BASE_FILE": str(tmp_path / f"base_{tag}"),
           "GITHUB_OUTPUT": str(tmp_path / f"out_{tag}")}
    return subprocess.run(["bash", str(ROOT / "scripts" / name)], cwd=cwd, capture_output=True, env=env,
                          encoding="utf-8", errors="replace")


def test_persist_saves_only_state_without_touching_worktree(tmp_path):
    origin, a, _b = _repo(tmp_path)
    assert _sh("sync_notification_state.sh", a, tmp_path, "a").returncode == 0
    (a / STATE_REL).write_text('{"schema": 2, "products": {"p": {}}, "records": {}}\n', encoding="utf-8")
    (a / "docs" / "index.html").write_text("generated but not committed\n", encoding="utf-8")
    r = _sh("persist_notification_state.sh", a, tmp_path, "a")
    assert r.returncode == 0, r.stderr
    assert "sha=" in (tmp_path / "out_a").read_text()
    log = _git(a, "--git-dir", str(origin), "log", "-1", "--name-only", "--format=%an|%s", "main")
    assert "github-actions[bot]|通知の台帳の保存" in log and STATE_REL in log and "docs/index.html" not in log
    assert (a / "docs" / "index.html").read_text() == "generated but not committed\n"   # 作業ツリーに触れない
    assert "<<<<<<<" not in (a / "docs" / "index.html").read_text()
    r2 = _sh("persist_notification_state.sh", a, tmp_path, "a")                     # 変わっていなければ何もしない
    assert r2.returncode == 0 and _git(a, "--git-dir", str(origin), "rev-list", "--count", "main").strip() == "2"


def test_persist_refuses_when_main_state_changed(tmp_path):
    """合わせた後に別の実行が main の台帳を変えたら、上書きせずに止める（監査 H-1）。"""
    origin, a, b = _repo(tmp_path)
    assert _sh("sync_notification_state.sh", a, tmp_path, "a").returncode == 0      # 古い台帳から始めた実行
    assert _sh("sync_notification_state.sh", b, tmp_path, "b").returncode == 0
    (b / STATE_REL).write_text('{"schema": 2, "products": {}, "records": {"rB": {}}}\n', encoding="utf-8")
    assert _sh("persist_notification_state.sh", b, tmp_path, "b").returncode == 0   # 先の実行が保存
    (a / STATE_REL).write_text('{"schema": 2, "products": {}, "records": {"rA": {}}}\n', encoding="utf-8")
    r = _sh("persist_notification_state.sh", a, tmp_path, "a")
    assert r.returncode == 1
    shown = _git(a, "--git-dir", str(origin), "show", f"main:{STATE_REL}")
    assert '"rB"' in shown and '"rA"' not in shown                                   # 先の記録を消さない
    assert _sh("sync_notification_state.sh", a, tmp_path, "a").returncode == 0      # 否定の対照: 合わせ直せば読める
    assert '"rB"' in (a / STATE_REL).read_text()


def test_persist_requires_sync(tmp_path):
    _origin, a, _b = _repo(tmp_path)
    (a / STATE_REL).write_text('{"schema": 2, "products": {"x": {}}, "records": {}}\n', encoding="utf-8")
    r = _sh("persist_notification_state.sh", a, tmp_path, "nosync")
    assert r.returncode == 1


def test_persist_script_refuses_secrets(tmp_path):
    _origin, a, _b = _repo(tmp_path)
    _sh("sync_notification_state.sh", a, tmp_path, "a")
    for leak in ('{"x": "https://discord.com/api/webhooks/1/abc"}', '{"h": "Authorization: Bearer xyz"}',
                 '{"t": "123456789:AAHabcdefghijklmnopqrstuvwxyz012345"}', '{"Authorization": "x"}',
                 '{"h": "authorization : y"}'):
        (a / STATE_REL).write_text(leak, encoding="utf-8")
        assert _sh("persist_notification_state.sh", a, tmp_path, "a").returncode == 1, leak
    (a / STATE_REL).write_text('{"note": "authorization の語だけ"}', encoding="utf-8")   # 否定の対照: キーでない語は通す
    assert _sh("persist_notification_state.sh", a, tmp_path, "a").returncode == 0


def test_persist_without_state_is_noop(tmp_path):
    r = subprocess.run(["bash", str(ROOT / "scripts" / "persist_notification_state.sh")], cwd=tmp_path,
                       capture_output=True, text=True, env={**os.environ, "GITHUB_OUTPUT": str(tmp_path / "o")})
    assert r.returncode == 0 and "sha=" in (tmp_path / "o").read_text()


def test_generator_skips_when_not_synced(tmp_path, monkeypatch):
    from src.content.daily_lp_generator import DailyLPGenerator
    monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(tmp_path))
    monkeypatch.setenv("NOTIFICATION_OUTBOX_SYNCED", "false")
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    assert g._write_actionable_notifications(_diag(ps5()), NOW) is None
    assert json.loads((tmp_path / "latest.json").read_text())["error"] == "OutboxNotSynced"
    assert not (tmp_path / ob.STORE_NAME).exists()
    monkeypatch.setenv("NOTIFICATION_OUTBOX_SYNCED", "true")            # 否定の対照
    assert g._write_actionable_notifications(_diag(ps5()), NOW) is not None


def test_unexpected_transport_error_is_ambiguous():
    def boom(payload, key):
        raise RuntimeError("https://discord.com/api/webhooks/1/secret")
    a = FixtureAdapter(lambda c, k: None)
    a.transport = boom
    with pytest.raises(ad.ProviderError) as e:
        a.send({"message": "x"}, "k")
    assert e.value.kind == ad.AMBIGUOUS and "secret" not in e.value.error_class


def test_not_configured_does_not_rewrite_timestamps():
    """本番で送信先が無いとき、毎回時刻だけを書き換えない（監査 L-3）。"""
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, dry_run=False)
    _r, st = run(_diag(ps5()), st, dry_run=False)
    before = ob.dumps(st)
    ob.prepare(st, _rows(_diag(ps5())), now=NOW + timedelta(minutes=30), mode=ob.MODE_LIVE, attempt_id="z")
    assert ob.dumps(st) == before


def test_local_attempt_ids_are_unique():
    assert ob.attempt_id_from_env({}, NOW) != ob.attempt_id_from_env({}, NOW)
    assert ob.attempt_id_from_env({"GITHUB_RUN_ID": "9", "GITHUB_RUN_ATTEMPT": "2"}) == "gh-9-2"


def test_deploy_check_856_ok_on_fixtures():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_check
    res = deploy_check._check_phase20_notification_outbox()[0]
    assert res["level"] in ("ok", "warning"), res["message"]


# ── 受入の場面（PS5 Pro・GR IV HDF） ─────────────────────────────────────────

def test_fixture_acceptance_ps5():
    (_r0, r1, r2, r3, r4), st = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()), _diag(ps5()),
                                    _diag(ps5("OUT_OF_STOCK")), _diag(ps5()))
    assert (r1["notification_candidates"], r1["dispatch_planned"], r1["dispatch_sent"]) == (1, 1, 0)
    assert r2["notification_candidates"] == 0 and len(st["records"]) == 2 and r4["notification_candidates"] == 1


def test_fixture_acceptance_gr4():
    (_r0, r1, r2), st = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)), _diag(gr4(OPEN)))
    assert (r1["notification_candidates"], r1["dispatch_planned"]) == (1, 1) and r2["notification_candidates"] == 0
    assert len(st["records"]) == 1


def test_fixture_acceptance_lottery_to_stock():
    reps, _ = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)), _diag(stock_gr4()), _diag(gr4(OPEN)))
    assert [r["notification_candidates"] for r in reps] == [0, 1, 1, 0]


def test_expired_record_revived_when_actionable_again():
    """配信の前に期限切れになった（送っていない）記録は、同じ変化がまた行動できれば同じキーで配信待ちに戻す。"""
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {})
    r, st = run(_diag(ps5()), st, dispatch_now=NOW + timedelta(hours=4))
    assert r["dispatch_expired"] == 1
    later = NOW + timedelta(hours=5)
    r, st = run(_diag(ps5(checked=later - timedelta(minutes=5), now=later)), st, now=later)
    assert r["dispatch_planned"] == 1 and len(st["records"]) == 1
    delivered = st
    r, _ = run(_diag(ps5(checked=later - timedelta(minutes=5), now=later)), delivered, now=later)
    assert r["notification_candidates"] == 0                           # 計画した後は戻さない


def test_prepare_skips_when_diagnostics_not_current(tmp_path):
    """今回の候補の記録（observe）と違う診断（生成に失敗した実行・古い診断）では確かめ直さない（レビュー M-2）。"""
    old = dict(_diag(ps5()), generated_at="2026-10-08T12:00:00+09:00")
    new = dict(_diag(ps5()), generated_at="2026-10-09T12:00:00+09:00")
    ob.run_observe(tmp_path, dict(_diag(ps5("OUT_OF_STOCK")), generated_at="x"), now=NOW, dry_run=True)
    ob.run_observe(tmp_path, new, now=NOW, dry_run=True)
    before = (tmp_path / ob.STORE_NAME).read_text(encoding="utf-8")
    r = ob.run_prepare(tmp_path, old, now=NOW, dry_run=True, attempt_id="a")
    assert r["skipped"] == "diagnostics_not_current"
    assert (tmp_path / ob.STORE_NAME).read_text(encoding="utf-8") == before
    r = ob.run_prepare(tmp_path, new, now=NOW, dry_run=True, attempt_id="a")      # 否定の対照: 同じ診断なら確かめる
    assert r["dispatch_planned"] == 1


def test_gateway_errors_are_ambiguous():
    """500・502・504 は相手が処理した後に返ることがある → 届いたか不明（自動では出し直さない）。503・429 は出し直す。"""
    for status in (500, 502, 504):
        assert ad.classify_http(status).kind == ad.AMBIGUOUS
    assert ad.classify_http(503).kind == ad.RETRYABLE and ad.classify_http(429).kind == ad.RETRYABLE


def test_payload_is_not_truncated():
    """本文を切り詰めない（末尾の購入 URL を欠かさない）。長すぎれば送らない（FAILED_FINAL）。"""
    rec = {"message": "x" * 1990 + "\n購入する: " + SONY}
    d = ad.DiscordAdapter(lambda p, k: (200, {}, {}))
    p = d.build_payload(rec)
    assert p["content"].endswith(SONY) and "too_long" in d.validate(p)
    with pytest.raises(ad.ProviderError) as e:
        d.send(rec, "k")
    assert e.value.kind == ad.FINAL
