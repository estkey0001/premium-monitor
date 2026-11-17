# -*- coding: utf-8 -*-
"""TCG の週次の更新（src/research/tcg_refresh.py）。ネットワーク・実データは使わない。

守ること: 集約サイトだけは VERIFIED にしない・遮断を「イベント無し」にしない・状態は今の日時から作り直す・
同じイベントを二重にしない・商品の種類（BOX / パック / カードセット）を混ぜない・再確認で日付を新しくしない・通知は送らない。
"""
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.research import tcg_refresh as R
from src.research import weekly_import as W
from src.tcg.lottery import manual as M

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=JST)
DATE = "2026-11-18"
GEO_URL = "https://geo-online.co.jp/news/790"


def _ev(**kw):
    base = {
        "kind": "LOTTERY_OPEN", "product_name": "ポケモンカードゲーム MEGA 拡張パック「ハドウシーカー」BOX", "tcg": "POKEMON", "retailer": "ゲオ",
        "application_start": "2026-11-18T10:00", "application_end": "2026-11-21T23:59", "winner_announcement": "2026-11-25",
        "purchase_start": "2026-11-26", "purchase_end": "2026-11-29", "official_url": GEO_URL, "source_url": GEO_URL,
        "source_type": "OFFICIAL", "checked_at": "2026-11-18 JST", "status": "OPEN", "confidence": "high", "classification": "FOUND",
        "retail_price": 6000, "eligibility": "テスト",
    }
    base.update(kw)
    return base


def _ver(**kw):
    v = {"primary_page_url": GEO_URL, "page_fetch_status": "OK",
         "page_facts": {"product": "ポケモンカードゲーム MEGA 拡張パック「ハドウシーカー」BOX", "application_start": "2026-11-18T10:00",
                        "application_end": "2026-11-21T23:59", "winner_announcement": "2026-11-25", "purchase_start": "2026-11-26",
                        "purchase_end": "2026-11-29", "price": "6,000円", "eligibility": "テスト"},
         "operator_evidence": {"url": "https://geo-online.co.jp/company/", "operator_name": "株式会社ゲオ", "quote": "会社概要"},
         "verdict": "PRIMARY_VERIFIED", "reason": ""}
    v.update(kw)
    return v


SRCS = [{"source": "GEO", "result": "FOUND", "url": GEO_URL, "checked_at": "2026-11-18 JST"}]


def _dir(tmp_path, events=None, sources=None):
    d = tmp_path / "w"
    d.mkdir()
    (d / "research_tcg_A.json").write_text(json.dumps({"date": DATE, "source_results": sources or [], "events": events or []}, ensure_ascii=False), encoding="utf-8")
    return d


def _run(tmp_path, events, sources=None, public=None, collectors=None, csv_rows=None):
    d = _dir(tmp_path, events, sources)
    csv_path = tmp_path / "v.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=M.CSV_COLUMNS)
        w.writeheader()
        for r in csv_rows or []:
            w.writerow(r)
    return R.refresh(d, DATE, now=NOW, recheck=False, csv_path=csv_path, public_events=public or [], collector_results=collectors or [])


# ---- 取得元の結果の意味 ----
def _src(**kw):
    s = {"source": "GEO", "health": "OK_NO_EVENTS", "state": "NO_ACTIVE_LOTTERY", "adapter": "geo_lottery", "retailer": "ゲオ",
         "source_id": "GEO", "last_checked": "2026-11-17T21:53:54+09:00", "last_success": "2026-11-17T21:54:55+09:00",
         "active_lotteries": 0, "blocked": False}
    s.update(kw)
    return s


