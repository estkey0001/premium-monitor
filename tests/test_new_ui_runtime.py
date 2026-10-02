"""新UIの抽選の閲覧時の状態（runtime state）のテスト。

- 固定時刻で状態の移り変わり・ボタン・件数・並び順を確かめる
- Python の derive_runtime_state と、ブラウザ側の deriveLotteryRuntimeState（node で実行）が
  同じ結果を返すことを、多数の時刻で確かめる
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.content.ui import home, parity
from src.content.ui import runtime as rt
from src.tcg.lottery.schema import compute_lottery_status
from src.tcg.models import JST

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=JST)
PCO = "https://www.pokemoncenter-online.com"
ROOT = Path(__file__).resolve().parent.parent


def _iso(delta: timedelta, base: datetime = NOW) -> str:
    return (base + delta).isoformat()


def _ev(**kw) -> dict:
    ev = {"tcg": "POKEMON", "product_name": "テストBOX", "retailer_name": "ポケモンセンターオンライン",
          "status": "OPEN", "source_url": f"{PCO}/news/1", "entry_url": f"{PCO}/lottery/1",
          "verified": True, "confidence": "high", "lottery_id": "lot-x"}
    ev.update(kw)
    return ev


def _vm(**kw) -> dict:
    return rt.tcg_vm(_ev(**kw), 0)


def _st(vm, t: datetime) -> dict:
    return rt.derive_runtime_state(vm, t)


# ── 状態の移り変わり（固定時刻） ───────────────────────────────────────

def test_upcoming_to_open_to_ending_to_closed():
    start, end = NOW + timedelta(hours=1), NOW + timedelta(days=2)
    vm = _vm(application_start=start.isoformat(), application_end=end.isoformat())
    seq = [
        (start - timedelta(minutes=1), "UPCOMING", "info"),
        (start, "OPEN", "apply"),
        (end - timedelta(hours=24, minutes=1), "OPEN", "apply"),
        (end - timedelta(hours=24), "ENDING_SOON", "apply"),
        (end - timedelta(seconds=1), "ENDING_SOON", "apply"),
        (end, "CLOSED", "info"),
    ]
    for t, status, cta in seq:
        s = _st(vm, t)
        assert (s["status"], s["cta"]["kind"]) == (status, cta), t
    # 締切を過ぎたら件数・並び順からも外れる
    before, after = _st(vm, end - timedelta(minutes=1)), _st(vm, end)
    assert before["open"] and before["bucket"] == rt.BUCKET_ENDING
    assert not after["open"] and after["bucket"] == rt.BUCKET_HIDDEN


def test_winner_purchase_to_ended():
    vm = _vm(application_start=_iso(-timedelta(days=10)), application_end=_iso(-timedelta(days=5)),
             purchase_start=_iso(-timedelta(days=1)), purchase_end=_iso(timedelta(hours=3)),
             purchase_url=f"{PCO}/purchase/1")
    s = _st(vm, NOW)
    assert s["status"] == "WINNER_PURCHASE_PERIOD"
    assert s["cta"]["kind"] == "purchase" and "当選者のみ" in s["cta"]["label"]
    assert s["cd_text"] == "購入期限まで あと3時間"
    s = _st(vm, NOW + timedelta(hours=3))
    assert s["status"] == "ENDED" and s["cta"]["kind"] == "info"


def test_source_conflict_never_becomes_open():
    vm = _vm(conflict=True, application_start=_iso(-timedelta(days=1)),
             application_end=_iso(timedelta(days=1)))
    for h in range(-48, 72, 3):
        s = _st(vm, NOW + timedelta(hours=h))
        assert s["status"] == "SOURCE_CONFLICT"
        assert s["cta"] is None or s["cta"]["kind"] == "info"
        # 受付中には数えないが、存在に気づけるよう HOME には出す
        assert not s["open"] and s["bucket"] == rt.BUCKET_CONFLICT


def test_date_only_values_never_get_time():
    vm = _vm(application_start=None, application_start_date="2026-10-02",
             application_end=None, application_end_date="2026-10-05")
    # 開始日当日は時刻が分からないので、まだ開始前（受付中と言わない）
    s = _st(vm, datetime(2026, 10, 2, 23, 59, tzinfo=JST))
    assert s["status"] == "UPCOMING" and s["cta"]["kind"] == "info"
    assert s["when"] == "10/2(金) 開始・時刻未公表" and s["cd_text"] == ""
    assert s["starting_24h"]
    s = _st(vm, datetime(2026, 10, 3, 0, 0, tzinfo=JST))
    assert s["status"] == "OPEN" and s["cta"]["kind"] == "apply"
    # 締切日当日は締切間近。締切前と言い切れないので「応募する」は出さない
    s = _st(vm, datetime(2026, 10, 5, 0, 0, tzinfo=JST))
    assert s["status"] == "ENDING_SOON" and s["cta"]["kind"] == "info"
    assert "時刻未公表" in s["when"] and "23:59" not in s["when"] and "00:00" not in s["when"]
    assert s["ending_today"]
    s = _st(vm, datetime(2026, 10, 6, 0, 0, tzinfo=JST))
    assert s["status"] == "CLOSED"


def test_unknown_start_no_apply():
    vm = _vm(application_start=None, application_end=_iso(timedelta(days=3)))
    s = _st(vm, NOW)
    assert s["status"] == "OPEN" and s["cta"]["kind"] == "info"


def test_timezone_preserved():
    vm = _vm(application_start="2026-10-01T03:00:00Z", application_end="2026-10-05T07:59:00Z")
    assert vm["ae"] == "2026-10-05T16:59:00+09:00"
    s = _st(vm, NOW)
    assert s["when"] == "10/5(月) 16:59 締切"
    s = rt.derive_runtime_state(vm, datetime(2026, 10, 5, 7, 58, tzinfo=timezone.utc))
    assert s["status"] == "ENDING_SOON" and s["cd_text"] == "締切まで あと1分"


def test_countdown_format():
    assert rt.countdown_text(2 * 86_400_000 + 5, 0) == "2日"
    assert rt.countdown_text(6 * 3_600_000 + 5, 0) == "6時間"
    assert rt.countdown_text(52 * 60_000 + 5, 0) == "52分"
    assert rt.countdown_text(10_000, 0) == "1分"
    assert rt.countdown_text(0, 0) == ""


# ── URL の安全性 ─────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,x", "vbscript:x",
    "http://www.pokemoncenter-online.com/lottery", "", None, "https://evil.example.com/x",
    "https://www.pokemoncenter-online.com.evil.com/x", "https://www.pokemoncenter-online.com/a b",
])
def test_unsafe_or_unofficial_apply_url_rejected(url):
    vm = _vm(entry_url=url, application_start=_iso(-timedelta(days=1)),
             application_end=_iso(timedelta(days=3)))
    assert vm["apply"] == ""
    s = _st(vm, NOW)
    assert s["cta"]["kind"] != "apply"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:x", "vbscript:x", "http://x.com/"])
def test_unsafe_info_url_not_linked(url):
    vm = _vm(source_url=url, entry_url=None, status="UPCOMING",
             application_start=_iso(timedelta(hours=3)), application_end=_iso(timedelta(days=3)))
    assert vm["info"] == "" and _st(vm, NOW)["cta"] is None


def test_closed_and_ended_have_no_action_cta():
    for kw in ({"application_start": _iso(-timedelta(days=5)), "application_end": _iso(-timedelta(days=1))},
               {"application_start": _iso(-timedelta(days=60)), "application_end": _iso(-timedelta(days=50))}):
        s = _st(_vm(**kw), NOW)
        assert s["status"] in ("CLOSED", "ENDED")
        assert s["cta"]["kind"] == "info" and s["cta"]["style"] == "secondary"


# ── 重複・旧来の抽選 ──────────────────────────────────────────────

def test_legacy_lottery_appears_once():
    report = {"lotteries": [_ev(product_name="Nintendo Switch 2 限定モデル", lottery_id="lot-a")]}
    legacy = [{"id": "l1", "product_name": "Nintendo Switch 2 限定モデル", "brand": "Nintendo"},
              {"id": "l2", "product_name": "RICOH GR IV", "brand": "RICOH",
               "entry_start_at": "2026-10-01 10:00", "entry_end_at": "2026-10-04 10:00",
               "url": "https://www.ricoh-imaging.co.jp/x", "entry_form_url": "https://www.ricoh-imaging.co.jp/f"},
              {"id": "l3", "product_name": "参考", "reference_only": True}]
    vms = rt.build_vms(report, legacy)
    assert [v["id"] for v in vms] == ["lot-a", "l2"]
    s = _st(vms[1], NOW)
    assert s["status"] == "OPEN" and s["cta"]["kind"] == "apply"
    assert vms[1]["ae"] == "2026-10-04T10:00:00+09:00"


def test_legacy_date_only_not_given_time():
    vm = rt.legacy_vm({"product_name": "x", "entry_end_at": "2026-10-03"}, 0)
    assert vm["ae"] == "" and vm["aed"] == "2026-10-03"


# ── HOME の件数・並び順が閲覧時刻で変わる ─────────────────────────────

def test_home_counts_and_order_change_with_time():
    end = NOW + timedelta(minutes=30)
    report = {"lotteries": [
        _ev(lottery_id="soon", application_start=_iso(-timedelta(days=1)), application_end=end.isoformat()),
        _ev(lottery_id="up", status="UPCOMING", application_start=_iso(timedelta(minutes=10)),
            application_end=_iso(timedelta(days=3))),
    ]}

    def model(t):
        return home.build_home_model(tcg_report=report, opportunities={}, profit_routes={},
                                     legacy_lotteries=[], now=t)
    m0 = model(NOW)
    assert m0.counts["lottery_open"] == 1 and m0.counts["starting_24h"] == 1
    assert [r[4]["id"] for r in m0.actions] == ["soon", "up"]
    m1 = model(NOW + timedelta(minutes=10))     # up が受付開始
    assert m1.counts["lottery_open"] == 2 and m1.counts["starting_24h"] == 0
    assert [r[4]["id"] for r in m1.actions] == ["soon", "up"]
    m2 = model(end)                              # soon が締切
    assert m2.counts["lottery_open"] == 1 and m2.counts["ending_today"] == 0
    assert [r[4]["id"] for r in m2.actions] == ["up"]
    assert m2.states["soon"]["cta"]["kind"] == "info"


# ── Python と JS の一致 ────────────────────────────────────────────

_NODE = shutil.which("node")


def _js_states(vms: list[dict], nows_ms: list[int]) -> list[list[dict]]:
    harness = (
        "const R = require(process.argv[1]);"
        "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{"
        "const x=JSON.parse(s);"
        "const out=x.nows.map(n=>x.vms.map(v=>R.deriveLotteryRuntimeState(v,n,x.cfg)));"
        "process.stdout.write(JSON.stringify(out));});"
    )
    res = subprocess.run([_NODE, "-e", harness, str(rt.JS_PATH)],
                         input=json.dumps({"vms": vms, "nows": nows_ms, "cfg": rt.config()}),
                         capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def _fixture_vms() -> list[dict]:
    evs = [
        dict(application_start=_iso(timedelta(hours=1)), application_end=_iso(timedelta(days=2))),
        dict(application_start=None, application_start_date="2026-10-02",
             application_end=None, application_end_date="2026-10-04"),
        dict(application_start=_iso(-timedelta(days=3)), application_end=_iso(-timedelta(hours=2)),
             winner_announcement_at=_iso(timedelta(days=1)), purchase_start=_iso(timedelta(days=2)),
             purchase_end=_iso(timedelta(days=4)), purchase_url=f"{PCO}/p", result_url=f"{PCO}/r"),
        dict(application_start=_iso(-timedelta(days=3)), application_end=_iso(-timedelta(hours=2)),
             winner_announcement_date="2026-10-03"),
        dict(application_start=_iso(-timedelta(days=1)), application_end=None),
        dict(conflict=True, application_start=_iso(-timedelta(days=1)), application_end=_iso(timedelta(days=1))),
        dict(announcement_only=True),
        dict(application_start=_iso(-timedelta(days=1)), application_end=_iso(timedelta(hours=5)),
             entry_url="javascript:alert(1)"),
        dict(application_start=_iso(-timedelta(days=30)), application_end=_iso(-timedelta(days=20))),
        dict(application_start="2026-10-01T03:00:00Z", application_end="2026-10-05T07:59:00Z",
             source_url="https://example.com/n"),
    ]
    vms = [rt.tcg_vm(_ev(lottery_id=f"lot-{i}", **kw), i) for i, kw in enumerate(evs)]
    vms.append(rt.legacy_vm({"id": "lg", "product_name": "GR", "entry_start_at": "2026-10-02 12:00",
                             "entry_end_at": "2026-10-03", "url": "https://www.ricoh-imaging.co.jp/"}, 0))
    return vms


def _nows(vms) -> list[datetime]:
    nows = [NOW + timedelta(minutes=30 * k) for k in range(-200, 400)]
    # 各日時・日付の境目の前後
    for vm in vms:
        for short, _key in rt.TIME_KEYS:
            v = vm.get(short)
            if not v:
                continue
            t = datetime.fromisoformat(v) if "T" in v else datetime.fromisoformat(v + "T00:00:00+09:00")
            for d in (timedelta(0), timedelta(milliseconds=-1), timedelta(days=1),
                      timedelta(days=1, milliseconds=-1), timedelta(hours=-24), timedelta(days=14)):
                nows.append(t + d)
    return nows


@pytest.mark.skipif(_NODE is None, reason="node が無い")
def test_python_and_js_runtime_state_identical():
    vms = _fixture_vms()
    nows = _nows(vms)
    js = _js_states(vms, [rt._ms(t) for t in nows])
    for t, row in zip(nows, js):
        for vm, j in zip(vms, row):
            p = rt.derive_runtime_state(vm, t)
            assert p == j, (vm["id"], t.isoformat(), p, j)


@pytest.mark.skipif(_NODE is None, reason="node が無い")
def test_python_and_js_on_real_exports():
    p = ROOT / "exports" / "tcg" / "latest.json"
    if not p.exists():
        pytest.skip("exports/tcg/latest.json が無い")
    vms = rt.build_vms(json.loads(p.read_text(encoding="utf-8")), [])
    nows = _nows(vms)[::7]
    js = _js_states(vms, [rt._ms(t) for t in nows])
    for t, row in zip(nows, js):
        for vm, j in zip(vms, row):
            assert rt.derive_runtime_state(vm, t) == j, (vm["id"], t.isoformat())


def test_derive_matches_export_status_at_export_time():
    """exports の生成時刻で判定し直すと、exports の状態と同じになる（VM 変換の誤りが無い）。"""
    p = ROOT / "exports" / "tcg" / "latest.json"
    if not p.exists():
        pytest.skip("exports/tcg/latest.json が無い")
    report = json.loads(p.read_text(encoding="utf-8"))
    at = datetime.fromisoformat(report["generated_at"])
    lots = [e for e in report["lotteries"] if e.get("status") != "ENDED"]
    for i, e in enumerate(lots):
        s = rt.derive_runtime_state(rt.tcg_vm(e, i), at)["status"]
        expected = "SOURCE_CONFLICT" if e.get("conflict") else e["status"]
        assert s == expected, e.get("product_name")
        assert compute_lottery_status(e, at) == e["status"]


# ── 新旧の件数照合 ─────────────────────────────────────────────────

def _render_lp(monkeypatch, report, *, legacy=None, lp_time=None):
    import yaml

    from src.content.daily_lp_generator import DailyLPGenerator
    monkeypatch.setattr(DailyLPGenerator, "_load_tcg_report", staticmethod(lambda: report))

    class Repo:
        def __getattr__(self, name):
            if name == "list_lottery_events":
                return lambda *a, **k: list(legacy or [])
            return lambda *a, **k: []
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    with open(ROOT / "config" / "lp_settings.yaml", encoding="utf-8") as f:
        g.settings = yaml.safe_load(f) or {}
    g.repo = Repo()
    return g._render_page(
        date_str="2026-10-02", time_str="10:00", latest_buyback_at=None, latest_deals_at=None,
        lp_generated_at=lp_time or datetime(2026, 10, 2, 10, 0), beginner_easy=[], beginner_watch=[],
        advanced_deals=[], advanced_snaps=[], watch_candidates=[], buyback_alerts=[],
        all_deals=[], iphone_deals=[], game_deals=[])


def _parity_rows(html):
    import re
    root = html[html.index('<div id="new-ui-root"'):html.index("<!-- /new-ui-root -->")]
    return dict(re.findall(r'data-parity="([^"]+)" data-match="([01])"', root))


def _fixture_report(at: datetime) -> dict:
    def e(i, **kw):
        ev = _ev(lottery_id=f"lot-{i}", product_name=f"商品{i}", **kw)
        ev["status"] = compute_lottery_status(ev, at)   # exports と同じ判定（conflict は別の印）
        return ev
    return {"generated_at": at.isoformat(), "lotteries": [
        e(1, application_start=_iso(-timedelta(days=1), at), application_end=_iso(timedelta(days=3), at)),
        e(2, application_start=_iso(-timedelta(days=1), at), application_end=_iso(timedelta(hours=3), at)),
        e(3, application_start=_iso(timedelta(hours=1), at), application_end=_iso(timedelta(days=3), at)),
        e(4, conflict=True, application_start=_iso(-timedelta(days=1), at),
          application_end=_iso(timedelta(days=2), at)),
        e(5, application_start=_iso(-timedelta(days=5), at), application_end=_iso(-timedelta(days=1), at)),
        e(6, announcement_only=True),
    ]}


def test_parity_with_old_ui_rendered_counts(monkeypatch):
    # LP 生成（10:00）より前に exports が作られた場合。AI Opportunities は新旧とも実ファイル
    report = _fixture_report(datetime(2026, 10, 2, 8, 30, tzinfo=JST))
    html = _render_lp(monkeypatch, report)
    rows = _parity_rows(html)
    assert set(rows) == {"lottery_total", "OPEN", "ENDING_SOON", "UPCOMING", "SOURCE_CONFLICT",
                         "vm_fields", "legacy_open", "buy", "opportunities"}
    assert all(v == "1" for v in rows.values()), rows
    old = parity.old_ui_counts_from_html(html)
    assert old["found_lottery_section"] == 1
    assert (old["OPEN"], old["ENDING_SOON"], old["UPCOMING"], old["SOURCE_CONFLICT"],
            old["AFTER"], old["ANNOUNCEMENT"]) == (1, 1, 1, 1, 1, 1)


def test_parity_runtime_difference_is_explained(monkeypatch):
    """exports の後に受付が始まった抽選は「時刻」の差として説明され、不一致にならない。"""
    at = datetime(2026, 10, 2, 8, 30, tzinfo=JST)
    report = {"generated_at": at.isoformat(), "lotteries": [
        _ev(lottery_id="a", product_name="A", status="UPCOMING",
            application_start=_iso(timedelta(minutes=30), at), application_end=_iso(timedelta(days=3), at))]}
    html = _render_lp(monkeypatch, report)     # LP は 10:00（受付開始後）
    import re
    root = html[html.index('<div id="new-ui-root"'):html.index("<!-- /new-ui-root -->")]
    row = re.search(r'data-parity="OPEN" data-match="1"><td>[^<]*</td><td>0</td><td>1</td><td>\+1</td>', root)
    assert row, "OPEN: 旧UI 0 / 新UI 1 / 時刻 +1 で一致扱い"


def test_parity_guard_difference_is_explained():
    class M:
        vms, states = [], {}
        opp_cards = [home.Action(action="BUY", title="A"), home.Action(action="WAIT", title="C")]
        hidden_prices, alert_count = 1, 1
    rows = {r["key"]: r for r in parity.build(M, {}, {"buy": 2, "opportunities": 4})}
    assert rows["buy"]["unexplained"] == 0 and rows["buy"]["guard"] == -1
    assert rows["opportunities"]["unexplained"] == 0
    rows = {r["key"]: r for r in parity.build(M, {}, {"buy": 3, "opportunities": 4})}
    assert rows["buy"]["unexplained"] != 0


def test_parity_detects_conversion_bug(monkeypatch):
    """VM への変換で締切が落ちるような誤りがあると、照合が不一致になる。"""
    report = _fixture_report(datetime(2026, 10, 2, 9, 0, tzinfo=JST))
    orig = rt.tcg_vm

    def broken(ev, idx):
        vm = orig(ev, idx)
        vm["ae"] = ""
        return vm
    monkeypatch.setattr(rt, "tcg_vm", broken)
    rows = _parity_rows(_render_lp(monkeypatch, report))
    assert "0" in rows.values()


def test_generation_time_naive_is_local_time(monkeypatch):
    """CI（UTC）で datetime.now() の値を JST とみなさない。"""
    import os
    import time

    from src.content.daily_lp_generator import DailyLPGenerator
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        got = DailyLPGenerator._nu_now(datetime(2026, 10, 2, 3, 0))     # UTC 03:00
        assert got == datetime(2026, 10, 2, 12, 0, tzinfo=JST)
    finally:
        monkeypatch.delenv("TZ")
        os.environ.pop("TZ", None)
        time.tzset()


# ── 再レビューの指摘（M-1〜M-4・L-1〜L-4）の回帰テスト ─────────────────────

@pytest.mark.parametrize("url", [
    "https://evil.com\\.pokemoncenter-online.com/x",
    "https://evil.com\\@www.pokemoncenter-online.com/x",
    "https://evil.com%5C.pokemoncenter-online.com/x",
    "https://user@www.pokemoncenter-online.com/x",
    "https://www.pokemoncenter-online.com:8443/x",
    "https://www.pokemoncenter-online.com/ｘ　",
    "https://[::1", "https://a]b.com/", "https://[::1]@pokemon-card.com/",
])
def test_url_parser_differential_rejected(url):
    vm = _vm(entry_url=url, source_url=url, application_start=_iso(-timedelta(days=1)),
             application_end=_iso(timedelta(days=3)))       # 例外にならない（L-2）
    assert vm["apply"] == "" and vm["info"] == ""


def test_date_only_value_in_exact_field_kept_as_date():
    vm = _vm(application_start="2026-10-01", application_end="2026-10-05")
    assert (vm["as"], vm["asd"], vm["ae"], vm["aed"]) == ("", "2026-10-01", "", "2026-10-05")
    assert _st(vm, NOW)["status"] == "OPEN"


def test_legacy_same_product_different_store_kept():
    legacy = [{"id": "a", "product_name": "RICOH GR IV", "entry_start_at": "2026-10-01 10:00",
               "entry_end_at": "2026-10-05 10:00"},
              {"id": "b", "product_name": "RICOH GR IV", "entry_start_at": "2026-10-03 10:00",
               "entry_end_at": "2026-10-08 10:00"}]
    assert [v["id"] for v in rt.build_vms({}, legacy)] == ["a", "b"]


def test_infinite_values_do_not_break_home():
    o = {"product": "X", "action": "BUY", "kind": "main", "confidence": "high", "priority": 1,
         "buy_price": 100, "sell_price": float("inf"), "net_profit": float("inf"), "roi": 0.5,
         "buy_price_evidence": "VERIFIED_CURRENT", "sell_price_evidence": "VERIFIED_CURRENT", "sell_canonical_type": "BUYBACK_CASH"}
    m = home.build_home_model(tcg_report={}, opportunities={"todays_opportunities": [o]},
                              profit_routes={}, legacy_lotteries=[], now=NOW)
    assert m.hidden_prices == 1


def test_unconfirmed_manual_never_apply():
    vm = _vm(collection_method="MANUAL_VERIFIED", verified=False, confidence="medium",
             application_start=_iso(-timedelta(days=1)), application_end=_iso(timedelta(days=3)))
    s = _st(vm, NOW)
    assert s["status"] == "OPEN" and s["cta"]["kind"] == "info"


def test_conflict_shown_in_home():
    report = {"lotteries": [_ev(lottery_id="c", conflict=True, application_start=_iso(-timedelta(days=1)),
                                application_end=_iso(timedelta(days=2)))]}
    m = home.build_home_model(tcg_report=report, opportunities={}, profit_routes={},
                              legacy_lotteries=[], now=NOW)
    assert [r[4]["id"] for r in m.actions] == ["c"] and m.counts["lottery_open"] == 0
    html = home.render_home(m)
    assert "日程要確認" in html and "応募する" not in html


@pytest.mark.parametrize("mutate", [
    lambda vm: vm.update(ae=_iso(timedelta(hours=9), datetime.fromisoformat(vm["ae"]))) if vm["ae"] else None,
    lambda vm: vm.update(ae=_iso(timedelta(hours=1), datetime.fromisoformat(vm["ae"]))) if vm["ae"] else None,
    lambda vm: vm.update(apply=""),
    lambda vm: vm.update(apply="https://evil.example.com/x") if vm["apply"] else None,
    lambda vm: vm.update(conflict=not vm["conflict"]),
])
def test_parity_detects_mutations(monkeypatch, mutate):
    report = _fixture_report(datetime(2026, 10, 2, 9, 0, tzinfo=JST))
    orig = rt.tcg_vm

    def broken(ev, idx):
        vm = orig(ev, idx)
        mutate(vm)
        return vm
    monkeypatch.setattr(rt, "tcg_vm", broken)
    rows = _parity_rows(_render_lp(monkeypatch, report))
    assert rows.get("vm_fields") == "0"


@pytest.mark.skipif(_NODE is None, reason="node が無い")
def test_js_next_change_is_nearest_boundary():
    vm = _vm(application_start=_iso(timedelta(minutes=5)), application_end=_iso(timedelta(days=3)))
    harness = ("const R=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d)"
               ".on('end',()=>{const x=JSON.parse(s);process.stdout.write(String("
               "R.nextChange(x.vms,x.now,x.cfg)));});")
    res = subprocess.run([_NODE, "-e", harness, str(rt.JS_PATH)], capture_output=True, text=True,
                         check=True, input=json.dumps({"vms": [vm], "now": rt._ms(NOW),
                                                       "cfg": rt.config()}))
    assert int(res.stdout) == rt._ms(NOW + timedelta(minutes=5))



# ── N-1: 日付だけの値・重複で照合が誤って不一致にならない ─────────────────

def _real_now():
    return datetime.now(JST).replace(microsecond=0)


def _fmt(d):
    return d.strftime("%Y-%m-%d %H:%M")


@pytest.mark.parametrize("item_fn", [
    # 締切が日付だけ（3日後）
    lambda n: {"id": "a", "product_name": "GR A", "status": "active",
               "entry_start_at": _fmt(n - timedelta(days=1)),
               "entry_end_at": (n + timedelta(days=3)).strftime("%Y-%m-%d")},
    # 開始が日付だけ（今日）: 旧UIは受付中、新UIは開始前
    lambda n: {"id": "b", "product_name": "GR B", "status": "active",
               "entry_start_at": n.strftime("%Y-%m-%d"), "entry_end_at": _fmt(n + timedelta(days=3))},
    # 締切が日付だけ（今日）: 旧UIは締切後、新UIは締切間近
    lambda n: {"id": "c", "product_name": "GR C", "status": "active",
               "entry_start_at": _fmt(n - timedelta(days=2)), "entry_end_at": n.strftime("%Y-%m-%d")},
    # 時刻つき（差が出ない）
    lambda n: {"id": "d", "product_name": "GR D", "status": "active",
               "entry_start_at": _fmt(n - timedelta(days=1)), "entry_end_at": _fmt(n + timedelta(days=2))},
    # TCG と同じ商品名（新UIは TCG を優先して外す）
    lambda n: {"id": "e", "product_name": "商品1", "status": "active",
               "entry_start_at": _fmt(n - timedelta(days=1)), "entry_end_at": _fmt(n + timedelta(days=2))},
])
def test_legacy_parity_no_false_alarm(monkeypatch, item_fn):
    n = _real_now()
    report = _fixture_report(n - timedelta(minutes=5))
    rows = _parity_rows(_render_lp(monkeypatch, report, legacy=[item_fn(n)], lp_time=datetime.now()))
    assert rows.get("legacy_open") == "1", rows


def test_legacy_parity_detects_conversion_bug(monkeypatch):
    n = _real_now()
    item = {"id": "d", "product_name": "GR D", "status": "active",
            "entry_start_at": _fmt(n - timedelta(days=1)), "entry_end_at": _fmt(n + timedelta(days=2))}
    orig = rt.legacy_vm

    def broken(it, idx):
        vm = orig(it, idx)
        vm["ae"] = _iso(-timedelta(days=30), n)     # 締切を取り違える
        return vm
    monkeypatch.setattr(rt, "legacy_vm", broken)
    rows = _parity_rows(_render_lp(monkeypatch, _fixture_report(n), legacy=[item], lp_time=datetime.now()))
    assert rows.get("legacy_open") == "0"


def test_tcg_date_in_exact_field_no_false_alarm(monkeypatch):
    """exports の時刻の欄に日付だけの締切があり、締切日当日に exports が作られた場合。"""
    at = datetime(2026, 10, 5, 8, 0, tzinfo=JST)
    ev = _ev(lottery_id="d1", product_name="日付だけ", application_start="2026-10-01",
             application_end="2026-10-05")
    ev["status"] = compute_lottery_status(ev, at)       # exports は 0:00 とみなす（CLOSED）
    report = {"generated_at": at.isoformat(), "lotteries": [ev]}
    rows = _parity_rows(_render_lp(monkeypatch, report, lp_time=datetime(2026, 10, 5, 8, 30)))
    assert all(v == "1" for v in rows.values()), rows


def test_parity_detects_unv_mutation(monkeypatch):
    report = _fixture_report(datetime(2026, 10, 2, 9, 0, tzinfo=JST))
    report["lotteries"][0].update(collection_method="MANUAL_VERIFIED", verified=False)
    orig = rt.tcg_vm

    def broken(ev, idx):
        vm = orig(ev, idx)
        vm["unv"] = False
        return vm
    monkeypatch.setattr(rt, "tcg_vm", broken)
    assert _parity_rows(_render_lp(monkeypatch, report)).get("vm_fields") == "0"


# ── N-4: 旧来の抽選の照合が、変換の誤りを「ガード」に逃がさない ─────────────

def _legacy_items(n):
    return [{"id": "x", "product_name": "GR X", "status": "active",
             "entry_start_at": _fmt(n - timedelta(days=1)), "entry_end_at": _fmt(n + timedelta(days=2))},
            {"id": "y", "product_name": "GR Y", "status": "active",
             "entry_start_at": _fmt(n - timedelta(days=5)), "entry_end_at": _fmt(n - timedelta(days=1))}]


@pytest.mark.parametrize("mutate", [
    lambda vm: vm["ae"] and vm.update(ae=_iso(timedelta(days=30), datetime.fromisoformat(vm["ae"]))),
    lambda vm: vm["as"] and vm.update(asd=vm["as"][:10], **{"as": ""}),       # 開始の時刻を落とす
    lambda vm: vm["ae"] and vm.update(aed=vm["ae"][:10], ae=""),               # 締切の時刻を落とす
    lambda vm: vm["ae"] and vm.update(ae=_iso(timedelta(days=1), datetime.fromisoformat(vm["ae"]))),
])
def test_legacy_parity_catches_vm_mutations(monkeypatch, mutate):
    n = _real_now()
    orig = rt.legacy_vm

    def broken(it, idx):
        vm = orig(it, idx)
        mutate(vm)
        return vm
    monkeypatch.setattr(rt, "legacy_vm", broken)
    rows = _parity_rows(_render_lp(monkeypatch, _fixture_report(n), legacy=_legacy_items(n),
                                   lp_time=datetime.now()))
    assert rows.get("legacy_open") == "0", rows


def test_legacy_parity_catches_dropped_items(monkeypatch):
    n = _real_now()
    orig = rt.build_vms
    monkeypatch.setattr(rt, "build_vms", lambda report, legacy: orig(report, []))
    rows = _parity_rows(_render_lp(monkeypatch, _fixture_report(n), legacy=_legacy_items(n),
                                   lp_time=datetime.now()))
    assert rows.get("legacy_open") == "0", rows


def test_parity_detects_info_mutation(monkeypatch):
    report = _fixture_report(datetime(2026, 10, 2, 9, 0, tzinfo=JST))
    orig = rt.tcg_vm

    def broken(ev, idx):
        vm = orig(ev, idx)
        vm["info"] = "https://evil.example.com/x"
        return vm
    monkeypatch.setattr(rt, "tcg_vm", broken)
    assert _parity_rows(_render_lp(monkeypatch, report)).get("vm_fields") == "0"



@pytest.mark.parametrize("mutate", [
    lambda vm: vm.update(apply="https://evil.example.com/x"),
    lambda vm: vm.update(info="https://evil.example.com/x"),
    lambda vm: vm.update(wa=_iso(timedelta(hours=9))),
])
def test_legacy_parity_catches_url_and_result_mutations(monkeypatch, mutate):
    n = _real_now()
    items = _legacy_items(n)
    items[0].update(entry_form_url="https://www.ricoh-imaging.co.jp/form",
                    url="https://www.ricoh-imaging.co.jp/info",
                    result_announcement_at=_fmt(n + timedelta(days=5)))
    orig = rt.legacy_vm

    def broken(it, idx):
        vm = orig(it, idx)
        if it.get("id") == "x":
            mutate(vm)
        return vm
    monkeypatch.setattr(rt, "legacy_vm", broken)
    rows = _parity_rows(_render_lp(monkeypatch, _fixture_report(n), legacy=items, lp_time=datetime.now()))
    assert rows.get("legacy_open") == "0", rows


def test_legacy_parity_urls_ok(monkeypatch):
    n = _real_now()
    items = _legacy_items(n)
    items[0].update(entry_form_url="https://www.ricoh-imaging.co.jp/form",
                    url="https://www.ricoh-imaging.co.jp/info",
                    result_announcement_at=_fmt(n + timedelta(days=5)))
    rows = _parity_rows(_render_lp(monkeypatch, _fixture_report(n), legacy=items, lp_time=datetime.now()))
    assert rows.get("legacy_open") == "1", rows
