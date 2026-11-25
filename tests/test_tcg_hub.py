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
    assert '<td data-label="締切" class="w2"><span title="2026-11-22（日付のみ・時刻未公表）">11/22</span>' in html     # 日付のみは `11/22` だけ（原値は title・注記は表の上）。時刻は作らない
    assert "日付のみ" in html
    assert "11/22 00:00" not in html and "2026-11-22 00:00" not in html
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


# ---- UI/UX 刷新で追加した表示のテスト ----

def _reg_with_image(url):
    reg = {"products": [dict(REG["products"][0], official_image_url=url)]}
    return reg


def test_product_image_only_from_pokemon_official_https():
    ok = page.render(_hub([_ev()], reg=_reg_with_image("https://www.pokemon-card.com/products/2026/images/x.jpg")))
    assert 'src="https://www.pokemon-card.com/products/2026/images/x.jpg"' in ok
    assert 'referrerpolicy="no-referrer"' in ok and "onerror" not in ok
    for bad in ("https://evil.example.com/x.jpg", "http://www.pokemon-card.com/x.jpg", "javascript:alert(1)"):
        html = page.render(_hub([_ev()], reg=_reg_with_image(bad)))
        assert "<img" not in html and "evil.example.com" not in html and "javascript:" not in html


def test_one_piece_never_gets_an_image():
    h = _hub([_ev(tcg="ONE_PIECE", product_id="op-18", product_name="ブースター OP-18")])
    h["products"][0]["image_url"] = "https://www.pokemon-card.com/x.jpg"
    assert "<img" not in page.render(h)


def test_each_lottery_appears_once_in_the_table():
    evs = [_ev(lottery_id=f"L{i}", source_url=f"https://www.c-labo.jp/shop/x/blog/{i}/",
               application_end_date="2026-11-20") for i in range(3)]
    html = page.render(_hub(evs))
    n = html.count('class="ev ') + html.count('class="ev"')
    assert n == len(evs), n


def test_empty_state_has_meaningful_text():
    html = page.render(_hub([]))
    assert "<h1>" in html and "受付中" in html


# ── 00:00 規則（時刻が無い・未確認の行に 00:00 を出さない）──
def _visible(html: str) -> str:
    """属性（title の原値）を除いた、画面に見える文字だけ。"""
    return re.sub(r"<[^>]+>", " ", html)


def _midnight(text: str) -> bool:
    """時刻としての 00:00（12:00:00 の秒・分の並びは除く）。"""
    return re.search(r"(?<![\d:])00:00(?![\d:])", text) is not None


def _midnight_ev(**kw):
    d = dict(application_start="2026-11-04T00:00:00+09:00", application_end="2026-11-23T00:00:00+09:00",
             winner_announcement_at="2026-11-24T00:00:00+09:00", purchase_start="2026-11-25T00:00:00+09:00",
             purchase_end="2026-11-30T00:00:00+09:00", application_start_date=None, application_end_date=None)
    d.update(kw)
    return _ev(**d)


def test_unverified_row_never_shows_midnight_or_any_time():
    h = _hub([_midnight_ev(verified=False, lottery_id="U1")])
    html = page.render(h)
    assert not _midnight(_visible(html))                        # 表・カード・カレンダー・今後 7 日のどこにも出ない
    assert "11/23" in _visible(html) and "時刻は未確認のため日付のみ" in html
    assert "原値 2026-11-23 00:00" in html                      # 原値は title に残す
    v = h["events"][0]
    assert v["end"]["time"] == "00:00"                          # when() の結果は変えない（描画側で処理）


def test_verified_date_only_and_midnight_get_no_time_but_real_times_stay():
    only = page.render(_hub([_ev()]))
    assert not _midnight(_visible(only)) and "11/22" in _visible(only)
    mid = page.render(_hub([_midnight_ev(verified=True, lottery_id="V1")]))
    assert not _midnight(_visible(mid))                         # 00:00 は明示か補完か区別できないので日付のみ
    real = page.render(_hub([_ev(application_end="2026-11-22T23:59:00+09:00", application_end_date=None)]))
    assert "11/22 23:59" in _visible(real)                      # 確認済みの 00:00 以外の時刻は残す