def test_collector_blocked_is_not_no_event(tmp_path):
    p = tmp_path / "s.json"
    # health が OK_NO_EVENTS でも、状態が SOURCE_BLOCKED なら読めていない（遮断を「イベント無し」にしない）
    p.write_text(json.dumps({"sources": [_src(state="SOURCE_BLOCKED", blocked=True, error="HTTP 403")]}), encoding="utf-8")
    assert R.collector_source_results(p, research_date=DATE)[0]["result"] == "BLOCKED"
    p.write_text(json.dumps({"sources": [_src(health="OK_NO_EVENTS", state="SOURCE_BLOCKED")]}), encoding="utf-8")
    assert R.collector_source_results(p, research_date=DATE)[0]["result"] == "BLOCKED"


def test_collector_results_skip_unmonitored_stale_and_adapterless(tmp_path):
    p = tmp_path / "s.json"
    rows = [_src(state="SOURCE_NOT_MONITORED"), _src(last_checked="2026-10-01T00:00:00+09:00"), _src(adapter=None), _src(last_checked=None)]
    p.write_text(json.dumps({"sources": rows}), encoding="utf-8")
    assert R.collector_source_results(p, research_date=DATE) == []             # 読んでいない取得元を読んだことにしない


def test_collector_found_and_no_event_semantics(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"sources": [_src(health="HEALTHY", state="ACTIVE_LOTTERY", active_lotteries=3), _src(source_id="X", retailer="Y")]}), encoding="utf-8")
    r = R.collector_source_results(p, research_date=DATE)
    assert [x["result"] for x in r] == ["FOUND", "NO_EVENT_FOUND"]            # 一覧を読んだだけで「イベント無し」とは確定しない


def test_top_page_only_never_confirmed_no_current_event_and_blocked_is_not_raw_read():
    rs = [{"source": "GEO", "result": "NO_CURRENT_EVENT"},                          # evidence 無し → NO_EVENT_FOUND まで
          {"source": "ヨドバシ", "result": "BLOCKED", "reason": "r", "alternative_source": "a", "alternative_finding": "f"},
          {"source": "Joshin", "result": "FAILED"}]
    rep = R.source_report(rs)
    assert rep["per_source"]["geo"] == "NO_EVENT_FOUND" and rep["sources_confirmed_no_current_event"] == 0
    assert rep["per_source"]["yodobashi"] == "BLOCKED" and rep["per_source"]["joshin"] == "FAILED"
    assert rep["sources_checked"] == 3 and rep["sources_not_researched"] == 14
    assert rep["raw_read_coverage_pct"] == round(100 / 17, 2)                        # BLOCKED・FAILED は読めた扱いにしない
    assert rep["accounted_coverage_pct"] == round(200 / 17, 2)                       # 理由を 3 つとも記録した BLOCKED だけ accounted


# ---- 商品の同一性と重複 ----
def test_same_product_does_not_mix_box_pack_cardset_or_series_only():
    a = "ポケモンカードゲーム MEGA 拡張パック「ハドウシーカー」（1BOX）"
    assert R.same_product(a, "ポケモンカードゲーム MEGA 拡張パック ハドウシーカー（BOX）")
    assert not R.same_product(a, "ポケモンカードゲーム MEGA 拡張パック ハドウシーカー 5パック")          # BOX とパック単位
    assert not R.same_product("ポケモンカードゲーム MEGA 拡張パック 30th CELEBRATION", "ポケモンカードゲームMEGA 30th CELEBRATION カードセット9種")
    assert not R.same_product("ポケモンカードゲーム 拡張パック", "ポケモンカードゲーム スターターデッキ")      # シリーズ名・一般名詞だけでは同じにしない
    assert not R.same_product("ONE PIECEカードゲーム ブースターパック 神の支配【OP-18】", "エクストラブースター ONE PIECE Heroines Edition vol.2【EB-05】")


