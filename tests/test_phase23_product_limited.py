"""Phase 23（Telegram の商品の通知の限定運用）のテスト。

ネットワークには出ない（偽の通信だけ。トークン・チャット ID はダミー）。行は Phase 18 の判定の正本
（actionability.evaluate → 診断の形）から作る。各テストに否定の対照を付ける。
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
from src.notifiers import telegram_transport as tt

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "123456789:AAdummydummydummydummydummydummy00X"
CHAT = "-1009876543210"
FULL = {"NOTIFICATION_REAL_SEND": "true", "NOTIFICATION_DRY_RUN": "false", "NOTIFICATION_PROVIDERS": "telegram",
        "PRODUCT_REAL_SEND_ENABLED": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT}
OK = (200, json.dumps({"ok": True, "result": {"message_id": 501}}).encode())


class Opener:
    def __init__(self, result):
        self.result, self.requests = result, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        if isinstance(self.result, BaseException):
            raise self.result
        status, body = self.result
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(body))
        return SimpleNamespace(getcode=lambda: status, headers={}, read=lambda: body)


def cam(stock="IN_STOCK", now=NOW):
    """2件目の通常販売の利益商品（GR IV HDF の在庫販売。公式の購入ページ）。"""
    return _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock=stock,
                                              stock_checked_at=now - timedelta(minutes=10), buy_url=RICOH, now=now),
                 net=16200, roi=0.073, name="RICOH GR IV HDF")


class Run:
    """手順ごとの本番の流れ（LP の生成 observe → prepare → 保存 → send）を一時の台帳で行う。"""

    def __init__(self, tmp):
        self.tmp, self.n, self.requests = Path(tmp), 0, []

    def __call__(self, *views, now=NOW, result=OK, allowed=True, dry=False, prev=None):
        self.n += 1
        d = dict(_diag(*views, prev=prev), generated_at=f"{now.isoformat()}#{self.n}")
        aid = f"gh-{self.n}-1"
        ob.run_observe(self.tmp, d, now=now, dry_run=dry)
        prep = ob.run_prepare(self.tmp, d, now=now, dry_run=dry, attempt_id=aid,
                              live_channels=None if dry else set(ob.LIVE_CHANNELS),
                              send_limit=None if dry else ad.PRODUCT_SEND_LIMIT_PER_RUN, acceptance_env=ob.NO_ACCEPTANCE_GATE)
        op = Opener(result)
        a = ad.TelegramAdapter(tt.make_telegram_transport(TOKEN, CHAT, opener=op))
        sent = ob.run_send(self.tmp, now=now, dry_run=dry, attempt_id=aid,
                           persisted_sha=ob.file_sha(self.tmp / ob.STORE_NAME), adapters={"telegram": a},
                           real_send_allowed=allowed, limit=ad.PRODUCT_SEND_LIMIT_PER_RUN, acceptance_env=ob.NO_ACCEPTANCE_GATE)
        self.requests.append(len(op.requests))
        return SimpleNamespace(prep=prep, sent=sent, op=op, store=self.store())

    def store(self):
        return ob.load(self.tmp / ob.STORE_NAME)[0]

    def recs(self, pid=None):
        return [r for r in self.store()["records"].values() if not r.get("is_canary")
                and (pid is None or r["product_id"] == pid)]


@pytest.fixture
def run(tmp_path):
    return Run(tmp_path)


def _texts(op):
    return [json.loads(r.data.decode())["text"] for r in op.requests]


# ── 関門 ───────────────────────────────────────────────────────────────────

def test_gate_opens_only_with_all_conditions():
    assert ad.real_send_gate(FULL)["allowed"]                                    # 否定の対照: 全部そろえば開く
    for k in ("NOTIFICATION_REAL_SEND", "PRODUCT_REAL_SEND_ENABLED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
              "NOTIFICATION_PROVIDERS", "GITHUB_EVENT_NAME"):
        assert not ad.real_send_gate({x: v for x, v in FULL.items() if x != k})["allowed"], k
    assert not ad.real_send_gate(dict(FULL, NOTIFICATION_DRY_RUN="true"))["allowed"]
    assert not ad.real_send_gate(dict(FULL, NOTIFICATION_PROVIDERS="telegram,discord"))["allowed"]
    assert not ad.real_send_gate(dict(FULL, NOTIFICATION_PROVIDERS="discord"))["allowed"]


def test_limited_mode_default_and_cannot_be_turned_off():
    g = ad.real_send_gate({})
    assert g["checks"]["limited_mode"] is True and not g["allowed"]             # 既定で限定モード
    assert ad.real_send_gate(FULL)["send_limit"] == 1 == ad.PRODUCT_SEND_LIMIT_PER_RUN
    assert not ad.real_send_gate(dict(FULL, PRODUCT_NOTIFICATION_LIMITED_MODE="false"))["allowed"]   # 全開放しない
    assert ad.PRODUCT_UNLIMITED_ALLOWED is False
    assert ad.real_send_gate(dict(FULL, PRODUCT_NOTIFICATION_LIMITED_MODE="true"))["allowed"]       # 否定の対照


def test_manual_run_only():
    for ev in ("schedule", "push", ""):
        assert not ad.real_send_gate(dict(FULL, GITHUB_EVENT_NAME=ev))["allowed"], ev
        assert not ad.product_live_intent(dict(FULL, GITHUB_EVENT_NAME=ev))["allowed"], ev
    assert ad.product_live_intent(FULL)["allowed"]                               # 否定の対照


def test_live_intent_does_not_need_secrets():
    env = {k: v for k, v in FULL.items() if not k.startswith("TELEGRAM_")}
    assert ad.product_live_intent(env)["allowed"] and "config_valid" not in ad.product_live_intent(env)["checks"]
    assert not ad.real_send_gate(env)["allowed"]                                 # 送信の手順は設定を確かめる


def test_gate_returns_no_secret_values():
    g = json.dumps(ad.real_send_gate(dict(FULL, TELEGRAM_CHAT_ID="bad value")))
    assert TOKEN not in g and CHAT not in g and "bad value" not in g


# ── 送る・送らない ──────────────────────────────────────────────────────────

def test_actionable_candidate_sends_one(run):
    run(ps5("OUT_OF_STOCK"))
    r = run(ps5())
    assert len(r.op.requests) == 1 and r.sent["dispatch_sent"] == 1 and r.sent["requests"] == 1
    rec = run.recs()[0]
    c = rec["channels"]["telegram"]
    assert rec["status"] == ob.DELIVERED and list(rec["channels"]) == ["telegram"] and rec["mode"] == ob.MODE_LIVE
    assert c["provider_delivery_id"] == "501" and c["delivered_at"] and rec["notification_type"] == "ACTIONABLE_NOW"


def test_message_content_direct_sale(run):
    run(ps5("OUT_OF_STOCK"))
    text = _texts(run(ps5()).op)[0]
    lines = text.split("\n")
    assert lines[:4] == ["Premium Monitor", "購入可能になりました", "", "商品: PlayStation 5 Pro"]
    for part in ("想定純利益: +¥54,870", "ROI: 39.6%", "状態: 在庫あり", "確認: 10/09 11:30（公式）",
                 "購入する: https://pur.store.sony.jp/"):
        assert part in text, part
    assert TOKEN not in text and CHAT not in text and "締切" not in text


def test_message_content_lottery(run):
    run(gr4(lottery_event(NOW + timedelta(days=1), NOW + timedelta(days=3), status="upcoming")))
    text = _texts(run(gr4(OPEN)).op)[0]
    assert text.startswith("Premium Monitor\n抽選受付が始まりました\n\n商品: RICOH GR IV HDF")
    for part in ("想定純利益: +¥16,200", "ROI: 7.3%", "状態: 抽選受付中", "締切: 10/11", RICOH):
        assert part in text, part


def test_non_actionable_no_send(run):
    run(ps5("OUT_OF_STOCK"))
    r = run(ps5("OUT_OF_STOCK"))
    assert r.op.requests == [] and run.recs() == []
    r = run(ps5())                                                               # 否定の対照
    assert len(r.op.requests) == 1


def test_one_send_limit_and_second_candidate_remains(run):
    run(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    r = run(ps5(), cam())
    assert len(r.op.requests) == 1 and r.prep["dispatch_sending"] == 1 and r.prep["dispatch_held"] == 1
    a, b = run.recs("prod_ps5_pro")[0], run.recs("prod_gr4_hdf")[0]
    assert a["status"] == ob.DELIVERED                                           # 既存の順位（診断の行の順）で先の商品
    assert b["status"] == ob.READY and b["channels"]["telegram"]["error_class"] == "limited_send_hold"
    assert b["channels"]["telegram"]["attempt_count"] == 0                       # 送っていないので試行に数えない
    r = run(ps5(), cam())                                                        # 次の本番の実行: 残りの1件だけ
    assert len(r.op.requests) == 1 and run.recs("prod_gr4_hdf")[0]["status"] == ob.DELIVERED
    assert "RICOH GR IV HDF" in _texts(r.op)[0]


def test_send_limit_enforced_in_send_even_if_more_sending(run):
    """配信の直前の確認を飛ばして SENDING が2件あっても、送信の手順は1件だけ送る（二重の守り）。"""
    st = ob.empty_store()
    rows = ob._rows(_diag(ps5(), cam()))
    ob.observe(st, ob._rows(_diag(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))), now=NOW, mode=ob.MODE_LIVE,
               channels=["telegram"])
    ob.observe(st, rows, now=NOW, mode=ob.MODE_LIVE, channels=["telegram"])
    ob.prepare(st, rows, now=NOW, mode=ob.MODE_LIVE, attempt_id="x", live_channels={"telegram"})   # 上限なし
    assert ob.counts(st)["sending"] == 2
    op = Opener(OK)
    out = ob.send(st, now=NOW, attempt_id="x", limit=1,
                  adapters={"telegram": ad.TelegramAdapter(tt.make_telegram_transport(TOKEN, CHAT, opener=op))})
    assert len(op.requests) == 1 and out["held"] == 1 and ob.counts(st)["outbox_pending"] == 1


def test_same_idempotency_no_resend_and_rerun(run):
    run(ps5("OUT_OF_STOCK"))
    run(ps5())
    for _ in range(3):                                                           # 在庫ありが続くだけ・同じ実行の再実行
        assert run(ps5()).op.requests == []
    assert len(run.recs()) == 1 and run.recs()[0]["channels"]["telegram"]["attempt_count"] == 1


def test_rerun_of_same_attempt_does_not_resend(run, tmp_path):
    """同じ workflow を再実行（新しい attempt）しても、送った通知・送信中の通知を送り直さない。"""
    run(ps5("OUT_OF_STOCK"))
    d = dict(_diag(ps5()), generated_at="g1")
    ob.run_observe(tmp_path, d, now=NOW, dry_run=False)
    ob.run_prepare(tmp_path, d, now=NOW, dry_run=False, attempt_id="gh-9-1", live_channels={"telegram"}, send_limit=1, acceptance_env=ob.NO_ACCEPTANCE_GATE)
    # 送った後・保存の前に止まった → 再実行（attempt 2）は届いたか不明にして送らない
    d2 = dict(_diag(ps5()), generated_at="g2")
    ob.run_observe(tmp_path, d2, now=NOW, dry_run=False)
    p = ob.run_prepare(tmp_path, d2, now=NOW, dry_run=False, attempt_id="gh-9-2", live_channels={"telegram"},
                       send_limit=1, acceptance_env=ob.NO_ACCEPTANCE_GATE)
    assert p["dispatch_unknown"] == 1 and p["dispatch_sending"] == 0
    assert run.recs()[0]["status"] == ob.UNKNOWN_DELIVERY


def test_rearm_sends_later(run):
    run(ps5("OUT_OF_STOCK"))
    assert len(run(ps5()).op.requests) == 1
    run(ps5("OUT_OF_STOCK"))                                                     # 在庫切れ → re-arm
    r = run(ps5())
    assert len(r.op.requests) == 1 and len(run.recs()) == 2                      # 新しい移り変わりは送る
    assert len({x["idempotency_key"] for x in run.recs()}) == 2


def test_same_lottery_no_resend_and_deadline_extension(run):
    run(gr4(lottery_event(NOW + timedelta(days=1), NOW + timedelta(days=3), status="upcoming")))
    assert len(run(gr4(OPEN)).op.requests) == 1
    assert run(gr4(OPEN)).op.requests == []                                      # 同じ受付
    ext = lottery_event(NOW - timedelta(days=1), NOW + timedelta(days=5))         # 締切の延長だけ
    assert run(gr4(ext)).op.requests == [] and len(run.recs()) == 1


def test_closed_lottery_no_send(run):
    run(gr4(lottery_event(NOW + timedelta(days=1), NOW + timedelta(days=3), status="upcoming")))
    r = run(gr4(CLOSED))
    assert r.op.requests == [] and run.recs() == []


def test_stale_stock_no_send(run):
    run(ps5("OUT_OF_STOCK"))
    r = run(ps5(checked=NOW - timedelta(hours=5)))                               # 在庫の確認が古い（期限切れ）
    assert r.op.requests == []
    # 候補にした後に期限が過ぎた: 送る直前に確かめて送らない
    run2 = Run(Path(run.tmp) / "b")
    run2(ps5("OUT_OF_STOCK"))
    d = dict(_diag(ps5()), generated_at="x")
    ob.run_observe(run2.tmp, d, now=NOW, dry_run=False)
    ob.run_prepare(run2.tmp, d, now=NOW, dry_run=False, attempt_id="z", live_channels={"telegram"}, send_limit=1, acceptance_env=ob.NO_ACCEPTANCE_GATE)
    op = Opener(OK)
    s = ob.run_send(run2.tmp, now=NOW + timedelta(hours=4), dry_run=False, attempt_id="z",
                    persisted_sha=ob.file_sha(run2.tmp / ob.STORE_NAME), real_send_allowed=True, limit=1,
                    adapters={"telegram": ad.TelegramAdapter(tt.make_telegram_transport(TOKEN, CHAT, opener=op))}, acceptance_env=ob.NO_ACCEPTANCE_GATE)
    assert op.requests == [] and run2.recs()[0]["status"] == ob.EXPIRED and s["dispatch_sent"] == 0


def test_reference_profit_and_generic_url_no_send(run):
    run(_view("p1", act.evaluate(profitable=False, identity_ok=True, stock="OUT_OF_STOCK",
                                 stock_checked_at=NOW - timedelta(minutes=5), buy_url=ps5().action.cta_url, now=NOW)))
    r = run(_view("p1", act.evaluate(profitable=False, identity_ok=True, stock="IN_STOCK",
                                     stock_checked_at=NOW - timedelta(minutes=5), buy_url=ps5().action.cta_url, now=NOW)))
    assert r.op.requests == []                                                   # 参考の利益は行動できない
    run(ps5("OUT_OF_STOCK", url="https://www.sony.jp/"))
    r = run(ps5(url="https://www.sony.jp/"))                                     # 一般のページ（購入ページでない）
    assert r.op.requests == []


def test_scheduled_dry_run_keeps_live_candidate(run):
    run(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    run(ps5(), cam())
    r = run(ps5(), cam(), dry=True)                                              # 定時の実行（dry-run）
    assert r.op.requests == [] and run.recs("prod_gr4_hdf")[0]["status"] == ob.READY
    assert not [x for x in run.recs() if x["mode"] == ob.MODE_DRY]               # 同じ移り変わりの dry-run の記録を作らない
    r = run(ps5(), cam())                                                        # 次の本番（手動）の実行で送る
    assert len(r.op.requests) == 1


def test_scheduled_dry_run_expires_stale_live_candidate(run):
    run(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    run(ps5(), cam())
    run(ps5(), cam("OUT_OF_STOCK"), dry=True)                                    # 定時の実行で在庫切れ
    assert run.recs("prod_gr4_hdf")[0]["status"] == ob.CANCELLED
    r = run(ps5(), cam())                                                        # 新しい移り変わりは別のキーで送る
    assert len(r.op.requests) == 1 and len(run.recs("prod_gr4_hdf")) == 2


def test_gate_closed_releases_sending_not_unknown(run):
    run(ps5("OUT_OF_STOCK"))
    r = run(ps5(), allowed=False)
    rec = run.recs()[0]
    assert r.op.requests == [] and r.sent["released"] == 1 and rec["status"] == ob.READY
    assert rec["channels"]["telegram"]["attempts"][-1]["status"] == "NOT_SENT"
    r = run(ps5())                                                               # 次の実行で送る（届いたか不明にしない）
    assert len(r.op.requests) == 1 and run.recs()[0]["status"] == ob.DELIVERED


# ── 応答 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("result", [(500, b""), (502, b""), (504, b""), TimeoutError("t"),
                                    (200, json.dumps({"ok": True, "result": {}}).encode())])
def test_unknown_no_retry(run, result):
    run(ps5("OUT_OF_STOCK"))
    r = run(ps5(), result=result)
    assert len(r.op.requests) == 1 and run.recs()[0]["status"] == ob.UNKNOWN_DELIVERY
    for _ in range(2):
        assert run(ps5()).op.requests == []


@pytest.mark.parametrize("status,want", [(400, ob.FAILED_FINAL), (401, ob.FAILED_FINAL), (403, ob.FAILED_FINAL),
                                         (429, ob.FAILED_RETRYABLE), (503, ob.FAILED_RETRYABLE)])
def test_error_classes(run, status, want):
    run(ps5("OUT_OF_STOCK"))
    r = run(ps5(), result=(status, b""))
    assert len(r.op.requests) == 1 and run.recs()[0]["status"] == want
    assert run(ps5()).op.requests == []                                          # 同じ実行の中・すぐには送り直さない


def test_message_id_persisted_and_no_secrets_in_ledger(run):
    run(ps5("OUT_OF_STOCK"))
    run(ps5())
    text = (Path(run.tmp) / ob.STORE_NAME).read_text(encoding="utf-8")
    assert '"provider_delivery_id": "501"' in text and TOKEN not in text and CHAT not in text
    assert "api.telegram.org" not in text


# ── 表示・履歴 ─────────────────────────────────────────────────────────────

def test_delivered_history_only_delivered(run):
    run(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    run(ps5(), cam())
    h = ob.delivered_history(run.store())
    assert [x["product_id"] for x in h] == ["prod_ps5_pro"]                      # READY（未送信）は入れない
    assert set(h[0]) == {"product_id", "product", "type", "availability", "state", "net_profit", "roi", "delivered_at"}
    assert ob.delivered_history(ob.empty_store()) == []


def test_mypage_shows_only_delivered(run, monkeypatch):
    from src.content.ui import mypage
    run(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    run(ps5(), cam())
    v = SimpleNamespace(product_name="PlayStation 5 Pro", changes=[], actionability=None)
    details = {"prod_ps5_pro": v, "prod_gr4_hdf": SimpleNamespace(product_name="GR", changes=[], actionability=None)}
    monkeypatch.setattr(mypage, "_now_text", lambda v: "—")
    ev = mypage.build_events(details, [], {}, NOW, actionable_delivered=ob.delivered_history(run.store()))
    assert [e["pid"] for e in ev] == ["prod_ps5_pro"] and "利益 ¥54,870" in ev[0]["what"]
    assert mypage.build_events(details, [], {}, NOW) == []                       # 否定の対照: 渡さなければ出ない


def test_product_status_counts(run):
    run(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    run(ps5(), cam())
    s = ob.product_status(run.store(), gate=ad.real_send_gate(FULL), now=NOW, sent_this_run=1)
    assert s["enabled"] and s["limited_mode"] and s["send_limit"] == 1 and s["sent_today"] == 1
    assert (s["pending"], s["delivered"], s["unknown"], s["failed"]) == (1, 1, 0, 0)
    assert TOKEN not in json.dumps(s) and CHAT not in json.dumps(s)


def test_admin_shows_product_block():
    from src.content.ui import admin
    rep = {"generated_at": NOW.isoformat(), "provider_status": {"telegram": {"configured": True},
           "product": {"enabled": False, "limited_mode": True, "send_limit": 1, "sent_today": 0, "pending": 2,
                       "delivered": 1, "unknown": 0, "failed": 0}},
           "delivered_history": [{"product": "PlayStation 5 Pro", "state": "購入可能になりました", "net_profit": 54870,
                                  "delivered_at": NOW.isoformat()}]}
    a = admin.build_actionable_notices(rep)
    html = admin._act_notices(a)
    for part in ("商品の通知の本番の送信", "無効", "限定モード", "1回の実行の上限", "1件", "配信待ち", "2件",
                 "PlayStation 5 Pro", "+¥54,870"):
        assert part in html, part


# ── ワークフロー・Secrets・検査 ────────────────────────────────────────────

def _dc():
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_check
    return deploy_check


def _wf():
    return (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")


def _steps(wf):
    import re
    return {m.group(1): m.group(2) for m in re.finditer(r"- name: ([^\n]+)\n(.*?)(?=\n      - name:|\n      # |\Z)",
                                                          wf, re.S)}


def test_secret_isolation():
    import re
    assert _dc()._notification_secret_exposure(ROOT) == []
    st = _steps(_wf())
    for n in ("Generate daily LP Variant A", "Prepare notification dispatch"):
        assert not re.search(r"secrets\.", st[n]), n
    assert "secrets.TELEGRAM_BOT_TOKEN" in st["Send notifications"]                # 否定の対照


def test_workflow_product_flag_is_manual_only():
    st = _steps(_wf())
    expr = ("PRODUCT_REAL_SEND_ENABLED: ${{ github.event_name == 'workflow_dispatch' && "
            "vars.PRODUCT_REAL_SEND_ENABLED || 'false' }}")
    for n in ("Generate daily LP Variant A", "Prepare notification dispatch", "Send notifications"):
        assert expr in st[n] and _dc()._notification_vars_ok(st[n]), n
    assert not _dc()._notification_vars_ok(st["Send notifications"].replace(
        "github.event_name == 'workflow_dispatch' && vars.PRODUCT_REAL_SEND_ENABLED || 'false'",
        "vars.PRODUCT_REAL_SEND_ENABLED || 'false'"))


def test_deploy_check_859_ok_and_detects_ledger_over_limit(tmp_path):
    import shutil
    dc = _dc()
    assert dc._check_phase23_product_limited()[0]["level"] == "ok"
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(ROOT / ".github" / "workflows" / "daily_lp.yml", tmp_path / ".github" / "workflows")
    led = tmp_path / "exports" / "notifications" / "actionable"
    run = Run(led)
    run(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    run(ps5(), cam())
    assert dc._check_phase23_product_limited(tmp_path)[0]["level"] == "ok"
    st = run.store()
    b = [r for r in st["records"].values() if r["product_id"] == "prod_gr4_hdf"][0]
    a = [r for r in st["records"].values() if r["product_id"] == "prod_ps5_pro"][0]
    b["channels"]["telegram"]["attempts"].append(dict(a["channels"]["telegram"]["attempts"][-1]))   # 同じ実行で2件目
    ob.save(led / ob.STORE_NAME, st)
    res = dc._check_phase23_product_limited(tmp_path)[0]
    assert res["level"] == "error" and "上限より多く" in res["message"]


def test_deploy_check_856_allows_valid_limited_record(tmp_path):
    dc = _dc()
    run = Run(tmp_path)
    run(ps5("OUT_OF_STOCK"))
    run(ps5())
    rec = run.recs()[0]
    assert dc._is_valid_limited_product_record(rec)
    assert not dc._is_valid_limited_product_record(dict(rec, confirmed=False))
    assert not dc._is_valid_limited_product_record(dict(rec, action_url="https://example.com/"))
    bad = json.loads(json.dumps(rec))
    bad["channels"]["telegram"]["provider_delivery_id"] = ""
    assert not dc._is_valid_limited_product_record(bad)
    bad = json.loads(json.dumps(rec))
    bad["channels"]["discord"] = bad["channels"]["telegram"]
    assert not dc._is_valid_limited_product_record(bad)


def test_no_canary_resend_in_product_run(run):
    """商品の通知の実行で、接続の試験（canary）は送らない（記録は DELIVERED のまま）。"""
    st = ob.empty_store()
    cid = ob.DEFAULT_CANARY_ID
    rec = ob._new_canary(cid, NOW)
    rec["channels"]["telegram"].update(status=ob.DELIVERED, provider_delivery_id="3", delivered_at=NOW.isoformat())
    rec["status"] = ob.DELIVERED
    st["records"][rec["notification_id"]] = rec
    ob.save(Path(run.tmp) / ob.STORE_NAME, st)
    run(ps5("OUT_OF_STOCK"))
    r = run(ps5())
    assert len(r.op.requests) == 1 and "[TEST]" not in _texts(r.op)[0]
    assert ob.canary_status(run.store(), cid) == ob.DELIVERED


# ── レビューの指摘（M-1・L-2） ──────────────────────────────────────────────

def test_rerun_same_run_does_not_send_second_candidate(tmp_path):
    """同じ run の再実行（attempt 2）は、attempt 1 で1件送っていれば残りの候補を送らない（上限は run ごと。M-1）。"""
    run = Run(tmp_path)
    run(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    sent = []
    for attempt in (1, 2):
        d = dict(_diag(ps5(), cam()), generated_at=f"g{attempt}")
        aid = f"gh-777-{attempt}"
        ob.run_observe(tmp_path, d, now=NOW, dry_run=False)
        p = ob.run_prepare(tmp_path, d, now=NOW, dry_run=False, attempt_id=aid, live_channels={"telegram"},
                           send_limit=1, acceptance_env=ob.NO_ACCEPTANCE_GATE)
        op = Opener(OK)
        ob.run_send(tmp_path, now=NOW, dry_run=False, attempt_id=aid, persisted_sha=ob.file_sha(tmp_path / ob.STORE_NAME),
                    real_send_allowed=True, limit=1,
                    adapters={"telegram": ad.TelegramAdapter(tt.make_telegram_transport(TOKEN, CHAT, opener=op))}, acceptance_env=ob.NO_ACCEPTANCE_GATE)
        sent.append((p["dispatch_sending"], len(op.requests)))
    # 再実行の prepare は SENDING を作らない（prepare と send の両方で run ごとに数える）
    assert sent == [(1, 1), (0, 0)] and run.recs("prod_gr4_hdf")[0]["status"] == ob.READY
    assert ob.product_sends_in_run(run.store(), "gh-777-3") == 1 and ob.product_sends_in_run(run.store(), "gh-778-1") == 0
    r = run(ps5(), cam())                                                        # 否定の対照: 別の run なら送る
    assert len(r.op.requests) == 1


def test_run_key():
    assert ob.run_key("gh-123-2") == ob.run_key("gh-123-1") == "gh-123" and ob.run_key("local-x") == "local-x"


def test_stale_live_candidate_expires_and_is_not_revived(run):
    run(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    run(ps5(), cam())                                                            # cam は READY のまま
    later = NOW + timedelta(hours=ob.LIVE_CANDIDATE_MAX_AGE_HOURS + 1)
    r = run(ps5(now=later, checked=later - timedelta(minutes=5)), cam(now=later), now=later)
    rec = run.recs("prod_gr4_hdf")[0]
    assert r.op.requests == [] and rec["status"] == ob.EXPIRED
    assert rec["channels"]["telegram"]["error_class"] == "stale_candidate"
    r = run(ps5(now=later, checked=later - timedelta(minutes=5)), cam(now=later), now=later)
    assert r.op.requests == [] and run.recs("prod_gr4_hdf")[0]["status"] == ob.EXPIRED   # 戻さない
    run(ps5(now=later), cam("OUT_OF_STOCK", now=later), now=later)               # 新しい移り変わりは送る
    r = run(ps5(now=later), cam(now=later), now=later)
    assert len(r.op.requests) == 1 and "RICOH" in _texts(r.op)[0]


def test_deploy_check_859_counts_per_run(tmp_path):
    import shutil
    dc = _dc()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(ROOT / ".github" / "workflows" / "daily_lp.yml", tmp_path / ".github" / "workflows")
    led = tmp_path / "exports" / "notifications" / "actionable"
    run = Run(led)
    run(ps5("OUT_OF_STOCK"), cam("OUT_OF_STOCK"))
    run(ps5(), cam())
    run(ps5(), cam())
    assert dc._check_phase23_product_limited(tmp_path)[0]["level"] == "ok"      # 別の run の2件は ok
    st = run.store()
    b = [r for r in st["records"].values() if r["product_id"] == "prod_gr4_hdf"][0]
    a = [r for r in st["records"].values() if r["product_id"] == "prod_ps5_pro"][0]
    b["channels"]["telegram"]["attempts"][-1]["attempt_id"] = a["channels"]["telegram"]["attempts"][-1][
        "attempt_id"][:-1] + "9"                                                 # 同じ run の再実行で送った形
    ob.save(led / ob.STORE_NAME, st)
    assert dc._check_phase23_product_limited(tmp_path)[0]["level"] == "error"


# ── 監査の指摘（M-1・M-2） ──────────────────────────────────────────────────

def test_no_canary_in_product_run(tmp_path, monkeypatch):
    """商品の通知の関門が開いた実行では、接続の試験の旗が立っていても canary を送らない（監査 M-1）。"""
    import src.cli as cli
    import src.notifiers.telegram_transport as ttm
    calls = []
    monkeypatch.setattr(ttm, "make_telegram_transport", lambda *a, **k: calls.append(1) or (lambda p, key: OK))
    for k, v in dict(FULL, TELEGRAM_CANARY="true", TELEGRAM_CANARY_ID="telegram_canary_v9").items():
        monkeypatch.setenv(k, v)
    ob.save(tmp_path / ob.STORE_NAME, ob.empty_store())
    res = cli._telegram_canary(tmp_path, now=NOW, attempt_id="gh-1-1", product_gate=ad.real_send_gate(FULL))
    assert res["canary"] == "skipped_product_run" and res["requests"] == 0 and calls == []
    assert ob.canary_record(ob.load(tmp_path / ob.STORE_NAME)[0], "telegram_canary_v9") is None
    res = cli._telegram_canary(tmp_path, now=NOW, attempt_id="gh-1-1", product_gate={"allowed": False},
                               product_requests=1)
    assert res["canary"] == "skipped_product_run" and calls == []
    st = json.loads((tmp_path / "provider_status.json").read_text(encoding="utf-8"))
    assert TOKEN not in json.dumps(st) and CHAT not in json.dumps(st)


def test_operator_resolved_delivered_record_is_valid(run):
    """届いたか不明を人が「届いていた」と解決した記録（配信先の ID なし）で #856・#859 が LP を止めない（監査 M-2）。"""
    dc = _dc()
    run(ps5("OUT_OF_STOCK"))
    run(ps5(), result=(502, b""))
    st = run.store()
    nid = next(iter(st["records"]))
    ob.resolve(st, nid, ob.MARK_DELIVERED, rows=ob._rows(_diag(ps5())), now=NOW)
    rec = st["records"][nid]
    assert rec["status"] == ob.DELIVERED and not rec["channels"]["telegram"]["provider_delivery_id"]
    assert dc._is_valid_limited_product_record(rec)
    bad = json.loads(json.dumps(rec))
    bad["channels"]["telegram"]["resolutions"] = []
    assert not dc._is_valid_limited_product_record(bad)                          # 否定の対照: 解決の記録が無い
