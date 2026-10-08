"""Phase 19（今すぐ行動できるようになった商品の通知）のテスト。

行動できない → できる に変わった確定の利益商品だけを候補にする。同じ状態では出さない・できないと確かめた状態の後は
再び通知できる・配信の直前にもう一度確かめる・dry-run では送らない。判定は Phase 18 の正本（actionability.evaluate）の
結果を、診断（opportunity_diagnostics）と同じ形にして使う。各テストに否定の対照を付ける。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.market import actionability as act
from src.market import opportunity_diagnostics as diag
from src.notifiers import actionable as an
from src.tcg.models import JST

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=JST)
SONY = "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/"
RICOH = "https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0&pid=S0001567&cat=002010"


# ── 判定の正本 → 診断の行 ───────────────────────────────────────────────

def _view(pid, a, *, net=54870, roi=0.396, name=None):
    return SimpleNamespace(product_id=pid, product_name=name or pid, net_profit=net, roi=roi, action=a,
                           actionable=a.actionable)


def _diag(*views, prev=None):
    """診断の「今すぐ行動」（opportunity_diagnostics._actionability_summary）をそのまま作る。"""
    s = SimpleNamespace(eligible=list(views))
    acts = [{"product_id": v.product_id} for v in views if v.actionable]
    return {"actionability": diag._actionability_summary(s, acts, prev)}


def ps5(stock="IN_STOCK", checked=NOW - timedelta(minutes=30), url=SONY, now=NOW, profitable=True):
    return _view("prod_ps5_pro", act.evaluate(profitable=profitable, identity_ok=True, stock=stock,
                                              stock_checked_at=checked, buy_url=url, now=now),
                 name="PlayStation 5 Pro")


def lottery_event(start, end, *, status="active", checked=NOW - timedelta(hours=1), form=RICOH, **kw):
    ev = {"product_id": "prod_gr4_hdf", "product_code": "S0001567", "sale_method": "抽選販売", "status": status,
          "entry_start_at": start.isoformat(), "entry_end_at": end.isoformat() if end else "",
          "checked_at": checked.isoformat(), "entry_form_url": form}
    ev.update(kw)
    return ev


def gr4(event, now=NOW):
    return _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock="LOTTERY", stock_checked_at=None,
                                              sale_method="抽選販売", event=event, now=now),
                 net=16200, roi=0.073, name="RICOH GR IV HDF")


OPEN = lottery_event(NOW - timedelta(days=1), NOW + timedelta(days=2))
CLOSED = lottery_event(datetime(2026, 9, 25, 12, tzinfo=JST), datetime(2026, 9, 28, 12, tzinfo=JST), status="closed")


def run(d, ledger, now=NOW, **kw):
    return an.run(d, ledger, now=now, **kw)


def seq(*diags, ledger=None):
    """続けて実行し、各回の報告を返す（最初の台帳は空 = 基準日ではない）。"""
    st = {} if ledger is None else ledger
    reps = []
    for d in diags:
        rep, st = run(d, st)
        reps.append(rep)
    return reps, st


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
    rep4, _ = run(_diag(ps5()), {"prod_ps5_pro": {"availability": "OUT_OF_STOCK", "notified_key": ""}})
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
    assert c["dispatch_status"] == an.PLANNED and c["dry_run"] is True
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
    r3, _ = run(_diag(gr4(OPEN)), {"prod_gr4_hdf": {"notified_key": r1["candidates"][0]["dedupe_key"]}})
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
    assert an.revalidate(_cand(), NOW) == []


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
    assert why in an.revalidate(_cand(**kw), NOW)
    assert an.dispatch([_cand(**kw)], now=NOW)[0]["status"] == an.BLOCKED


def test_dispatch_time_expiry_blocks():
    """候補を作ってから配信までに期限（3時間）を過ぎたら送らない。"""
    c = _cand()
    assert an.dispatch([c], now=NOW)[0]["status"] == an.PLANNED
    late = datetime.fromtimestamp(c["until_ms"] / 1000, tz=JST) + timedelta(seconds=1)
    assert an.dispatch([c], now=late)[0]["status"] == an.BLOCKED


def test_lottery_deadline_revalidated():
    (_r1, r2), _ = seq(_diag(gr4(CLOSED)), _diag(gr4(OPEN)))
    c = r2["candidates"][0]
    assert an.revalidate(c, NOW) == []
    assert "deadline_invalid" in an.revalidate(dict(c, deadline=""), NOW)
    after = NOW + timedelta(days=3)
    assert an.dispatch([c], now=after)[0]["status"] == an.BLOCKED


def test_dry_run_never_calls_sender():
    called = []
    res = an.dispatch([_cand()], now=NOW, dry_run=True, sender=lambda c, k: called.append(k))
    assert res[0]["status"] == an.PLANNED and called == []
    res = an.dispatch([_cand()], now=NOW, dry_run=False, sender=lambda c, k: called.append(k))
    assert res[0]["status"] == an.SENT and len(called) == 1       # 否定の対照: dry-run でなければ呼ぶ


def test_not_dry_run_without_sender_does_not_send():
    res = an.dispatch([_cand()], now=NOW, dry_run=False, sender=None)
    assert res[0]["status"] == an.NOT_CONFIGURED


def test_is_dry_run_default():
    assert an.is_dry_run({}) and an.is_dry_run({"NOTIFICATION_DRY_RUN": "true"})
    assert not an.is_dry_run({"NOTIFICATION_DRY_RUN": "false"})


@pytest.mark.parametrize("status,attempts,final", [(None, 3, an.FAILED), (429, 3, an.FAILED), (503, 3, an.FAILED),
                                                    (400, 1, an.FAILED)])
def test_retry_semantics(status, attempts, final):
    keys = []

    def sender(c, k):
        keys.append(k)
        raise an.SendError(status)
    r = an.dispatch([_cand()], now=NOW, dry_run=False, sender=sender)[0]
    assert (r["status"], r["attempts"]) == (final, attempts)
    assert len(set(keys)) == 1                     # 再試行は同じ識別子（受け側で重ねない）


def test_retry_then_success():
    n = []

    def sender(c, k):
        n.append(k)
        if len(n) < 2:
            raise an.SendError(429)
    r = an.dispatch([_cand()], now=NOW, dry_run=False, sender=sender)[0]
    assert r["status"] == an.SENT and r["attempts"] == 2


def test_failure_keeps_candidate_and_does_not_mark_sent():
    """送信の失敗は通知済みにしない（次の実行で出し直す）。成功した後は出さない（重複しない）。"""
    st = {}
    _r, st = an.run(_diag(ps5("OUT_OF_STOCK")), st, now=NOW)

    def fail(c, k):
        raise an.SendError(503)
    r1, st = an.run(_diag(ps5()), st, now=NOW, dry_run=False, sender=fail)
    assert r1["dispatch_failed"] == 1 and r1["candidates"] and st["prod_ps5_pro"]["notified_key"] == ""
    sent = []
    r2, st = an.run(_diag(ps5()), st, now=NOW, dry_run=False, sender=lambda c, k: sent.append(k))
    assert r2["dispatch_sent"] == 1 and len(sent) == 1
    r3, st = an.run(_diag(ps5()), st, now=NOW, dry_run=False, sender=lambda c, k: sent.append(k))
    assert r3["notification_candidates"] == 0 and len(sent) == 1


def test_blocked_candidate_is_not_marked():
    st = {"prod_ps5_pro": {"availability": "OUT_OF_STOCK", "notified_key": ""}}
    late = NOW + timedelta(hours=5)        # 判定は NOW、配信は期限の後
    cands, _s, nxt = an.detect(_diag(ps5())["actionability"]["products"], st, now=NOW)
    res = an.dispatch(cands, now=late)
    assert res[0]["status"] == an.BLOCKED
    assert an.apply_results(nxt, res, late)["prod_ps5_pro"]["notified_key"] == ""


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
    assert len(hist["runs"]) == 3 and hist["runs"][1]["candidates"][0]["dispatch_status"] == an.PLANNED
    st = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert st["products"]["prod_ps5_pro"]["notified_key"]


def test_admin_shows_counts_without_keys():
    from src.content.ui import admin
    (_r1, r2), _ = seq(_diag(ps5("OUT_OF_STOCK")), _diag(ps5()))
    a = admin.build_actionable_notices(r2)
    html = admin._act_notices(a)
    assert "dry-run" in html and "PlayStation 5 Pro" in html and "購入可能になりました" in html
    assert "::" not in html and SONY not in html             # 重複の抑制の識別子・URL は出さない
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
    assert st["prod_ps5_pro"]["availability"] == an.NOT_CONFIRMED
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
    st = {"prod_ps5_pro": {"availability": "OUT_OF_STOCK", "notified_key": ""}}
    r, st2 = run(_diag(ps5()), st, dispatch_now=NOW + timedelta(hours=3))
    assert r["notification_candidates"] == 1 and r["dispatch_blocked"] == 1 and r["dispatch_planned"] == 0
    assert st2["prod_ps5_pro"]["notified_key"] == ""            # 止めたものは通知済みにしない
    r, _ = run(_diag(ps5()), st, dispatch_now=NOW - timedelta(hours=1))   # 生成より前の時刻は使わない
    assert r["dispatch_planned"] == 1


def test_nan_profit_is_not_notified():
    st = {"prod_ps5_pro": {"availability": "OUT_OF_STOCK", "notified_key": ""}}
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
    monkeypatch.setattr(an, "run", boom)
    assert g._write_actionable_notifications(_diag(ps5()), NOW) is None
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["failed"] is True and latest["dispatch_sent"] == 0
    assert (tmp_path / "state.json").read_text(encoding="utf-8") == before


def test_report_links_to_diagnostics():
    d = dict(_diag(ps5()), generated_at="2026-10-09T12:00:00+09:00")
    r, _ = run(d, None)
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
    st = {"prod_gr4_hdf": {"availability": "OUT_OF_STOCK", "notified_key": ""}}
    stock_view = _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock="IN_STOCK",
                                                    stock_checked_at=NOW - timedelta(minutes=10), buy_url=RICOH,
                                                    now=NOW))
    r, st = run(_diag(stock_view), st)
    assert r["dispatch_planned"] == 1
    r, st = run(_diag(gr4(OPEN)), st, dispatch_now=NOW + timedelta(days=3))    # 新しい受付・配信の時点で期限切れ
    assert r["dispatch_blocked"] == 1
    r, st = run(_diag(gr4(OPEN)), st)                                           # 次の実行では有効
    assert r["notification_candidates"] == 1 and r["dispatch_planned"] == 1
    r, st = run(_diag(gr4(OPEN)), st)
    assert r["notification_candidates"] == 0                                    # 否定の対照: 届いた後は出さない


def test_send_failure_retried_with_sender():
    st = {"prod_gr4_hdf": {"availability": "OUT_OF_STOCK", "notified_key": ""}}
    stock_view = _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock="IN_STOCK",
                                                    stock_checked_at=NOW - timedelta(minutes=10), buy_url=RICOH,
                                                    now=NOW))
    sent = []
    r, st = run(_diag(stock_view), st, dry_run=False, sender=lambda c, k: sent.append(k))

    def fail(c, k):
        raise an.SendError(503)
    r, st = run(_diag(gr4(OPEN)), st, dry_run=False, sender=fail)
    assert r["dispatch_failed"] == 1
    r, st = run(_diag(gr4(OPEN)), st, dry_run=False, sender=lambda c, k: sent.append(k))
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
    st = {"prod_gr4_hdf": {"availability": "OUT_OF_STOCK", "notified_key": ""}}
    counts = []
    for d in (_diag(gr4(OPEN)), _diag(stock_view), _diag(gr4(OPEN)), _diag(gr4(nxt))):
        r, st = run(d, st)
        counts.append(r["notification_candidates"])
    assert counts == [1, 1, 0, 1]
    assert len(st["prod_gr4_hdf"]["notified_events"]) == 2


def test_notified_events_expire_after_deadline():
    st = {"prod_gr4_hdf": {"availability": "OUT_OF_STOCK", "notified_key": ""}}
    _r, st = run(_diag(gr4(OPEN)), st)
    assert st["prod_gr4_hdf"]["notified_events"]
    later = NOW + timedelta(days=5)                     # OPEN の締切の後
    _r, st = run(_diag(ps5("OUT_OF_STOCK", now=later)), st, now=later)
    _r, st = run(_diag(gr4(CLOSED, now=later)), st, now=later)
    assert st["prod_gr4_hdf"]["notified_events"] == []



def _stock_gr4():
    return _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock="IN_STOCK",
                                              stock_checked_at=NOW - timedelta(minutes=10), buy_url=RICOH, now=NOW))


def test_lottery_and_stock_flapping_does_not_repeat():
    """抽選 E1 と在庫ありを行き来しても、どちらも2回目は出さない（監査 M-1・レビュー H-1）。"""
    st = {"prod_gr4_hdf": {"availability": "OUT_OF_STOCK", "notified_key": ""}}
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
    """前の形式の台帳（notified_events が無い）でも、通知済みの受付をもう一度出さない（監査 L-2）。"""
    r0, _ = run(_diag(gr4(OPEN)), {"prod_gr4_hdf": {"availability": "OUT_OF_STOCK", "notified_key": ""}})
    old = {"prod_gr4_hdf": {"availability": "LOTTERY_OPEN", "actionable": True,
                            "notified_key": r0["candidates"][0]["dedupe_key"]}}
    counts = []
    for d in (_diag(_stock_gr4()), _diag(gr4(OPEN))):
        r, old = run(d, old)
        counts.append(r["dispatch_planned"])
    assert counts == [1, 0]


def test_live_events_drops_malformed():
    e1 = "prod_gr4_hdf|2026-10-08T12:00+09:00|2026-10-11T12:00+09:00"
    assert an._live_events([e1, "p|x|", "junk", 5], NOW) == [e1]
    assert an._live_events([e1], NOW + timedelta(days=5)) == []