def test_same_event_requires_retailer_store_type_and_end_day():
    base = {"tcg": "POKEMON", "retailer": "CARD_LABO", "store_name": "浜松店", "event_type": "LOTTERY", "application_end": "2026-11-19T23:59:00+09:00",
            "product_name": "拡張パック「30th CELEBRATION」", "source_url": "https://www.c-labo.jp/a/1"}
    other = dict(base, product_name="ポケモンカードゲーム MEGA 拡張パック 30th CELEBRATION", source_url="https://www.c-labo.jp/a/2")
    assert R.same_event(base, other)
    assert not R.same_event(base, dict(other, store_name="岐阜店"))
    assert not R.same_event(base, dict(other, application_end="2026-11-20T23:59:00+09:00"))
    assert not R.same_event(base, dict(other, event_type="PREORDER"))
    assert not R.same_event(base, dict(other, retailer="GEO"))


# ---- 状態は今の日時から ----
def test_status_is_derived_from_now_and_ai_status_is_ignored():
    ev = _ev(status="OPEN", application_start="2026-11-01", application_end="2026-11-05", winner_announcement="2026-11-08",
             purchase_start="2026-11-09", purchase_end="2026-11-12")
    assert R.derive_status(ev, NOW) == "ENDED"                                       # AI が OPEN と申告しても、締切後・購入期間後は ENDED
    assert R.derive_status(_ev(application_start="2026-11-18", application_end="2026-11-21"), NOW) == "UPCOMING"   # 日付だけ・開始日当日は開始前
    assert R.derive_status(_ev(), NOW) == "OPEN"
    assert R.derive_status(_ev(application_end="2026-11-19T10:00"), NOW) == "ENDING_SOON"
    assert R.derive_status({}, NOW) == "UNKNOWN"


def test_old_search_result_is_not_revived_as_open(tmp_path):
    ev = _ev(application_start="2026-11-01", application_end="2026-11-05", purchase_end="2026-11-12", status="OPEN", classification="VERIFIED")
    st = _run(tmp_path, [ev, ], public=[])
    c = st["candidates"][0]
    assert c["verification_status"] == "EXPIRED" and c["derived_status"] != "OPEN" and not st["new_rows"]


# ---- 公開の条件 ----
def test_aggregator_only_stays_discovered_and_is_not_published(tmp_path):
    ev = _ev(source_url="https://nyuka-now.com/archives/1", official_url="", source_type="AGGREGATOR", classification="VERIFIED")
    st = _run(tmp_path, [ev])
    c = st["candidates"][0]
    assert c["verification_status"] == "DISCOVERED" and "no_primary_evidence" in c["reasons"]
    assert st["new_rows"] == [] and st["by_status"]["DISCOVERED"] == 1


def test_primary_verified_event_becomes_new_row_without_claiming_human_confirmation(tmp_path):
    st = _run(tmp_path, [dict(_ev(), verification=_ver())], sources=SRCS)
    assert st["by_status"]["VERIFIED"] == 1 and len(st["new_rows"]) == 1
    row = st["new_rows"][0]
    assert row["human_confirmed"] == "false" and row["source_url"] == GEO_URL and row["retailer"] == "GEO"
    assert R.validate(st) == []
    c = st["candidates"][0]
    assert c["tcg"] == "POKEMON" and c["normalized_product_name"] and c["application_end"] and c["checked_at"] == "2026-11-18 JST"


def test_verification_that_is_not_primary_does_not_publish(tmp_path):
    st = _run(tmp_path, [dict(_ev(), verification=_ver(verdict="UNVERIFIED"))])
    assert st["new_rows"] == [] and st["candidates"][0]["verification_status"] == "DISCOVERED"
    (tmp_path / "b").mkdir()
    bad = _ver(operator_evidence={"url": "", "operator_name": "", "quote": ""})
    st2 = _run(tmp_path / "b", [dict(_ev(), verification=bad)])            # 運営者の証拠が無ければ公開しない
    assert st2["new_rows"] == [] and st2["candidates"][0]["verification_status"] == "DISCOVERED"


