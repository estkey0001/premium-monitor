"""Phase 19（今すぐ行動できるようになった商品の通知）のテスト。Phase 20 で outbox（src/notifiers/outbox）の上に移した。

行動できない → できる に変わった確定の利益商品だけを候補にする。同じ状態では出さない・できないと確かめた状態の後は
再び通知できる・配信の直前にもう一度確かめる・dry-run では送らない。判定は Phase 18 の正本（actionability.evaluate）の
結果を、診断（opportunity_diagnostics）と同じ形にして使う（tests/_notify_helpers）。各テストに否定の対照を付ける。
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from src.market import actionability as act
from src.notifiers import actionable as an
from src.notifiers import outbox as ob
from _notify_helpers import (CLOSED, NOW, OPEN, RICOH, SONY, FixtureAdapter, SendFail, _diag, _view, gr4, lottery_event, ps5,
                                   run, seq)
from _notify_helpers import stock_gr4 as _stock_gr4

# ── 候補（行動できない → できる だけ） ──────────────────────────────────

def test_false_to_true_is_candidate():
    (r1, r2), _ = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()))
    assert r1["notification_candidates"] == 0          # 否定の対照: 在庫切れでは出さない
    assert r2["notification_candidates"] == 1 and r2["candidates"][0]["transition"] == "OUT_OF_STOCK→IN_STOCK"


def test_true_to_true_no_candidate():
    (_r1, r2, r3), _ = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()), _diag(ps5()))
    assert r2["notification_candidates"] == 1
    assert r3["notification_candidates"] == 0 and r3["dedupe_suppressed"] == 1


def test_true_to_false_no_candidate():
    (_r1, _r2, r3), _ = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()), _diag(ps5("OUT_OF_STOCK")))
    assert r3["notification_candidates"] == 0 and r3["dedupe_suppressed"] == 0


def test_rearm_after_confirmed_out_of_stock():
    reps, _ = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()), _diag(ps5("OUT_OF_STOCK")), _diag(ps5()))
    assert [r["notification_candidates"] for r in reps] == [0, 1, 0, 1]


@pytest.mark.parametrize("stock,checked", [("UNKNOWN", None), ("IN_STOCK", NOW - timedelta(hours=4))])
def test_no_rearm_on_unknown_or_stale(stock, checked):
    """在庫未確認・更新待ち（確認できなかった）では re-arm しない（取得の失敗のたびに同じ通知を繰り返さない）。"""
    reps, _ = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()), _diag(ps5(stock, checked)), _diag(ps5()))
    assert [r["notification_candidates"] for r in reps] == [0, 1, 0, 0]


def test_baseline_has_no_candidates():
    rep, st = run(_diag(ps5()), None)
    assert rep["is_baseline"] and rep["notification_candidates"] == 0
    rep2, _ = run(_diag(ps5()), st)
    assert rep2["notification_candidates"] == 0       # 基準日の状態は通知済みとして扱う
    rep3, _ = run(_diag(ps5()), {})                   # 台帳はあるが記録の無い商品も、その商品の基準日（監査 M-1）
    assert rep3["notification_candidates"] == 0 and not rep3["is_baseline"]
    _r, st4 = run(_diag(ps5("OUT_OF_STOCK")), {})
    rep4, _ = run(_diag(ps5()), st4)
    assert rep4["notification_candidates"] == 1        # 否定の対照: 在庫切れを見ていた商品は候補


def test_profit_only_is_not_candidate():
    """利益がプラスになっただけ（在庫切れのまま）では出さない。"""
    (r1, r2), _ = seq(_diag(ps5("OUT_OF_STOCK", profitable=False)), _diag(ps5("OUT_OF_STOCK")))
    assert r1["notification_candidates"] == r2["notification_candidates"] == 0


# ── 通常販売（PS5 Pro） ─────────────────────────────────────────────────

def test_ps5_restock_scenario():
    (_r0, r1, r2, r3, r4), _ = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()), _diag(ps5()),
                                    _diag(ps5("OUT_OF_STOCK")), _diag(ps5()))
    c = r1["candidates"][0]
    assert (c["product_id"], c["availability"], c["status"]) == ("prod_ps5_pro", "IN_STOCK", "購入可能になりました")
    assert c["net_profit"] == 54870 and c["roi"] == 0.396 and c["cta_url"] == SONY and c["cta_label"] == "購入する"
    assert c["dispatch_status"] == ob.DRY_RUN_PLANNED and c["dry_run"] is True
    assert r2["notification_candidates"] == 0 and r3["notification_candidates"] == 0
    assert r4["notification_candidates"] == 1


@pytest.mark.parametrize("kw", [{"checked": NOW - timedelta(hours=4)}, {"stock": "UNKNOWN"},
                                {"url": "https://www.apple.com/jp/shop/"}, {"profitable": False}])
def test_ps5_not_actionable_no_candidate(kw):
    """更新待ち・在庫未確認・一般のページ・利益なしでは候補にしない。"""
    (_r1, r2), _ = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5(**kw)))
    assert r2["notification_candidates"] == 0


# ── 抽選（GR IV HDF） ──────────────────────────────────────────────────

def test_gr4_new_lottery_scenario():
    (r1, r2, r3), _ = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)), _diag(gr4(OPEN)))
    assert r1["notification_candidates"] == 0
    c = r2["candidates"][0]
    assert c["availability"] == "LOTTERY_OPEN" and c["status"] == "抽選受付が始まりました"
    assert c["cta_url"] == RICOH and c["cta_label"] == "抽選に申し込む" and c["deadline"]
    assert c["event_id"].startswith("prod_gr4_hdf|")
    assert r3["notification_candidates"] == 0


def test_gr4_old_closed_event_does_not_hide_new_open():
    ev = act.find_event([CLOSED, OPEN], "prod_gr4_hdf", "S0001567")
    assert ev is OPEN
    old_newer_check = dict(CLOSED, checked_at=(NOW - timedelta(minutes=5)).isoformat())
    assert act.find_event([old_newer_check, OPEN], "prod_gr4_hdf") is old_newer_check   # 新しい確認の終了を優先（Phase 18）


def test_new_lottery_identity_renotifies():
    """同じ商品でも、別の受付（受付期間が違う）が始まれば新しい通知にする。"""
    nxt = lottery_event(NOW + timedelta(days=3), NOW + timedelta(days=6))
    later = NOW + timedelta(days=4)
    _r0, st = run(_diag(gr4(CLOSED)), {})
    r1, st = run(_diag(gr4(OPEN)), st)
    r2, st = run(_diag(gr4(nxt, now=later)), st, now=later)
    assert r1["notification_candidates"] == 1 and r2["notification_candidates"] == 1
    assert r1["candidates"][0]["event_id"] != r2["candidates"][0]["event_id"]
    r3, _ = run(_diag(gr4(OPEN, now=later)), st, now=later)
    assert r3["notification_candidates"] == 0         # 否定の対照: 同じ受付は出さない


@pytest.mark.parametrize("ev", [
    CLOSED,
    lottery_event(NOW - timedelta(days=1), None),                                           # 締切が不明
    dict(OPEN, entry_start_at=""),                                                          # 開始が不明
    dict(OPEN, status_conflict="true"),                                                     # 状態の矛盾
    lottery_event(NOW - timedelta(days=1), NOW + timedelta(days=2), checked=NOW - timedelta(days=10)),  # 確認が古い
    lottery_event(NOW - timedelta(days=1), NOW + timedelta(days=2), form="https://ricohimagingstore.com/"),
])
def test_lottery_not_open_no_candidate(ev):
    (_r1, r2), _ = seq(_diag(gr4(CLOSED)), _diag(gr4(ev)))
    assert r2["notification_candidates"] == 0


@pytest.mark.parametrize("kind,avail,title", [("予約販売", "PREORDER_OPEN", "予約受付が始まりました"),
                                               ("先着販売", "FIRST_COME_OPEN", "先着販売が始まりました")])
def test_preorder_and_first_come(kind, avail, title):
    ev = dict(OPEN, sale_method=kind)
    v = _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock="PREORDER", stock_checked_at=None,
                                           sale_method=kind, event=ev, now=NOW))
    (_r1, r2), _ = seq(_diag(gr4(CLOSED)), _diag(v))
    assert r2["notification_candidates"] == 1 and r2["candidates"][0]["availability"] == avail
    assert r2["candidates"][0]["status"] == title


# ── 配信の直前の確認・dry-run・失敗と再試行 ───────────────────────────────

def _cand(**kw):
    (_r, r2), _ = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()))
    return dict(r2["candidates"][0], **kw)


def test_revalidation_passes_for_valid_candidate():
    assert an.revalidate_fields(_cand(), NOW) == []


@pytest.mark.parametrize("kw,why", [
    ({"until_ms": int((NOW - timedelta(seconds=1)).timestamp() * 1000)}, "expired"),
    ({"cta_url": "https://www.apple.com/jp/shop/"}, "url_not_official"),
    ({"cta_url": "https://estkey0001.github.io/premium-monitor/"}, "url_not_official"),
    ({"confirmed": False}, "profit_not_confirmed"),
    ({"net_profit": 0}, "profit_not_confirmed"),
    ({"availability": "STOCK_STALE"}, "not_actionable"),
    ({"reasons": ["stock_out"]}, "has_reasons"),
])
def test_revalidation_blocks(kw, why):
    assert why in an.revalidate_fields(_cand(**kw), NOW)


@pytest.mark.parametrize("field,value,status", [
    ("until_ms", None, ob.EXPIRED),                                   # 期限が無い
    ("cta_url", "https://www.apple.com/jp/shop/", ob.CANCELLED),      # 一般のページ
    ("confirmed", False, ob.CANCELLED),                               # 参考の利益
    ("net_profit", 0, ob.CANCELLED),                                  # 利益なし
])
def test_prepare_blocks_invalid_rows(field, value, status):
    """配信の直前に、最新の診断の行で確かめ直す（行の値が変わったら送らない）。"""
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {})
    d = _diag(ps5())
    st2 = ob.migrate(st)
    ob.observe(st2, d["actionability"]["products"], now=NOW, mode=ob.MODE_DRY)
    row = dict(d["actionability"]["products"][0], **{"cta_url" if field == "cta_url" else field: value})
    out = ob.prepare(st2, [row], now=NOW, mode=ob.MODE_DRY, attempt_id="x")
    assert out["planned"] == 0
    assert {r["status"] for r in st2["records"].values()} == {status}


def test_dispatch_time_expiry_blocks():
    """候補を作ってから配信までに期限（3時間）を過ぎたら送らない（EXPIRED）。"""
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {})
    late = NOW + timedelta(hours=3)
    r, st = run(_diag(ps5()), st, dispatch_now=late)
    assert r["dispatch_planned"] == 0 and r["dispatch_expired"] == 1
    _r, st0 = run(_diag(ps5("OUT_OF_STOCK")), {})
    r, _ = run(_diag(ps5()), st0)                                     # 否定の対照: 期限の内なら計画する
    assert r["dispatch_planned"] == 1


def test_lottery_deadline_revalidated():
    (_r1, r2), st = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)))
    c = r2["candidates"][0]
    assert an.revalidate_fields(c, NOW) == []
    assert "deadline_invalid" in an.revalidate_fields(dict(c, deadline=""), NOW)
    _r, st = run(_diag(gr4(CLOSED)), {})
    r, _ = run(_diag(gr4(OPEN)), st, dispatch_now=NOW + timedelta(days=3))    # 締切の後
    assert r["dispatch_planned"] == 0 and r["dispatch_expired"] == 1


def test_dry_run_never_calls_sender():
    called = []
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, channels=["fixture"])
    st2 = ob.migrate(st)
    ob.cycle(st2, _diag(ps5()), now=NOW, mode=ob.MODE_DRY, channels=["fixture"],
             adapters={"fixture": FixtureAdapter(
                 lambda c, k: called.append(k))})
    assert called == [] and ob.counts(st2)["dry_run_planned"] == 1
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, dry_run=False, sender=lambda c, k: called.append(k))
    r, _ = run(_diag(ps5()), st, dry_run=False, sender=lambda c, k: called.append(k))
    assert r["dispatch_sent"] == 1 and len(called) == 1                # 否定の対照: 本番の方式なら呼ぶ


def test_not_dry_run_without_sender_does_not_send():
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, dry_run=False)
    r, st = run(_diag(ps5()), st, dry_run=False)
    assert r["dispatch_not_configured"] == 1 and r["dispatch_sent"] == 0
    assert ob.counts(st)["outbox_pending"] == 1


def test_is_dry_run_default():
    assert an.is_dry_run({}) and an.is_dry_run({"NOTIFICATION_DRY_RUN": "true"})
    assert not an.is_dry_run({"NOTIFICATION_DRY_RUN": "false"})


@pytest.mark.parametrize("status,final", [("connect", ob.FAILED_RETRYABLE), (429, ob.FAILED_RETRYABLE),
                                          (503, ob.FAILED_RETRYABLE), (400, ob.FAILED_FINAL),
                                          ("read", ob.UNKNOWN_DELIVERY)])
def test_retry_semantics(status, final):
    """1回の実行では1回だけ送る（再試行は次の実行）。接続できない・429・5xx は出し直す、400 は出し直さない、
    送った後の切断は届いたか不明（自動では送り直さない）。"""
    keys = []

    def sender(c, k):
        keys.append(k)
        raise SendFail(status)
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, dry_run=False, sender=sender)
    r, st = run(_diag(ps5()), st, dry_run=False, sender=sender)
    rec = next(iter(st["records"].values()))
    assert rec["status"] == final and rec["channels"]["fixture"]["attempt_count"] == 1 and len(keys) == 1


def test_retry_then_success():
    n = []

    def sender(c, k):
        n.append(k)
        if len(n) < 2:
            raise SendFail(429, {"Retry-After": "60"})
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, dry_run=False, sender=sender)
    r, st = run(_diag(ps5()), st, dry_run=False, sender=sender)
    assert r["dispatch_failed"] == 1
    later = NOW + timedelta(minutes=10)
    r, st = run(_diag(ps5(checked=later - timedelta(minutes=5), now=later)), st, now=later, dry_run=False, sender=sender)
    assert r["dispatch_sent"] == 1 and len(n) == 2 and len(set(n)) == 1   # 同じ冪等性のキーで出し直す


def test_failure_keeps_candidate_and_does_not_mark_sent():
    """送信の失敗は送信済みにしない（次の実行で出し直す）。成功した後は出さない（重複しない）。"""
    def fail(c, k):
        raise SendFail(503)
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {}, dry_run=False, sender=fail)
    r1, st = run(_diag(ps5()), st, dry_run=False, sender=fail)
    assert r1["dispatch_failed"] == 1 and ob.counts(st)["delivered"] == 0
    sent = []
    later = NOW + timedelta(minutes=10)
    v = ps5(checked=later - timedelta(minutes=5), now=later)
    r2, st = run(_diag(v), st, now=later, dry_run=False, sender=lambda c, k: sent.append(k))
    assert r2["dispatch_sent"] == 1 and len(sent) == 1
    r3, st = run(_diag(v), st, now=later, dry_run=False, sender=lambda c, k: sent.append(k))
    assert r3["notification_candidates"] == 0 and len(sent) == 1


def test_blocked_candidate_is_not_marked():
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {})
    late = NOW + timedelta(hours=5)        # 判定は NOW、配信は期限の後
    r, st = run(_diag(ps5()), st, dispatch_now=late)
    assert r["dispatch_expired"] == 1 and ob.counts(st)["dry_run_planned"] == 0 and ob.counts(st)["delivered"] == 0


# ── 本文・配信先・秘密の値 ───────────────────────────────────────────────

def test_message_content():
    m = _cand()["message"]
    assert "購入可能になりました" in m and "PlayStation 5 Pro" in m and "+¥54,870" in m and "ROI 39.6%" in m
    assert SONY in m and "購入する" in m
    (_r1, r2), _ = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)))
    g = r2["candidates"][0]["message"]
    assert "抽選受付が始まりました" in g and "締切" in g and "抽選に申し込む" in g


def test_no_misleading_wording_for_non_actionable():
    """行動できない商品は候補にならないので、「買えます」「申し込めます」の本文を作らない。"""
    rep, _ = run(_diag(ps5("UNKNOWN"), gr4(CLOSED)), {})
    assert rep["candidates"] == []


def test_channels_follow_existing_routing():
    from src.notifiers.routing import RANK_CHANNELS
    assert _cand()["channels"] == RANK_CHANNELS[an.RANK]


def test_report_has_no_secrets(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123456/secret-token")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    rep, st = run(_diag(ps5()), {})
    text = json.dumps([rep, st], ensure_ascii=False)
    assert "secret-token" not in text and "ABCDEFGHIJ" not in text and "webhooks" not in text


def test_engine_registers_type():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "scripts" / "generate_notifications.py"
    spec = importlib.util.spec_from_file_location("_gn19", p)
    gn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gn)
    assert gn.PRIORITY[an.TYPE] == an.PRIORITY
    c = _cand()
    assert gn._template({"type": an.TYPE, "data": c}) == c["message"]


# ── LP の生成との接続・運営者向け ─────────────────────────────────────────

def test_generator_writes_and_dedupes(tmp_path, monkeypatch):
    """LP の生成は候補を outbox に PENDING で入れて保存するだけ（配信は次の手順）。同じ状態では新しい記録を作らない。"""
    from src.content.daily_lp_generator import DailyLPGenerator
    monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(tmp_path))
    monkeypatch.delenv("NOTIFICATION_DRY_RUN", raising=False)
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    r0 = g._write_actionable_notifications(_diag(ps5("OUT_OF_STOCK")), NOW)
    assert r0["is_baseline"] and r0["dry_run"] is True
    r1 = g._write_actionable_notifications(_diag(ps5()), NOW)
    r2 = g._write_actionable_notifications(_diag(ps5()), NOW)
    assert (r1["notification_candidates"], r2["notification_candidates"]) == (1, 0)
    hist = json.loads((tmp_path / "history" / "2026-10-09.json").read_text(encoding="utf-8"))
    assert len(hist["runs"]) == 3 and hist["runs"][1]["candidates"][0]["outbox_status"] == ob.PENDING
    st = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert st["schema"] == ob.SCHEMA and len(st["records"]) == 1
    assert r2["counts"]["outbox_pending"] == 1 and r2["dispatch_planned"] == 0


def test_admin_shows_counts_without_keys(tmp_path):
    from src.content.ui import admin
    ob.run_observe(tmp_path, _diag(ps5("OUT_OF_STOCK")), now=NOW, dry_run=True)
    d = dict(_diag(ps5()), generated_at=NOW.isoformat())
    rep = ob.run_observe(tmp_path, d, now=NOW, dry_run=True)
    rep = ob.run_prepare(tmp_path, d, now=NOW, dry_run=True, attempt_id="a")
    a = admin.build_actionable_notices(rep)
    html = admin._act_notices(a)
    assert "dry-run" in html and "PlayStation 5 Pro" in html and "購入可能になりました" in html
    assert a["dry_run_planned"] == 1 and a["outbox_pending"] == 0
    assert "ACTIONABLE_NOW:" not in html and SONY not in html        # 冪等性のキー・URL は出さない
    empty = admin._act_notices(admin.build_actionable_notices(None))
    assert "記録がありません" in empty


def test_diagnostics_row_has_notification_fields():
    rows = _diag(gr4(OPEN))["actionability"]["products"]
    r = rows[0]
    assert r["confirmed"] is True and r["net_profit"] == 16200 and r["cta_url"] == RICOH and r["until_ms"]
    assert r["event_key"] == "prod_gr4_hdf|2026-10-08T12:00+09:00|2026-10-11T12:00+09:00"
    p = _diag(ps5())["actionability"]["products"][0]
    assert p["event_key"] == "" and p["cta_label"] == "購入する"


def test_message_has_no_forbidden_wording():
    """通知の本文に、煽りの禁止表現（src/content/safety）を使わない。"""
    from src.content import safety
    (_r1, r2), _ = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)))
    for m in (_cand()["message"], r2["candidates"][0]["message"]):
        assert safety.check_forbidden(m) == []


def test_top10_note_survives_safety_filter():
    """TOP10 の注記（7日の在庫と「今すぐ行動」の違い）が、禁止表現の置き換えで崩れない。"""
    from src.content import safety
    from src.content.ui import opportunities_page, pages
    import inspect
    for mod in (opportunities_page, pages):
        src = inspect.getsource(mod)
        assert "購入・申込ができるかは各商品の「今すぐ行動」" in src
        assert safety.check_forbidden("在庫は7日以内の確認。購入・申込ができるかは各商品の「今すぐ行動」") == []


# ── 監査の指摘（M-1・L-1・L-3・L-4） ───────────────────────────────────

def test_profit_return_while_in_stock_is_not_notified():
    """確定の利益から外れていた間の変化は見ていないので、利益だけ戻って在庫ありのままなら通知しない（監査 M-1）。"""
    st = {}
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), st)
    other = _view("prod_other", act.evaluate(profitable=True, identity_ok=True, stock="OUT_OF_STOCK",
                                             stock_checked_at=NOW - timedelta(minutes=10), buy_url=SONY, now=NOW))
    _r, st = run(_diag(other), st)                              # 利益から外れた（ほかの商品だけが診断の行にある）
    assert st["products"]["prod_ps5_pro"]["availability"] == an.NOT_CONFIRMED
    r, st = run(_diag(ps5()), st)                                # 利益が戻った・在庫あり
    assert r["notification_candidates"] == 0 and r["baseline_recorded"] == 1
    r, st = run(_diag(ps5()), st)
    assert r["notification_candidates"] == 0 and r["dedupe_suppressed"] == 1
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), st)                # 否定の対照: その後の在庫切れ → 在庫ありは通知
    r, st = run(_diag(ps5()), st)
    assert r["notification_candidates"] == 1


def test_event_key_format_change_is_same_event():
    """受付の時刻の書式・商品コードの有無が変わっても、同じ受付として扱う（監査 L-1）。"""
    rewritten = dict(OPEN, entry_start_at=OPEN["entry_start_at"].replace("T", " ")[:16], product_code="")
    reps, _ = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)), _diag(gr4(rewritten)))
    assert [r["notification_candidates"] for r in reps] == [0, 1, 0]
    assert reps[2]["dedupe_suppressed"] == 1


def test_dispatch_now_is_used_for_revalidation():
    """配信の直前の確認は、生成を始めた時刻より後の時刻で行う（監査 L-3）。"""
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {})
    st_b = ob.migrate(json.loads(json.dumps(st)))
    r, st2 = run(_diag(ps5()), st, dispatch_now=NOW + timedelta(hours=3))
    assert r["notification_candidates"] == 1 and r["dispatch_blocked"] == 1 and r["dispatch_planned"] == 0
    assert ob.counts(st2)["dry_run_planned"] == 0                  # 止めたものは計画・送信済みにしない
    r, _ = run(_diag(ps5()), st_b, dispatch_now=NOW - timedelta(hours=1))   # 生成より前の時刻は使わない
    assert r["dispatch_planned"] == 1


def test_nan_profit_is_not_notified():
    _r, st = run(_diag(ps5("OUT_OF_STOCK")), {})
    v = ps5()
    v.net_profit = float("nan")
    r, _ = run(_diag(v), st)
    assert r["dispatch_planned"] == 0 and r["dispatch_blocked"] == 1


def test_generator_records_failure(tmp_path, monkeypatch):
    """生成に失敗したら latest.json に失敗を書く（前回の件数を今回のものとして読ませない。監査 L-4）。台帳は変えない。"""
    from src.content.daily_lp_generator import DailyLPGenerator
    monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(tmp_path))
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g._write_actionable_notifications(_diag(ps5("OUT_OF_STOCK")), NOW)
    before = (tmp_path / "state.json").read_text(encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(ob, "observe", boom)
    assert g._write_actionable_notifications(_diag(ps5()), NOW) is None
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["failed"] is True and latest["dispatch_sent"] == 0
    assert (tmp_path / "state.json").read_text(encoding="utf-8") == before


def test_report_links_to_diagnostics(tmp_path):
    d = dict(_diag(ps5()), generated_at="2026-10-09T12:00:00+09:00")
    r = ob.run_observe(tmp_path, d, now=NOW, dry_run=True)
    assert r["diagnostics_generated_at"] == "2026-10-09T12:00:00+09:00"


@pytest.mark.parametrize("leak", ["https://discord.com/api/v10/webhooks/123/abc-DEF",
                                  "https://discordapp.com/api/webhooks/123/abc",
                                  "https://hooks.slack.com/services/T0/B0/xyz"])
def test_secret_patterns(leak):
    import re
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import deploy_check
    assert any(re.search(p, f"x {leak} y") for p in deploy_check._SECRET_PATTERNS)
    assert not any(re.search(p, "https://pur.store.sony.jp/ps5/") for p in deploy_check._SECRET_PATTERNS)


# ── レビューの指摘（H-1・M-2・L-2） ────────────────────────────────────

def test_same_lottery_closed_then_open_is_not_renotified():
    """同じ受付がページの表示の揺れで 受付中 → 終了 → 受付中 になっても、もう一度通知しない（レビュー M-2）。"""
    flap = dict(OPEN, status="closed")
    reps, _ = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)), _diag(gr4(flap)), _diag(gr4(OPEN)))
    assert [r["notification_candidates"] for r in reps] == [0, 1, 0, 0]


def test_actionable_to_actionable_without_new_event_is_not_notified():
    """できる → できる で販売の形が同じ・新しい受付でもないなら通知しない（レビュー L-2）。新しい受付なら通知する。"""
    pre = dict(OPEN, sale_method="予約販売")              # 同じ受付期間（同じ受付の識別）で表示が予約に変わった
    pre_view = _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock="PREORDER",
                                                  stock_checked_at=None, sale_method="予約販売", event=pre, now=NOW))
    nxt = lottery_event(NOW - timedelta(hours=2), NOW + timedelta(days=5))
    reps, _ = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)), _diag(pre_view), _diag(gr4(nxt)))
    assert [r["notification_candidates"] for r in reps] == [0, 1, 0, 1]


def test_generate_notifications_only_when_enabled(tmp_path, monkeypatch):
    """台帳を読み書きするのは notifications=True の生成（CLI の generate-daily-lp）だけ（レビュー H-1）。"""
    import inspect
    from src import cli
    from src.content.daily_lp_generator import DailyLPGenerator
    src_cli = inspect.getsource(cli)
    assert src_cli.count("notifications=True") == 1
    assert "gen.generate(date_str=date_str, variant=variant, notifications=True)" in src_cli
    from src.jobs import buyback_premium_job
    assert "notifications=True" not in inspect.getsource(buyback_premium_job)
    assert inspect.signature(DailyLPGenerator.generate).parameters["notifications"].default is False


# ── 再監査の指摘（M-1・L-1・L-3） ─────────────────────────────────────

def test_undelivered_event_is_retried_after_previous_delivery():
    """前に別の組み合わせを通知済みでも、配信できなかった新しい受付は次の実行で出し直す（再監査 M-1）。"""
    _r, st = run(_diag(gr4(CLOSED)), {})
    stock_view = _stock_gr4()
    r, st = run(_diag(stock_view), st)
    assert r["dispatch_planned"] == 1
    r, st = run(_diag(gr4(OPEN)), st, dispatch_now=NOW + timedelta(days=3))    # 新しい受付・配信の時点で期限切れ
    assert r["dispatch_blocked"] == 1
    r, st = run(_diag(gr4(OPEN)), st)                                           # 次の実行では有効
    assert r["notification_candidates"] == 1 and r["dispatch_planned"] == 1
    r, st = run(_diag(gr4(OPEN)), st)
    assert r["notification_candidates"] == 0                                    # 否定の対照: 届いた後は出さない


def test_send_failure_retried_with_sender():
    sent = []
    _r, st = run(_diag(gr4(CLOSED)), {}, dry_run=False, sender=lambda c, k: sent.append(k))
    r, st = run(_diag(_stock_gr4()), st, dry_run=False, sender=lambda c, k: sent.append(k))

    def fail(c, k):
        raise SendFail(503)
    r, st = run(_diag(gr4(OPEN)), st, dry_run=False, sender=fail)
    assert r["dispatch_failed"] == 1
    later = NOW + timedelta(minutes=10)
    r, st = run(_diag(gr4(OPEN, now=later)), st, now=later, dry_run=False, sender=lambda c, k: sent.append(k))
    assert r["dispatch_sent"] == 1 and len(sent) == 2


def test_lottery_to_general_sale_is_notified():
    """抽選の受付中から一般販売（在庫あり）に変わったら、新しい買い方として通知する（再監査 L-1）。"""
    stock_view = _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock="IN_STOCK",
                                                    stock_checked_at=NOW - timedelta(minutes=10), buy_url=RICOH,
                                                    now=NOW))
    reps, _ = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)), _diag(stock_view), _diag(stock_view))
    assert [r["notification_candidates"] for r in reps] == [0, 1, 1, 0]


def test_diagnostics_failure_records_notification_failure(tmp_path, monkeypatch):
    """診断に失敗した実行では、通知の latest.json にも失敗を書く（再監査 L-3）。"""
    from src.content.daily_lp_generator import DailyLPGenerator
    monkeypatch.setenv("ACTIONABLE_NOTIFICATIONS_DIR", str(tmp_path))
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g._write_notification_failure(NOW, None, "DiagnosticsFailed")
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["failed"] is True and latest["error"] == "DiagnosticsFailed" and not (tmp_path / "state.json").exists()



def test_empty_run_keeps_ledger():
    """診断の行が1件も無い実行では台帳を変えない（全商品を基準日に戻さない。レビュー L-1）。"""
    reps, st = seq(_diag(ps5("OUT_OF_STOCK")), _diag(), _diag(ps5()))
    assert [r["notification_candidates"] for r in reps] == [0, 0, 1]
    other = _view("prod_other", act.evaluate(profitable=True, identity_ok=True, stock="OUT_OF_STOCK",
                                             stock_checked_at=NOW - timedelta(minutes=10), buy_url=SONY, now=NOW))
    reps, _ = seq(_diag(ps5("OUT_OF_STOCK")), _diag(other), _diag(ps5()))   # 否定の対照: ほかの商品だけ残った実行
    assert [r["notification_candidates"] for r in reps] == [0, 0, 0] and reps[2]["baseline_recorded"] == 1



def test_same_lottery_after_general_sale_is_not_renotified():
    """抽選 → 一般販売 → 同じ抽選 と行き来しても、同じ受付は2回通知しない（レビュー H-1）。新しい受付は通知する。"""
    stock_view = _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock="IN_STOCK",
                                                    stock_checked_at=NOW - timedelta(minutes=10), buy_url=RICOH,
                                                    now=NOW))
    nxt = lottery_event(NOW - timedelta(hours=2), NOW + timedelta(days=5))
    _r, st = run(_diag(gr4(CLOSED)), {})
    counts = []
    for d in (_diag(gr4(OPEN)), _diag(stock_view), _diag(gr4(OPEN)), _diag(gr4(nxt))):
        r, st = run(d, st)
        counts.append(r["notification_candidates"])
    assert counts == [1, 1, 0, 1]
    assert sum(1 for r in st["records"].values() if r["kind"] == "event") == 2


def test_known_events_expire_after_deadline():
    """基準日に受付中だった受付の記録は、締切から保持日数を過ぎたら消す（締切の延長に備えて少し残す）。"""
    _r, st = run(_diag(gr4(OPEN)), None)
    assert st["products"]["prod_gr4_hdf"]["known_events"]
    later = NOW + timedelta(days=5 + ob.RETENTION_DAYS)   # OPEN の締切から保持日数の後
    _r, st = run(_diag(gr4(CLOSED, now=later)), st, now=later)
    assert st["products"]["prod_gr4_hdf"]["known_events"] == {}


def test_lottery_and_stock_flapping_does_not_repeat():
    """抽選 E1 と在庫ありを行き来しても、どちらも2回目は出さない（監査 M-1・レビュー H-1）。"""
    _r, st = run(_diag(gr4(CLOSED)), {})
    counts = []
    for d in (_diag(gr4(OPEN)), _diag(_stock_gr4()), _diag(gr4(OPEN)), _diag(_stock_gr4()), _diag(gr4(OPEN))):
        r, st = run(d, st)
        counts.append(r["dispatch_planned"])
    assert counts == [1, 1, 0, 0, 0]


def test_baseline_records_open_event():
    """基準日の時点ですでに受付中の抽選は、後で「始まりました」と出さない（監査 L-1）。"""
    reps, st = [], None
    for d in (_diag(gr4(OPEN)), _diag(_stock_gr4()), _diag(gr4(OPEN))):
        r, st = run(d, st)
        reps.append(r["dispatch_planned"])
    assert reps == [0, 1, 0]


def test_old_ledger_without_events():
    """前の形式（Phase 19）の台帳でも、通知済みの受付をもう一度出さない。抽選だけを通知していたら、一般販売は通知する。"""
    e1 = "prod_gr4_hdf|2026-10-08T12:00+09:00|2026-10-11T12:00+09:00"
    old = {"prod_gr4_hdf": {"availability": "LOTTERY_OPEN", "actionable": True,
                            "notified_key": f"prod_gr4_hdf::ACTIONABLE_NOW::LOTTERY_OPEN::{e1}",
                            "notified_events": [e1]}}
    counts = []
    for d in (_diag(_stock_gr4()), _diag(gr4(OPEN))):
        r, old = run(d, old)
        counts.append(r["dispatch_planned"])
    assert counts == [1, 0]
    direct = {"prod_ps5_pro": {"availability": "IN_STOCK", "actionable": True,
                               "notified_key": "prod_ps5_pro::ACTIONABLE_NOW::IN_STOCK::"}}
    r, _ = run(_diag(ps5()), direct)
    assert r["notification_candidates"] == 0                 # 一般販売を通知済み → 同じ在庫ありは出さない


def test_known_events_drops_malformed():
    e1 = "prod_gr4_hdf|2026-10-08T12:00+09:00"
    known = {e1: "2026-10-11T12:00+09:00", "p|x|": "2026-10-11T12:00+09:00", "junk": "x", "q|s": ""}
    assert ob._live_known(known, NOW) == {e1: "2026-10-11T12:00+09:00"}
    assert ob._live_known({e1: "2026-10-11T12:00+09:00"}, NOW + timedelta(days=5)) != {}
    assert ob._live_known({e1: "2026-10-11T12:00+09:00"}, NOW + timedelta(days=5 + ob.RETENTION_DAYS)) == {}
