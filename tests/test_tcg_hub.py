# -*- coding: utf-8 -*-
"""TCG Lottery Hub（src/tcg/hub・src/content/tcg_hub_page）のテスト。"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from src.content import tcg_hub_page as page
from src.tcg import action_url as au
from src.tcg import event_quality as eq
from src.tcg.hub import profit_link as pl
from src.tcg.hub import status as st
from src.tcg.hub.product_view import build_hub
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=JST)


def _ev(**kw):
    d = {"tcg": "POKEMON", "product_name": "拡張パック「テスト弾」", "retailer": "CARD_LABO", "retailer_name": "カードラボ",
         "event_type": "LOTTERY", "product_id": "pokemon-拡張パック-テスト弾", "product_match": "exact",
         "application_start_date": "2026-11-18", "application_end_date": "2026-11-22",
         "source_url": "https://www.c-labo.jp/shop/x/blog/1/", "source_type": "STORE_OFFICIAL", "verified": True,
         "status": "ENDED"}                       # 保存値は嘘でも、状態は now から導出される
    d.update(kw)
    return d


REG = {"products": [{"product_id": "pokemon-拡張パック-テスト弾", "name": "拡張パック「テスト弾」", "tcg": "POKEMON",
                     "product_type": "BOOSTER_BOX", "release_date": "2026-12-01T00:00:00+09:00",
                     "official_url": "https://www.pokemon-card.com/ex/x/"}]}
MSRP = {"verified": [{"product_id": "pokemon-拡張パック-テスト弾", "tcg": "POKEMON", "product_type": "BOOSTER_BOX",
                      "retail_price": 5400, "price_text": "5,400円", "basis": "product_unit", "checked_at": "2026-11-19T00:00:00+09:00",
                      "official_url": "https://www.pokemon-card.com/ex/x/"}]}


def _hub(events, now=NOW, reg=REG, msrp=MSRP):
    return build_hub({"items": events, "generated_at": "2026-11-19T22:00:00+09:00"}, reg, msrp, now)


def test_only_exact_is_bound_to_a_product():
    h = _hub([_ev(), _ev(product_match="partial", product_id=None), _ev(product_match="none", product_id=None),
              _ev(product_match="ambiguous", product_id=None), _ev(product_match="exact", product_id=None)])
    assert len(h["products"]) == 1 and len(h["products"][0]["events"]) == 1
    assert [v["canonical"] for v in h["unbound"]] == ["UNMATCHED", "UNMATCHED", "AMBIGUOUS", "UNMATCHED"]
    assert h["stats"]["bound_exact"] == 1 and h["stats"]["unbound"] == 4 and h["stats"]["bind_rate"] == 0.2


def test_one_piece_exact_is_discovered_without_master_fields():
    h = _hub([_ev(tcg="ONE_PIECE", product_id="op-18", product_name="ブースター OP-18")])
    p = h["products"][0]
    assert p["canonical"] == "DISCOVERED" and p["name"] == "ブースター OP-18"
    assert p["release_date"] is None and p["profit"]["msrp"] is None


def test_status_is_rederived_from_now():
    ev = _ev(status="OPEN")
    assert st.live_status(ev, datetime(2026, 11, 17, 12, tzinfo=JST)) == "UPCOMING"
    assert st.live_status(ev, NOW) == "OPEN"
    assert st.live_status(ev, datetime(2026, 11, 23, 12, tzinfo=JST)) != "OPEN"
    assert _hub([ev], datetime(2026, 11, 17, 12, tzinfo=JST))["events"][0]["status"] == "UPCOMING"
    assert _hub([ev])["events"][0]["status"] == "OPEN"


def test_today_applicable_only_while_applying_and_without_conflict():
    assert st.is_applicable_today(_ev(), NOW)
    assert not st.is_applicable_today(_ev(conflict=True), NOW)
    assert not st.is_applicable_today(_ev(application_start_date="2026-11-20"), NOW)       # 日付のみの開始日当日は開始前
    assert not st.is_applicable_today(_ev(application_end_date="2026-11-19"), NOW)
    assert st.aggregate_status(["ENDED", "OPEN", "UPCOMING"]) == "OPEN" and st.aggregate_status([]) == "UNKNOWN"


def test_date_only_never_gets_a_time():
    v = _hub([_ev()])["events"][0]
    assert v["end"] == {"date": "2026-11-22", "time": None, "precision": "date"}
    html = page.render(_hub([_ev()]))
    assert "2026-11-22（日付のみ・時刻未公表）" in html and "2026-11-22 00:00" not in html
    cal = [c for c in _hub([_ev()])["calendar"] if c["kind"] == "END"]
    assert cal and cal[0]["time"] is None


def test_profit_is_none_without_evidence():
    p = _hub([_ev()])["products"][0]["profit"]
    assert p["net_profit"] is None and p["roi_pct"] is None and p["label"] == "算出前"
    assert p["msrp"]["retail_price"] == 5400
    html = page.render(_hub([_ev()]))
    assert "算出前" in html and "ROI" not in html and "高利益" not in html


def test_msrp_requires_exact_id_and_matching_type():
    rows = MSRP["verified"]
    assert pl.msrp_for("pokemon-拡張パック-テスト弾", "POKEMON", "BOOSTER_BOX", rows)["retail_price"] == 5400
    assert pl.msrp_for("pokemon-拡張パック-テスト", "POKEMON", "BOOSTER_BOX", rows) is None        # 前方一致は採用しない
    assert pl.msrp_for("pokemon-拡張パック-テスト弾", "ONE_PIECE", "BOOSTER_BOX", rows) is None
    assert pl.msrp_for("pokemon-拡張パック-テスト弾", "POKEMON", "STARTER_DECK", rows) is None
    assert pl.msrp_for("pokemon-拡張パック-テスト弾", "POKEMON", None, [dict(rows[0], basis="pack")]) is None
    assert pl.msrp_for("pokemon-拡張パック-テスト弾", "POKEMON", None, [dict(rows[0], retail_price=True)]) is None
    assert pl.msrp_for("pokemon-拡張パック-テスト弾", "POKEMON", None, rows + rows) is None        # 曖昧


def test_priority_is_a_mapping_of_existing_functions_only():
    assert st.priority_of_event(_ev(), NOW, bound_exact=True) == "A"
    assert st.priority_of_event(_ev(), NOW, bound_exact=False) == "WATCH"
    assert st.priority_of_event(_ev(verified=False), NOW, bound_exact=True) == "WATCH"
    assert st.priority_of_event(_ev(application_end_date="2026-11-20"), NOW, bound_exact=True) == "B"   # 締切間近だが応募先 URL 未確認
    assert st.priority_of_event(_ev(application_end_date="2026-11-10"), NOW, bound_exact=True) is None  # 応募期間後は対象外
    # 写像に使うのは既存の関数だけ（独自の閾値・点数を持たない）
    src = (ROOT / "src" / "tcg" / "hub" / "status.py").read_text(encoding="utf-8")
    assert "eq.priority_of" in src and "au.classify" in src
    assert not re.search(r"timedelta\(|score|>=\s*\d|<=\s*\d", src.split("def priority_of_event")[1])
    assert eq.P_DEADLINE_SOON == "DEADLINE_SOON" and au.Q_COMPLETE == "complete"


def test_priority_s_needs_complete_action_quality(monkeypatch):
    monkeypatch.setattr(au, "classify", lambda ev, now: {"quality": au.Q_COMPLETE})
    assert st.priority_of_event(_ev(application_end_date="2026-11-20"), NOW, bound_exact=True) == "S"


def test_broken_inputs_do_not_raise():
    for bad in (None, [], "x", 5, {"items": None}, {"items": ["x", None, 3, {}, {"tcg": 5, "application_end_date": 7}]},
                {"items": [{"product_match": "exact", "product_id": 5, "retailer": None}]}):
        for reg in (None, [], {"products": "x"}, {"products": [None, 1, {"product_id": 3}]}):
            h = build_hub(bad, reg, "junk", NOW)
            assert isinstance(page.render(h), str)
    assert page.render(None).startswith("<!doctype html>")
    assert st.live_status(None) == "UNKNOWN" and st.priority_of_event(5) is None and not st.is_applicable_today("x")
    assert pl.msrp_for(None, None, None, "x") is None


def test_html_has_no_path_private_or_injected_script():
    evil = "<script>alert(1)</script>"
    h = _hub([_ev(product_name=evil, store_name=evil, eligibility_text=evil, product_id=None, product_match="none")])
    html = page.render(h)
    assert evil not in html and "&lt;script&gt;" in html
    assert html.count("<script") == 1                                   # 絞り込み用の自前の JS だけ
    for bad in ("/Users/", ".private", "file://"):
        assert bad not in html


def test_links_only_official_https_and_none_without_entry_url():
    ev = _ev(source_url="https://evil.example.com/x", entry_url=None)
    v = _hub([ev])["events"][0]
    assert v["announcement_url"] is None and v["application_url"] is None
    html = page.render(_hub([ev]))
    assert "evil.example.com" not in html and "応募ページの URL は未確認" in html
    ok = _hub([_ev()])["events"][0]
    assert ok["announcement_url"] == "https://www.c-labo.jp/shop/x/blog/1/" and ok["application_url"] is None
    # 外部ドメインの entry_url は応募の URL にしない
    bad = _hub([_ev(entry_url="https://evil.example.com/e/abc123")])["events"][0]
    assert bad["application_url"] is None
    assert all(u.startswith("https://") for u in re.findall(r'href="(http[^"]+)"', page.render(_hub([_ev(), bad["ev"]]))))
    # 商品の公式ページは公式ドメインだけ
    reg = {"products": [dict(REG["products"][0], official_url="https://evil.example.com/p")]}
    assert "evil.example.com" not in page.render(_hub([_ev()], reg=reg))


def test_checked_at_is_source_value_not_generation_time():
    html = page.render_from_json({"items": [_ev()], "generated_at": "2026-01-02T03:04:05+09:00",
                                  "evaluated_at": "2026-01-02T03:05:00+09:00"}, REG, MSRP, NOW)
    assert "2026-01-02T03:04:05+09:00" in html and "確認時刻ではありません" in html


def test_unverified_is_shown_as_unconfirmed():
    html = page.render(_hub([_ev(verified=False)]))
    assert "未確認（公式での再確認待ち）" in html


def test_real_data_renders_and_filters_present():
    exp = ROOT / "exports" / "tcg"
    if not (exp / "lotteries.json").exists():
        return
    L = lambda f: json.loads((exp / f).read_text(encoding="utf-8"))
    h = build_hub(L("lotteries.json"), L("pokemon_registry.json"), L("msrp.json"), NOW)
    html = page.render(h)
    assert h["stats"]["events_total"] == len(L("lotteries.json")["items"])
    assert 'id="flt"' in html and "算出前" in html and html.count("<h1>") == 1


# ── 監査の指摘の回帰 ──
def test_unverified_lottery_is_not_counted_as_applicable_today():
    h = _hub([_ev(), _ev(verified=False, retailer="SURUGAYA", source_url="https://www.suruga-ya.jp/x/1")])
    assert h["stats"]["today"] == 1 and len(h["today_list"]) == 1                    # 未確認（公式での再確認待ち）は数えない
    assert st.is_applicable_today(_ev(verified=False), NOW) is False


def test_new_section_only_has_not_yet_finished_applying_statuses():
    pub = "2026-11-19T10:00:00+09:00"
    open_ev = _ev(published_at=pub)
    pending = _ev(published_at=pub, application_start_date="2026-11-10", application_end_date="2026-11-12",
                  winner_announcement_date="2026-11-25", product_id=None, product_match="none")           # 結果待ち
    h = _hub([open_ev, pending])
    assert len(h["new"]) == 1 and h["new"][0]["status"] in ("OPEN", "ENDING_SOON", "UPCOMING")


def test_page_states_the_snapshot_time_and_warns_when_source_is_old():
    hub = build_hub({"items": [_ev()], "generated_at": "2026-11-15T22:00:00+09:00"}, REG, MSRP, NOW)
    html = page.render(hub)
    assert "時点のものです" in html and "開いている間は進みません" in html
    assert "抽選データの取得が 5 日前です" in html
    fresh = page.render(_hub([_ev()]))
    assert "抽選データの取得が" not in fresh
    nodate = page.render(build_hub({"items": [_ev()]}, REG, MSRP, NOW))
    assert "取得日時が確認できません" in nodate


def test_broken_main_json_does_not_overwrite_the_public_page(tmp_path, monkeypatch, capsys):
    import scripts.build_public_lp as bp
    exp = tmp_path / "exports" / "tcg"
    exp.mkdir(parents=True)
    (exp / "lotteries.json").write_text("{broken", encoding="utf-8")
    pub = tmp_path / "docs"
    pub.mkdir()
    (pub / "tcg.html").write_text("PREVIOUS", encoding="utf-8")
    monkeypatch.setattr(bp, "PROJECT_ROOT", tmp_path)
    bp._build_tcg_hub_html(pub)
    assert (pub / "tcg.html").read_text(encoding="utf-8") == "PREVIOUS" and "壊れている" in capsys.readouterr().out    # 空ページで上書きしない


def test_official_announcement_rejects_lookalike_hosts():
    from src.tcg.hub.product_view import official_announcement
    assert official_announcement({"retailer": "CARD_LABO", "source_url": "https://www.c-labo.jp/shop/x/"})
    assert official_announcement({"retailer": "CARD_LABO", "source_url": "https://evilc-labo.jp/x/"}) is None
    assert official_announcement({"retailer": "CARD_LABO", "source_url": "https://xxxxc-labo.jp/x/"}) is None


def test_malformed_event_types_skip_only_that_event_and_page_still_renders():
    bad = [_ev(retailer=["x"]), _ev(tcg={"a": 1}), _ev(prefecture=5), _ev(product_name=True)]
    h = _hub([_ev()] + bad)
    assert h["stats"]["skipped_malformed"] == 4 and h["stats"]["events_total"] == 1
    assert "TCG 抽選ハブ" in page.render(h)


def test_real_exports_pass_the_build_guard_and_dict_without_items_does_not_overwrite(tmp_path, monkeypatch):
    import scripts.build_public_lp as bp
    real = json.loads((ROOT / "exports" / "tcg" / "lotteries.json").read_text(encoding="utf-8"))
    assert isinstance(real.get("items"), list)                                      # 守りが見るキー（items）が実データにある
    exp = tmp_path / "exports" / "tcg"
    exp.mkdir(parents=True)
    (exp / "lotteries.json").write_text(json.dumps({"generated_at": "x"}), encoding="utf-8")    # 辞書だが items が無い
    pub = tmp_path / "docs"
    pub.mkdir()
    (pub / "tcg.html").write_text("PREVIOUS", encoding="utf-8")
    monkeypatch.setattr(bp, "PROJECT_ROOT", tmp_path)
    bp._build_tcg_hub_html(pub)
    assert (pub / "tcg.html").read_text(encoding="utf-8") == "PREVIOUS"