def test_duplicate_of_public_event_and_within_research_is_not_published_twice(tmp_path):
    pub = [{"lottery_id": "lot-1", "tcg": "POKEMON", "retailer": "GEO", "store_name": None, "event_type": "LOTTERY",
            "application_end": "2026-11-21T23:59:00+09:00", "product_name": "ポケモンカードゲーム MEGA 拡張パック ハドウシーカー BOX", "source_url": "https://x/y"}]
    st = _run(tmp_path, [dict(_ev(), verification=_ver())], public=pub)
    assert st["new_rows"] == [] and st["candidates"][0]["verification_status"] == "DUPLICATE" and st["candidates"][0]["duplicate_of"] == "lot-1"
    # 同じ調査の中に同じイベントが 2 回（別の URL・別の表記）あっても 1 件
    a = dict(_ev(), verification=_ver())
    b = dict(_ev(product_name="拡張パック「ハドウシーカー」（BOX）", source_url="https://geo-online.co.jp/news/791"),
             verification=_ver(primary_page_url="https://geo-online.co.jp/news/791", page_facts=dict(_ver()["page_facts"], product="拡張パック「ハドウシーカー」（BOX）")))
    (tmp_path / "2").mkdir()
    st2 = _run(tmp_path / "2", [a, b])
    assert len(st2["new_rows"]) == 1 and st2["by_status"]["DUPLICATE"] == 1


def test_event_type_without_lottery_import_path_is_not_published(tmp_path):
    st = _run(tmp_path, [dict(_ev(kind="RESTOCK"), verification=_ver())])
    assert st["new_rows"] == [] and st["candidates"][0]["verification_status"] != "VERIFIED"


def test_stale_or_missing_checked_at_is_not_current(tmp_path):
    for n, ck in enumerate(("2026-11-01 JST", "2026-11-19 JST", "")):
        d = tmp_path / f"c{n}"
        d.mkdir()
        st = _run(d, [dict(_ev(checked_at=ck), verification=_ver())])
        assert st["new_rows"] == [] and st["candidates"][0]["verification_status"] != "VERIFIED", ck


# ---- 変化・通知・履歴 ----
def _pub(key, status, **kw):
    return dict({"key": key, "tcg": "POKEMON", "retailer": "GEO", "product": "p", "event_type": "LOTTERY", "status": status}, **kw)


def test_diff_events_use_existing_vocabulary():
    prev = [_pub("a", "UPCOMING"), _pub("b", "OPEN"), _pub("c", "OPEN"), _pub("d", "RESULT_PENDING"), _pub("e", "WINNER_ANNOUNCED"), _pub("f", "OPEN")]
    cur = [_pub("a", "OPEN"), _pub("b", "ENDING_SOON"), _pub("c", "CLOSED"), _pub("d", "WINNER_ANNOUNCED"), _pub("e", "WINNER_PURCHASE_PERIOD"),
           _pub("f", "OPEN"), _pub("g", "OPEN")]
    got = {e["key"]: e["type"] for e in R.diff_events(prev, cur)}
    assert got == {"a": "UPCOMING_TO_OPEN", "b": "OPEN_TO_ENDING", "c": "OPEN_TO_CLOSED", "d": "WINNER_ANNOUNCED", "e": "PURCHASE_PERIOD_STARTED", "g": "NEW_EVENT"}
    assert R.diff_events(None, cur) == []                                            # 基準が無い週に NEW_EVENT を大量に出さない


def test_notification_is_dry_run_and_never_sends():
    ev = R.diff_events([_pub("a", "UPCOMING")], [_pub("a", "OPEN"), _pub("n", "OPEN")])
    n = R.notification_dry_run(ev, [_pub("z", "ENDING_SOON")])
    assert n["mode"] == "DRY_RUN" and n["sent"] == 0 and n["would_notify"] == 3
    assert {i["label"] for i in n["items"]} == {"受付開始", "新規の抽選・予約", "締切間近"}


def test_history_same_day_overwrites_and_keeps_limit():
    h = None
    for i in range(30):
        h = R.merge_history(h, {"research_date": f"2026-10-{i + 1:02d}"})
    assert len(h["snapshots"]) == R.HISTORY_KEEP and h["snapshots"][-1]["research_date"] == "2026-10-30"
    h = R.merge_history(h, {"research_date": "2026-10-30", "x": 1})
    assert len(h["snapshots"]) == R.HISTORY_KEEP and h["snapshots"][-1].get("x") == 1


