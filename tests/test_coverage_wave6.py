"""Market Research Coverage Wave 6: 実行をまたぐ台帳・買取の勢い・検知の遅れの測定・TCG 収集の並列化と同一 run のキャッシュ。

通信はしない（合成の値と偽の取得だけ）。台帳は「前回の run から引き継げたとき」だけ意味を持つ。勢い・first_seen を、引き継げていない日に作らない。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.collectors.tcg import runcache
from src.research import candidates as rc
from src.research import retail_lookup as rl
from src.research import signals as sg
from src.research import triage as tr
from src.tcg import collection_metrics as cm
from src.tcg import detection_delay as dd
from src.tcg import profit_dense as pdn

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=JST)
FRESH = "2026-10-30T10:00:00+09:00"
PREV_AT = "2026-10-29T10:00:00+09:00"


# ── 台帳（実行をまたいだ復元・同一 run の再利用・壊れ・鍵なし・短い鍵）─────────────────────

def _state(run_id, cands=None, **extra):
    return {"schema": 1, "run_id": run_id, "candidates": cands if cands is not None else {}, **extra}


def test_ledger_restored_across_runs_but_reused_within_the_same_run():
    raw = _state("gh-1-1", {"dp_a": {"discovered_at": "x"}})
    assert rc.classify_ledger(raw, "gh-2-1", True)[0] == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN        # 別の run の台帳 = 引き継いだ
    assert rc.classify_ledger(raw, "gh-1-1", True)[0] == rc.LEDGER_REUSED_WITHIN_RUN                 # 同じ run の再生成 = 引き継ぎではない
    assert rc.classify_ledger(raw, "gh-1-2", True)[0] == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN        # 同じ run の再試行（attempt 違い）は別の run
    assert rc.first_seen_scope(rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN) == "ACROSS_RUNS"
    assert rc.first_seen_scope(rc.LEDGER_REUSED_WITHIN_RUN) == "THIS_RUN_ONLY"


def test_ledger_corrupt_wrong_shape_and_no_key():
    assert rc.classify_ledger({"corrupt": True}, "r", True)[0] == rc.LEDGER_CORRUPT                  # 復号できなかった印
    assert rc.classify_ledger({"candidates": []}, "r", True)[0] == rc.LEDGER_CORRUPT
    assert rc.classify_ledger(None, "r", False)[0] == rc.LEDGER_NOT_AVAILABLE                        # 鍵なし: 実行をまたいで保持する手段が無い
    assert rc.classify_ledger(None, "r", True)[0] == rc.LEDGER_NEW_THIS_RUN                          # 鍵あり・台帳なし（初回・キャッシュのミス）


@pytest.mark.skipif(__import__("shutil").which("bash") is None, reason="bash が無い")
def test_key_check_step_rejects_no_key_and_short_key_and_never_prints_the_key(tmp_path):
    steps = {st.get("name"): st for st in yaml.safe_load((ROOT / ".github/workflows/daily_lp.yml").read_text(encoding="utf-8"))["jobs"]["update-lp"]["steps"]}
    script = steps["Research ledger key check"]["run"]

    def run(k):
        out, env = tmp_path / "out", tmp_path / "env"
        for f in (out, env):
            f.write_text("", encoding="utf-8")
        r = subprocess.run(["bash", "-e", "-c", script], env={**os.environ, "K": k, "GITHUB_OUTPUT": str(out), "GITHUB_ENV": str(env)},
                           capture_output=True, text=True)
        return r, out.read_text(), env.read_text()

    secret = "Zq" * 20                                                  # 40 文字
    r, o, e = run(secret)
    assert "enabled=true" in o and "RESEARCH_LEDGER_PERSISTENCE=enabled" in e and secret not in r.stdout + r.stderr + o + e
    for k in ("", "short-key", "x" * 31):
        r, o, e = run(k)
        assert "enabled=false" in o and "RESEARCH_LEDGER_PERSISTENCE" not in e                       # 鍵なし・短い鍵は引き継がない
        assert k == "" or k not in r.stdout + r.stderr                                               # 短い鍵も出力しない


def test_workflow_ledger_is_never_committed_or_uploaded_in_plaintext():
    wf = (ROOT / ".github/workflows/daily_lp.yml").read_text(encoding="utf-8")
    commit_steps = [st["run"] for st in yaml.safe_load(wf)["jobs"]["update-lp"]["steps"] if "git add docs/" in str(st.get("run", ""))]
    assert commit_steps and all(".private" not in r and "ledger" not in r for r in commit_steps)       # 台帳をコミットしない
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".private" in gi
    cache_paths = [st["with"]["path"] for st in yaml.safe_load(wf)["jobs"]["update-lp"]["steps"]
                   if str(st.get("uses", "")).startswith("actions/cache")]
    assert cache_paths and all(p == ".private/ledger.enc" for p in cache_paths)                      # キャッシュに置くのは暗号化したファイルだけ
    assert "timeout-minutes" in yaml.safe_load(wf)["jobs"]["update-lp"] and yaml.safe_load(wf)["jobs"]["update-lp"]["timeout-minutes"] >= 180


# ── 買取の勢い ───────────────────────────────────────────────────────────────────────

def _prev(price=100000, at=PREV_AT, stale=False):
    return {"price": price, "at": at, "stale": stale}


def _r(sell=106000, observed_at=FRESH):
    return {"observed_sell_price": sell, "observed_at": observed_at}


def test_first_observation_is_new_observation_and_never_rising():
    m = sg.momentum(_r(), None, comparable=True, now=NOW)
    assert m["momentum_state"] == sg.MOM_NEW_OBSERVATION and m["delta_yen"] is None and not m["momentum_usable"]


def test_not_comparable_day_has_no_numbers_and_no_rising():
    m = sg.momentum(_r(), _prev(), comparable=False, now=NOW)
    assert m["momentum_state"] == sg.MOM_NOT_COMPARABLE and m["previous_price"] is None and not m["momentum_usable"]


def test_rising_records_previous_current_delta_and_both_times():
    m = sg.momentum(_r(106000), _prev(100000), comparable=True, now=NOW)
    assert m["momentum_state"] == sg.MOM_RISING and m["momentum_usable"]
    assert (m["previous_price"], m["current_price"], m["delta_yen"], m["delta_percent"]) == (100000, 106000, 6000, 6.0)
    assert (m["previous_observed_at"], m["current_observed_at"]) == (PREV_AT, FRESH)


def test_falling_flat_and_small_rise_are_not_rising():
    assert sg.momentum(_r(90000), _prev(), comparable=True, now=NOW)["momentum_state"] == sg.MOM_FALLING
    assert sg.momentum(_r(100000), _prev(), comparable=True, now=NOW)["momentum_state"] == sg.MOM_FLAT
    assert sg.momentum(_r(102000), _prev(), comparable=True, now=NOW)["momentum_state"] == sg.MOM_FLAT   # 3% 未満


def test_stale_previous_value_is_ignored_and_same_observation_is_not_momentum():
    m = sg.momentum(_r(130000), _prev(stale=True), comparable=True, now=NOW)
    assert m["momentum_state"] == sg.MOM_STALE_BASELINE and m["delta_yen"] is None and not m["momentum_usable"]
    same = sg.momentum(_r(130000, observed_at=PREV_AT), _prev(at=PREV_AT), comparable=True, now=NOW)
    assert same["momentum_state"] == sg.MOM_SAME_OBSERVATION and not same["momentum_usable"]          # 同じ観測を新しい値として数えない


def test_quarantined_momentum_is_kept_as_reference_but_unusable():
    m = sg.momentum(_r(190000), _prev(), comparable=True, now=NOW, quarantined=True)
    assert m["momentum_state"] == sg.MOM_RISING and m["delta_yen"] == 90000 and m["momentum_quarantined"]
    assert not m["momentum_usable"]                                                                  # 参考値だけ。点・上昇の件数には使わない


def test_prev_buyback_lookup_returns_stale_flag_and_is_none_without_a_restored_ledger():
    raw = {"buyback_prices": {"a": {"price": 100000, "at": PREV_AT}, "old": {"price": 90000, "at": "2026-09-01T10:00:00+09:00"},
                              "bad": {"price": 0, "at": PREV_AT}, "future": {"price": 5, "at": "2027-01-01T00:00:00+09:00"}}}
    f = rc.prev_buyback_lookup(raw, rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN, NOW)
    assert f({"candidate_id": "a"}) == {"price": 100000, "at": PREV_AT, "stale": False}
    assert f({"candidate_id": "old"})["stale"] is True
    assert f({"candidate_id": "bad"}) is None and f({"candidate_id": "future"}) is None and f({"candidate_id": "zz"}) is None
    for st in (rc.LEDGER_NOT_AVAILABLE, rc.LEDGER_NEW_THIS_RUN, rc.LEDGER_REUSED_WITHIN_RUN, rc.LEDGER_CORRUPT):
        assert rc.prev_buyback_lookup(raw, st, NOW) is None


def _dp(cid="dp_1", price=106000, **k):
    return {"candidate_id": cid, "kind": "DISCOVERED_PRODUCT_CANDIDATE", "status": rc.DISCOVERED, "name": "Nikon Z9 ボディ",
            "identity_basis": "JAN", "jan": "4960759900000", "observed_sell_price": price, "observed_at": FRESH,
            "retail_price_hint": None, "missing_requirements": ["CANONICAL_UNREGISTERED", "OFFICIAL_PRICE_UNKNOWN"], **k}


def _lk(price=100000, **k):
    base = {"status": "MATCHED", "retailer": "ニコンダイレクト", "source_type": "OFFICIAL_DIRECT", "product_url": "https://nij.nikon.com/a/",
            "price": price, "listed_price": price, "availability_state": "IN_STOCK", "observed_at": FRESH,
            "identity_evidence": {"basis": "JAN", "matched_name": "Z9 ボディ"}, "price_basis": "UNCONDITIONAL",
            "price_conditions": [], "points": 0, "cashback": 0}
    base.update(k)
    if "product_name" not in k and base.get("lottery_id"):
        base["product_name"] = "商品-" + str(base["lottery_id"])
    return base


def _k(lid="lot-1", **k):
    return dd.event_key(_ev(lottery_id=lid, **k))


def _annotate(rows, prev_obs_of, comparable):
    tri = tr.triage(rows, NOW, lookup_ready_of=lambda c: True,
                    lookup_results={c["candidate_id"]: {"status": "MATCHED"} for c in rows if c.get("retail_price") is not None})
    counts = sg.annotate_buyback_rows(tri["rows"], NOW, prev_obs_of=prev_obs_of, comparable=comparable)
    return tri["rows"], counts


def test_rising_row_gets_points_only_when_fresh_exact_and_not_quarantined():
    good, bad = _dp("dp_good"), _dp("dp_bad", price=300000)                      # 小売 10 万円・買取 30 万円 = 誤価格の疑い
    rc.apply_lookups([good, bad], {"dp_good": _lk(), "dp_bad": _lk()}, NOW, FRESH)
    rows, counts = _annotate([good, bad], lambda r: _prev(), True)
    by = {r["candidate_id"]: r for r in rows}
    assert by["dp_good"]["momentum"]["momentum_usable"] and sg.BUY_RISING in by["dp_good"]["buyback_signals"]
    assert by["dp_bad"]["momentum"]["momentum_quarantined"] and not by["dp_bad"]["momentum"]["momentum_usable"]
    assert by["dp_bad"]["signal_points"] == 0 and sg.BUY_RISING not in by["dp_bad"]["buyback_signals"]
    assert counts["buyback_rising_candidates"] == 1 and counts["momentum_quarantined"] == 1
    assert by["dp_good"]["status"] != rc.VERIFIED and by["dp_bad"]["status"] != rc.VERIFIED          # 勢いは確定を作らない


def test_new_observation_and_not_comparable_are_counted_and_never_rising():
    d = _dp()
    rc.apply_lookups([d], {"dp_1": _lk()}, NOW, FRESH)
    rows, counts = _annotate([d], lambda r: None, True)                          # 台帳は引き継げたが、この候補の前回が無い
    assert rows[0]["momentum"]["momentum_state"] == sg.MOM_NEW_OBSERVATION and counts["momentum_new_observation"] == 1
    assert counts["buyback_rising_candidates"] == 0
    d2 = _dp()
    rc.apply_lookups([d2], {"dp_1": _lk()}, NOW, FRESH)
    rows, counts = _annotate([d2], None, False)                                  # 台帳を引き継げていない日
    assert rows[0]["momentum"]["momentum_state"] == sg.MOM_NOT_COMPARABLE and counts["momentum_not_comparable"] == 1
    assert counts["buyback_rising_candidates"] == 0 and counts["momentum_observed"] == 0
    d3 = _dp()
    rc.apply_lookups([d3], {"dp_1": _lk()}, NOW, FRESH)
    rows, counts = _annotate([d3], lambda r: _prev(), False)                     # 前回の値を渡されても、引き継げていない日は比べない
    assert rows[0]["momentum"]["momentum_state"] == sg.MOM_NOT_COMPARABLE and rows[0]["momentum"]["previous_price"] is None
    assert counts["buyback_rising_candidates"] == 0 and counts["momentum_observed"] == 0


def test_baseline_uses_only_normal_prices_and_carries_the_previous_one_for_quarantined():
    good = {"candidate_id": "g", "observed_sell_price": 110000, "observed_at": FRESH, "momentum": {"momentum_quarantined": False}, "status": "RESEARCH_CANDIDATE"}
    spike = {"candidate_id": "s", "observed_sell_price": 400000, "observed_at": FRESH, "momentum": {"momentum_quarantined": True}, "status": "RESEARCH_CANDIDATE"}
    spike2 = {"candidate_id": "s2", "observed_sell_price": 400000, "observed_at": FRESH, "momentum": {"momentum_quarantined": True}, "status": "RESEARCH_CANDIDATE"}
    # 勢いの対象外の行（買取が古い・LOW）でも、誤価格の疑いのある価格は基準にしない（momentum の有無に依存しない）
    off = {"candidate_id": "o", "observed_sell_price": 400000, "observed_at": PREV_AT, "status": "RESEARCH_CANDIDATE",
           "missing_requirements": ["ABOVE_GENRE_MAX"], "signal_reasons": ["not_eligible"]}
    cond = {"candidate_id": "c", "observed_sell_price": 90000, "observed_at": FRESH, "status": "RESEARCH_CANDIDATE", "retail_conditions": ["クーポン"]}
    assert "o" not in rc._buyback_baseline([off], None) and "c" not in rc._buyback_baseline([cond], None)
    base = rc._buyback_baseline([good, spike, spike2], lambda r: _prev(95000) if r["candidate_id"] == "s" else None)
    assert base["g"] == {"price": 110000, "at": FRESH}
    assert base["s"] == {"price": 95000, "at": PREV_AT}                          # 隔離された価格を基準にせず、前回の正常な基準を引き継ぐ（日時も前回のまま）
    assert "s2" not in base                                                      # 前回の基準が無ければ、隔離された価格を基準にしない
    old = rc._buyback_baseline([spike], lambda r: _prev(95000, stale=True))
    assert old == {}                                                             # 古すぎる基準は引き継がない


def test_state_roundtrip_across_two_runs_gives_rising_with_both_timestamps(tmp_path):
    """run N の台帳 → run N+1: RESTORED_FROM_PREVIOUS_RUN で前回の価格・時刻が使われる。"""
    prev_rows = [{"candidate_id": "dp_1", "observed_sell_price": 100000, "observed_at": PREV_AT, "momentum": {}, "status": "RESEARCH_CANDIDATE"}]
    report = {"generated_at": PREV_AT, "buyback_prices": rc._buyback_baseline(prev_rows, None), "tcg_first_seen": {}}
    (tmp_path / "priv").mkdir()
    state = {"schema": rc.SCHEMA, "updated_at": PREV_AT, "run_id": "gh-1-1", "candidates": {}, "buyback_prices": report["buyback_prices"],
             "tcg_first_seen": {}}
    (tmp_path / "priv" / "state.json").write_text(json.dumps(state), encoding="utf-8")
    raw = json.loads((tmp_path / "priv" / "state.json").read_text(encoding="utf-8"))
    ls, _ = rc.classify_ledger(raw, "gh-2-1", True)
    assert ls == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN
    m = sg.momentum(_r(106000), rc.prev_buyback_lookup(raw, ls, NOW)({"candidate_id": "dp_1"}), comparable=True, now=NOW)
    assert m["momentum_state"] == sg.MOM_RISING and m["previous_observed_at"] == PREV_AT and m["current_observed_at"] == FRESH


# ── 検知の遅れの測定 ─────────────────────────────────────────────────────────────────

def _ev(**k):
    base = {"status": "OPEN", "event_type": "LOTTERY", "retailer": "CARD_LABO", "product_name": "商品", "lottery_id": "lot-1",
            "application_start": "2026-10-30T09:00:00+09:00", "application_end": "2026-11-02T23:59:00+09:00",
            "published_at": "2026-10-30T07:00:00+09:00", "source_url": "https://x.example/a"}
    base.update(k)
    if "product_name" not in k and base.get("lottery_id"):     # lottery_id が違えば別の商品（別イベント）として扱う
        base["product_name"] = "商品-" + str(base["lottery_id"])
    if "source_url" not in k:                                  # 出来事固有の情報元 URL（商品ごとに別。測定の対象になるのは固有 URL のイベントだけ）
        import zlib
        base["source_url"] = f"https://x.example/news/{zlib.crc32(str(base['product_name']).encode('utf-8'))}/"
    return base


def _k(lid="lot-1", **k):
    return dd.event_key(_ev(lottery_id=lid, **k))


def test_without_a_trusted_ledger_nothing_is_measured_and_first_seen_is_not_claimed():
    state, counts, rows = dd.update([_ev()], None, comparable=False, now=NOW)
    assert counts["comparable"] == 0 and counts["measured"] == 0 and rows[0]["measurable"] is False and rows[0]["detection_delay_hours"] is None


def test_events_already_present_when_the_ledger_started_are_baseline_not_measured():
    s1, c1, _ = dd.update([_ev()], None, comparable=False, now=NOW - timedelta(days=1))
    s2, c2, rows = dd.update([_ev()], s1, comparable=True, now=NOW)
    assert c2["comparable"] == 1 and c2["baseline_events"] == 1 and c2["measured"] == 0
    assert s2["events"][_k()]["first_seen"] == s1["events"][_k()]["first_seen"]               # first_seen は保持される
    assert s2["events"][_k()]["last_seen"] != s1["events"][_k()]["last_seen"]                 # last_seen だけ更新


def test_new_event_after_baseline_measures_delay_from_source_published_at():
    s1, _, _ = dd.update([_ev()], None, comparable=False, now=NOW - timedelta(days=1))
    items = [_ev(), _ev(lottery_id="lot-2", published_at="2026-10-30T08:00:00+09:00", application_start="2026-10-30T09:00:00+09:00")]
    s2, c, rows = dd.update(items, s1, comparable=True, now=NOW)
    new = [r for r in rows if r["measurable"]]
    assert c["new_after_baseline"] == 1 and c["measured"] == 1 and len(new) == 1
    assert new[0]["detection_delay_hours"] == 4.0                                                   # 12:00 に初めて見た − 08:00 公開
    assert new[0]["detected_before_start"] is False and 0 <= new[0]["remaining_fraction"] <= 1
    assert c["median_delay_hours"] == 0 and c["delay_values_withheld"] == 1                        # 1 件だけだと個別の値になるので公開しない
    more = [_ev(lottery_id=f"n{k}", published_at=f"2026-10-30T0{k}:00:00+09:00") for k in (6, 7, 8)]
    _, c3, _ = dd.update(more, s1, comparable=True, now=NOW)
    assert c3["measured"] == 3 and c3["median_delay_hours"] == 5.0 and c3["max_delay_hours"] == 6.0 and c3["delay_values_withheld"] == 0


def test_date_only_published_at_event_key_stability_source_gap_and_remeasure_window():
    s1, _, _ = dd.update([_ev()], None, comparable=False, now=NOW - timedelta(days=1))
    # 日付だけの公開日は時刻の精度が無いので、遅れを作らない
    _, c, _r = dd.update([_ev(lottery_id="d1", published_at="2026-10-30")], s1, comparable=True, now=NOW)
    assert c["measured"] == 0 and c["unknown_published_at"] == 1
    # lottery_id が無くても、商品名の微修正で別イベントにならない（情報元 URL で決める）
    assert dd.event_key(_ev(lottery_id=None, product_name="A", source_url="https://x.example/news/1234/")) == dd.event_key(
        _ev(lottery_id=None, product_name="A 修正", source_url="https://x.example/news/1234/"))
    # 前回その取得元が見えていない（停止・ブロックの後の復旧日）の「新規」は、遅れとして測らない
    _, c, _r = dd.update([_ev(lottery_id="g1", retailer="OTHER_SHOP")], s1, comparable=True, now=NOW)
    assert c["measured"] == 0 and c["source_gap_excluded"] == 1
    # 同じイベントは、初めて見えた run でだけ測る（翌日の run で、また数えない。同じ run の再生成は数える）
    s2, c2, _r = dd.update([_ev(lottery_id="m1", published_at="2026-10-30T08:00:00+09:00")], s1, comparable=True, now=NOW, run_id="run-A")
    assert c2["measured"] == 1
    s2b, c2b, _r = dd.update([_ev(lottery_id="m1", published_at="2026-10-30T08:00:00+09:00")], s2, comparable=True, now=NOW, run_id="run-A")
    assert c2b["measured"] == 1                                                                         # 同じ run の再生成
    _, c3, _r = dd.update([_ev(lottery_id="m1", published_at="2026-10-30T08:00:00+09:00")], s2b, comparable=True,
                          now=NOW + timedelta(hours=20), run_id="run-B")
    assert c3["measured"] == 0 and c3["new_after_baseline"] == 1                                       # 翌日の run: 数えない
    # 収集した時刻（observed_at）を first_seen にする（LP の生成時刻より正確）
    s4, _c, _r = dd.update([_ev(lottery_id="o1", observed_at="2026-10-30T09:30:00+09:00")], s1, comparable=True, now=NOW)
    assert s4["events"][_k("o1")]["first_seen"].startswith("2026-10-30T09:30:00")


def test_source_gap_decision_is_stable_across_a_same_run_regeneration_and_healthy_sources_count():
    s0, _, _ = dd.update([_ev()], None, comparable=False, now=NOW - timedelta(days=3), run_id="r0")    # 3 日前: CARD_LABO が見えた
    s1, _, _ = dd.update([_ev()], s0, comparable=True, now=NOW - timedelta(days=2), run_id="r1")        # 2 日前
    gap = [_ev(lottery_id="g1", published_at="2026-10-30T08:00:00+09:00")]
    sa, ca, _ = dd.update(gap, s1, comparable=True, now=NOW, run_id="r2")                              # 最初の生成: 40 時間以上見えていない
    assert ca["source_gap_excluded"] == 1 and ca["measured"] == 0
    _, cb, _ = dd.update(gap, sa, comparable=True, now=NOW, run_id="r2")                               # 同じ run の再生成: 判定は変わらない
    assert cb["source_gap_excluded"] == 1 and cb["measured"] == 0
    # 取得元が正常に取れていれば（イベントが無い日でも）見えていたことにする: 新しい抽選が出た日を測れる
    s1h, _, _ = dd.update([], s1, comparable=True, now=NOW - timedelta(hours=20), run_id="r1b", healthy_sources={"CARD_LABO"})
    _, ch, _ = dd.update(gap, s1h, comparable=True, now=NOW, run_id="r2", healthy_sources={"CARD_LABO"})
    assert ch["source_gap_excluded"] == 0 and ch["measured"] == 1


def test_same_run_regeneration_of_an_untrusted_first_generation_never_measures():
    s_first, c1, _ = dd.update([_ev()], None, comparable=False, now=NOW - timedelta(hours=1), run_id="r9")        # 台帳なし: 測らない
    assert c1["comparable"] == 0 and s_first["trusted"] is False
    _, c2, _ = dd.update([_ev(lottery_id="z")], s_first, comparable=True, now=NOW, run_id="r9")                    # 再生成
    assert c2["comparable"] == 0 and c2["measured"] == 0                                                           # 最初の生成が信頼できないなら、再生成も測らない・comparable にしない


def test_missing_or_contradictory_published_at_is_unknown_never_guessed():
    s1, _, _ = dd.update([_ev()], None, comparable=False, now=NOW - timedelta(days=1))
    items = [_ev(lottery_id="n1", published_at=None), _ev(lottery_id="n2", published_at="2027-01-01T00:00:00+09:00")]   # 公開日時なし / 未来
    _, c, rows = dd.update(items, s1, comparable=True, now=NOW)
    assert c["measured"] == 0 and c["unknown_published_at"] == 2 and all(r["detection_delay_hours"] is None for r in rows)


def test_same_run_regeneration_carries_first_seen_instead_of_resetting_it():
    """REUSED_WITHIN_RUN（同じ run の再生成）でも、前回の run までの first_seen を捨てない（捨てると across-runs の記録が消える）。"""
    s1, _, _ = dd.update([_ev()], None, comparable=False, now=NOW - timedelta(days=3))
    s2, _, _ = dd.update([_ev()], s1, comparable=True, now=NOW - timedelta(days=2))
    s3, _, _ = dd.update([_ev()], s2, comparable=True, now=NOW - timedelta(days=2))                  # 同じ run の再生成
    assert s3["events"][_k()]["first_seen"] == s1["events"][_k()]["first_seen"] and s3["started_at"] == s1["started_at"]


def test_build_keeps_first_seen_on_same_run_regeneration_and_does_not_carry_without_a_ledger():
    products = [{"id": "p", "name": "既存", "genre": "camera", "jan": "", "part_numbers": []}]
    base = dict(products=products, observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), catalog=[], retail_lookups=None)
    s1, _, _ = dd.update([_ev()], None, comparable=False, now=NOW - timedelta(days=3))
    kept, _ = rc.build(**base, now=NOW, tcg_events=[_ev()], ledger_state=rc.LEDGER_REUSED_WITHIN_RUN, prev_tcg_first_seen=s1)
    assert kept["tcg_first_seen"]["events"][_k()]["first_seen"] == s1["events"][_k()]["first_seen"]      # 再生成でも捨てない
    restored, _ = rc.build(**base, now=NOW, tcg_events=[_ev()], ledger_state=rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN, prev_tcg_first_seen=s1)
    assert restored["tcg_first_seen"]["events"][_k()]["first_seen"] == s1["events"][_k()]["first_seen"]
    for st in (rc.LEDGER_NOT_AVAILABLE, rc.LEDGER_CORRUPT, rc.LEDGER_NEW_THIS_RUN):
        fresh, _ = rc.build(**base, now=NOW, tcg_events=[_ev()], ledger_state=st, prev_tcg_first_seen=s1)
        assert fresh["tcg_first_seen"]["events"][_k()]["first_seen"] != s1["events"][_k()]["first_seen"]   # 台帳を使えない日は引き継がない
        assert fresh["metrics"]["tcg_detection_delay"]["comparable"] == 0


def test_broken_first_seen_ledger_is_treated_as_missing_and_inactive_events_are_skipped():
    for bad in ({"events": []}, {"started_at": 1, "events": {}}, "x", [], {"started_at": "2026-10-01T00:00:00+09:00", "events": {"a": "b"}}):
        s, c, _ = dd.update([_ev()], bad, comparable=True, now=NOW)
        assert c["comparable"] in (0, 1) and _k() in s["events"]
    _, c, rows = dd.update([_ev(status="ENDED")], None, comparable=False, now=NOW)
    assert c["events_active"] == 0 and rows == []


def test_old_unseen_events_are_pruned_but_recent_ones_survive_a_missing_day():
    s1, _, _ = dd.update([_ev()], None, comparable=False, now=NOW - timedelta(days=70))
    s2, _, _ = dd.update([], s1, comparable=True, now=NOW)
    assert s2["events"] == {}                                                                       # 60 日を超えて見えないものは捨てる
    s1, _, _ = dd.update([_ev()], None, comparable=False, now=NOW - timedelta(days=2))
    s2, _, _ = dd.update([], s1, comparable=True, now=NOW)
    assert _k() in s2["events"]


def test_build_report_has_private_detection_rows_and_public_counts_only():
    products = [{"id": "p", "name": "既存", "genre": "camera", "jan": "", "part_numbers": []}]
    rep, _ = rc.build(products=products, observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW,
                      catalog=[], retail_lookups=None, tcg_events=[_ev()])
    assert set(rep["metrics"]["tcg_detection_delay"]) >= {"events_active", "measured", "comparable"}
    assert "tcg_first_seen" in rep and "tcg_detection_events" in rep
    pub = rc.public_summary(rep)
    assert "tcg_detection_delay" in json.dumps(pub) and not rc.find_private_keys(pub)
    assert "tcg_first_seen" not in json.dumps(pub) and "momentum" not in json.dumps(pub).replace("momentum_", "")


# ── limited（曖昧な語だけでは限定にしない）──────────────────────────────────────────────

def test_generic_special_words_are_not_limited_but_official_evidence_is():
    for n in ("Special Pack", "特別なケース付き", "スペシャルセット", "記念パック"):
        assert not sg.limited_signal(official_name=n, official_url="https://o.example/", official=True)["limited"]
    assert sg.limited_signal(official_name="数量限定 BOX", official_url="https://o.example/", official=True)["limited"]
    assert sg.limited_signal(official_name="Special Pack", official_url="https://o.example/", official=True, structured_limited=True)["limited"]
    assert not sg.limited_signal(official_name="数量限定 BOX", official_url="http://o.example/", official=True)["limited"]   # https でない


# ── TCG: 応募の URL の区別 ─────────────────────────────────────────────────────────────

def _full(**k):
    base = {"status": "OPEN", "event_type": "LOTTERY", "retailer": "CARD_LABO", "product_name": "商品", "product_id": "pid-1", "product_match": "exact",
            "application_start": "2026-10-30T09:00:00+09:00", "application_end": "2026-11-02T23:59:00+09:00",
            "winner_announcement_date": "2026-11-04", "purchase_start_date": "2026-11-05", "purchase_end_date": "2026-11-08",
            "entry_url": "https://shop.example/entry", "source_url": "https://shop.example/news"}
    base.update(k)
    return base


def test_announcement_url_alone_is_never_actionable():
    ok = pdn.completeness(_full(), NOW)
    assert ok["actionable_event"] and ok["application_url_confirmed"] and not ok["announcement_url_only"]
    ann = pdn.completeness(_full(entry_url=None), NOW)
    assert not ann["actionable_event"] and ann["announcement_url_only"] and not ann["application_url_confirmed"]
    pur = pdn.completeness(_full(entry_url=None, purchase_url="https://shop.example/buy"), NOW)
    assert not pur["actionable_event"]                                                              # 購入の URL（当選後）は応募の URL ではない
    c = pdn.evaluate([_full(), _full(entry_url=None)], None, NOW)["counts"]
    assert c["tcg_application_url_confirmed"] == 1 and c["tcg_announcement_url_only"] == 1 and c["tcg_actionable_events"] == 1


# ── TCG: 同一 run のキャッシュ・ドメインごとの直列化・全体の上限 ───────────────────────────

def test_same_url_is_fetched_once_even_when_requested_concurrently():
    cache = runcache.TcgRunCache()
    calls = []

    def do():
        calls.append(1)
        time.sleep(0.15)
        return {"html": "<p>x</p>", "error": None, "blocked": False, "status": 200, "final_url": None}
    out = []
    ts = [threading.Thread(target=lambda: out.append(cache.fetch("https://A.example/p/?q=1#frag", do))) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(calls) == 1 and sum(1 for _e, hit in out if not hit) == 1 and sum(1 for _e, hit in out if hit) == 4
    assert cache.stats()["fetches"] == 1 and cache.stats()["cache_hits"] == 4
    assert runcache.normalize_url("HTTPS://A.example/p/?q=1#f") == runcache.normalize_url("https://a.example/p?q=1")   # 正規化（大小・末尾スラッシュ・フラグメント）
    assert runcache.normalize_url("https://a.example/p?q=1") != runcache.normalize_url("https://a.example/p?q=2")      # クエリは別の URL


def test_failed_and_blocked_fetches_are_cached_and_never_retried():
    cache = runcache.TcgRunCache()
    n = []
    fail = {"html": None, "error": "HTTP 403", "blocked": True, "status": 403, "final_url": None}
    for _ in range(3):
        e, _hit = cache.fetch("https://b.example/x", lambda: (n.append(1), fail)[1])
        assert e["html"] is None
    assert len(n) == 1                                                                              # ブロックされた URL を取り直さない（回避しない）
    boom = []
    e, _ = cache.fetch("https://b.example/y", lambda: (_ for _ in ()).throw(RuntimeError("x")))      # 取得の例外もキャッシュされ、止まらない
    assert e["html"] is None and e["error"] == "RuntimeError"
    cache.fetch("https://b.example/y", lambda: boom.append(1) or fail)
    assert boom == []


def test_cache_is_active_only_inside_the_run_and_dropped_afterwards():
    assert runcache.active() is None
    with runcache.activate() as c:
        assert runcache.active() is c
        c.fetch("https://c.example/", lambda: {"html": "a", "error": None, "blocked": False, "status": 200, "final_url": None})
    assert runcache.active() is None                                                                # 抜けたら捨てる。次の run に持ち越さない
    with runcache.activate() as c2:
        assert c2 is not c and c2.stats()["fetches"] == 0                                           # 前回の応答は新しい証拠として使わない


def test_collector_fetch_uses_run_cache_and_records_hits_without_refetching(monkeypatch):
    from src.collectors.tcg.base import BaseTcgCollector

    class C(BaseTcgCollector):
        source_key, source_name, tcg = "T", "t", "POKEMON"
        calls = 0

        def _fetch_once(self, url, page_type="other", referer=None):
            C.calls += 1
            diag = self.funnel.add_page(__import__("src.tcg.funnel", fromlist=["PageDiagnostic"]).PageDiagnostic(url=url, page_type=page_type))
            self.funnel.pages_requested += 1
            if "blocked" in url:
                diag.http_status, diag.error = 403, "HTTP 403"
                self.health["blocked"] = True
                self.funnel.blocked_pages += 1
                return None
            self._fill_page_diag(diag, "<title>t</title><a href='/x'>a</a>", status=200, final_url=url)
            return "<title>t</title><a href='/x'>a</a>"
    with runcache.activate():
        a, b = C(), C()
        assert a._fetch("https://d.example/news") and b._fetch("https://d.example/news")
        assert C.calls == 1                                                                         # 2 つの取得元が同じ URL を取っても 1 回
        assert b.funnel.pages_requested == 1 and b.funnel.pages_loaded == 1                         # 省いた取得も、取得元の診断には 1 ページとして残る
        assert a._fetch("https://d.example/blocked") is None and b._fetch("https://d.example/blocked") is None
        assert C.calls == 2 and b.health["blocked"] is True and b.funnel.blocked_pages == 1         # ブロックの記録は引き継がれ、取り直さない
    c = C()
    C.calls = 0
    assert c._fetch("https://d.example/news") and C.calls == 1                                      # キャッシュ外では普通に取る（テスト・他の呼び出しに影響しない）
    assert c._fetch("https://d.example/news") and C.calls == 2


def test_same_domain_is_serialised_but_different_domains_run_in_parallel():
    active, peak, lock = {}, {"same": 0, "all": 0}, threading.Lock()

    def work(url):
        with runcache.domain_lock(url):
            with lock:
                active[url] = True
                peak["same"] = max(peak["same"], sum(1 for u in active if "same.example" in u))
                peak["all"] = max(peak["all"], len(active))
            time.sleep(0.12)
            with lock:
                active.pop(url)
    ts = [threading.Thread(target=work, args=(u,)) for u in
          ("https://same.example/1", "https://same.example/2", "https://same.example/3", "https://o1.example/", "https://o2.example/")]
    t0 = time.monotonic()
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak["same"] == 1                                                                        # 同じドメインは同時に 1 つ
    assert peak["all"] >= 3 and time.monotonic() - t0 < 0.12 * 5                                    # 別のドメインは重なる（全部直列にしない）


def test_private_signal_fields_are_in_the_private_list_and_a_summary_containing_them_is_rejected():
    for k in ("momentum", "tcg_first_seen", "tcg_detection_events", "buyback_prices"):
        assert k in rc.PRIVATE_KEYS                                                                 # 勢い・first_seen・前回の価格は非公開
    for k in ("momentum", "tcg_first_seen", "tcg_detection_events"):
        assert rc.find_private_keys({"metrics": {k: {"x": 1}}})                                    # 公開の集計に混ざったら検知する


def test_global_cap_limits_simultaneous_requests_and_one_failure_does_not_stop_others():
    assert 1 < runcache.GLOBAL_CAP <= 16                                                            # 上限なしの並列にしない
    cur, peak, lock = [0], [0], threading.Lock()

    def job(i):
        def f():
            with runcache.global_slot():                                                            # 通信の間だけ枠を使う（base._fetch_once と同じ）
                with lock:
                    cur[0] += 1
                    peak[0] = max(peak[0], cur[0])
                time.sleep(0.05)
                with lock:
                    cur[0] -= 1
            if i == 3:
                raise ValueError("x")
            return i
        return f
    res = runcache.run_parallel([(f"t{i}", job(i)) for i in range(40)])
    assert peak[0] <= runcache.GLOBAL_CAP and len(res) == 40                                        # 同時に通信するのは GLOBAL_CAP まで
    assert res["t3"]["error"].startswith("ValueError") and res["t4"]["result"] == 4 and res["t0"]["error"] is None


def test_slot_is_not_held_while_waiting_for_the_interval():
    """間隔の待ち（sleep）の間は枠を使わない: 枠を全部使い切っていても、別のドメインの通信が止まらない。"""
    held = [runcache._GLOBAL_SLOTS.acquire(blocking=False) for _ in range(runcache.GLOBAL_CAP - 1)]
    try:
        assert all(held)
        with runcache.global_slot():                                                                # 残り 1 枠はまだ使える
            pass
    finally:
        for h in held:
            if h:
                runcache._GLOBAL_SLOTS.release()


def test_polite_floor_is_still_60_seconds_per_domain(monkeypatch):
    """ドメインごとの間隔（60 秒以上）は並列化しても維持される（RateLimiter の下限）。"""
    from src.collectors import rate_limiter as rlm
    from src.collectors.tcg import base
    assert base.MIN_INTERVAL_SEC >= 60
    lim = rlm.RateLimiter()
    sleeps = []
    monkeypatch.setattr(rlm.time, "sleep", lambda s: sleeps.append(s))
    lim._last_access.pop("floor.example", None)
    lim.wait_if_needed("https://floor.example/a", 1)                  # 1 秒を指定しても
    lim.wait_if_needed("https://floor.example/b", 1)
    assert sleeps and sleeps[0] >= 55                                 # 実際には約 60 秒空ける
    lim._last_access.pop("floor.example", None)


def test_collect_sources_runs_sources_concurrently_and_keeps_registry_order(monkeypatch):
    from src.tcg.lottery import pipeline as pl

    class A:
        max_detail_fetch = 1

        def __init__(self):
            self.health, self.announcements = {"status": "HEALTHY"}, []

        def collect(self):
            time.sleep(0.3)
            return []
    monkeypatch.setattr(pl, "_adapters", lambda: {"a": A, "b": A, "c": A, "d": A})
    srcs = [{"source_id": s.upper(), "retailer": s, "adapter": s} for s in "abcd"]
    timings: dict = {}
    t0 = time.monotonic()
    _e, health, _a = pl.collect_sources(srcs, timings)
    assert time.monotonic() - t0 < 0.3 * 4 - 0.3                                                   # 4 つを直列（1.2 秒）にしていない
    assert list(health) == ["A", "B", "C", "D"] and set(timings) == {"A", "B", "C", "D"}


def test_a_failed_source_is_recorded_as_failed_not_healthy(monkeypatch):
    from src.tcg.lottery import pipeline as pl

    class Bad:
        max_detail_fetch = 1

        def __init__(self):
            raise RuntimeError("boom")
    monkeypatch.setattr(pl, "_adapters", lambda: {"bad": Bad})
    _e, health, _a = pl.collect_sources([{"source_id": "BAD", "retailer": "b", "adapter": "bad"}])
    assert health["BAD"]["status"] == "FAILED" and health["BAD"]["errors"] == 1


# ── 取得元の健全性の分類（run が成功しても、取得元が健全とは限らない）───────────────────────

def test_source_health_classes_distinguish_zero_degraded_blocked_unreachable_failed_truncated():
    ok = {"status": "HEALTHY", "funnel": {"pages_loaded": 3}}
    assert cm.classify(ok) == cm.HEALTHY
    assert cm.classify({"status": "OK_NO_EVENTS", "funnel": {"pages_loaded": 1}}) == cm.ZERO_EVENTS     # 0 件 = 取得できた事実だけ
    assert cm.classify({"status": "DEGRADED", "funnel": {"pages_loaded": 1}}) == cm.PARSER_DEGRADED
    assert cm.classify({"status": "OK_NO_EVENTS", "funnel": {"pages_loaded": 1, "structure_changed_pages": 1}}) == cm.PARSER_DEGRADED
    assert cm.classify({"status": "BLOCKED", "blocked": True, "funnel": {"pages_loaded": 0}}) == cm.BLOCKED
    assert cm.classify({"status": "FAILED", "unreachable": True, "funnel": {"pages_loaded": 0}}) == cm.UNREACHABLE
    assert cm.classify({"status": "FAILED", "error_messages": ["ReadTimeout: x"], "funnel": {"pages_loaded": 0}}) == cm.UNREACHABLE
    assert cm.classify({"status": "FAILED", "funnel": {"pages_loaded": 0}}) == cm.FAILED
    assert cm.classify({"status": "???", "funnel": {"pages_loaded": 0}}) == cm.FAILED                  # 不明な状態を healthy にしない
    assert cm.classify(None) == cm.FAILED
    assert cm.is_truncated({"skipped_due_to_limit": 3}) and not cm.is_truncated({"skipped_due_to_limit": 0})


def test_collection_metrics_are_counts_and_seconds_only_and_label_the_cache_scope():
    health = [{"status": "HEALTHY", "funnel": {"pages_loaded": 2, "pages_requested": 2}}, {"status": "BLOCKED", "blocked": True, "funnel": {}}]
    lot = [{"health": "HEALTHY", "reachable": True, "detail_fetched": 5, "detail_candidates": 9, "skipped_due_to_limit": 2},
           {"health": "FAILED", "reachable": False, "unreachable": True}]
    m = cm.summarize(health, lot, total_seconds=1234.5, cache_stats={"fetches": 30, "cache_hits": 4, "domains": 9, "max_per_domain": 12},
                     collector_seconds={"A": 400.0}, lottery_seconds={"B": 900.0}, global_cap=8)
    assert m["sources_by_health"][cm.HEALTHY] == 2 and m["sources_by_health"][cm.BLOCKED] == 1 and m["sources_by_health"][cm.UNREACHABLE] == 1
    assert m["truncated_sources"] == 1 and m["detail_fetched"] == 5 and m["http_cache_hits"] == 4 and m["cache_scope"] == "THIS_RUN_ONLY"
    assert m["slowest_source_seconds"] == 900.0 and m["per_domain_concurrency"] == 1 and m["global_cap"] == 8
    assert all(isinstance(v, (int, float, str, dict)) for v in m.values()) and "http" not in json.dumps(m).replace("http_", "")


# ── 仕入れ元 API（鍵なしでは 0 リクエスト・鍵の値を出さない）──────────────────────────────

def test_api_sources_make_no_requests_without_secrets_and_never_leak_values(monkeypatch):
    import requests
    calls = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("request")))
    monkeypatch.setattr(requests, "post", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("request")))
    st = rl.api_source_statuses({})
    assert {a["status"] for a in st} == {rl.API_PENDING} and calls == []
    leaked = rl.api_source_statuses({"YAHOO_SHOPPING_APP_ID": "SECRET-APP-ID-123", "ENABLE_YAHOO_API": "true", "RAKUTEN_APP_ID": "SECRET-RAKUTEN"})
    assert "SECRET-APP-ID-123" not in json.dumps(leaked) and "SECRET-RAKUTEN" not in json.dumps(leaked) and calls == []


def test_workflow_passes_api_keys_only_as_secret_env_never_in_scripts_or_artifacts():
    doc = yaml.safe_load((ROOT / ".github/workflows/daily_lp.yml").read_text(encoding="utf-8"))
    for st in doc["jobs"]["update-lp"]["steps"]:
        run = str(st.get("run", ""))
        assert "YAHOO_SHOPPING_APP_ID" not in run and "RAKUTEN_APP_ID" not in run                   # スクリプトに鍵を書かない・出力しない
        for k, v in (st.get("env") or {}).items():
            if k in ("YAHOO_SHOPPING_APP_ID", "RAKUTEN_APP_ID", "RESEARCH_LEDGER_KEY"):
                assert str(v).startswith("${{ secrets.")                                              # 鍵は Secrets の参照だけ（値を直接書かない）
        if str(st.get("uses", "")).startswith("actions/upload-artifact"):
            assert ".private" not in str(st.get("with", {}).get("path", ""))                          # 公開の artifact に非公開を入れない


# ── レビュー・監査の指摘への対応（Wave 6）────────────────────────────────────────────────

def test_small_yen_changes_are_not_momentum_even_above_three_percent():
    assert sg.momentum(_r(3200), _prev(3000), comparable=True, now=NOW)["momentum_state"] == sg.MOM_FLAT        # +6.7% だが 200 円
    assert sg.momentum(_r(3600), _prev(3000), comparable=True, now=NOW)["momentum_state"] == sg.MOM_RISING     # 600 円
    assert sg.BUY_RISING not in sg.buyback_signals(_row_b(3200), prev_sell=3000)
    m = sg.momentum(_r(106000), _prev(100000), comparable=True, now=NOW)
    assert m["days_since_previous"] == 1                                                                       # 前回からの経過日数も残す


def _row_b(sell):
    return {"observed_sell_price": sell, "retail_price": None, "category": "x"}


def test_momentum_baseline_survives_a_same_run_regeneration():
    """同じ run の再生成（REUSED_WITHIN_RUN）でも、前回の run から引き継いだ基準で勢いを再計算する（比べられなくならない・基準を上書きしない）。"""
    prev_run = {"buyback_prices": {"dp_1": {"price": 100000, "at": PREV_AT}}}
    base, ls, persist = rc.momentum_baseline(prev_run, rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN)
    assert ls == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN and persist == prev_run["buyback_prices"]
    # この run の最初の生成が書いた state: buyback_prices は今回の値・buyback_prices_prev は引き継いだ前回の基準
    first_gen = {"buyback_prices": {"dp_1": {"price": 106000, "at": FRESH}}, "buyback_prices_prev": persist}
    base2, ls2, persist2 = rc.momentum_baseline(first_gen, rc.LEDGER_REUSED_WITHIN_RUN)
    assert persist2 == persist                                                                                  # 基準は上書きされず引き継がれる
    got = rc.prev_buyback_lookup(base2, ls2, NOW)({"candidate_id": "dp_1"})
    assert got["price"] == 100000 and got["at"] == PREV_AT                                                      # 今回の値ではなく、前回の基準と比べる
    for st in (rc.LEDGER_NOT_AVAILABLE, rc.LEDGER_NEW_THIS_RUN, rc.LEDGER_CORRUPT):
        assert rc.momentum_baseline(first_gen, st) == (None, st, None)
    assert rc.momentum_baseline({"buyback_prices": {}}, rc.LEDGER_REUSED_WITHIN_RUN)[0] is None               # 最初の生成が引き継げていなければ比べない
    assert rc.momentum_baseline("CORRUPT", rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN) == (None, rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN, None)
    # 最初の生成が引き継げなかった（保存された基準が None）なら、再生成も「比べられない」（空の基準で NEW_OBSERVATION にしない）
    assert rc.momentum_baseline({"buyback_prices": {}, "buyback_prices_prev": None}, rc.LEDGER_REUSED_WITHIN_RUN)[0] is None
    assert "buyback_prices_prev" in rc.PRIVATE_KEYS


def test_limited_words_are_not_matched_inside_other_words_or_negations():
    for n in ("Unlimited Pack", "限定なしセット", "非限定版", "Limitedly Pack"):
        assert not sg.limited_signal(official_name=n, official_url="https://o.example/", official=True)["limited"]
    assert sg.limited_signal(official_name="Limited Edition", official_url="https://o.example/", official=True)["limited"]
    hint = sg.limited_signal(official_name="Special Pack", official_url="https://o.example/", official=True)
    assert not hint["limited"] and hint["limited_hint"] == "Special"                                          # 曖昧な語は点にも件数にもしない（人が確かめる手がかり）
    assert sg.profit_density(limited=hint)["signal_points"] == 0


def test_cache_key_separates_js_and_static_fetches_and_releases_waiters_on_interrupt():
    cache = runcache.TcgRunCache()
    e1, h1 = cache.fetch("https://j.example/p", lambda: {"html": "static", "error": None, "blocked": False, "status": 200, "final_url": None})
    e2, h2 = cache.fetch("https://j.example/p", lambda: {"html": "rendered", "error": None, "blocked": False, "status": 200, "final_url": None}, variant="js")
    assert (e1["html"], e2["html"], h1, h2) == ("static", "rendered", False, False)                           # JS 描画の応答と静的な応答を混ぜない
    boom = []

    def interrupted():
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        cache.fetch("https://k.example/", interrupted)
    done = threading.Event()

    def waiter():
        cache.fetch("https://k.example/", lambda: (boom.append(1), {"html": "ok", "error": None, "blocked": False, "status": 200, "final_url": None})[1])
        done.set()
    threading.Thread(target=waiter, daemon=True).start()
    assert done.wait(3) and boom == [1]                                                                       # 中断で待機側を永久に待たせない（次の要求は取り直せる）


def test_cached_page_keeps_the_real_fetch_time_for_events(monkeypatch):
    """キャッシュで受け取った側も、実際に取得した時刻を使う（受け取った時刻を観測時刻にしない。偽の鮮度にしない）。"""
    from src.collectors.tcg.base import BaseTcgCollector
    from src.tcg.funnel import PageDiagnostic

    class C(BaseTcgCollector):
        source_key, source_name, tcg = "T", "t", "POKEMON"

        def _fetch_once(self, url, page_type="other", referer=None):
            diag = self.funnel.add_page(PageDiagnostic(url=url, page_type=page_type))
            self._fill_page_diag(diag, "<title>t</title>", status=200, final_url=url)
            return "<title>t</title>"
    with runcache.activate():
        a, b = C(), C()
        a._fetch("https://t.example/news")
        t_real = a._fetched_at
        time.sleep(0.02)
        b._fetch("https://t.example/news")
        assert b._fetched_at == t_real                                                                         # 2 つ目の取得元は、受け取った時刻ではなく実際の取得時刻


def test_partial_block_is_visible_even_when_status_is_healthy():
    m = cm.summarize([{"status": "HEALTHY", "blocked": True, "funnel": {"pages_loaded": 2, "pages_requested": 3}}], [],
                     total_seconds=1, cache_stats={})
    assert m["sources_by_health"][cm.HEALTHY] == 1 and m["partial_blocked_sources"] == 1                      # 一部だけ読めた取得元を、健全の中に隠さない


def test_generator_research_step_runs_across_runs_and_keeps_the_momentum_baseline(tmp_path, monkeypatch):
    """生成器の調査候補の工程（例外は握りつぶされる）が、前回の run の台帳でも同じ run の再生成でも落ちない。"""
    from tests.test_market_research import _gen
    prev = json.dumps({"schema": rc.SCHEMA, "run_id": "gh-0-1", "candidates": {}, "buyback_prices": {"dp_x": {"price": 100000, "at": PREV_AT}},
                       "tcg_first_seen": {}})
    g, ctx, catalog = _gen(tmp_path, monkeypatch, state_text=prev)
    s1 = g._write_research_candidates(ctx, catalog)
    assert s1 is not None and s1["ledger_state"] == "RESTORED_FROM_PREVIOUS_RUN" and "momentum_observed" in s1["research_signals"]
    st1 = json.loads((tmp_path / "priv" / "state.json").read_text(encoding="utf-8"))
    assert st1["buyback_prices_prev"] == {"dp_x": {"price": 100000, "at": PREV_AT}}                 # 引き継いだ前回の基準を残す
    s2 = g._write_research_candidates(ctx, catalog)                                                   # 同じ run の再生成
    assert s2 is not None and s2["ledger_state"] == "REUSED_WITHIN_RUN"
    st2 = json.loads((tmp_path / "priv" / "state.json").read_text(encoding="utf-8"))
    assert st2["buyback_prices_prev"] == st1["buyback_prices_prev"]                                  # 基準を上書きしない
    assert "momentum" not in json.dumps(s2).replace("momentum_", "") and "buyback_prices" not in json.dumps(s2)


def test_event_key_is_stable_when_the_application_period_is_filled_in_later():
    """詳細の取得で応募期間が後から入っても（lottery_id が変わっても）同じイベント。新規として測らない（Final Gate M1）。"""
    a = _ev(lottery_id="lot-a", product_name="同じ商品", application_start=None, application_end=None)
    b = _ev(lottery_id="lot-b", product_name="同じ商品")
    assert dd.event_key(a) == dd.event_key(b)
    assert dd.event_key(_ev(retailer="OTHER_SHOP", source_url="https://y.example/news/1/")) != dd.event_key(_ev())
    s1, _, _ = dd.update([a], None, comparable=False, now=NOW - timedelta(days=2))
    _, c, _r = dd.update([b], s1, comparable=True, now=NOW)
    assert c["measured"] == 0 and c["new_after_baseline"] == 0


def test_limited_word_next_to_japanese_text_is_detected_but_unlimited_is_not():
    """日本語に隣り合った明確な限定語を見逃さない。英単語の一部（Unlimited）は除く（Final Gate M2）。"""
    from src.research import signals as sg
    for name in ("ポケモンセンターLimited Box", "Limited版 BOX", "Exclusive版"):
        assert sg.limited_signal(official=True, official_url="https://x", official_name=name)["limited"] is True, name
    for name in ("Unlimited Box", "Limitedly Box"):
        assert sg.limited_signal(official=True, official_url="https://x", official_name=name)["limited"] is False, name


def test_ledger_with_an_old_key_version_is_not_carried_and_never_measures_existing_events_as_new():
    """旧鍵（版なし・別の版）の台帳が来ても、既存イベントを「新規」として測らない。台帳は新しい版で作り直す（監査 M-1）。"""
    old_items = [_ev(lottery_id=f"x{n}", published_at="2026-10-27T07:00:00+09:00") for n in range(5)]
    s1, _, _ = dd.update(old_items, None, comparable=False, now=NOW - timedelta(days=5))
    legacy = {k: v for k, v in s1.items() if k != "event_key_version"}
    legacy["events"] = {f"x{n}": {"first_seen": "2026-10-25T12:00:00+09:00", "last_seen": "2026-10-29T12:00:00+09:00", "retailer": "CARD_LABO"} for n in range(5)}
    legacy["trusted"] = True
    legacy["sources"] = {"CARD_LABO": (NOW - timedelta(hours=24)).isoformat(timespec="seconds")}
    assert dd.sanitize(legacy) == {} and dd.sanitize({**legacy, "event_key_version": 1}) == {}
    s2, c, _r = dd.update(old_items, legacy, comparable=True, now=NOW, run_id="r-new")
    assert c["measured"] == 0 and c["new_after_baseline"] == 0 and c["comparable"] == 0
    assert s2["event_key_version"] == dd.EVENT_KEY_VERSION and s2["trusted"] is False
    _, c3, _ = dd.update(old_items, s2, comparable=True, now=NOW + timedelta(days=1), run_id="r-next")     # 次の run は新しい版で引き継ぐ
    assert c3["comparable"] == 1 and c3["new_after_baseline"] == 0


def test_event_key_does_not_change_when_product_id_is_attached_later_and_keeps_stores_and_types_apart():
    """product_id は正本との照合で後から付く。付いても同じイベント（再査読 M-A）。店舗別・種別は分ける。"""
    a = _ev(lottery_id="lot-a", product_name="同じ商品")
    assert dd.event_key(a) == dd.event_key({**a, "product_id": "p9", "product_match": "exact"})
    assert dd.event_key({**a, "store_specific": True, "store_name": "A店"}) != dd.event_key({**a, "store_specific": True, "store_name": "B店"})
    assert dd.event_key(a) != dd.event_key({**a, "event_type": "PREORDER"})


def test_items_collapsing_into_one_key_are_counted_and_measured_once_in_the_same_run():
    """期間違いのラウンドなど、同じ鍵に潰れる複数のアイテムを同じ run で件数どおり測らない（1 イベントで公開の閾値を越えない。再レビュー M-1）。"""
    s0, _, _ = dd.update([_ev(lottery_id="seed", product_name="別の商品")], None, comparable=False, now=NOW - timedelta(days=1))
    rounds = [_ev(lottery_id=f"r{n}", product_name="同じ商品", published_at=f"2026-10-30T0{7 + n}:00:00+09:00",
                  application_start=f"2026-10-3{n}T09:00:00+09:00") for n in range(3)]
    s1, c, rows = dd.update(rounds, s0, comparable=True, now=NOW)
    assert c["events_active"] == 1 and c["new_after_baseline"] == 1 and c["measured"] == 1 and len(rows) == 1
    assert c["median_delay_hours"] == 0 and c["delay_values_withheld"] == 1 and len(s1["events"]) == 2


# ── 最終ゲートの Medium 2 件: 入力の鮮度（M-1）と イベントの同一性（M-2）────────────────────────

FRESH_AT = (NOW - timedelta(hours=1)).isoformat()
STALE_AT = (NOW - timedelta(hours=30)).isoformat()
URL1 = "https://x.example/news/623006/"


def _seeded(now_back=timedelta(days=2), **extra):
    """台帳を使い始めた後（trusted）の状態。CARD_LABO は 20 時間前に見えていた。"""
    s0, _, _ = dd.update([_ev(lottery_id="seed", product_name="別の商品", source_url="https://x.example/news/1/")], None, comparable=False,
                         now=NOW - now_back, run_id="r0")
    s1, _, _ = dd.update([_ev(lottery_id="seed", product_name="別の商品", source_url="https://x.example/news/1/")], s0, comparable=True,
                         now=NOW - timedelta(hours=20), run_id="r1")
    return s1


def test_input_freshness_gate_accepts_only_recent_generated_at():
    assert dd.input_is_fresh(FRESH_AT, FRESH_AT, now=NOW) is True
    assert dd.input_is_fresh(FRESH_AT, STALE_AT, now=NOW) is False                  # 片方でも古ければ古い
    assert dd.input_is_fresh(None, now=NOW) is False and dd.input_is_fresh("", now=NOW) is False and dd.input_is_fresh("壊れた", now=NOW) is False
    assert dd.input_is_fresh((NOW + timedelta(hours=2)).isoformat(), now=NOW) is False      # 未来の生成時刻も信用しない
    assert dd.input_is_fresh(now=NOW) is False


def test_stale_input_does_not_renew_sources_last_seen_or_ledger_and_is_not_comparable():
    s1 = _seeded()
    ev = [_ev(lottery_id="seed", product_name="別の商品", source_url="https://x.example/news/1/"),
          _ev(lottery_id="n9", product_name="停止中に公開", published_at="2026-10-29T08:00:00+09:00", source_url="https://x.example/news/9/")]
    s2, c, rows = dd.update(ev, s1, comparable=True, now=NOW, run_id="r2", healthy_sources={"CARD_LABO"}, input_fresh=False)
    assert s2 == s1                                                                  # 台帳は 1 文字も進めない（sources・last_seen・first_seen）
    assert c["comparable"] == 0 and c["stale_input"] == 1 and c["measured"] == 0 and c["new_after_baseline"] == 0 and rows == []
    assert c["source_not_observed_this_run"] == 1 and c["median_delay_hours"] == 0


def test_stale_input_with_no_previous_ledger_returns_no_ledger():
    s, c, _ = dd.update([_ev()], None, comparable=False, now=NOW, input_fresh=False)
    assert s == {} and c["stale_input"] == 1 and c["comparable"] == 0               # 台帳を作らない（次の run が、既存イベントを新規として測らない）
    s2, c2, _ = dd.update([_ev()], s, comparable=True, now=NOW + timedelta(days=1), run_id="r5")
    assert c2["comparable"] == 0 and c2["measured"] == 0


def test_outage_is_not_recovered_by_a_stale_file_and_recovery_needs_a_fresh_input():
    """停止中（古い生成物が残った日）を挟んでも、復旧日の「新規」は除外される。新しい入力で取得できたときだけ復旧。"""
    s1 = _seeded()
    pub = "2026-10-30T08:00:00+09:00"
    # 停止の 2 日: 古い生成物で 2 回動く（台帳は進まない）
    s2, _c, _r = dd.update([_ev(lottery_id="seed", product_name="別の商品", source_url="https://x.example/news/1/")], s1, comparable=True,
                           now=NOW - timedelta(hours=1), run_id="r2", input_fresh=False)
    s3, _c, _r = dd.update([], s2, comparable=True, now=NOW + timedelta(days=1), run_id="r3", input_fresh=False)
    # 復旧日（新しい入力）: 停止中に公開されたイベントは、取得元が 36 時間以上見えていないので測らない
    _, c, _r = dd.update([_ev(lottery_id="n9", product_name="停止中に公開", published_at=pub, source_url="https://x.example/news/9/")], s3,
                         comparable=True, now=NOW + timedelta(days=2), run_id="r4", input_fresh=True)
    assert c["measured"] == 0 and c["source_gap_excluded"] == 1


def test_fresh_input_updates_last_seen_and_real_recovery_is_measured_once_source_is_seen():
    s1 = _seeded()
    ev = [_ev(lottery_id="seed", product_name="別の商品", source_url="https://x.example/news/1/")]
    s2, c, _ = dd.update(ev, s1, comparable=True, now=NOW, run_id="r2", healthy_sources={"CARD_LABO"}, input_fresh=True)
    k = dd.event_key(ev[0])
    assert s2["events"][k]["last_seen"] != s1["events"][k]["last_seen"] and c["stale_input"] == 0 and c["comparable"] == 1
    assert s2["sources"]["CARD_LABO"] == NOW.isoformat(timespec="seconds")
    # 取得元が見えている日に出たイベントは測れる
    _, c2, _ = dd.update([*ev, _ev(lottery_id="n7", product_name="新規", published_at=(NOW + timedelta(hours=2)).isoformat(), source_url="https://x.example/news/7/")],
                         s2, comparable=True, now=NOW + timedelta(hours=6), run_id="r3", input_fresh=True)
    assert c2["measured"] == 1


def test_no_timestamp_only_renewal_when_the_same_stale_content_is_seen_again():
    """内容が同じ古い入力を何度見ても、時刻は進まない（台帳が同一）。"""
    s1 = _seeded()
    cur = s1
    for n in range(3):
        cur, _c, _r = dd.update([_ev(lottery_id="seed", product_name="別の商品", source_url="https://x.example/news/1/")], cur, comparable=True,
                                now=NOW + timedelta(hours=n), run_id=f"r{n + 2}", input_fresh=False)
    assert cur == s1


def test_stale_input_never_reaches_the_candidates_metrics_as_comparable():
    from src.research import candidates as rc
    keys = rc.COVERAGE_KEYS["tcg_detection_delay"]
    assert {"stale_input", "source_not_observed_this_run", "identity_ambiguous"} <= set(keys)


def test_same_event_url_with_renamed_product_product_id_and_dates_is_the_same_event():
    base = _ev(lottery_id="a", product_name="ポケモンカード 拡張パック", source_url=URL1)
    k = dd.event_key(base)
    assert dd.event_key({**base, "product_name": "ポケモンカード 拡張パック 抽選のお知らせ"}) == k          # 商品名の修正
    assert dd.event_key({**base, "product_name": "ポケモンカード　拡張パック【抽選】"}) == k
    assert dd.event_key({**base, "product_id": "p9", "product_match": "exact"}) == k                        # product_id が後から付く
    assert dd.event_key({**base, "application_start": None, "application_end": None, "lottery_id": "b"}) == k   # 期間が後から入る・lottery_id が変わる
    assert dd.event_key({**base, "source_url": URL1 + "?utm_source=x"}) == k                                  # 計測用パラメータ
    s1, _, _ = dd.update([_ev(lottery_id="seed", product_name="別", source_url="https://x.example/news/1/"), base], None, comparable=False, now=NOW - timedelta(days=2))
    s2, _, _ = dd.update([base], s1, comparable=True, now=NOW - timedelta(days=1), run_id="r1")          # 台帳を使い始めた時点で既にあった = baseline
    _, c, _ = dd.update([{**base, "product_name": "改名した商品", "product_id": "p9", "application_start": None}], s2, comparable=True, now=NOW, run_id="r2")
    assert c["measured"] == 0 and c["new_after_baseline"] == 0 and c["events_active"] == 1


def test_different_event_url_store_and_type_are_different_events():
    base = _ev(lottery_id="a", product_name="同じ商品", source_url=URL1)
    k = dd.event_key(base)
    assert dd.event_key({**base, "source_url": "https://x.example/news/623007/"}) != k                       # 別 URL（別回次）
    assert dd.event_key({**base, "store_specific": True, "store_name": "A店"}) != dd.event_key({**base, "store_specific": True, "store_name": "B店"})
    assert dd.event_key({**base, "event_type": "PREORDER"}) != k
    assert dd.event_key({**base, "retailer": "OTHER"}) == k                                                  # URL が固有なので、小売の表記ゆれでは変わらない


def test_generic_urls_are_not_used_as_event_identity():
    for u in ("https://x.example/", "https://x.example", "https://x.example/news/", "https://x.example/news", "https://x.example/search?q=abc",
              "https://x.example/category/pokemon/", "https://x.example/shop/otaro/", "https://x.example/list?page=2", "ftp://x.example/news/12/", "", None):
        assert dd.specific_url(u) == "", u
    for u in ("https://www.c-labo.jp/shop/otaro/blog/623006/", "https://www.hbst.net/?p=411488", "https://pokemon.fukufukutoreka.com/lottery/24",
              "https://www.pokemoncenter-online.com/news/?id=20260929"):
        assert dd.specific_url(u), u
    a, b = _ev(lottery_id="a", product_name="商品A", source_url="https://x.example/news/"), _ev(lottery_id="b", product_name="商品B", source_url="https://x.example/news/")
    assert dd.event_key(a) != dd.event_key(b) and dd.event_key(a).startswith("n|")                             # 一般的な URL は名前の鍵に落ちる（商品 A と B を潰さない）


def test_two_products_under_one_announcement_url_stay_separate_and_unseen_names_are_not_measured():
    u = "https://www.pokemoncenter-online.com/news/?id=20260929"
    a, b = _ev(lottery_id="a", product_name="商品A", source_url=u), _ev(lottery_id="b", product_name="商品B", source_url=u)
    assert dd.event_key(a, multi_urls={dd.specific_url(u)}) != dd.event_key(b, multi_urls={dd.specific_url(u)})
    s0, _, _ = dd.update([_ev(lottery_id="seed", product_name="別", source_url="https://x.example/news/1/")], None, comparable=False, now=NOW - timedelta(days=3))
    s1, _, _ = dd.update([_ev(lottery_id="seed", product_name="別", source_url="https://x.example/news/1/"), a, b], s0, comparable=True,
                         now=NOW - timedelta(days=2), run_id="r1")
    assert len([v for v in s1["events"].values() if v.get("url")]) == 3
    # 片方が終了して 1 件になっても、台帳に 2 件ある URL は共有のまま（鍵が切り替わって「新規」にならない）
    s2, c, _ = dd.update([a], s1, comparable=True, now=NOW - timedelta(days=1), run_id="r2")
    assert c["measured"] == 0 and c["new_after_baseline"] == 0
    # 共有 URL で台帳に無い名前（新規か改名か区別できない）は測らない
    _, c3, _ = dd.update([{**a, "product_name": "商品A 改"}], s2, comparable=True, now=NOW, run_id="r3")
    assert c3["measured"] == 0 and c3["identity_ambiguous"] >= 1


def test_old_event_key_version_ledger_is_not_carried_after_the_rule_change():
    s1 = _seeded()
    assert s1["event_key_version"] == dd.EVENT_KEY_VERSION == 4
    assert dd.sanitize({**s1, "event_key_version": 3}) == {} and dd.sanitize({k: v for k, v in s1.items() if k != "event_key_version"}) == {}


def test_events_without_a_specific_url_are_never_measured_because_a_rename_cannot_be_told_from_a_new_event():
    """URL が無い・一般的な URL のイベントは、名前が変わると「新規」か「改名」か区別できない。測らない（再監査 M-A）。"""
    for url in (None, "", "https://x.example/lottery/", "https://x.example/news/"):
        s0, _, _ = dd.update([_ev(lottery_id="seed", product_name="別の商品")], None, comparable=False, now=NOW - timedelta(days=3))
        base = _ev(lottery_id="a", product_name="ポケカ ABC BOX", source_url=url, published_at="2026-10-29T08:00:00+09:00")
        s1, _, _ = dd.update([_ev(lottery_id="seed", product_name="別の商品"), base], s0, comparable=True, now=NOW - timedelta(days=2), run_id="r1")
        s2, _, _ = dd.update([base], s1, comparable=True, now=NOW - timedelta(days=1), run_id="r2")
        _, c, _ = dd.update([{**base, "product_name": "ポケカ ABC BOX 【抽選】"}], s2, comparable=True, now=NOW, run_id="r3")
        assert c["measured"] == 0 and c["identity_ambiguous"] >= 1, url


def test_http_and_https_of_the_same_event_url_are_the_same_event():
    a = _ev(lottery_id="a", source_url="http://x.example/news/623006/")
    assert dd.event_key(a) == dd.event_key({**a, "source_url": "https://X.example/news/623006"})


def test_event_that_gets_a_specific_url_later_is_the_same_event_and_is_not_measured_as_new():
    """URL が無かった（名前の鍵で台帳に載った）イベントに後から固有 URL が付いても、新規として測らない（最終レビュー M-1）。"""
    s0, _, _ = dd.update([_ev(lottery_id="seed", product_name="別の商品")], None, comparable=False, now=NOW - timedelta(days=4))
    foo = _ev(lottery_id="foo", product_name="ポケカ Foo BOX", source_url=None, published_at="2026-10-28T08:00:00+09:00")
    s1, _, _ = dd.update([_ev(lottery_id="seed", product_name="別の商品"), foo], s0, comparable=True, now=NOW - timedelta(days=3), run_id="r1")
    s2, _, _ = dd.update([foo], s1, comparable=True, now=NOW - timedelta(days=2), run_id="r2")
    with_url = {**foo, "source_url": "https://x.jp/blog/123/"}
    s3, c, _ = dd.update([with_url], s2, comparable=True, now=NOW, run_id="r3")
    assert c["measured"] == 0 and c["events_active"] == 1
    k = dd.event_key(with_url)
    assert k in s3["events"] and dd.name_event_key(foo) not in s3["events"]                                  # 鍵が移っている（二重に載らない）
    assert s3["events"][k]["first_seen"] == s1["events"][dd.name_event_key(foo)]["first_seen"]               # first_seen を保つ
    assert s3["events"][k]["url"] == "https://x.jp/blog/123"


def test_event_published_before_the_previous_observation_of_its_source_is_never_measured_as_new():
    """前回その取得元を観測した後に公開されたイベントだけ測る。前に公開されていたものが今回初めて「新規」に見えても測らない
    （URL の付け替え・日程の補完で受付中になった・種別の再分類。最終監査 M-2）。"""
    s1 = _seeded()                                                                   # CARD_LABO は NOW-20h に見えていた
    last = NOW - timedelta(hours=20)
    # (1) 情報元 URL が変わった（前に公開されていた）
    before = {"published_at": (last - timedelta(hours=40, minutes=17)).isoformat()}
    changed_url = _ev(lottery_id="seed", product_name="別の商品", source_url="https://x.example/news/99999/", **before)
    _, c, _ = dd.update([changed_url], s1, comparable=True, now=NOW, run_id="r2", healthy_sources={"CARD_LABO"})
    assert c["measured"] == 0 and c["previously_observable_excluded"] + c["identity_ambiguous"] >= 1
    # (2) 日程不足で台帳に載らず、後から補完されて受付中になった（前に公開されていた）
    late = _ev(lottery_id="late", product_name="後から受付中", **before)
    _, c2, _ = dd.update([late], s1, comparable=True, now=NOW, run_id="r2", healthy_sources={"CARD_LABO"})
    assert c2["measured"] == 0 and c2["previously_observable_excluded"] == 1
    # (3) 本当に前回の観測の後に公開された新規は測る
    fresh = _ev(lottery_id="fresh", product_name="本当の新規", published_at=(last + timedelta(hours=2)).isoformat())
    _, c3, _ = dd.update([fresh], s1, comparable=True, now=NOW, run_id="r2", healthy_sources={"CARD_LABO"})
    assert c3["measured"] == 1 and c3["previously_observable_excluded"] == 0


def test_manual_events_and_unhealthy_sources_do_not_make_a_blocked_source_look_observed():
    """ブロック中の取得元（手動の確認済みイベントだけがある）を「見えていた」ことにしない。復旧日の停止中の公開分は除外される（最終監査 M-1）。"""
    pco = dict(retailer="PCO", collection_method="MANUAL_VERIFIED", published_at="2026-10-20T08:00:00+09:00")
    s0, _, _ = dd.update([_ev(lottery_id="seed", product_name="別の商品")], None, comparable=False, now=NOW - timedelta(days=5), run_id="r0")
    cur = s0
    for n in range(1, 5):                                                            # ブロックが続く 4 日間: 手動の有効イベントだけがある
        cur, _c, _r = dd.update([_ev(lottery_id="man", product_name="手動", **pco)], cur, comparable=True, now=NOW - timedelta(days=5 - n),
                                run_id=f"r{n}", healthy_sources=set())
        assert "PCO" not in cur["sources"]
    # healthy_sources が渡されない呼び出しでも、手動のイベントは取得元の根拠にならない
    cur2, _c, _r = dd.update([_ev(lottery_id="man", product_name="手動", **pco)], s0, comparable=True, now=NOW - timedelta(days=1), run_id="x")
    assert "PCO" not in cur2["sources"]
    # 復旧日: 停止中に公開された新規は、取得元が見えていなかったので測らない
    _, c, _ = dd.update([_ev(lottery_id="n1", product_name="停止中の公開", retailer="PCO", published_at=(NOW - timedelta(days=2)).isoformat())],
                        cur, comparable=True, now=NOW, run_id="r9", healthy_sources={"PCO"})
    assert c["measured"] == 0 and c["source_gap_excluded"] == 1


def test_event_already_measured_in_an_earlier_run_is_not_counted_again_even_if_the_source_record_is_old():
    """前の run で測った（または除外した）イベントを、翌日の run でまた測らない。観測済み除外（前回の観測より前の公開）とは独立した防御。"""
    s1 = _seeded()
    fresh = _ev(lottery_id="fresh", product_name="本当の新規", published_at=(NOW - timedelta(hours=18)).isoformat())
    s2, c, _ = dd.update([fresh], s1, comparable=True, now=NOW - timedelta(hours=10), run_id="r2", healthy_sources={"CARD_LABO"})
    assert c["measured"] == 1
    s2 = {**s2, "sources": {"CARD_LABO": (NOW - timedelta(days=1)).isoformat(timespec="seconds")}}            # 取得元の記録が古い（観測済み除外が効かない状態）
    _, c2, _ = dd.update([fresh], s2, comparable=True, now=NOW, run_id="r3", healthy_sources={"CARD_LABO"})
    assert c2["measured"] == 0


def test_sources_are_recorded_only_for_healthy_sources_when_they_are_given():
    s1 = _seeded()
    ev = [_ev(lottery_id="seed", product_name="別の商品"), _ev(lottery_id="o", product_name="他社", retailer="OTHER_SHOP")]
    s2, _c, _r = dd.update(ev, s1, comparable=True, now=NOW, run_id="r2", healthy_sources={"CARD_LABO"})
    assert "OTHER_SHOP" not in s2["sources"] and s2["sources"]["CARD_LABO"] == NOW.isoformat(timespec="seconds")
    s3, _c, _r = dd.update(ev, s1, comparable=True, now=NOW, run_id="r2")                                  # 渡されない呼び出しだけ、収集した受付中のイベントを根拠にする
    assert s3["sources"]["OTHER_SHOP"] == NOW.isoformat(timespec="seconds")


def test_midnight_published_at_is_date_only_unknown_and_manual_events_are_not_measured():
    """収集器は日付だけの公開日を T00:00:00+09:00 に変換して出す。時刻の精度が無いので UNKNOWN（最終監査 M-1）。手動イベントは測らない。"""
    for v in ("2026-10-02", "2026-10-02T00:00:00+09:00", "2026-10-02T00:00:00", "2026-10-02 00:00:00 JST", "2026-10-02T00:00+09:00", "2026-10-02T00:00:00Z"):
        assert dd._date_only(v) is True, v
    for v in ("2026-10-02T00:05:00+09:00", "2026-10-02T08:00:00+09:00", "2026-10-02T12:00:00+09:00", "", None):
        assert dd._date_only(v) is False, v
    s1 = _seeded()
    last = NOW - timedelta(hours=20)
    mid = (last + timedelta(hours=3)).replace(hour=0, minute=0, second=0).isoformat()
    ev = [_ev(lottery_id=f"m{n}", product_name=f"日付だけ{n}", published_at=mid) for n in range(3)]
    _, c, _ = dd.update(ev, s1, comparable=True, now=NOW, run_id="r2", healthy_sources={"CARD_LABO"})
    assert c["measured"] == 0 and c["unknown_published_at"] + c["previously_observable_excluded"] == 3 and c["median_delay_hours"] == 0
    manual = _ev(lottery_id="man", product_name="手動", collection_method="MANUAL_VERIFIED", published_at=(last + timedelta(hours=2)).isoformat())
    _, c2, _ = dd.update([manual], s1, comparable=True, now=NOW, run_id="r2", healthy_sources={"CARD_LABO"})
    assert c2["measured"] == 0 and c2["unknown_published_at"] == 1


def test_ambiguous_new_events_are_not_counted_as_baseline():
    s0, _, _ = dd.update([_ev(lottery_id="seed", product_name="別の商品")], None, comparable=False, now=NOW - timedelta(days=3))
    s1, _, _ = dd.update([_ev(lottery_id="seed", product_name="別の商品")], s0, comparable=True, now=NOW - timedelta(days=2), run_id="r1")
    amb = _ev(lottery_id="a", product_name="URL なし", source_url=None)
    _, c, _ = dd.update([amb], s1, comparable=True, now=NOW - timedelta(days=1), run_id="r2")
    assert c["identity_ambiguous"] == 1 and c["baseline_events"] == 0
