"""Phase 25（Phase 24 の受入の状態の検知・記録・見える化）のテスト。

行は Phase 18 の判定の正本（actionability.evaluate → 診断の形）から作る（テストだけの fixture。本番には入れない）。
送信はしない（受入の流れの確認だけ偽の通信）。各テストに否定の対照を付ける。
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from _notify_helpers import CLOSED, NOW, OPEN, RICOH, _diag, _view, gr4, lottery_event, ps5
from src.market import actionability as act
from src.notifiers import adapters as ad
from src.notifiers import outbox as ob
from src.notifiers import readiness as rd
from src.notifiers import telegram_transport as tt

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "123456789:AAdummydummydummydummydummydummy00X"
CHAT = "-1009876543210"
OK = (200, json.dumps({"ok": True, "result": {"message_id": 901}}).encode())


def cam(stock="IN_STOCK", now=NOW):
    return _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock=stock,
                                              stock_checked_at=now - timedelta(minutes=10), buy_url=RICOH, now=now),
                 net=16200, roi=0.073, name="RICOH GR IV HDF")


class Sched:
    """定時の実行（dry-run）の LP の生成の observe を一時の台帳で行い、受入の状態を返す。"""

    def __init__(self, tmp):
        self.tmp, self.n = Path(tmp), 0
        self.tmp.mkdir(parents=True, exist_ok=True)
        if not (self.tmp / ob.STORE_NAME).exists():
            ob.save(self.tmp / ob.STORE_NAME, ob.empty_store())                 # 台帳はある（本番と同じ）

    def __call__(self, *views, now=NOW, dry=True):
        self.n += 1
        d = dict(_diag(*views), generated_at=f"{now.isoformat()}#{self.n}")
        rep = ob.run_observe(self.tmp, d, now=now, dry_run=dry)
        ob.run_prepare(self.tmp, d, now=now, dry_run=True, attempt_id=f"gh-{self.n}-1", acceptance_env=ob.NO_ACCEPTANCE_GATE)      # 定時の実行の dry-run
        return rep["phase24_readiness"]

    def store(self):
        return ob.load(self.tmp / ob.STORE_NAME)[0]

    def file(self):
        return rd.load(self.tmp)


@pytest.fixture
def sched(tmp_path):
    return Sched(tmp_path)


def later(h):
    return NOW + timedelta(hours=h)


# ── 状態 ───────────────────────────────────────────────────────────────────

def test_no_candidate_is_waiting(sched):
    g = sched(ps5("OUT_OF_STOCK"), gr4(CLOSED))
    assert g["status"] == rd.WAITING and g["candidate_count"] == 0 and g["detection"] == rd.NO_ACTIONABLE_CHANGE
    g = sched(ps5("OUT_OF_STOCK"), gr4(CLOSED))
    assert g["status"] == rd.WAITING and g["external_sends"] == 0
    assert sched.file()["status"] == rd.WAITING                                   # 出力のファイルも同じ


def test_new_real_candidate_is_ready_ps5(sched):
    sched(ps5("OUT_OF_STOCK"))
    g = sched(ps5())
    assert g["status"] == rd.READY and g["detection"] == rd.NEW_ACTIONABLE_FOUND and g["candidate_count"] == 1
    c = g["candidates"][0]
    assert (c["product_id"], c["net_profit"], c["roi"], c["availability"]) == ("prod_ps5_pro", 54870, 0.396, "IN_STOCK")
    assert c["action_url"].startswith("https://pur.store.sony.jp/") and c["detected_at"] and c["age_hours"] == 0.0
    assert c["priority"] == 1 and g["top_candidate"] == c["candidate_id"] and g["send_limit"] == 1


def test_new_real_candidate_is_ready_lottery(sched):
    sched(gr4(lottery_event(later(24), later(72), status="upcoming")))
    g = sched(gr4(OPEN))
    assert g["status"] == rd.READY and g["candidates"][0]["type"] == "抽選受付が始まりました"
    assert g["candidates"][0]["deadline"]


def test_missing_ledger_is_review_required(tmp_path):
    """台帳が無い・読めない実行は判定できない（WAITING / READY にしない。レビュー L-4）。"""
    rep = ob.run_observe(tmp_path, dict(_diag(ps5()), generated_at="g"), now=NOW, dry_run=True)
    assert rep["phase24_readiness"]["status"] == rd.REVIEW_REQUIRED and rep["phase24_readiness"]["error"] == "no_store"
    rep = ob.run_observe(tmp_path, {"generated_at": "g2"}, now=NOW, dry_run=True)   # 診断に判定が無い（監査 L-1）
    assert rep["phase24_readiness"]["status"] == rd.REVIEW_REQUIRED


def test_baseline_actionable_is_not_a_candidate(sched):
    """前の状態を見ていない（基準日）商品が行動できても、受入候補にしない（変化を見ていない）。"""
    g = sched(ps5())
    assert g["status"] == rd.WAITING and g["actionable"] == 1


def test_same_true_state_not_new_but_ready_continues(sched):
    sched(ps5("OUT_OF_STOCK"))
    g1 = sched(ps5())
    g2 = sched(ps5(checked=later(2) - timedelta(minutes=10), now=later(2)), now=later(2))
    assert g2["status"] == rd.READY and g2["detection"] == rd.ACTIONABLE_STILL_PRESENT
    assert g2["candidates"][0]["new_this_run"] is False
    assert g2["candidates"][0]["detected_at"] == g1["candidates"][0]["detected_at"]   # 検知の時刻を新しくしない
    assert g2["candidates"][0]["candidate_id"] == g1["candidates"][0]["candidate_id"]
    assert len([h for h in g2["history"] if h["candidate_id"] == g1["candidate_ids"][0]]) == 1   # 毎回新規にしない
    h1 = [h for h in g1["history"] if h["candidate_id"] == g1["candidate_ids"][0]][0]
    h2 = [h for h in g2["history"] if h["candidate_id"] == g1["candidate_ids"][0]][0]
    assert h2["changed_at"] == h1["changed_at"]                                  # 状態が同じなら履歴の時刻も動かさない
    t = later(ob.LIVE_CANDIDATE_MAX_AGE_HOURS + 1)
    g3 = sched(ps5(checked=t - timedelta(minutes=10), now=t), now=t)
    h3 = [h for h in g3["history"] if h["candidate_id"] == g1["candidate_ids"][0]][0]
    assert h3["changed_at"] == t.isoformat(timespec="seconds")                   # 否定の対照: 状態が変われば進む


def test_detected_at_is_earliest_record():
    """検知の時刻は、その変化の記録のうち最も古い時刻（後の記録で新しくしない）。"""
    recs = [{"created_at": later(5).isoformat()}, {"created_at": NOW.isoformat()}, {"created_at": later(2).isoformat()}]
    assert rd._detected_at(recs) == NOW and rd._detected_at([]) is None


def test_candidate_persists_across_runs(sched, tmp_path):
    sched(ps5("OUT_OF_STOCK"))
    g1 = sched(ps5())
    s2 = Sched(tmp_path)                                                         # 次の実行（同じ台帳・出力）
    s2.n = 10
    g2 = s2(ps5(checked=later(1) - timedelta(minutes=10), now=later(1)), now=later(1))
    assert g2["candidate_ids"] == g1["candidate_ids"]


def test_candidate_expires_after_24h(sched):
    sched(ps5("OUT_OF_STOCK"))
    sched(ps5())
    t = later(ob.LIVE_CANDIDATE_MAX_AGE_HOURS + 1)
    g = sched(ps5(checked=t - timedelta(minutes=10), now=t), now=t)
    assert g["status"] == rd.WAITING and g["detection"] == rd.ACTIONABLE_LOST
    assert g["history"][0]["lifecycle"] == rd.C_EXPIRED
    t2 = later(ob.LIVE_CANDIDATE_MAX_AGE_HOURS - 1)                              # 否定の対照: 24時間以内は READY
    s = Sched(Path(sched.tmp) / "b")
    s(ps5("OUT_OF_STOCK"))
    s(ps5())
    assert s(ps5(checked=t2 - timedelta(minutes=10), now=t2), now=t2)["status"] == rd.READY


@pytest.mark.parametrize("view,why", [
    (lambda: ps5("OUT_OF_STOCK"), "not_actionable"),
    (lambda: ps5(profitable=False), "not_actionable"),                            # 利益が確定でなくなった
    (lambda: ps5(checked=NOW - timedelta(hours=5)), "not_actionable"),            # 在庫の確認が古い
    (lambda: ps5(url="https://www.sony.jp/"), "not_actionable"),                  # 公式の購入ページでない
])
def test_candidate_invalidated(sched, view, why):
    sched(ps5("OUT_OF_STOCK"))
    assert sched(ps5())["status"] == rd.READY
    g = sched(view())
    assert g["status"] == rd.WAITING and g["history"][0]["lifecycle"] in (rd.C_INVALIDATED,)
    assert why in g["history"][0]["reason"] or g["history"][0]["reason"] == "not_current"


def test_lottery_deadline_passed_invalidated(sched):
    sched(gr4(lottery_event(later(24), later(72), status="upcoming")))
    assert sched(gr4(OPEN))["status"] == rd.READY
    g = sched(gr4(CLOSED))
    assert g["status"] == rd.WAITING and g["history"][0]["lifecycle"] == rd.C_INVALIDATED


def test_delivered_and_cancelled_removed(sched):
    sched(ps5("OUT_OF_STOCK"))
    sched(ps5())
    st = sched.store()
    ob.observe(st, ob._rows(_diag(ps5())), now=NOW, mode=ob.MODE_LIVE, channels=["telegram"])   # 受入の実行が引き継ぐ
    live = [r for r in st["records"].values() if r["mode"] == ob.MODE_LIVE][0]
    live["channels"]["telegram"].update(status=ob.DELIVERED, provider_delivery_id="9")
    live["status"] = ob.DELIVERED
    g = rd.evaluate(st, ob._rows(_diag(ps5())), now=NOW)
    assert g["status"] == rd.ACCEPTANCE_DONE and g["history"][0]["lifecycle"] == rd.C_DELIVERED and not g["candidates"]
    live["channels"]["telegram"].update(status=ob.FAILED_FINAL, provider_delivery_id="")
    live["status"] = ob.FAILED_FINAL
    g = rd.evaluate(st, ob._rows(_diag(ps5())), now=NOW)
    assert g["status"] == rd.WAITING and g["history"][0]["lifecycle"] == rd.C_CANCELLED
    live["channels"]["telegram"].update(status=ob.UNKNOWN_DELIVERY)
    live["status"] = ob.UNKNOWN_DELIVERY
    g = rd.evaluate(st, ob._rows(_diag(ps5())), now=NOW)
    assert g["history"][0]["lifecycle"] == rd.C_UNKNOWN and g["status"] == rd.REVIEW_REQUIRED   # 解決まで次の受入をしない
    live["channels"]["telegram"].update(status=ob.READY)                         # 否定の対照: 送っていない
    live["status"] = ob.READY
    assert rd.evaluate(st, ob._rows(_diag(ps5())), now=NOW)["status"] == rd.READY


def test_multiple_candidates_priority_preview(sched):
    sched(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    g = sched(ps5(), cam())
    assert g["candidate_count"] == 2 and g["send_limit"] == 1
    # 既存の順位（診断の行の並び）。新しい順位の体系は作らない
    rows = ob._rows(_diag(ps5(), cam()))
    assert [c["product_id"] for c in g["candidates"]] == [r["product_id"] for r in rows if r["actionable"]]
    assert [c["priority"] for c in g["candidates"]] == [1, 2] and g["top_candidate"] == g["candidates"][0]["candidate_id"]


def test_detection_failure_is_review_required(tmp_path):
    g = rd.failed(NOW, "OutboxNotSynced")
    assert g["status"] == rd.REVIEW_REQUIRED and g["candidate_count"] == 0 and g["candidates"] == []
    # 生成の失敗で REVIEW_REQUIRED を書く（READY と推測しない。前の履歴は残す）
    from src.content.daily_lp_generator import DailyLPGenerator
    gen = DailyLPGenerator.__new__(DailyLPGenerator)
    import os
    os.environ["ACTIONABLE_NOTIFICATIONS_DIR"] = str(tmp_path)
    try:
        rd.write(tmp_path, {"status": rd.READY, "history": [{"candidate_id": "x", "lifecycle": "READY"}]})
        gen._write_notification_failure(NOW, None, "DiagnosticsFailed")
        d = rd.load(tmp_path)
        assert d["status"] == rd.REVIEW_REQUIRED and d["history"][0]["candidate_id"] == "x"
    finally:
        del os.environ["ACTIONABLE_NOTIFICATIONS_DIR"]


def test_evaluate_exception_is_review_required(tmp_path, monkeypatch):
    monkeypatch.setattr(rd, "evaluate", lambda *a, **k: 1 / 0)
    rep = ob.run_observe(tmp_path, dict(_diag(ps5()), generated_at="g"), now=NOW, dry_run=True)
    assert rep["phase24_readiness"]["status"] == rd.REVIEW_REQUIRED and rep["phase24_readiness"]["error"] == "no_store"


def test_no_send_and_safe_defaults(sched, monkeypatch):
    calls = []
    monkeypatch.setattr(tt, "make_telegram_transport", lambda *a, **k: calls.append(1))
    sched(ps5("OUT_OF_STOCK"))
    g = sched(ps5())
    assert g["status"] == rd.READY and calls == [] and g["external_sends"] == 0
    assert ob.counts(sched.store())["delivered"] == 0 and ob.counts(sched.store())["sending"] == 0
    assert not ad.real_send_gate({})["allowed"] and not ad.product_live_intent({})["allowed"]


def test_scheduled_run_cannot_real_send():
    env = {"NOTIFICATION_REAL_SEND": "true", "NOTIFICATION_DRY_RUN": "false", "NOTIFICATION_PROVIDERS": "telegram",
           "PRODUCT_REAL_SEND_ENABLED": "true", "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT}
    assert not ad.real_send_gate(dict(env, GITHUB_EVENT_NAME="schedule"))["allowed"]
    assert ad.real_send_gate(dict(env, GITHUB_EVENT_NAME="workflow_dispatch"))["allowed"]          # 否定の対照


def test_readiness_output_has_no_secrets_or_keys(sched):
    sched(ps5("OUT_OF_STOCK"))
    sched(ps5())
    text = (Path(sched.tmp) / rd.FILE_NAME).read_text(encoding="utf-8")
    assert TOKEN not in text and CHAT not in text and "ACTIONABLE_NOW:" not in text   # 冪等性のキーも出さない


# ── Phase 24 への引き継ぎ（定時の実行で検知 → 手動の受入の実行で1件だけ） ─────────────

class Opener:
    def __init__(self, result):
        self.result, self.requests = result, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        status, body = self.result
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(body))
        return SimpleNamespace(getcode=lambda: status, headers={}, read=lambda: body)


def _accept(tmp, *views, now=NOW, aid="gh-500-1"):
    d = dict(_diag(*views), generated_at=f"{now.isoformat()}#acc{aid}")
    obs = ob.run_observe(tmp, d, now=now, dry_run=False)
    ob.run_prepare(tmp, d, now=now, dry_run=False, attempt_id=aid, live_channels={"telegram"}, send_limit=1, acceptance_env=ob.NO_ACCEPTANCE_GATE)
    op = Opener(OK)
    ob.run_send(tmp, now=now, dry_run=False, attempt_id=aid, persisted_sha=ob.file_sha(Path(tmp) / ob.STORE_NAME),
                real_send_allowed=True, limit=1,
                adapters={"telegram": ad.TelegramAdapter(tt.make_telegram_transport(TOKEN, CHAT, opener=op))}, acceptance_env=ob.NO_ACCEPTANCE_GATE)
    return obs, op


def test_handoff_scheduled_detection_to_acceptance(sched):
    sched(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    g = sched(ps5(), cam())                                                      # 定時の実行で2件検知
    assert g["status"] == rd.READY and g["candidate_count"] == 2
    t = later(3)
    views = (ps5(checked=t - timedelta(minutes=10), now=t), cam(now=t))
    obs, op = _accept(sched.tmp, *views, now=t)                                  # 手動の受入の実行
    assert len(op.requests) == 1 and obs["phase24_readiness"]["status"] == rd.READY
    st = sched.store()
    live = [r for r in st["records"].values() if r["mode"] == ob.MODE_LIVE]
    assert len(live) == 2 and all(r.get("adopted_from") for r in live)
    d = [r for r in live if r["status"] == ob.DELIVERED]
    assert len(d) == 1 and d[0]["product_id"] == "prod_ps5_pro"                  # 既存の順位の先頭
    assert d[0]["created_at"] == g["candidates"][0]["detected_at"]               # 検知の時刻（新しくしない）
    assert d[0]["channels"]["telegram"]["provider_delivery_id"] == "901"
    # 同じ run の再実行: 送らない。受入は1件だけなので、残りの候補を READY にしない（受入済み。レビュー M-1）
    _o, op2 = _accept(sched.tmp, *views, now=t, aid="gh-500-2")
    assert op2.requests == []
    g2 = sched(*views, now=t)
    assert g2["status"] == rd.ACCEPTANCE_DONE and g2["candidate_count"] == 0
    assert {h["lifecycle"] for h in g2["history"]} == {rd.C_DELIVERED, rd.C_HELD}


def test_handoff_same_candidate_reevaluated_no_new_outbox(sched):
    sched(ps5("OUT_OF_STOCK"))
    sched(ps5())
    st = sched.store()
    o1 = ob.observe(st, ob._rows(_diag(ps5())), now=NOW, mode=ob.MODE_LIVE, channels=["telegram"])
    o2 = ob.observe(st, ob._rows(_diag(ps5())), now=NOW, mode=ob.MODE_LIVE, channels=["telegram"])
    assert o1.get("adopted") == 1 and o2.get("adopted") is None
    assert o2["notification_candidates"] == 0 and o2["dedupe_suppressed"] == 1 and o2["new_outbox"] == []


def test_handoff_rejects_older_than_24h(sched):
    sched(ps5("OUT_OF_STOCK"))
    sched(ps5())
    t = later(ob.LIVE_CANDIDATE_MAX_AGE_HOURS + 1)
    obs, op = _accept(sched.tmp, ps5(checked=t - timedelta(minutes=10), now=t), now=t)
    assert op.requests == [] and obs["notification_candidates"] == 0             # 24時間を過ぎた検知は送らない


def test_handoff_rejects_cancelled_dry_record(sched):
    """dry-run の記録が取り消し（行動できなくなった）なら引き継がない。READY にもしない。"""
    sched(ps5("OUT_OF_STOCK"))
    sched(ps5())
    st = sched.store()
    rec = next(iter(st["records"].values()))
    rec["status"] = ob.CANCELLED
    for c in rec["channels"].values():
        c["status"] = ob.CANCELLED
    assert not ob.handoff_ok(st, rec["idempotency_key"], NOW)
    g = rd.evaluate(st, ob._rows(_diag(ps5())), now=NOW)
    assert g["status"] == rd.WAITING and "outbox_not_creatable" in g["history"][0]["reason"]


def test_canary_and_product_not_same_run(tmp_path, monkeypatch):
    import src.cli as cli
    monkeypatch.setattr(tt, "make_telegram_transport", lambda *a, **k: pytest.fail("canary を送った"))
    for k, v in {"NOTIFICATION_REAL_SEND": "true", "NOTIFICATION_DRY_RUN": "false", "NOTIFICATION_PROVIDERS": "telegram",
                 "TELEGRAM_CANARY": "true", "TELEGRAM_CANARY_ID": "telegram_canary_v7", "GITHUB_EVENT_NAME": "workflow_dispatch",
                 "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT}.items():
        monkeypatch.setenv(k, v)
    ob.save(tmp_path / ob.STORE_NAME, ob.empty_store())
    res = cli._telegram_canary(tmp_path, now=NOW, attempt_id="gh-1-1", product_gate={"allowed": True, "checks": {}})
    assert res["canary"] == "skipped_product_run"


# ── 表示・CI ───────────────────────────────────────────────────────────────

def test_admin_readiness_waiting_and_ready(sched):
    from src.content.ui import admin
    html = admin._readiness(admin.build_readiness(sched(ps5("OUT_OF_STOCK"))))
    assert "実データの候補待ち" in html and "受入候補</dt><dd>0件" in html and "Run workflow" not in html
    html = admin._readiness(admin.build_readiness(sched(ps5())))
    for part in ("Phase 24 の本番受入候補あり", "PlayStation 5 Pro", "+¥54,870", "39.6%", "購入可能", "Run workflow",
                 "PRODUCT_REAL_SEND_ENABLED=false", "外部への送信</dt><dd>0件"):
        assert part in html, part
    assert "<button" not in html and "<form" not in html                         # 送れるような偽の操作を置かない
    assert "ACTIONABLE_NOW:" not in html


def test_admin_readiness_unknown_is_review_required():
    from src.content.ui import admin
    assert admin.build_readiness(None) == {} and admin._readiness({}) == ""      # 通知を作らない生成は欄を出さない
    for d in ({}, {"status": "BOGUS", "candidates": [{"product": "x"}]},
              {"status": rd.READY, "candidate_count": 3, "candidates": []}):     # 壊れた READY（監査 L-2）
        r = admin.build_readiness(d)
        assert r["status"] == rd.REVIEW_REQUIRED and r["candidates"] == [] and r["count"] == 0
        assert "判定できない" in admin._readiness(r)


def test_admin_history_lifecycles(sched):
    from src.content.ui import admin
    sched(ps5("OUT_OF_STOCK"))
    sched(ps5())
    t = later(25)
    html = admin._readiness(admin.build_readiness(sched(ps5(checked=t - timedelta(minutes=5), now=t), now=t)))
    assert "期限切れ（検知から24時間）" in html and "候補が無くなった" in html


def test_cli_readiness_summary(tmp_path, monkeypatch):
    from click.testing import CliRunner
    import src.cli as cli
    s = Sched(tmp_path)
    s(ps5("OUT_OF_STOCK"))
    s(ps5())
    summ = tmp_path / "summary.md"
    dg = tmp_path / "diag"
    dg.mkdir()
    (dg / "latest.json").write_text(json.dumps(dict(_diag(ps5()), generated_at=f"{NOW.isoformat()}#2")), encoding="utf-8")
    monkeypatch.setenv("OPPORTUNITY_DIAGNOSTICS_DIR", str(dg))

    class _DT(cli.datetime):                                                     # CLI の「今」をテストの時刻に
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(cli, "datetime", _DT)
    monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summ))
    out = CliRunner().invoke(cli.cli, ["notification", "readiness"]).output
    assert "Phase24 readiness: PHASE24_REAL_CANDIDATE_READY" in out and "external sends: 0" in out
    assert "PHASE24_REAL_CANDIDATE_READY" in summ.read_text(encoding="utf-8")
    monkeypatch.setenv("GITHUB_RUN_ID", "99999")                                # 前回の run の出力（チェックアウトに残った）
    out = CliRunner().invoke(cli.cli, ["notification", "readiness"]).output
    assert "PHASE24_REVIEW_REQUIRED" in out                                      # 今回の run でなければ判定できない
    monkeypatch.delenv("GITHUB_RUN_ID")
    (dg / "latest.json").unlink()
    out = CliRunner().invoke(cli.cli, ["notification", "readiness"]).output
    assert "PHASE24_REVIEW_REQUIRED" in out                                      # 読めなければ READY と推測しない


def _dc():
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_check
    return deploy_check


def test_deploy_check_860_ok_and_detects_fake_ready(tmp_path):
    import shutil
    dc = _dc()
    assert dc._check_phase25_readiness()[0]["level"] == "ok"
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(ROOT / ".github" / "workflows" / "daily_lp.yml", tmp_path / ".github" / "workflows")
    out = tmp_path / "exports" / "notifications" / "actionable"
    rd.write(out, rd.failed(NOW, "x") | {"status": rd.WAITING})
    assert dc._check_phase25_readiness(tmp_path)[0]["level"] == "ok"
    rd.write(out, rd.failed(NOW, "x") | {"status": rd.READY})                   # 候補なしで READY
    assert dc._check_phase25_readiness(tmp_path)[0]["level"] == "error"
    diag = tmp_path / "exports" / "opportunity_diagnostics"
    diag.mkdir(parents=True)
    (diag / "latest.json").write_text(json.dumps(_diag(ps5("OUT_OF_STOCK"))), encoding="utf-8")
    rd.write(out, rd.failed(NOW, "x") | {"status": rd.READY, "candidates": [{"product_id": "prod_ps5_pro"}]})
    assert dc._check_phase25_readiness(tmp_path)[0]["level"] == "error"        # 診断で行動できない候補の READY


# ── レビュー・監査の指摘（M-1・M-2・L-1〜L-5） ─────────────────────────────

def test_refresh_after_send_shows_acceptance_done(sched, monkeypatch):
    """送信の手順の後に確かめ直すと、送った実行の状態は受入済み（READY のまま出さない。監査 M-1・レビュー M-1）。"""
    sched(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    sched(ps5(), cam())
    t = later(2)
    views = (ps5(checked=t - timedelta(minutes=10), now=t), cam(now=t))
    monkeypatch.setenv("GITHUB_RUN_ID", "500")
    obs, op = _accept(sched.tmp, *views, now=t, aid="gh-500-1")
    assert len(op.requests) == 1 and obs["phase24_readiness"]["status"] == rd.READY   # observe の時点
    diag = dict(_diag(*views), generated_at=f"{t.isoformat()}#accgh-500-1")
    d = rd.refresh(sched.store(), diag, ob._load_report(sched.tmp), now=t, attempt_id="gh-500-1", prev=sched.file())
    assert d["status"] == rd.ACCEPTANCE_DONE and d["sent_this_run"] == 1 and d["candidates"] == []
    assert d["detection"] == rd.ACCEPTANCE_COMPLETED                             # 「候補が無くなった」ではない
    assert any("追加の手動の実行はしない" in ln for ln in rd.summary_lines(d))
    monkeypatch.setenv("GITHUB_RUN_ID", "501")                                   # 別の run の報告: 判定できない
    d = rd.refresh(sched.store(), diag, ob._load_report(sched.tmp), now=t, attempt_id="gh-501-1", prev=sched.file())
    assert d["status"] == rd.REVIEW_REQUIRED


def test_adopted_is_not_new_detection(sched):
    sched(ps5("OUT_OF_STOCK"))
    sched(ps5())
    obs, _op = _accept(sched.tmp, ps5(), now=NOW)
    assert obs["phase24_readiness"]["detection"] == rd.ACTIONABLE_STILL_PRESENT     # 引き継ぎは新しい検知ではない


def test_handoff_ok_respects_retry_time_and_attempts(sched):
    sched(ps5("OUT_OF_STOCK"))
    sched(ps5())
    st = sched.store()
    ob.observe(st, ob._rows(_diag(ps5())), now=NOW, mode=ob.MODE_LIVE, channels=["telegram"])
    live = [r for r in st["records"].values() if r["mode"] == ob.MODE_LIVE][0]
    c = live["channels"]["telegram"]
    assert ob.handoff_ok(st, live["idempotency_key"], NOW)                      # 否定の対照
    c.update(status=ob.FAILED_RETRYABLE, next_attempt_at=later(1).isoformat())
    assert not ob.handoff_ok(st, live["idempotency_key"], NOW)                  # 再試行の時刻の前
    c.update(next_attempt_at="", attempt_count=ob.MAX_ATTEMPTS)
    assert not ob.handoff_ok(st, live["idempotency_key"], NOW)                  # 試行の上限


def test_lost_after_review_required(sched):
    sched(ps5("OUT_OF_STOCK"))
    sched(ps5())
    rd.write(sched.tmp, rd.failed(NOW, "x", prev=sched.file()))                 # 間に判定できない実行
    g = sched(ps5("OUT_OF_STOCK"))
    assert g["detection"] == rd.ACTIONABLE_LOST


def test_normalized_rejects_malformed_ready():
    assert rd.normalized({"status": rd.READY, "candidates": []})["status"] == rd.REVIEW_REQUIRED
    assert rd.normalized({"status": rd.READY, "candidates": [{"x": 1}]})["status"] == rd.REVIEW_REQUIRED
    ok = {"status": rd.READY, "candidates": [{"product_id": "p", "candidate_id": "c"}]}
    assert rd.normalized(ok)["status"] == rd.READY                              # 否定の対照