# ---- 既存の公開イベントの再確認 ----
def test_recheck_does_not_change_dates_and_separates_results():
    rows = [{"retailer": "SANYODO", "product": "ポケモンカードゲーム MEGA 拡張パック「ハドウシーカー」（1BOX）", "source_url": "https://a/1", "application_end": "2026-11-15T23:59:00+09:00"},
            {"retailer": "SURUGAYA", "product": "ポケモンカードゲーム MEGA 拡張パック ハドウシーカー（BOX）", "source_url": "https://a/2", "application_end": "2026-11-22T23:59:00+09:00"},
            {"retailer": "X", "product": "ハドウシーカー", "source_url": "https://a/3", "application_end": "2026-11-22T23:59:00+09:00"}]
    pages = {"https://a/1": "<p>ハドウシーカー 1BOX 抽選 11月15日 締切</p>", "https://a/2": "<p>ハドウシーカー 応募は11/30まで</p>", "https://a/3": None}
    out = R.recheck_public(rows, lambda u: (pages[u], "" if pages[u] else "HTTP 403"), NOW)
    assert [o["result"] for o in out] == ["RECONFIRMED", "PAGE_CHANGED", "FETCH_FAILED"]
    assert out[1]["reason"] == "application_end_not_found" and out[2]["reason"] == "HTTP 403"
    assert [o["application_end"] for o in out] == [r["application_end"] for r in rows]


# ---- 書き込み ----
def test_dry_run_writes_nothing_and_apply_appends_only_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "WEEKLY_ROOT", tmp_path / ".private" / "weekly")      # 実際の .private を触らない
    st = _run(tmp_path, [dict(_ev(), verification=_ver()), _ev(product_name="集約だけ", source_url="https://nyuka-now.com/1", classification="VERIFIED")], sources=SRCS)
    csv_path = tmp_path / "v.csv"
    before = csv_path.read_bytes()
    out = R.summarize(st, apply=False, written=None, problems=R.validate(st))
    assert out["mode"] == "DRY_RUN" and csv_path.read_bytes() == before and not (tmp_path / "w" / R.CANDIDATE_FILE).exists()
    assert out["verified_new"] == 1 and out["unverified"] == 1 and out["notification_dry_run"]["sent"] == 0
    exp = tmp_path / "exp"
    written = R.write_all(st, tmp_path / "w", export_dir=exp, csv_path=csv_path)
    # --dir が .private の外なら、未確認の候補はそこへ書かず既定の非公開の場所へ書く
    assert (exp / R.HISTORY_FILE).exists() and not (tmp_path / "w" / R.CANDIDATE_FILE).exists()
    assert (tmp_path / ".private" / "weekly" / DATE / R.CANDIDATE_FILE).exists()
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8", newline="")))
    assert len(rows) == 1 and rows[0]["source_url"] == GEO_URL and written
    hist = json.loads((exp / R.HISTORY_FILE).read_text(encoding="utf-8"))
    snap = hist["snapshots"][-1]
    assert snap["counts"]["verified_new"] == 1 and snap["counts"]["unverified"] == 1 and snap["notification_dry_run"]["sent"] == 0
    assert "nyuka-now" not in json.dumps(hist, ensure_ascii=False)                 # 未確認の候補は公開の履歴に入れない


def test_validate_rejects_ended_human_claim_and_missing_files(tmp_path):
    st = _run(tmp_path, [dict(_ev(), verification=_ver())], sources=SRCS)
    st["new_rows"][0]["human_confirmed"] = "true"
    assert any("人の確認を名乗" in p for p in R.validate(st))
    empty = R.refresh(tmp_path / "nofiles", DATE, now=NOW, recheck=False, csv_path=tmp_path / "v.csv", public_events=[], collector_results=[])
    assert any("調査ファイル" in p for p in R.validate(empty)) and any("0 件" in p for p in R.validate(empty))