def test_midnight_rule_applies_in_calendar_and_agenda_without_duplicates():
    h = _hub([_midnight_ev(verified=False, lottery_id="U1", application_end="2026-11-21T00:00:00+09:00")])
    html = page.render(h)
    assert page.show_time("00:00", True) is None and page.show_time("00:00", False) is None
    assert page.show_time("12:30", False) is None and page.show_time("12:30", True) == "12:30"
    assert html.count('class="ev ') == 1                        # 同じ抽選を重ねて出さない
    agenda = html[html.index('class="agenda"'):]
    assert not _midnight(_visible(agenda.split("</details>")[0]))


def test_count_labels_and_timestamp_labels_are_distinguished():
    html = page.render(_hub([_ev(verified=False)]))
    assert "未確認を含む" in html and "id=\"count-def\"" in html and "HOME" in html
    assert "画面生成" in html and "情報の確認時刻ではありません" in html


def test_priority_badge_is_not_hidden_by_new_or_deadline_flag():
    ev = _ev(application_end_date="2026-11-20", published_at="2026-11-19T10:00:00+09:00",
             application_url="https://www.c-labo.jp/x", entry_url="https://www.c-labo.jp/x")
    html = page.render(_hub([ev]))
    row = html[html.index('<tr class="ev'):html.index("</tr>", html.index('<tr class="ev'))]
    assert "今日締切" in row and re.search(r"[SAB] (今すぐ|応募したい|余裕あり)", _visible(row))


def test_calendar_collapses_empty_weeks():
    h = _hub([_ev(application_end_date="2026-12-24", application_start_date="2026-12-20")])
    html = page.render(h)
    assert "予定のない週は省略しています" in html


def test_product_card_without_open_lottery_does_not_read_as_open():
    """受付中の抽選が 0 件の商品カードに、「受付中」と読める代替文言を出さない。受付中がある商品は従来どおりチップを出す。"""
    ended = page.render(_hub([_ev(application_start_date="2026-11-10", application_end_date="2026-11-12")]))
    assert "この商品に紐付いた、応募受付中の抽選はありません" in ended and "受付中・開始前なし" not in ended
    live = page.render(_hub([_ev()]))
    assert "この商品に紐付いた、応募受付中の抽選はありません" not in live and "<b>1</b>受付中" in live


def test_product_card_no_open_lottery_text_is_scoped_to_linked_and_points_to_unlinked():
    """商品カードの本文は「この商品に紐付いた」ものだけの話。商品に未紐付けの受付中の抽選があれば、抽選一覧への案内を同じ行に足す（紐付けは推測しない）。"""
    ended = _ev(application_start_date="2026-11-10", application_end_date="2026-11-12")
    unlinked_open = _ev(product_match="none", product_id=None, product_name="拡張パック二種（再販）",
                        application_start_date="2026-11-18", application_end_date="2026-11-30")
    h0 = _hub([ended])
    assert h0["stats"]["unbound_applying"] == 0
    html0 = page.render(h0)
    assert "この商品に紐付いた、応募受付中の抽選はありません" in html0 and "紐付け前の告知は抽選一覧を参照" not in html0
    h1 = _hub([ended, unlinked_open])
    assert h1["stats"]["unbound_applying"] == 1
    html1 = page.render(h1)
    assert "この商品に紐付いた、応募受付中の抽選はありません。紐付け前の告知は抽選一覧を参照" in html1
    h2 = _hub([ended, {**unlinked_open, "verified": False}])        # 未検証の未紐付けは「受付中」に数えない
    assert h2["stats"]["unbound_applying"] == 0
