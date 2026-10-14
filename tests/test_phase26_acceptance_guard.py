"""Phase 26（受入の関門: 受入状態を実送信の必須の条件にする）のテスト。

本物の関門の経路を通す: LP の生成の observe → CLI の dispatch-notifications --step prepare → 保存 → --step send を、
ワークフローと同じ環境変数で呼ぶ。Telegram の通信だけを偽物にする（ネットワークに出ない）。CLI は今の時刻を使うので、
行も今の時刻から Phase 18 の判定の正本で作る（テストだけの fixture。本番には入れない）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from _notify_helpers import RICOH, _diag, _view, ps5
from src.market import actionability as act
from src.notifiers import actionable as an
from src.notifiers import adapters as ad
from src.notifiers import outbox as ob
from src.notifiers import readiness as rd
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "123456789:AAdummydummydummydummydummydummy00X"
CHAT = "-1009876543210"
LIVE = {"NOTIFICATION_REAL_SEND": "true", "NOTIFICATION_DRY_RUN": "false", "NOTIFICATION_PROVIDERS": "telegram",
        "PRODUCT_REAL_SEND_ENABLED": "true", "PRODUCT_NOTIFICATION_LIMITED_MODE": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch", "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT}
SAFE = {"NOTIFICATION_REAL_SEND": "false", "NOTIFICATION_DRY_RUN": "true", "PRODUCT_REAL_SEND_ENABLED": "false",
        "GITHUB_EVENT_NAME": "schedule"}


def ps(stock="IN_STOCK", now=None):
    now = now or datetime.now(JST)
    return ps5(stock, checked=now - timedelta(minutes=10), now=now)


def cam(stock="IN_STOCK", now=None):
    now = now or datetime.now(JST)
    return _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock=stock,
                                              stock_checked_at=now - timedelta(minutes=10), buy_url=RICOH, now=now),
                 net=16200, roi=0.073, name="RICOH GR IV HDF")


class World:
    """一時の台帳・診断で、ワークフローの通知の手順を実行する。"""

    def __init__(self, tmp, monkeypatch):
        self.out, self.diag_dir = Path(tmp) / "out", Path(tmp) / "diag"
        self.out.mkdir()
        self.diag_dir.mkdir()
        ob.save(self.out / ob.STORE_NAME, ob.empty_store())
        self.mp, self.n, self.requests = monkeypatch, 0, []
        monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(self.out))
        monkeypatch.setenv("OPPORTUNITY_DIAGNOSTICS_DIR", str(self.diag_dir))
        import src.notifiers.telegram_transport as ttm

        def fake(token, chat_id, **kw):
            assert token == TOKEN and chat_id == CHAT

            def transport(payload, key):
                self.requests.append(payload["text"])
                return 200, {}, {"ok": True, "result": {"message_id": 700 + len(self.requests)}}
            return transport
        monkeypatch.setattr(ttm, "make_telegram_transport", fake)

    def env(self, env):
        for k in set(LIVE) | set(SAFE) | {rd.CANDIDATE_VAR, "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "TELEGRAM_CANARY"}:
            self.mp.delenv(k, raising=False)
        for k, v in env.items():
            self.mp.setenv(k, v)

    def run(self, *views, env=SAFE, cid=None, run_id=None, attempt=1, at=None):
        """1回の workflow の実行（生成 → prepare → 保存 → send）。この実行の送信の要求の数を返す。"""
        self.n += 1
        e = dict(env, GITHUB_RUN_ID=str(run_id or 1000 + self.n), GITHUB_RUN_ATTEMPT=str(attempt))
        if cid is not None:
            e[rd.CANDIDATE_VAR] = cid
        self.env(e)
        now = at or datetime.now(JST)
        d = dict(_diag(*views), generated_at=f"{now.isoformat()}#{self.n}")
        (self.diag_dir / "latest.json").write_text(json.dumps(d), encoding="utf-8")
        dry = an.is_dry_run() or not ad.product_live_intent()["allowed"]      # LP の生成と同じ決め方
        self.observe = ob.run_observe(self.out, d, now=now, dry_run=dry)
        import src.cli as cli
        r = CliRunner()
        before = len(self.requests)
        self.prep = json.loads(r.invoke(cli.cli, ["dispatch-notifications", "--step", "prepare"]).output)
        sha = ob.file_sha(self.out / ob.STORE_NAME)
        res = r.invoke(cli.cli, ["dispatch-notifications", "--step", "send", "--persisted-sha", sha])
        assert res.exit_code == 0, res.output
        self.send = json.loads(res.output)
        assert TOKEN not in res.output and CHAT not in res.output
        return len(self.requests) - before

    def store(self):
        return ob.load(self.out / ob.STORE_NAME)[0]

    def ready(self, *views):
        """今の候補（受入状態）。"""
        return rd.evaluate(self.store(), ob._rows(_diag(*views)), now=datetime.now(JST))

    def live(self, pid=None):
        return [r for r in self.store()["records"].values() if r["mode"] == ob.MODE_LIVE and not r.get("is_canary")
                and (pid is None or r["product_id"] == pid)]


@pytest.fixture
def w(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def _two_ready(w):
    w.run(ps("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))                             # 定時の実行
    assert w.run(ps(), cam()) == 0                                               # 定時の実行で2件検知（送らない）
    g = w.ready(ps(), cam())
    assert g["status"] == rd.READY and g["candidate_count"] == 2
    return g["candidates"][0]["candidate_id"], g["candidates"][1]["candidate_id"]


# ── 関門 ───────────────────────────────────────────────────────────────────

def test_waiting_blocks_send(w):
    w.run(ps("OUT_OF_STOCK"))
    assert w.ready(ps("OUT_OF_STOCK"))["status"] == rd.WAITING
    assert w.run(ps("OUT_OF_STOCK"), env=LIVE, cid="0123456789abcdef") == 0
    assert w.prep["acceptance"]["reason"] in ("candidate_not_in_ledger", "readiness_PHASE24_WAITING")


def test_ready_exact_candidate_sends_once(w):
    a, _b = _two_ready(w)
    assert w.run(ps(), cam(), env=LIVE, cid=a) == 1                             # 受入: 選んだ A の1件だけ
    assert "PlayStation 5 Pro" in w.requests[-1] and w.prep["acceptance"]["allowed"] is True
    assert w.send["acceptance_send"]["allowed"] is True
    rec = w.live("prod_ps5_pro")[0]
    assert rec["status"] == ob.DELIVERED and rec["channels"]["telegram"]["provider_delivery_id"]
    assert rd.candidate_id(rec["idempotency_key"]) == a


def test_wrong_candidate_blocks(w):
    _two_ready(w)
    for bad in ("0123456789abcdef", "prod_ps5_pro", "PlayStation 5 Pro", "", "ACTIONABLE_NOW:prod_ps5_pro"):
        assert w.run(ps(), cam(), env=LIVE, cid=bad) == 0, bad                   # 候補の ID 以外・任意の商品では送れない
        assert w.prep["dispatch_sending"] == 0, bad
    assert all(r["status"] != ob.DELIVERED for r in w.live())


def test_two_candidates_a_sent_b_held_and_second_run_zero(w):
    a, b = _two_ready(w)
    assert w.run(ps(), cam(), env=LIVE, cid=a) == 1
    assert {r["product_id"]: r["status"] for r in w.live()} == {"prod_ps5_pro": ob.DELIVERED, "prod_gr4_hdf": ob.READY}
    g = w.ready(ps(), cam())
    assert g["status"] == rd.ACCEPTANCE_DONE and not g["candidates"]
    assert {h["lifecycle"] for h in g["history"]} == {rd.C_DELIVERED, rd.C_HELD}
    # 変数を戻し忘れた（LIVE のまま）新しい手動の実行: 同じ指定・B の指定・指定なしのどれでも送らない
    for cid in (a, b, ""):
        assert w.run(ps(), cam(), env=LIVE, cid=cid) == 0, cid
        assert w.prep["acceptance"]["allowed"] is False
        assert w.prep["dispatch_sending"] == 0                                   # prepare の段でも SENDING にしない
    assert w.prep["acceptance"]["reason"] in ("acceptance_done", "no_candidate_selected")
    assert len(w.requests) == 1


def test_variables_left_on_after_delivery_blocks(w):
    a, _b = _two_ready(w)
    w.run(ps(), cam(), env=LIVE, cid=a)
    assert ad.real_send_gate()["allowed"]                                        # 変数の関門は開いたまま
    assert w.run(ps(), cam(), env=LIVE, cid=a) == 0
    assert w.prep["acceptance"]["reason"] == "acceptance_done"


def test_same_workflow_rerun_blocks(w):
    a, _b = _two_ready(w)
    assert w.run(ps(), cam(), env=LIVE, cid=a, run_id=777, attempt=1) == 1
    assert w.run(ps(), cam(), env=LIVE, cid=a, run_id=777, attempt=2) == 0


def test_scheduled_run_blocks(w):
    a, _b = _two_ready(w)
    env = dict(LIVE, GITHUB_EVENT_NAME="schedule")
    assert w.run(ps(), cam(), env=env, cid=a) == 0
    assert w.observe["dry_run"] is True and not w.live()


def test_expired_candidate_blocks(w):
    old = datetime.now(JST) - timedelta(hours=ob.LIVE_CANDIDATE_MAX_AGE_HOURS + 1)
    w.run(ps("OUT_OF_STOCK", now=old - timedelta(hours=1)), at=old - timedelta(hours=1))
    w.run(ps(now=old), at=old)                                                   # 25時間前に検知
    cid = rd.candidate_id(next(iter(w.store()["records"].values()))["idempotency_key"])
    assert w.run(ps(), env=LIVE, cid=cid) == 0
    assert w.ready(ps())["status"] == rd.WAITING


@pytest.mark.parametrize("lost", [lambda: ps("OUT_OF_STOCK"), lambda: ps5(profitable=False),
                                  lambda: ps5(checked=datetime.now(JST) - timedelta(hours=5))])
def test_invalidated_candidate_blocks(w, lost):
    w.run(ps("OUT_OF_STOCK"))
    w.run(ps())
    cid = w.ready(ps())["candidate_ids"][0]
    assert w.run(lost(), env=LIVE, cid=cid) == 0


def test_unknown_blocks(w):
    a, b = _two_ready(w)
    w.run(ps(), cam(), env=LIVE, cid=a)
    st = w.store()
    rec = [r for r in st["records"].values() if r["mode"] == ob.MODE_LIVE and r["product_id"] == "prod_ps5_pro"][0]
    rec["channels"]["telegram"]["status"] = ob.UNKNOWN_DELIVERY
    rec["status"] = ob.UNKNOWN_DELIVERY
    ob.save(w.out / ob.STORE_NAME, st)
    assert w.ready(ps(), cam())["status"] == rd.REVIEW_REQUIRED
    for cid in (a, b):
        assert w.run(ps(), cam(), env=LIVE, cid=cid) == 0
        assert w.prep["acceptance"]["reason"] == "unknown_delivery_needs_resolution"


def test_in_progress_does_not_move_to_other_candidate(w):
    a, b = _two_ready(w)
    import src.notifiers.telegram_transport as ttm
    w.mp.setattr(ttm, "make_telegram_transport", lambda *x, **k: (lambda p, key: (503, {}, {})))
    assert w.run(ps(), cam(), env=LIVE, cid=a) == 0                              # 503（数えるのは偽の通信の外）
    assert w.live("prod_ps5_pro")[0]["status"] == ob.FAILED_RETRYABLE
    assert w.ready(ps(), cam())["status"] == rd.IN_PROGRESS
    w.run(ps(), cam(), env=LIVE, cid=b)
    assert w.prep["acceptance"]["reason"] == "acceptance_in_progress_other_candidate"
    assert w.live("prod_gr4_hdf")[0]["status"] != ob.DELIVERED                   # 別の候補へ自動で移らない


def test_held_candidate_never_auto_ready(w):
    a, _b = _two_ready(w)
    w.run(ps(), cam(), env=LIVE, cid=a)
    for _ in range(3):                                                           # 定時の実行が続いても
        w.run(ps(), cam())
        assert w.ready(ps(), cam())["status"] == rd.ACCEPTANCE_DONE


def test_no_fifo_drain_without_selection(w):
    _two_ready(w)
    for _ in range(3):                                                           # 指定なしの手動の実行を繰り返しても
        assert w.run(ps(), cam(), env=LIVE) == 0
    assert not [r for r in w.live() if r["status"] == ob.DELIVERED]


def test_canary_unaffected(w):
    st = w.store()
    rec = ob._new_canary(ob.DEFAULT_CANARY_ID, datetime.now(JST))
    rec["channels"]["telegram"].update(status=ob.DELIVERED, provider_delivery_id="3")
    rec["status"] = ob.DELIVERED
    st["records"][rec["notification_id"]] = rec
    ob.save(w.out / ob.STORE_NAME, st)
    a, _b = _two_ready(w)                                                        # canary の DELIVERED は受入を使ったことにしない
    assert w.run(ps(), cam(), env=dict(LIVE, TELEGRAM_CANARY="true"), cid=a) == 1
    assert not any("[TEST]" in t for t in w.requests)
    assert ob.canary_status(w.store(), ob.DEFAULT_CANARY_ID) == ob.DELIVERED


def test_summary_shows_acceptance(w):
    a, _b = _two_ready(w)
    w.run(ps(), cam(), env=LIVE, cid=a)
    import src.cli as cli
    out = CliRunner().invoke(cli.cli, ["notification", "readiness"]).output
    assert "PHASE24_ACCEPTANCE_DONE" in out and f"selected candidate: {a}" in out
    assert "external requests (this run): 1・delivered: 1" in out and "acceptance state: ACCEPTED" in out
    assert TOKEN not in out and CHAT not in out


def test_prune_keeps_acceptance_evidence(w):
    a, _b = _two_ready(w)
    w.run(ps(), cam(), env=LIVE, cid=a)
    st = w.store()
    ob.prune(st, datetime.now(JST) + timedelta(days=ob.RETENTION_DAYS + 5))
    assert rd.acceptance_state(st)["state"] == rd.A_ACCEPTED                     # 30日後も受入済み


def test_acceptance_gate_unit():
    """関門の単体: 状態ごとの理由（受入を使ったか・指定の形・一致）。"""
    st = ob.empty_store()
    g = rd.acceptance_gate(st, [], env={}, now=datetime.now(JST), attempt_id="x", stage="prepare")
    assert not g["allowed"] and g["reason"] == "no_candidate_selected"
    g = rd.acceptance_gate(st, [], env={rd.CANDIDATE_VAR: "PS5"}, now=datetime.now(JST), attempt_id="x", stage="prepare")
    assert not g["allowed"] and g["reason"] == "invalid_candidate_id"


# ── 表示・ワークフロー・検査 ─────────────────────────────────────────────────

def test_admin_wording(w):
    from src.content.ui import admin
    a, _b = _two_ready(w)
    html = admin._readiness(admin.build_readiness(w.ready(ps(), cam())))
    assert "Phase 24 の本番受入候補あり" in html and f"PHASE24_ACCEPTANCE_CANDIDATE_ID={a}" in html
    assert "<button" not in html and "<form" not in html
    w.run(ps(), cam(), env=LIVE, cid=a)
    html = admin._readiness(admin.build_readiness(w.ready(ps(), cam())))
    assert "Phase 24 の本番受入済み。追加の送信は禁止" in html and "PHASE24_ACCEPTANCE_CANDIDATE_ID=" not in html
    assert TOKEN not in html and CHAT not in html


def _dc():
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_check
    return deploy_check


def test_workflow_candidate_var_manual_only():
    import re
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    want = ("PHASE24_ACCEPTANCE_CANDIDATE_ID: ${{ github.event_name == 'workflow_dispatch' && "
            "vars.PHASE24_ACCEPTANCE_CANDIDATE_ID || '' }}")
    assert wf.count(want) == 3 and len(re.findall(r"PHASE24_ACCEPTANCE_CANDIDATE_ID:", wf)) == 3


def test_deploy_check_861_ok():
    assert _dc()._check_phase26_acceptance_guard()[0]["level"] == "ok"


def test_gate_reason_for_invalid_selected_candidate(w):
    """選んだ候補が無効（在庫切れ）なら、関門そのものが candidate_not_ready で止める（ほかの候補が READY でも）。"""
    a, b = _two_ready(w)
    assert w.run(ps(), cam("OUT_OF_STOCK"), env=LIVE, cid=b) == 0
    assert w.prep["acceptance"]["allowed"] is False and w.prep["acceptance"]["reason"] == "candidate_not_ready"


def test_send_stage_rejects_unselected_sending(w):
    """send の段: この実行の SENDING が選んだ候補でなければ送らない（READY に戻す）。"""
    a, b = _two_ready(w)
    w.env(dict(LIVE, GITHUB_RUN_ID="4242", GITHUB_RUN_ATTEMPT="1", **{rd.CANDIDATE_VAR: b}))
    now = datetime.now(JST)
    d = dict(_diag(ps(), cam()), generated_at=f"{now.isoformat()}#x")
    (w.diag_dir / "latest.json").write_text(json.dumps(d), encoding="utf-8")
    ob.run_observe(w.out, d, now=now, dry_run=False)
    ob.run_prepare(w.out, d, now=now, dry_run=False, attempt_id="gh-4242-1", live_channels={"telegram"}, send_limit=1, acceptance_env=ob.NO_ACCEPTANCE_GATE)
    assert ob.counts(w.store())["sending"] == 1                                   # 関門なしの prepare が A を SENDING に
    import src.cli as cli
    res = CliRunner().invoke(cli.cli, ["dispatch-notifications", "--step", "send", "--persisted-sha",
                                       ob.file_sha(w.out / ob.STORE_NAME)])
    out = json.loads(res.output)
    assert w.requests == [] and out["acceptance_send"]["reason"] == "sending_not_selected_candidate"
    assert ob.counts(w.store())["sending"] == 0                                   # 送らずに READY に戻す


def test_unknown_resolved_cancel_still_locks(w):
    """届いたか不明を人が cancel で解決しても（届いていたかもしれない）、別の候補 B は送らない（レビュー M-1）。"""
    a, b = _two_ready(w)
    import src.notifiers.telegram_transport as ttm
    from src.notifiers.adapters import TransportError

    def timeout(*x, **k):
        def t(p, key):
            raise TransportError("read")
        return t
    w.mp.setattr(ttm, "make_telegram_transport", timeout)
    w.run(ps(), cam(), env=LIVE, cid=a)
    st = w.store()
    nid = [n for n, r in st["records"].items() if r["mode"] == ob.MODE_LIVE and r["product_id"] == "prod_ps5_pro"][0]
    assert st["records"][nid]["status"] == ob.UNKNOWN_DELIVERY
    ob.resolve(st, nid, ob.CANCEL, rows=ob._rows(_diag(ps(), cam())), now=datetime.now(JST))
    ob.save(w.out / ob.STORE_NAME, st)
    assert rd.acceptance_state(w.store())["state"] == rd.A_ACCEPTED
    assert w.ready(ps(), cam())["status"] == rd.ACCEPTANCE_DONE
    for cid in (a, b):
        assert w.run(ps(), cam(), env=LIVE, cid=cid) == 0
    st = w.store()
    ob.prune(st, datetime.now(JST) + timedelta(days=ob.RETENTION_DAYS + 5))
    assert rd.acceptance_state(st)["state"] == rd.A_ACCEPTED                     # 30日後も残す


def test_library_default_closes_gate(w):
    """CLI を通さずに呼んでも、関門の環境を渡さなければ送らない（既定は閉じる。監査 L-1）。"""
    a, _b = _two_ready(w)
    now = datetime.now(JST)
    d = dict(_diag(ps(), cam()), generated_at=f"{now.isoformat()}#lib")
    ob.run_observe(w.out, d, now=now, dry_run=False)
    p = ob.run_prepare(w.out, d, now=now, dry_run=False, attempt_id="gh-1-1", live_channels={"telegram"}, send_limit=1)
    assert p["dispatch_sending"] == 0 and p["acceptance"]["reason"] == "no_candidate_selected"
    ob.run_observe(w.out, d, now=now, dry_run=False)                             # 次の実行の生成
    p = ob.run_prepare(w.out, d, now=now, dry_run=False, attempt_id="gh-1-2", live_channels={"telegram"}, send_limit=1,
                       acceptance_env={rd.CANDIDATE_VAR: a})
    assert p["dispatch_sending"] == 1                                            # 否定の対照: 指定すれば通る


def test_prepare_without_limit_respects_only_keys():
    """上限なしの分岐でも、受入で選んでいない候補は SENDING にしない（監査 L-2）。"""
    now = datetime.now(JST)
    st = ob.empty_store()
    rows0 = ob._rows(_diag(ps("OUT_OF_STOCK"), cam("OUT_OF_STOCK")))
    rows = ob._rows(_diag(ps(), cam()))
    ob.observe(st, rows0, now=now, mode=ob.MODE_LIVE, channels=["telegram"])
    ob.observe(st, rows, now=now, mode=ob.MODE_LIVE, channels=["telegram"])
    key = next(r["idempotency_key"] for r in st["records"].values() if r["product_id"] == "prod_ps5_pro")
    out = ob.prepare(st, rows, now=now, mode=ob.MODE_LIVE, attempt_id="x", live_channels={"telegram"},
                     only_keys={key})
    assert out["sending"] == 1 and out["held"] == 1


def test_send_rechecks_candidate_age():
    """送る直前にも候補の古さ（24時間）を確かめる（監査 L-3）。"""
    now = datetime.now(JST)
    st = ob.empty_store()
    ob.observe(st, ob._rows(_diag(ps("OUT_OF_STOCK"))), now=now, mode=ob.MODE_LIVE, channels=["telegram"])
    ob.observe(st, ob._rows(_diag(ps())), now=now, mode=ob.MODE_LIVE, channels=["telegram"])
    ob.prepare(st, ob._rows(_diag(ps())), now=now, mode=ob.MODE_LIVE, attempt_id="x", live_channels={"telegram"},
               send_limit=1)
    rec = next(iter(st["records"].values()))
    rec["created_at"] = (now - timedelta(hours=ob.LIVE_CANDIDATE_MAX_AGE_HOURS + 1)).isoformat(timespec="seconds")
    calls = []
    a = ad.TelegramAdapter(lambda p, k: calls.append(k) or (200, {}, {"ok": True, "result": {"message_id": 1}}))
    out = ob.send(st, now=now, attempt_id="x", adapters={"telegram": a}, limit=1)
    assert calls == [] and out["expired"] == 1 and rec["status"] == ob.EXPIRED