# ---- 品質の数（すべて 0） ----
def test_quality_checks_are_zero_for_clean_run_and_catch_violations(tmp_path):
    st = _run(tmp_path, [dict(_ev(), verification=_ver())], sources=SRCS)
    q = R.quality_checks(st)
    assert q == {"expired_shown_open": 0, "unverified_shown_verified": 0, "duplicate_event": 0,
                 "wrong_product_identity": 0, "fake_checked_at": 0, "source_failure_treated_no_event": 0}
    assert R.validate(st) == []
    # 違反が混ざったら書かない: 人の確認を名乗る行・期限切れの行・同じイベントの 2 行目
    bad = dict(st["new_rows"][0], human_confirmed="true", application_start="2026-11-01T00:00:00+09:00", application_end="2026-11-05T23:59:00+09:00",
               purchase_end="2026-11-10T23:59:00+09:00")
    st2 = dict(st, new_rows=[bad, dict(st["new_rows"][0], source_url="https://geo-online.co.jp/news/999")])
    q2 = R.quality_checks(st2)
    assert q2["unverified_shown_verified"] >= 1 and q2["expired_shown_open"] >= 1
    assert any("品質" in p for p in R.validate(st2))
    st3 = dict(st, new_rows=[st["new_rows"][0], dict(st["new_rows"][0], source_url="https://geo-online.co.jp/news/999")])
    assert R.quality_checks(st3)["duplicate_event"] == 1


# ---- レビューの指摘への回帰 ----
def test_official_domain_without_page_level_verification_is_not_published(tmp_path):
    # 公式ドメインの URL でも、運営者自身のページ本文での確認（verification）が無ければ AI の日付のまま公開しない
    st = _run(tmp_path, [_ev(classification="FOUND")], sources=SRCS)
    c = st["candidates"][0]
    assert c["verification_status"] == "DISCOVERED" and "no_page_level_verification" in c["reasons"] and st["new_rows"] == []


def test_existing_manual_csv_row_blocks_same_event_with_other_url(tmp_path):
    old = {k: "" for k in M.CSV_COLUMNS}
    old.update(tcg="POKEMON", product="ポケモンカードゲーム MEGA 拡張パック「ハドウシーカー」BOX", retailer="GEO", event_type="LOTTERY",
               application_end="2026-11-21T23:59:00+09:00", source_url="https://geo-online.co.jp/news/700", verified_at="2026-11-17", verified_by="x")
    st = _run(tmp_path, [dict(_ev(), verification=_ver())], sources=SRCS, csv_rows=[old])
    assert st["new_rows"] == [] and st["candidates"][0]["verification_status"] == "DUPLICATE"


def test_date_match_does_not_match_inside_other_numbers():
    assert not R._mentions_date("締切は11/21です", "2026-11-02T23:59")
    assert not R._mentions_date("11月5日まで", "2026-01-05T00:00")
    assert not R._mentions_date("12/10 締切", "2026-12-01T00:00")
    assert R._mentions_date("締切は11/21です", "2026-11-21T23:59") and R._mentions_date("2026年11月2日", "2026-11-02T00:00")


def test_new_event_is_only_reported_when_live():
    cur = [_pub("e", "ENDED"), _pub("u", "UNKNOWN"), _pub("o", "OPEN")]
    assert [e["key"] for e in R.diff_events([_pub("zzz", "OPEN")], cur)] == ["o"]


def test_verified_at_is_the_page_read_day_not_the_run_time(tmp_path):
    st = _run(tmp_path, [dict(_ev(checked_at="2026-11-15 JST"), verification=_ver())], sources=SRCS)
    assert st["new_rows"][0]["verified_at"] == "2026-11-15" and R.quality_checks(st)["fake_checked_at"] == 0
    st["new_rows"][0]["verified_at"] = "2026-11-18T12:00:00+09:00"            # 実行日時にすると品質で検出される
    assert R.quality_checks(st)["fake_checked_at"] == 1


def test_non_jst_offset_is_converted_not_dropped():
    assert R._split("2026-11-19T06:00:00Z") == ("2026-11-19T15:00:00+09:00", None)
    assert R.derive_status({"application_start": "2026-11-18T00:00:00+09:00", "application_end": "2026-11-19T06:00:00Z"}, NOW) == "OPEN"


def test_conflicting_source_results_take_the_worse_side_and_identity_fixes():
    rs = [{"source": "GEO", "result": "BLOCKED", "reason": "403", "alternative_source": "a", "alternative_finding": "f"},
          {"source": "ゲオ（自動収集 GEO）", "result": "NO_EVENT_FOUND"}]
    rep = R.source_report(rs)
    assert rep["per_source"]["geo"] == "BLOCKED" and rep["conflicts"][0]["key"] == "geo"        # 別の URL が読めても、遮断を「イベント無し」にしない
    assert R.source_report([{"source": "GEO", "result": "FOUND"}, {"source": "GEO", "result": "BLOCKED"}])["per_source"]["geo"] == "FOUND"
    a, b = "ONE PIECEカードゲーム エクストラブースター ONE PIECE Heroines Edition vol.2", "ワンピースカードゲーム『エクストラブースター ONE PIECE Heroines Edition vol.2【EB-05】』"
    assert R.same_product(a, b)                                                                  # 型番の有無だけで別物にしない
    assert not R.same_product("拡張パック ハドウシーカー", "ハイクラスパック ハドウシーカー")
    assert not R.same_product("拡張パック ストームエメラルダ", "スペシャルBOX ストームエメラルダ")
    assert R.same_product("【ワンピースカードゲーム】「神の支配", "ONE PIECEカードゲーム ブースターパック 神の支配【OP-18】")


def test_date_match_requires_boundaries_for_recheck_product_needs_two_words():
    rows = [{"retailer": "X", "product": "ポケモンカードゲーム MEGA 拡張パック「ハドウシーカー」（1BOX）", "source_url": "https://a/1", "application_end": "2026-11-22T23:59:00+09:00"}]
    out = R.recheck_public(rows, lambda u: ("<p>別の弾の告知 ハドウシーカー は 11月22日</p>", ""), NOW)
    assert out[0]["result"] in ("RECONFIRMED", "PAGE_CHANGED")


def test_second_review_regressions(tmp_path):
    for a, b in (("拡張パック Terastal Festa ex BOX", "拡張パック Terastal Charge BOX"), ("Special Edition BOX", "Limited Edition BOX"),
                 ("Premium Booster Vol1", "Premium Booster Vol2"), ("拡張パック SV11B", "拡張パック SV11W"),
                 ("拡張パック 30th Celebration", "拡張パック 30th Anniversary")):
        assert not R.same_product(a, b), (a, b)
    assert R.same_product("エクストラブースター Heroines Edition vol.2 PRECIOUS BOX", "エクストラブースター Heroines Edition vol.2")
    # 読む部品の無い取得元でも、遮断・到達不能の証拠は採る（イベント無しは採らない）
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"sources": [_src(adapter=None, state="SOURCE_BLOCKED", blocked=True, health="BLOCKED", source_id="T", retailer="トイザらス"),
                                         _src(adapter=None, source_id="U", retailer="X")]}), encoding="utf-8")
    assert [r["result"] for r in R.collector_source_results(p, research_date=DATE)] == ["BLOCKED"]
    assert R._mentions_date("11/1-11/21 受付", "2026-11-21T00:00")
    # 取得に失敗した（FAILED）のに PRIMARY_VERIFIED と書かれた行は公開しない
    st = _run(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, [dict(_ev(), verification=_ver(page_fetch_status="FAILED"))], sources=SRCS)
    assert st["new_rows"] == []
