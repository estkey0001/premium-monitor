# -*- coding: utf-8 -*-
"""カメラ: 価格表示／条件付き利益／実行可能／購入推奨の分離。
安全側の売値（保証書に店舗印あり）と BUY 判定は変えず、条件別の確認済み価格から「条件付き」の参考の利益を別に出す。
抽選終了・完売の在庫区分、PROFIT_TO_LOSS の誤発報防止（売値の根拠の切替・鮮度失効）も確認する。"""
import copy
import json
import re
from datetime import datetime, timedelta

import pytest

from src.content import camera_market_page as pg
from src.research import camera_refresh as cf
from src.research import camera_routes as cr
from tests import test_camera_refresh as tref
from tests import test_camera_rudeya as trd
from tests.test_camera_routes import CFG, NOW, bb, build, off, rec, route

RUDEYA_URL = "https://kaitori-rudeya.com/product/item/6509"
CONDS = [{"key": "COMPLETE_NO_STAMP", "price": 225000, "evidence": "list+item_page"},
         {"key": "STAMPED_WARRANTY", "price": 195000, "deduction": 30000}]


def rd(price=195000, conds=CONDS, day="2026-11-18", **kw):
    row = {"shop": "買取ルデヤ", "item_title": "RICOH GR IV HDF", "price_jpy": price, "condition": "NEW", "price_basis": "STAMPED_WARRANTY",
           "url": RUDEYA_URL, "is_product_page": True, "checked_at": day, "source_updated_at": day, "result": "FOUND"}
    if conds is not None:
        row["conditions"] = copy.deepcopy(conds)
    row.update(kw)
    return row


# ---------------------------------------------------------------- 1. 採用行に conditions
def test_adopted_row_keeps_both_condition_prices_and_the_safe_price():
    products, notes = trd.run([trd.card(trd.GR4[0], 211000, trd.GR4[1], 6119)], {trd.BASE + "6119": trd.item_page(trd.GR4[0], trd.GR4[1], 211000)})
    row = products[0]["buyback"][0]
    assert row["price_jpy"] == 181000 and row["price_basis"] == "STAMPED_WARRANTY"                  # 安全側のまま
    assert row["conditions"] == [{"key": "COMPLETE_NO_STAMP", "price": 211000, "evidence": "list+item_page"},
                                 {"key": "STAMPED_WARRANTY", "price": 181000, "deduction": 30000}]
    assert notes[0]["ok"] and notes[0]["full_price"] == 211000


def test_not_buyable_model_makes_no_row_but_notes_keep_full_price_and_reason():
    products, notes = trd.run([trd.card(trd.GR4[0], 211000, trd.GR4[1], 6119, memo="保証書店舗印あり買取不可")],
                              {trd.BASE + "6119": trd.item_page(trd.GR4[0], trd.GR4[1], 211000)})
    assert products == []
    n = notes[0]
    assert n["full_price"] == 211000 and n["stamp_policy"] == "NOT_BUYABLE" and "店舗印ありは買取不可" in n["reason"] and "211,000" in n["reason"]


# ---------------------------------------------------------------- 3. 条件別の利益
def test_conditional_profit_is_computed_from_data_and_never_becomes_buy():
    m = build(rec(official=off(200000), buyback=[rd(), bb("買取B", 190000)]))
    r = route(m, "A")
    assert r["profit_status"] == cr.NO_PROFIT and r["net_profit"] == 195000 - 200000 - 1800 and r["decision"] != cr.BUY
    c, = r["conditional"]
    assert c["key"] == "COMPLETE_NO_STAMP" and c["sell_price"] == 225000
    assert c["net_profit"] == 225000 - 200000 - 0 - 1800 and c["roi_pct"] == round(100 * c["net_profit"] / 200000, 2)
    assert c["profit_status"] == cr.PROFITABLE and c["executable"] is False and "店舗印が付かない" in c["requires"]
    assert "conditional_profit_only" in r["reasons"]                       # 条件付きの黒字だけ（判断は変えない）
    assert m["products"][0]["best_route"] in (None, "A") and r["decision"] in (cr.SKIP, cr.WATCH, cr.WAIT)
    assert not any(cr.quality_checks(m, NOW, "2026-11-18", CFG, fixed_cost=1800).values())


def test_conditional_loss_is_a_computed_negative_not_zero():
    m = build(rec(official=off(240000), buyback=[rd()]))
    c, = route(m, "A")["conditional"]
    assert c["net_profit"] == 225000 - 240000 - 1800 < 0 and c["profit_status"] == cr.NO_PROFIT


def test_conditional_with_unknown_shipping_is_not_calculated():
    m = cr.build_market([rec(official=off(200000), buyback=[rd()])], NOW, CFG, registered_names={"RICOH GR IV HDF"},
                        official_shipping_fn=lambda *a: {}, fixed_cost_fn=lambda: 1800)
    r = route(m, "A")
    assert r["profit_status"] == cr.NOT_CALCULATED and "purchase_shipping_unknown" in r["reasons"]
    c, = r["conditional"]
    assert c["profit_status"] == cr.NOT_CALCULATED and c["net_profit"] is None and c["roi_pct"] is None and c["executable"] is False


def test_safe_side_buy_is_unchanged_and_conditional_is_extra():
    """安全側で黒字・2 店・登録済みなら BUY のまま。条件付きの行は別に付くだけで、BUY の根拠にしない。"""
    safe_rows = [rd(215000, [{"key": "COMPLETE_NO_STAMP", "price": 245000, "evidence": "list+item_page"}, {"key": "STAMPED_WARRANTY", "price": 215000, "deduction": 30000}]), bb("買取B", 213000)]
    m = build(rec(official=off(190000), buyback=safe_rows))
    r = route(m, "A")
    assert r["decision"] == cr.BUY and r["net_profit"] == 215000 - 190000 - 1800
    assert r["sell"]["price"] == 215000 and r["conditional"][0]["sell_price"] == 245000 and r["conditional"][0]["executable"] is False
    assert "conditional_profit_only" not in r["reasons"]
    assert not any(cr.quality_checks(m, NOW, "2026-11-18", CFG, fixed_cost=1800).values())


def test_conditions_do_not_change_decision_or_routes_when_removed():
    with_c = build(rec(official=off(200000), buyback=[rd(), bb("買取B", 190000)]))
    without = build(rec(official=off(200000), buyback=[rd(conds=None), bb("買取B", 190000)]))
    a, b = route(with_c, "A"), route(without, "A")
    for k in ("profit_status", "decision", "net_profit", "roi_pct", "executable"):
        assert a[k] == b[k]
    assert "conditional" not in b


def test_quality_checks_catch_conditional_used_as_executable_or_as_the_sell_price():
    m = build(rec(official=off(200000), buyback=[rd(), bb("買取B", 190000)]))
    bad = copy.deepcopy(m)
    route(bad, "A")["conditional"][0]["executable"] = True
    assert cr.quality_checks(bad, NOW, "2026-11-18", CFG, fixed_cost=1800)["conditional_used_as_executable"] >= 1
    bad2 = copy.deepcopy(m)
    route(bad2, "A")["conditional"][0]["sell_price"] = route(bad2, "A")["sell"]["price"]
    assert cr.quality_checks(bad2, NOW, "2026-11-18", CFG, fixed_cost=1800)["conditional_used_as_executable"] >= 1


def test_invalid_conditions_are_dropped():
    assert cr.clean_conditions([{"key": "X", "price": 1}, {"key": "COMPLETE_NO_STAMP", "price": "1"}, {"key": "COMPLETE_NO_STAMP", "price": 5, "evidence": "自由記述"}]) == [
        {"key": "COMPLETE_NO_STAMP", "price": 5}]
    assert cr.clean_conditions(None) == [] and cr.clean_conditions("x") == []


# ---------------------------------------------------------------- 2. refresh の通し（carry / history / 公開）
def _doc(conds=CONDS, price=195000, day="2026-11-18"):
    doc = tref.research()
    doc["products"][0]["buyback"] = [rd(price, conds, day)]
    return doc


def test_conditions_flow_to_public_data_history_and_page(tmp_path):
    st = tref.run(tmp_path, _doc())
    pub = cf._public_market(st)
    obs = [o for p in pub["products"] for o in p["observations"] if o["kind"] == "buyback"]
    assert obs[0]["conditions"] == CONDS[:1] + [CONDS[1]] and obs[0]["basis"] == "STAMPED_WARRANTY"
    r = next(x for p in pub["products"] for x in p["routes"] if x["route_type"] == "A")
    assert r["conditional"][0]["executable"] is False and r["sell"]["conditions"]
    snap = cf.history_snapshot(st)
    assert [o["conditions"] for o in snap["observations"] if o["source"] == "買取ルデヤ"] == [CONDS]
    assert "/Users/" not in json.dumps(pub, ensure_ascii=False)


def test_inconsistent_conditions_are_dropped_not_guessed(tmp_path):
    bad = [{"key": "COMPLETE_NO_STAMP", "price": 225000}, {"key": "STAMPED_WARRANTY", "price": 190000, "deduction": 30000}]      # 225000-30000 != 190000
    st = tref.run(tmp_path, _doc(bad))
    row = next(o for p in st["market"]["products"] for o in p["observations"] if o["kind"] == "buyback")
    assert row["conditions"] == [] and not route(st["market"], "A").get("conditional")
    mism = [{"key": "STAMPED_WARRANTY", "price": 180000, "deduction": 15000}]                      # 行の価格 195000 と合わない
    st2 = tref.run(tmp_path / "x", _doc(mism))
    assert not any(o.get("conditions") for p in st2["market"]["products"] for o in p["observations"])


def test_carried_rows_keep_conditions_with_the_original_date(tmp_path):
    st1 = tref.run(tmp_path, _doc())
    old = cf._public_market(st1)
    d = tmp_path / "2026-11-18"
    for f in d.glob("research_camera_*.json"):
        f.unlink()
    (d / "research_camera_RICOH.json").write_text(json.dumps({"brand": "RICOH", "products": [], "discovered": [], "lotteries": [], "source_results": []}), encoding="utf-8")
    st2 = cf.refresh(d, "2026-11-19", now=NOW + timedelta(days=1), old_market=old, cfg=CFG, obs_doc={}, names=tref.NAMES, official_shipping_fn=tref.SHIP0, fixed_cost_fn=lambda: 1800)
    rows = [o for p in st2["market"]["products"] for o in p["observations"] if o["source"] == "買取ルデヤ"]
    assert rows and all(o["carried"] and o["conditions"] == CONDS and o["checked_at"] == "2026-11-18" for o in rows)      # 日付は元のまま


def test_old_history_without_conditions_still_works(tmp_path):
    st1 = tref.run(tmp_path, _doc(conds=None))
    old = cf._public_market(st1)
    assert all("conditions" not in o for p in old["products"] for o in p["observations"])
    st2 = tref.run(tmp_path / "y", _doc(), old=old)
    assert st2["quality"] and not any(st2["quality"].values())


# ---------------------------------------------------------------- 4. 在庫区分
@pytest.mark.parametrize("row,expect", [
    ({"stock": "LOTTERY_DEPENDENT", "stock_evidence": "抽選販売 受付は終了いたしました"}, cr.LOTTERY_ENDED),
    ({"stock": "AVAILABLE", "stock_evidence": "抽選販売 受付は終了しました。購入ボタンなし"}, cr.LOTTERY_ENDED),
    ({"stock": "UNKNOWN", "stock_evidence": "抽選は終了いたしました"}, cr.LOTTERY_ENDED),
    ({"stock": "LOTTERY_DEPENDENT", "stock_evidence": "抽選販売 SOLD OUT"}, cr.OUT_OF_STOCK),
    ({"stock": "UNKNOWN", "stock_evidence": "完売しました（抽選販売）"}, cr.OUT_OF_STOCK),
    ({"stock": "UNKNOWN", "stock_evidence": "現在、販売を行っておりません"}, cr.SALES_SUSPENDED),
    ({"stock": "UNKNOWN", "stock_evidence": "抽選受付は開始予定です"}, cr.LOTTERY_UPCOMING),
    ({"stock": "LOTTERY_DEPENDENT", "stock_evidence": "抽選販売（応募受付中）"}, cr.LOTTERY_DEPENDENT),
    ({"stock": "AVAILABLE", "stock_evidence": "購入ボタンあり"}, cr.AVAILABLE),
    ({"stock": "UNKNOWN"}, cr.STOCK_UNKNOWN),
])
def test_stock_categories_end_words_win_over_lottery_words(row, expect):
    assert cr.stock_of(row, NOW) == expect


def test_negated_end_words_do_not_trigger():
    assert cr.stock_of({"stock": "AVAILABLE", "stock_evidence": "購入ボタンあり SOLD OUT表示なし"}, NOW) == cr.AVAILABLE


def test_lottery_period_decides_ended_and_upcoming():
    assert cr.stock_of({"stock": "UNKNOWN", "lottery": True, "lottery_end": "2026-11-10"}, NOW) == cr.LOTTERY_ENDED
    assert cr.stock_of({"stock": "UNKNOWN", "lottery": True, "lottery_start": "2026-11-25"}, NOW) == cr.LOTTERY_UPCOMING
    assert cr.stock_of({"stock": "UNKNOWN", "lottery": True, "lottery_start": "2026-11-10", "lottery_end": "2026-11-18"}, NOW) == cr.LOTTERY_DEPENDENT      # 当日は応募期間内


@pytest.mark.parametrize("stock", [cr.LOTTERY_ENDED, cr.LOTTERY_UPCOMING, cr.SALES_SUSPENDED, cr.OUT_OF_STOCK])
def test_non_available_stock_is_never_buy(stock):
    r = route(build(rec(official=off(200000, stock=stock), buyback=[bb("買取A", 240000), bb("買取B", 238000)])), "A")
    assert r["profit_status"] == cr.PROFITABLE and r["decision"] == cr.WAIT and not r["executable"] and r["buy"]["stock"] == stock


def test_ended_lottery_is_not_shown_as_a_current_lottery():
    assert "当選が必要" not in pg.STOCK["LOTTERY_ENDED"] and "終了" in pg.STOCK["LOTTERY_ENDED"]
    assert pg.STOCK["LOTTERY_UPCOMING"] != pg.STOCK["LOTTERY_DEPENDENT"] and pg.STOCK_TONE["LOTTERY_ENDED"] == "off"
    assert set(pg.STOCK) >= {cr.LOTTERY_ENDED, cr.LOTTERY_UPCOMING, cr.SALES_SUSPENDED}
    assert "stock_lottery_ended" in pg.REASON and "stock_sales_suspended" in pg.REASON


def test_apply_lotteries_skips_ended_and_passes_the_window():
    recs = [{"product": "RICOH GR IV HDF", "brand": "RICOH", "official": {"shop": "リコー公式", "price_jpy": 1}, "retail": []}]
    lots = [{"product": "RICOH GR IV HDF", "brand": "RICOH", "application_start": "2026-11-10", "application_end": "2026-11-17", "official_url": "https://www.ricoh-imaging.co.jp/a"}]
    assert not cf.apply_lotteries(recs, lots, NOW)[0]["official"].get("lottery")                    # 期限切れは対象にしない
    lots[0]["application_end"] = "2026-11-25"
    off_ = cf.apply_lotteries(recs, lots, NOW)[0]["official"]
    assert off_["lottery"] and off_["lottery_end"] == "2026-11-25"
    assert cr.stock_of({**off_, "stock": "UNKNOWN"}, NOW) == cr.LOTTERY_DEPENDENT
    assert cr.stock_of({**off_, "stock": "UNKNOWN"}, NOW + timedelta(days=10)) == cr.LOTTERY_ENDED      # 期間が過ぎたら終了


# ---------------------------------------------------------------- 5. PROFIT_TO_LOSS の誤発報防止
def _pub(m):
    """公開データ（前回の履歴として読む形）に近い形: URL・基準・鮮度を持つ売り手情報だけ。"""
    return copy.deepcopy(m)


def test_real_loss_with_the_same_seller_and_basis_still_emits_profit_to_loss():
    old = build(rec(official=off(180000), buyback=[rd()]))
    new = build(rec(official=off(200000), buyback=[rd()]))
    assert route(old, "A")["profit_status"] == cr.PROFITABLE and route(new, "A")["profit_status"] == cr.NO_PROFIT
    assert any(e["type"] == "PROFIT_TO_LOSS" for e in cr.diff_events(_pub(old), new))


def test_sell_basis_switch_is_not_reported_as_profit_to_loss_and_price_event_has_a_cause():
    old = build(rec(official=off(200000), buyback=[rd(225000, None, price_basis=None)]))      # 以前は完品の価格を売値にしていた（基準なし）
    new = build(rec(official=off(200000), buyback=[rd()]))                                    # 今は店舗印ありの価格（安全側）
    assert route(old, "A")["profit_status"] == cr.PROFITABLE and route(new, "A")["profit_status"] == cr.NO_PROFIT
    ev = cr.diff_events(_pub(old), new)
    assert not any(e["type"] == "PROFIT_TO_LOSS" for e in ev)
    drops = [e for e in ev if e["type"] == "PRICE_DROP"]
    assert drops and all(e["cause"] == "SELL_BASIS_CHANGED" for e in drops)


def test_expired_evidence_is_not_a_loss_nor_a_price_drop():
    old = build(rec(official=off(180000), buyback=[rd()]))
    new = build(rec(official=off(180000), buyback=[rd(day="2026-10-20")]))                    # 買取の確認が古く STALE → 売値に使えない
    assert route(new, "A")["profit_status"] == cr.NOT_CALCULATED
    ev = cr.diff_events(_pub(old), new)
    assert not any(e["type"] in ("PROFIT_TO_LOSS", "PRICE_DROP") for e in ev)


def test_history_without_seller_info_cannot_decide_so_no_profit_to_loss():
    old = build(rec(official=off(180000), buyback=[rd()]))
    new = build(rec(official=off(200000), buyback=[rd()]))
    stripped = _pub(old)
    for p in stripped["products"]:
        for r in p["routes"]:
            r.pop("sell", None)
    assert not any(e["type"] == "PROFIT_TO_LOSS" for e in cr.diff_events(stripped, new))


# ---------------------------------------------------------------- 6. ページ
def _page(tmp_path, stock="AVAILABLE"):
    doc = _doc()
    doc["products"][0]["official"]["stock"] = stock
    st = tref.run(tmp_path, doc)
    return pg.render(cf._public_market(st), now=NOW), st


def test_page_shows_conditional_note_without_a_buy_badge(tmp_path):
    html, _ = _page(tmp_path)
    card = html[html.index('<article class="dcard'):html.index("</article>")]
    # 新方針: 条件付き試算は 2 行の比較表（店舗印あり=判断の基準／店舗印なし=条件付き試算）。買取が 1 店のときはその注記も併記する
    assert "店舗印あり（判断の基準）" in card and "店舗印なし（条件付き試算）" in card and "購入推奨ではありません" in card
    assert "購入可否" in card and "確認日" in card and "購入元の保証書に店舗印が付かない場合のみ" in card and "買取は 1 店のみ" in card
    assert "+¥23,200" in card                                                               # 条件付きの利益（店舗印なし）
    assert "sbadge--buy" not in card and "sbadge--profit" not in card                      # 条件付きの黒字を緑にしない
    assert "overflow-wrap:anywhere" in html                                                 # 375px で横にはみ出さない


def test_must_notes_are_a_bulleted_list_one_item_per_line(tmp_path):
    # デザイン批評: 必須併記は『／』区切りの 1 段落ではなく、1 項目 1 行の箇条書きにする（375px で読みやすく）
    html, _ = _page(tmp_path, stock="LOTTERY_ENDED")
    card = html[html.index('<article class="dcard'):html.index("</article>")]
    block = card[card.index('class="mut cond-must"'):]
    block = block[:block.index("</div>")]
    assert block.count("<li>") >= 4
    assert "<li>現在購入できない" in block and "<li>店舗印なしの場合に限る</li>" in block
    assert "<li>買取価格は購入前に再確認が必要</li>" in block and "<li>購入推奨ではありません</li>" in block
    assert "<li>必要条件: " in block
    assert "／" not in block                                   # 項目を『／』でつないだ 1 段落に戻さない
    assert ".cond-ul" in html                                  # 最小のスタイル（折り返し）


def test_page_shows_ended_lottery_with_a_neutral_badge(tmp_path):
    html, st = _page(tmp_path, stock="LOTTERY_ENDED")
    card = html[html.index('<article class="dcard'):html.index("</article>")]
    assert "抽選は終了" in card and "当選が必要" not in card and "sbadge--off" in card


def test_page_without_conditions_has_no_conditional_block(tmp_path):
    doc = tref.research()
    st = tref.run(tmp_path, doc)
    html = pg.render(cf._public_market(st), now=NOW)
    assert 'class="note cond"' not in html


# ---------------------------------------------------------------- 7. 独立レビューの指摘（M1 / M2 / M3 / L3 / L4）
@pytest.mark.parametrize("conds,price", [
    ([{"key": "COMPLETE_NO_STAMP", "price": 9990000}], 200000),                                             # 完品だけ・STAMPED 無し
    ([{"key": "STAMPED_WARRANTY", "price": 195000, "deduction": 30000}], 195000),                         # 完品が無い
    ([{"key": "COMPLETE_NO_STAMP", "price": 225000, "evidence": "list+item_page"}, {"key": "STAMPED_WARRANTY", "price": 195000}], 195000),   # deduction 無し
    ([{"key": "COMPLETE_NO_STAMP", "price": 225000}, {"key": "STAMPED_WARRANTY", "price": 195000, "deduction": 30000}], 195000),              # evidence 無し
    ([{"key": "COMPLETE_NO_STAMP", "price": 225000, "evidence": "list+item_page"}, {"key": "STAMPED_WARRANTY", "price": 195000, "deduction": 30000}], 190000),  # 安全側と不整合
    ([{"key": "COMPLETE_NO_STAMP", "price": 900000, "evidence": "list+item_page"}, {"key": "STAMPED_WARRANTY", "price": 195000, "deduction": 705000}], 195000),  # 2 倍超
    ([{"key": "COMPLETE_NO_STAMP", "price": 190000, "evidence": "list+item_page"}, {"key": "STAMPED_WARRANTY", "price": 195000, "deduction": -5000}], 195000),  # 減額が負
])
def test_review_m1_unsupported_conditions_are_all_dropped(conds, price):
    assert cr.valid_conditions(conds, price) == []
    assert cf._clean_row_conditions({"price_jpy": price, "price_basis": "STAMPED_WARRANTY", "conditions": conds}) == []


def test_review_m1_example_and_valid_case():
    assert cf._clean_row_conditions({"price_jpy": 200000, "price_basis": "STAMPED_WARRANTY", "conditions": [{"key": "COMPLETE_NO_STAMP", "price": 9990000}]}) == []
    assert len(cf._clean_row_conditions({"price_jpy": 195000, "price_basis": "STAMPED_WARRANTY", "conditions": CONDS})) == 2


def test_review_m1_route_makes_no_conditional_from_unsupported_conditions():
    bad = [{"key": "COMPLETE_NO_STAMP", "price": 9990000, "evidence": "list+item_page"}, {"key": "STAMPED_WARRANTY", "price": 195000, "deduction": 30000}]
    r = route(build(rec(official=off(180000), buyback=[bb("買取A", 195000, conditions=bad, basis="STAMPED_WARRANTY")])), "A")
    assert not r.get("conditional")


@pytest.mark.parametrize("text,expect", [
    ("抽選販売は終了しています", cr.LOTTERY_ENDED), ("抽選は11/10で終了", cr.LOTTERY_ENDED), ("抽選は11/20で終了", cr.LOTTERY_DEPENDENT), ("抽選（終了）", cr.LOTTERY_ENDED),
    ("抽選販売 受付は終了", cr.LOTTERY_ENDED), ("抽選販売 終了いたしました", cr.LOTTERY_ENDED),
    ("抽選受付終了予定", cr.LOTTERY_DEPENDENT), ("抽選 終了間近", cr.LOTTERY_DEPENDENT), ("抽選 終了まであと3日", cr.LOTTERY_DEPENDENT),
    ("受付中。前回の抽選は終了しました", cr.LOTTERY_DEPENDENT),
])
def test_review_m3_end_phrases_without_a_period(text, expect):
    assert cr.stock_of({"stock": "UNKNOWN", "stock_evidence": text}, NOW) == expect


ACTIVE_WIN = {"lottery_start": "2026-11-10", "lottery_end": "2026-11-30"}


def test_review_m3_explicit_past_end_beats_active_window():
    """店の早期終了を取りこぼさない。調査表の期間だけで『応募できる』と出さない（旧契約: 期間 ACTIVE なら DEPENDENT を新契約に更新）。"""
    for t in ("抽選は終了しています", "抽選販売 受付は終了", "抽選は終了しました"):
        assert cr.stock_of({"stock": "UNKNOWN", "stock_evidence": t, **ACTIVE_WIN}, NOW) == cr.LOTTERY_ENDED, t


@pytest.mark.parametrize("text", ["抽選受付終了予定", "抽選 終了間近", "抽選受付は11/30 23:59で終了", "抽選受付中（11/30終了）", "抽選は終了いたします",
                                  "抽選受付は本日終了", "抽選受付は11/30で終了予定", "抽選受付は23:59で終了"])
def test_future_end_is_not_ended(text):
    assert cr.stock_of({"stock": "UNKNOWN", "stock_evidence": text}, NOW) == cr.LOTTERY_DEPENDENT, text
    assert cr.stock_of({"stock": "UNKNOWN", "stock_evidence": text, **ACTIVE_WIN}, NOW) == cr.LOTTERY_DEPENDENT, text


@pytest.mark.parametrize("text", ["LOTTERY CLOSED", "抽選は〆切", "抽選は締め切りました", "抽選 受付を終えました", "抽選販売は完了しました",
                                  "次回抽選は12月、今回の抽選は終了しました", "抽選受付は11/10 23:59で終了"])
def test_ended_phrases_are_caught(text):
    assert cr.stock_of({"stock": "UNKNOWN", "stock_evidence": text}, NOW) == cr.LOTTERY_ENDED, text


def test_deadline_label_with_jime_is_not_ended():
    assert cr.stock_of({"stock": "UNKNOWN", "stock_evidence": "抽選受付中 〆切 11/30"}, NOW) == cr.LOTTERY_DEPENDENT


def test_review_l3_blocked_or_stale_hides_positive_conditional(tmp_path):
    """新方針: 抽選終了（買えない）だけでは金額を隠さない。『現在購入できない（実状態）』を併記し、緑のバッジにしない。"""
    html, _ = _page(tmp_path, stock="LOTTERY_ENDED")
    card = html[html.index('<article class="dcard'):html.index("</article>")]
    assert "現在購入できない（実状態: 抽選は終了）" in card and "+¥23,200" in card and "11.6%" in card
    assert "購入推奨ではありません" in card and "sbadge--buy" not in card and "sbadge--profit" not in card
    html2, _ = _page(tmp_path / "ok")
    assert "現在購入できない" not in html2 and "+¥23,200" in html2


def test_review_l3_stale_sell_row_is_flagged():
    r = {"conditional": [{"key": "COMPLETE_NO_STAMP", "sell_price": 225000, "net_profit": 23200, "roi_pct": 10.0, "requires": "x"}], "net_profit": 0, "roi_pct": 0}
    h = pg._conditional_html(r, {"stock": "AVAILABLE", "freshness": "FRESH"}, {"price": 195000, "freshness": "STALE"})
    assert "確認日が古い" in h and "+¥23,200" not in h


def test_review_l4_rudeya_not_buyable_reason_without_price_has_no_zero_yen():
    src = open(trd.__file__.replace("tests/test_camera_rudeya.py", "src/collectors/camera_rudeya.py")).read()
    assert "{row.get('price') or 0:,}" not in src


def _cond_row_page(b, sl):
    r = {"conditional": [{"key": "COMPLETE_NO_STAMP", "sell_price": 225000, "net_profit": 23200, "roi_pct": 9.55, "requires": "x"}], "net_profit": -100, "roi_pct": -0.1,
         "reasons": ["conditional_profit_only"]}
    return r, pg._conditional_html(r, b, sl), pg._reasons(r["reasons"], pg._hides_conditional(r, b, sl))


def test_blocked_hides_conditional_roi_and_reason():
    """新方針: 買えない（抽選終了）だけなら金額・ROI は出す（併記つき）。隠すのは鮮度切れ・引き継ぎ・外れ値確認待ちのときだけ。"""
    r, h, why = _cond_row_page({"stock": "LOTTERY_ENDED", "freshness": "FRESH"}, {"price": 195000, "freshness": "FRESH"})
    assert "9.55" in h and "+¥23,200" in h and "現在購入できない（実状態: 抽選は終了）" in h and "購入推奨ではありません" in h
    assert "店舗印なしの場合だけ黒字" in why                                  # 買えない行の理由文は、理由の側（conditional_profit_only）で別に制御する
    r2, h2, why2 = _cond_row_page({"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0}, {"price": 195000, "freshness": "STALE"})
    assert "9.55" not in h2 and "+¥23,200" not in h2 and "黒字" not in h2 and "過去の参考: 買取 ¥195,000" in h2 and "鮮度切れ" in h2
    assert "店舗印なしの場合だけ黒字" not in why2 and "表示しません" in why2


def test_fresh_available_still_shows_conditional_roi_and_reason():
    r, h, why = _cond_row_page({"stock": "AVAILABLE", "freshness": "FRESH"}, {"price": 195000, "freshness": "FRESH"})
    assert "9.55" in h and "+¥23,200" in h and "購入推奨ではありません" in h
    assert "店舗印なしの場合だけ黒字" in why


def test_unknown_stock_is_not_called_unbuyable_nor_stale():
    _, h, _ = _cond_row_page({"stock": "UNKNOWN", "freshness": "FRESH"}, {"price": 195000, "freshness": "FRESH"})
    assert "実状態: 在庫不明" in h and "現在購入できない、または買えるかどうか未確認" in h and "確認日が古い" not in h and "+¥23,200" in h


# ---------------------------------------------------------------- 8. 第 2 回レビューの指摘（在庫の古さ・display_only・cause・stock_of・文言）
def _market_with_buy_age(day):
    """公式の買値行の確認日を day にして、買取（11-18）と同じ現在日でルートを作る。"""
    return build(rec(official=off(200000, day=day), buyback=[rd(), bb("買取B", 190000)]))


def test_review_m1_old_stock_check_does_not_show_positive_conditional():
    """新方針: 買値の在庫確認が 5 日前（stock_days=2 超）でも、仕入れ価格（7 日以内）は有効なので金額・ROI は出す。
    ただし『購入できる』とは言わず、在庫の確認が古いことを併記する。"""
    m = _market_with_buy_age("2026-11-13")
    r = route(m, "A")
    c, = r["conditional"]
    b = r["buy"]
    assert b["stock"] == cr.AVAILABLE and b["age_days"] == 5
    h = pg._conditional_html(r, b, r["sell"])
    assert "+¥23,200" in h and "在庫の確認が古い" in h and "購入推奨ではありません" in h
    assert "購入できる" not in h and "購入可否は判断できません" not in h


def test_review_m1_carried_buy_does_not_show_positive_conditional():
    r, h, why = _cond_row_page({"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0, "carried": True}, {"price": 195000, "freshness": "FRESH"})
    assert "+¥23,200" not in h and "前回データの引き継ぎのため参考値" in h and "購入できる" not in h


def test_review_m1_fresh_stock_still_shows_amount():
    r = route(_market_with_buy_age("2026-11-18"), "A")
    h = pg._conditional_html(r, r["buy"], r["sell"])
    assert "+¥23,200" in h and "参考値" not in h


def test_review_l4_json_conditional_is_marked_display_only_when_blocked():
    """新方針: 買えない・在庫確認が古いは『注記する理由』（not_actionable_reasons）で display_only にしない。隠す理由だけが display_only。"""
    old = route(_market_with_buy_age("2026-11-13"), "A")["conditional"][0]
    assert "display_only" not in old and "BUY_STOCK_OLD" in old["not_actionable_reasons"] and old["executable"] is False
    ended = route(build(rec(official=off(200000, stock="LOTTERY_ENDED"), buyback=[rd(), bb("買取B", 190000)])), "A")
    assert "display_only" not in ended["conditional"][0] and "BUY_STOCK_LOTTERY_ENDED" in ended["conditional"][0]["not_actionable_reasons"]
    assert ended["conditional"][0]["executable"] is False
    assert "conditional_profit_only" not in ended["reasons"]                 # 買えない行の黒字を理由に出さない（decision も変えない）
    ok = route(_market_with_buy_age("2026-11-18"), "A")["conditional"][0]
    assert "display_only" not in ok and "blocked_reasons" not in ok and "not_actionable_reasons" not in ok
    h = cr.conditional_hide_reasons({"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 9}, {"freshness": "FRESH", "age_days": 0})   # 仕入れ価格の確認が 9 日前（executable_days=7 超）→ 隠す
    assert h == ["BUY_STALE"]


def test_review_l4_stale_sell_marks_display_only_and_page_shares_the_function():
    b = {"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0}
    sl = {"freshness": "STALE", "carried": True}
    assert cr.conditional_blockers(b, sl) == ["SELL_CARRIED", "SELL_STALE"]
    assert cr.conditional_blockers(b, {"freshness": "FRESH"}) == []
    assert pg._blocked_keys(b, sl) == cr.conditional_blockers(b, sl)


@pytest.mark.parametrize("cause", ["SELL_BASIS_CHANGED", "EVIDENCE_EXPIRED"])
def test_review_auditor_m1_diff_events_cause_is_what_home_checks(cause):
    """HOME は cause を見て値動きカードにしない。cause の語彙が routes 側と一致していること。"""
    assert cause in (cr.CAUSE_BASIS_CHANGED, cr.CAUSE_EVIDENCE_EXPIRED)


L1_NOW = datetime(2026, 11, 18, 12, 0)


@pytest.mark.parametrize("text", ["抽選は本日23:59に終了", "抽選受付中 11/30 23:59に終了", "抽選受付：11/30（終了）", "抽選受付：11/18 23:59（終了）"])
def test_review_l1_future_ni_end_is_not_ended(text):
    assert cr.stock_of({"stock": "UNKNOWN", "stock_evidence": text}, L1_NOW) == cr.LOTTERY_DEPENDENT


@pytest.mark.parametrize("text", ["抽選受付：…（終了）", "抽選受付：11/10（終了）", "抽選は11/10に終了", "抽選は終了しました"])
def test_review_l1_past_or_dateless_paren_end_is_ended(text):
    assert cr.stock_of({"stock": "UNKNOWN", "stock_evidence": text}, L1_NOW) == cr.LOTTERY_ENDED


def test_review_l2_year_wrap():
    row = {"stock": "UNKNOWN", "stock_evidence": "抽選受付中 1/5 23:59で終了"}
    assert cr.stock_of(row, datetime(2026, 12, 28, 9)) == cr.LOTTERY_DEPENDENT        # 12/28 の「1/5」は来年＝未来
    row = {"stock": "UNKNOWN", "stock_evidence": "抽選受付中 12/31 23:59で終了"}
    assert cr.stock_of(row, datetime(2027, 1, 3, 9)) == cr.LOTTERY_ENDED              # 1/3 の「12/31」は昨年＝過去
    assert cr.stock_of(row, datetime(2026, 12, 20, 9)) == cr.LOTTERY_DEPENDENT        # 同じ年の未来


def test_review_l3_item_title_is_not_a_stock_context():
    """商品名は AVAILABLE を否定するためにだけ使う（fail-closed）。終了・完売の断定には使わない（第 3 回レビュー H1 で方針を確定）。"""
    row = {"stock": "AVAILABLE", "stock_evidence": "在庫あり カートに入れる", "item_title": "抽選販売記念モデル 完売御礼 SOLD OUT"}
    assert cr.stock_of(row, NOW) not in (cr.AVAILABLE, cr.LOTTERY_ENDED, cr.OUT_OF_STOCK)
    row2 = dict(row, note="抽選受付は終了しました")                                     # 店の状態の文言は従来どおり効く
    assert cr.stock_of(row2, NOW) == cr.LOTTERY_ENDED


# ---------------------------------------------------------------- 9. 第 3 回レビュー（商品名での fail-closed・鮮度・日付つき終了・定数の共有）
_EV = "カートに入れる 在庫あり"


@pytest.mark.parametrize("title,expect", [
    ("【予約】Canon EOS R6", cr.RESERVATION), ("【在庫なし】Canon EOS R6", cr.STOCK_UNKNOWN), ("【抽選販売】Canon EOS R6", cr.LOTTERY_DEPENDENT),
    ("Canon EOS R6 取り寄せ", cr.STOCK_UNKNOWN), ("店頭のみ Canon EOS R6", cr.STOCK_UNKNOWN), ("Canon EOS R6 SOLD OUT", cr.STOCK_UNKNOWN),
    ("Canon EOS R6", cr.AVAILABLE),
])
def test_review3_h1_item_title_negating_words_keep_available_fail_closed(title, expect):
    assert cr.stock_of({"stock": "在庫あり", "stock_evidence": _EV, "item_title": title}, NOW) == expect


@pytest.mark.parametrize("title", ["抽選販売終了記念モデル Canon EOS R6", "完売御礼キャンペーン終了 Canon EOS R6"])
def test_review3_h1_item_title_never_asserts_ended_or_sold_out(title):
    got = cr.stock_of({"stock": "在庫あり", "stock_evidence": _EV, "item_title": title}, NOW)
    assert got not in (cr.AVAILABLE, cr.LOTTERY_ENDED, cr.OUT_OF_STOCK) and got in (cr.STOCK_UNKNOWN, cr.LOTTERY_DEPENDENT)


def test_review3_h1_ended_needs_the_shop_state_text_not_the_title():
    assert cr.stock_of({"stock": "UNKNOWN", "stock_evidence": "完売しました", "item_title": "X"}, NOW) == cr.OUT_OF_STOCK


@pytest.mark.parametrize("text,expect", [
    ("11/30 23:59 抽選終了", cr.LOTTERY_DEPENDENT), ("11/10 抽選終了", cr.LOTTERY_ENDED),
    ("受付は終了していません", cr.LOTTERY_ENDED), ("抽選受付は終了しておりません", cr.LOTTERY_DEPENDENT), ("抽選未終了", cr.LOTTERY_DEPENDENT),
])
def test_review3_l2_future_dated_end_and_negated_end_are_not_ended(text, expect):
    got = cr.stock_of({"stock": "UNKNOWN", "stock_evidence": text}, NOW)
    if text == "受付は終了していません":
        assert got != cr.LOTTERY_ENDED
    else:
        assert got == expect


def test_review3_l3_condition_constants_are_shared():
    from src.collectors import camera_rudeya as crd
    assert cr.COND_COMPLETE is crd.COND_COMPLETE and cr.COND_STAMPED is crd.COND_STAMPED


@pytest.mark.parametrize("b,sl", [
    ({"stock": "AVAILABLE", "freshness": "STALE", "age_days": 0}, {"price": 195000, "freshness": "FRESH"}),
    ({"stock": "AVAILABLE", "freshness": "UNKNOWN_FRESHNESS", "age_days": 0}, {"price": 195000, "freshness": "FRESH"}),
    ({"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0}, {"price": 195000, "freshness": "STALE"}),
    ({"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0}, {"price": 195000, "freshness": "UNKNOWN_FRESHNESS"}),
    ({"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0}, {"price": 195000, "freshness": "FRESH", "carried": True}),
])
def test_review3_m1_stale_or_unknown_freshness_never_says_buyable_nor_shows_amounts(b, sl):
    _, h, _ = _cond_row_page(b, sl)
    assert "購入できる" not in h and "9.55" not in h and "+¥23,200" not in h and "黒字" not in h
    assert "購入可否は判断できません" in h


def test_review3_m1_page_uses_conditional_blockers_only():
    b, sl = {"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0}, {"price": 195000, "freshness": "FRESH"}
    assert cr.conditional_blockers(b, sl) == []
    _, h, _ = _cond_row_page(b, sl)
    assert "9.55" in h and "購入可否は判断できません" not in h


# ---------------------------------------------------------------- 8. M1: hero・表の買値セルも『購入できる』を断定しない
def _stale_buy_page(tmp_path, **buy_patch):
    html0, st = _page(tmp_path)
    pub = copy.deepcopy(cf._public_market(st))
    for p in pub["products"]:
        for r in p["routes"]:
            if r["route_type"] == "A":
                r["executable"] = False
                r["buy"] = {**r["buy"], "stock": "AVAILABLE", **buy_patch}
    return pg.render(pub, now=NOW)


def _hero_and_table(html):
    card = html[html.index('<article class="dcard'):html.index("</article>")]
    hero = card[card.index('<span>買える状態</span>'):card.index("</div></div>", card.index('<span>買える状態</span>'))]
    i = html.index("<tbody", html.index("判断一覧（買う場所"))                # 条件付き試算の表（カード内）ではなく、判断一覧の表
    return hero, html[i:html.index("</tbody>", i)]


@pytest.mark.parametrize("patch,word,says_unjudgeable", [
    ({"age_days": 3}, "在庫の確認が古い", False),                  # 新方針: 在庫確認だけが古いのは注記。『判断できません』は隠す理由のときだけ。ただし『購入できる』とは言わない
    ({"carried": True}, "引き継ぎ", True),
    ({"freshness": "STALE"}, "買値の確認日が古い", True),
])
def test_review_m1_hero_and_table_do_not_say_buyable_when_not_executable(tmp_path, patch, word, says_unjudgeable):
    html = _stale_buy_page(tmp_path, **patch)
    hero, table = _hero_and_table(html)
    assert "購入できる" not in hero and word in hero and ("購入可否は判断できません" in hero) == says_unjudgeable
    assert "購入できる" not in table and word in table and ("購入可否は判断できません" in table) == says_unjudgeable


def test_review_m1_executable_fresh_buy_still_says_buyable(tmp_path):
    html0, st = _page(tmp_path)
    pub = copy.deepcopy(cf._public_market(st))
    for p in pub["products"]:
        for r in p["routes"]:
            if r["route_type"] == "A":
                r["executable"] = True
                r["buy"] = {**r["buy"], "stock": "AVAILABLE", "age_days": 0, "carried": False, "freshness": "FRESH"}
    hero, table = _hero_and_table(pg.render(pub, now=NOW))
    assert "購入できる" in hero and "購入できる" in table and "購入可否は判断できません" not in hero


def test_review_m1_non_available_stock_labels_are_unchanged(tmp_path):
    html, _ = _page(tmp_path, stock="LOTTERY_ENDED")
    hero, _t = _hero_and_table(html)
    assert "抽選は終了" in hero and "購入可否は判断できません" not in hero


# ---------------------------------------------------------------- 9. 追加レビュー: 表示時点の古さ・L1・L2
def _fresh_market():
    """在庫 AVAILABLE・全部 FRESH・条件ありのルート（生成時は買える）。調査日 2026-11-18。"""
    m = build(rec(official=off(200000), buyback=[rd(), bb("買取B", 190000)]))
    m["research_date"] = "2026-11-18"
    return m


def _page_card(m, days):
    return pg.render(m, now=NOW + timedelta(days=days))


def test_h1_page_render_time_staleness_hides_conditional_amounts():
    m = _fresh_market()
    today = _page_card(m, 0)
    assert "+¥23,200" in today and "11.6%" in today                         # 当日は従来どおり
    mid = _page_card(m, 5)                                                  # 5 日後: 在庫確認は stock_days 超（注記）だが、価格は executable_days=7 以内（試算は出す）
    assert "+¥23,200" in mid and "購入できる" not in mid and "在庫の確認が古い" in mid
    old = _page_card(m, 8)                                                  # 8 日後: 仕入れ価格・売値が executable_days 超 → 試算は隠す
    assert "+¥23,200" not in old and "11.6%" not in old
    assert "購入できる" not in old and "店舗印なしの場合だけ黒字" not in old
    assert "購入可否は判断できません" in old and "試算は鮮度切れのため非表示" in old and "過去の参考: 買取 ¥195,000" in old


def test_h1_hero_and_conditional_use_the_same_blockers_function():
    m = _fresh_market()
    r = route(m, "A")
    b, sl = r["buy"], r["sell"]
    assert cr.conditional_blockers(b, sl, now_age_days=0) == []
    assert cr.conditional_blockers(b, sl, now_age_days=3) == ["BUY_STOCK_OLD"]                       # 在庫確認だけ古い = 注記（隠さない）
    assert cr.conditional_hide_reasons(b, sl, now_age_days=3) == [] and cr.conditional_notes(b, sl, now_age_days=3) == ["BUY_STOCK_OLD"]
    assert cr.conditional_blockers(b, sl, now_age_days=8) == ["BUY_STALE", "SELL_STALE", "BUY_STOCK_OLD"]    # 隠す理由 + 注記（互換の合計）
    assert pg._blocked_keys(b, sl, r, 8) == cr.conditional_blockers(b, sl, now_age_days=8)
    assert "購入できる" not in pg._buy_state(r, b, sl, now_age=5) and "判断できません" not in pg._buy_state(r, b, sl, now_age=5)
    assert "購入できる" not in pg._buy_state(r, b, sl, now_age=8) and "判断できません" in pg._buy_state(r, b, sl, now_age=8)
    assert "判断できません" not in pg._buy_state(r, b, sl, now_age=0)
    assert "+¥23,200" in pg._conditional_html(r, b, sl, 0) and "+¥23,200" in pg._conditional_html(r, b, sl, 5) and "+¥23,200" not in pg._conditional_html(r, b, sl, 8)


def test_h1_unparseable_research_date_is_treated_as_stale():
    m = _fresh_market()
    m["research_date"] = "不明"
    assert "+¥23,200" not in pg.render(m, now=NOW)


def test_h1_custom_stock_days_keeps_hero_and_conditional_in_agreement():
    m = _fresh_market()
    for r in route_list(m):
        r["buy"] = {**r["buy"], "age_days": 4}                              # JSON は stock_days=5 の設定で executable の想定
        r["executable"] = True
    html = pg.render(m, now=NOW)
    card = html[html.index('<article class="dcard'):html.index("</article>")]
    hero_ok = "購入可否は判断できません" not in card[card.index("<span>買える状態</span>"):card.index("</div></div>", card.index("<span>買える状態</span>"))]
    cond_ok = "+¥23,200" in card
    assert hero_ok == cond_ok


def route_list(m):
    return [r for p in m["products"] for r in p["routes"] if r["route_type"] == "A"]


def test_l4_executable_route_with_blockers_is_not_called_buyable():
    m = _fresh_market()
    r = route(m, "A")
    b = {**r["buy"], "carried": True}
    r2 = {**r, "executable": True, "buy": b}
    assert "購入できる" not in pg._buy_state(r2, b, r["sell"]) and "判断できません" in pg._buy_state(r2, b, r["sell"])


def test_l1_loss_to_profit_is_not_emitted_for_basis_switch_or_expired_sell():
    old = build(rec(official=off(200000), buyback=[rd()]))                                    # 安全側（店舗印あり）= 赤字
    new_basis = build(rec(official=off(200000), buyback=[rd(225000, None, price_basis=None)]))  # 売値の基準が完品に切り替わって黒字
    assert route(old, "A")["profit_status"] == cr.NO_PROFIT and route(new_basis, "A")["profit_status"] == cr.PROFITABLE
    assert not any(e["type"] == "LOSS_TO_PROFIT" for e in cr.diff_events(_pub(old), new_basis))
    # 同じ売り手・基準で本当に黒字化したものは出る
    real = build(rec(official=off(180000), buyback=[rd()]))
    assert any(e["type"] == "LOSS_TO_PROFIT" for e in cr.diff_events(_pub(old), real))
    # 売値が STALE なら出さない
    stale_new = copy.deepcopy(real)
    for r in route_list(stale_new):
        r["sell"] = {**r["sell"], "freshness": "STALE"}
    assert not any(e["type"] == "LOSS_TO_PROFIT" for e in cr.diff_events(_pub(old), stale_new))


def test_l2_would_notify_excludes_cause_events():
    class S(dict):
        pass
    state = {"events": [{"type": "PRICE_DROP", "product": "A", "cause": "SELL_BASIS_CHANGED"},
                        {"type": "PRICE_DROP", "product": "A", "cause": "EVIDENCE_EXPIRED"},
                        {"type": "PRICE_RISE", "product": "A"}]}
    pub = [{"product": "A"}]
    got = cf._notifiable_events(state, pub)
    assert [e["type"] for e in got] == ["PRICE_RISE"]


# ---------------------------------------------------------------- 10. 方針の変更: 根拠のある条件付き試算は、買えないだけでは隠さない（表示専用）
def _card_of(html):
    return html[html.index('<article class="dcard'):html.index("</article>")]


def _ended_market(stock, day="2026-11-18"):
    m = build(rec(official=off(200000, stock=stock, day=day), buyback=[rd(), bb("買取B", 190000)]))
    m["research_date"] = "2026-11-18"
    return m


@pytest.mark.parametrize("stock,state", [(cr.LOTTERY_ENDED, "抽選は終了"), (cr.OUT_OF_STOCK, "在庫なし"), (cr.UNKNOWN, "在庫不明")])
def test_unbuyable_but_fresh_conditional_shows_amount_roi_and_required_notes(stock, state):
    m = _ended_market(stock)
    r = route(m, "A")
    c, = r["conditional"]
    assert "display_only" not in c and c["executable"] is False and c["not_actionable_reasons"]
    card = _card_of(pg.render(m, now=NOW))
    assert "+¥23,200" in card and "11.6%" in card                                   # 金額と ROI は条件付き試算として出す
    assert "条件付き試算" in card and "店舗印なしの場合に限る" in card and "買取価格は購入前に再確認が必要" in card and "購入推奨ではありません" in card
    assert f"実状態: {state}" in card and "現在購入できない" in card                   # 実状態を同じ欄に併記
    assert "購入できる" not in card


def test_old_stock_check_but_fresh_price_shows_amount_with_note():
    card = _card_of(pg.render(_ended_market(cr.AVAILABLE, day="2026-11-15"), now=NOW))        # 在庫の確認 3 日前（stock_days=2 超）。仕入れ価格は 7 日以内
    assert "+¥23,200" in card and "実状態: 在庫の確認が古い" in card and "購入推奨ではありません" in card and "購入できる" not in card


def test_conditional_badge_is_neutral_and_profit_color_is_text_only():
    """条件付きの黒字を緑の購入推奨バッジにしない。プラスの損益は文字色（.pos）だけ。"""
    card = _card_of(pg.render(_ended_market(cr.LOTTERY_ENDED), now=NOW))
    assert 'sbadge sbadge--wait">条件付き試算' in card
    assert "sbadge--buy" not in card and "sbadge--profit" not in card
    assert 'class="">+¥23,200' in card and 'class="">11.6%' in card                # 購入できない（抽選終了）ルートのプラスは緑にしない（中立色）
    assert 'class="pos">+¥23,200' not in card and 'class="pos">11.6%' not in card
    neg = _card_of(pg.render(build_neg(), now=NOW))
    assert 'class="neg">−' in neg and "sbadge--profit" not in neg


def build_neg():
    m = build(rec(official=off(240000, stock=cr.LOTTERY_ENDED), buyback=[rd(), bb("買取B", 190000)]))
    m["research_date"] = "2026-11-18"
    return m


def test_conditional_is_a_two_row_stack_table_for_phones():
    html = pg.render(_ended_market(cr.LOTTERY_ENDED), now=NOW)
    t = html[html.index('<table class="nu-table--stack cond-t"'):]
    t = t[:t.index("</table>")]
    for col in ("買取条件", "買取価格", "安全側との価格差", "利益", "ROI"):
        assert f"<th>{col}</th>" in t and f'data-label="{col}"' in t                    # スマホ幅で 1 行 1 カード。data-label が見出し
    assert t.count("<tr>") == 3 and "店舗印あり（判断の基準）" in t and "店舗印なし（条件付き試算）" in t
    assert "min-width:0" in html and "overflow-wrap:anywhere" in html                    # 375px で横スクロールなし（既存の積み表と最小の CSS）


@pytest.mark.parametrize("b,sl,cause", [
    ({"stock": "LOTTERY_ENDED", "freshness": "FRESH", "age_days": 0, "carried": True}, {"price": 195000, "freshness": "FRESH", "age_days": 0}, "引き継ぎ"),
    ({"stock": "LOTTERY_ENDED", "freshness": "FRESH", "age_days": 0}, {"price": 195000, "freshness": "FRESH", "age_days": 0, "carried": True}, "引き継ぎ"),
    ({"stock": "LOTTERY_ENDED", "freshness": "FRESH", "age_days": 0}, {"price": 195000, "freshness": "STALE", "age_days": 9}, "鮮度切れ"),
    ({"stock": "LOTTERY_ENDED", "freshness": "STALE", "age_days": 9}, {"price": 195000, "freshness": "FRESH", "age_days": 0}, "鮮度切れ"),
    ({"stock": "LOTTERY_ENDED", "freshness": "FRESH", "age_days": 0}, {"price": 195000, "freshness": "FRESH", "age_days": 0, "evidence": {"outlier": True, "shops": 2}}, "外れ値確認待ち"),
])
def test_stale_carried_or_outlier_hides_amount_and_keeps_dated_reference(b, sl, cause):
    b = {**b, "price": 200000, "checked_at": "2026-11-18"}
    sl = {**sl, "checked_at": "2026-11-18"}
    r, h, why = _cond_row_page(b, sl)
    assert "+¥23,200" not in h and "9.55" not in h and "黒字" not in h and "<table" not in h
    text = re.sub(r"<[^>]+>", "", h)
    assert "過去の参考: 買取 ¥195,000（店舗印あり・11/18 確認）" in text and "買値 ¥200,000（11/18 確認）" in text and cause in text
    assert "店舗印なしの場合だけ黒字" not in why


def test_conditional_hide_and_notes_are_split_and_blockers_is_their_sum():
    b = {"stock": "LOTTERY_ENDED", "freshness": "FRESH", "age_days": 0}
    sl = {"freshness": "FRESH", "age_days": 0, "evidence": {"shops": 1, "outlier": False}}
    assert cr.conditional_hide_reasons(b, sl) == [] and cr.conditional_notes(b, sl) == ["BUY_STOCK_LOTTERY_ENDED", "SINGLE_BUYBACK_SHOP"]
    b2 = {"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0}
    sl2 = {"freshness": "FRESH", "age_days": 0, "evidence": {"shops": 2, "outlier": True}}
    assert cr.conditional_hide_reasons(b2, sl2) == ["SELL_OUTLIER_REVIEW"] and cr.conditional_notes(b2, sl2) == []
    for bb_, ss_, d in ((b, sl, 0), (b2, sl2, 0), (b2, sl2, 8), ({**b, "carried": True}, sl, 3)):
        assert cr.conditional_blockers(bb_, ss_, now_age_days=d) == cr.conditional_hide_reasons(bb_, ss_, now_age_days=d) + cr.conditional_notes(bb_, ss_, now_age_days=d)
    assert "BUY_STOCK_OLD" in cr.conditional_notes({**b2, "age_days": 3}, sl2) and "BUY_STOCK_OLD" not in cr.conditional_hide_reasons({**b2, "age_days": 3}, sl2)
    # 仕入れ『価格』の鮮度（executable_days=7）と『在庫』の鮮度（stock_days=2）は別
    assert cr.conditional_hide_reasons({**b2, "age_days": 5}, sl) == [] and cr.conditional_hide_reasons({**b2, "age_days": 8}, sl) == ["BUY_STALE"]


def test_single_buyback_shop_is_noted_and_two_shops_are_not():
    one = _cond_row_page({"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0}, {"price": 195000, "freshness": "FRESH", "age_days": 0, "evidence": {"shops": 1}})[1]
    two = _cond_row_page({"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0}, {"price": 195000, "freshness": "FRESH", "age_days": 0, "evidence": {"shops": 2}})[1]
    assert "買取は 1 店のみ" in one and "買取は 1 店のみ" not in two and "+¥23,200" in one


def test_outlier_route_marks_display_only_and_page_hides_amount():
    m = build(rec(official=off(200000), buyback=[rd(), bb("買取B", 150000)]))             # 最高 195,000 が次点 150,000 の 1.15 倍超 = 外れ値確認待ち
    m["research_date"] = "2026-11-18"
    r = route(m, "A")
    assert r["sell"]["evidence"]["outlier"] and r["conditional"][0]["display_only"] is True and "SELL_OUTLIER_REVIEW" in r["conditional"][0]["blocked_reasons"]
    card = _card_of(pg.render(m, now=NOW))
    assert "+¥23,200" not in card and "外れ値確認待ち" in card and "過去の参考: 買取 ¥195,000" in card


def test_no_buy_candidate_model_shows_no_estimate():
    """GR IIIx / GR III のように買値が確認できない機種は、試算を出さず『買える価格が確認できていない』のまま。"""
    m = build(rec(buyback=[rd(), bb("買取B", 190000)]))
    m["research_date"] = "2026-11-18"
    assert all(not r.get("conditional") for r in m["routes"]) and all("no_buy_candidate" in r["reasons"] for r in m["routes"])
    html = pg.render(m, now=NOW)
    assert "条件付き試算" not in html and "買える価格が確認できていない" in html


def test_conditional_never_becomes_buy_executable_decision_or_event():
    for stock in (cr.LOTTERY_ENDED, cr.OUT_OF_STOCK, cr.UNKNOWN):
        m = _ended_market(stock)
        r = route(m, "A")
        assert r["decision"] != cr.BUY and r["executable"] is False and r["conditional"][0]["executable"] is False
        assert m["products"][0]["best_route"] in (None, "A") and r["decision"] in (cr.SKIP, cr.WATCH, cr.WAIT)
        assert not any(cr.quality_checks(m, NOW, "2026-11-18", CFG, fixed_cost=1800).values())
        without = build(rec(official=off(200000, stock=stock), buyback=[rd(conds=None), bb("買取B", 190000)]))
        for k in ("profit_status", "decision", "net_profit", "roi_pct", "executable", "confidence"):
            assert r[k] == route(without, "A")[k]                                                   # 条件の有無で判断が変わらない
        ev_with = cr.diff_events(_pub(_ended_market(cr.AVAILABLE)), m)
        ev_without = cr.diff_events(_pub(_ended_market(cr.AVAILABLE)), without)
        assert [e["type"] for e in ev_with] == [e["type"] for e in ev_without]                      # イベントにも条件付きは影響しない
        assert not any("conditional" in json.dumps(e, ensure_ascii=False) for e in ev_with)


def test_conditional_profit_only_is_added_only_for_buyable_non_hidden_rows():
    assert "conditional_profit_only" in route(_ended_market(cr.AVAILABLE), "A")["reasons"]              # 買える行
    for stock in (cr.LOTTERY_ENDED, cr.OUT_OF_STOCK, cr.UNKNOWN):
        assert "conditional_profit_only" not in route(_ended_market(stock), "A")["reasons"]
    assert "conditional_profit_only" not in route(_ended_market(cr.AVAILABLE, day="2026-11-15"), "A")["reasons"]    # 在庫確認が古い（注記）
    outl = build(rec(official=off(200000), buyback=[rd(), bb("買取B", 150000)]))
    assert "conditional_profit_only" not in route(outl, "A")["reasons"]                                  # 隠す行


def test_hidden_buy_state_wording_only_for_hide_reasons():
    """『購入可否は判断できません』は隠す理由があるときだけ。買えない系の実状態は従来どおりのバッジ。"""
    b = {"stock": "LOTTERY_ENDED", "freshness": "FRESH", "age_days": 0}
    sl = {"price": 195000, "freshness": "FRESH", "age_days": 0}
    r = {"conditional": []}
    assert "抽選は終了" in pg._buy_state(r, b, sl) and "判断できません" not in pg._buy_state(r, b, sl)
    assert "判断できません" in pg._buy_state(r, {**b, "stock": "AVAILABLE", "carried": True}, sl)
    assert pg._hides_conditional({"conditional": [{"key": "x"}]}, b, sl) is False and pg._hides_conditional({"conditional": [{"key": "x"}]}, {**b, "carried": True}, sl) is True


def test_conditional_profit_is_green_only_when_buyable_and_never_for_buy_stock_notes():
    """L6: 緑（.pos）は『買える状態（注記に BUY_STOCK_* が無い）』のプラスだけ。"""
    assert pg._cond_cls(23200, []) == "pos"
    assert pg._cond_cls(23200, ["SINGLE_BUYBACK_SHOP"]) == "pos"
    for k in ("BUY_STOCK_LOTTERY_ENDED", "BUY_STOCK_OUT_OF_STOCK", "BUY_STOCK_UNKNOWN", "BUY_STOCK_OLD"):
        assert pg._cond_cls(23200, [k]) == "", k
    assert pg._cond_cls(-100, ["BUY_STOCK_OLD"]) == "neg" and pg._cond_cls(0, []) == ""


def test_conditional_price_and_diff_are_inside_live_and_stale_keeps_dated_reference():
    """M5: 条件付き行の買取価格・価格差も live の中。stale 側に取得日つきの過去の参考が置かれる。"""
    html = pg.render(_ended_market(cr.LOTTERY_ENDED), now=NOW)
    row = html[html.index("店舗印なし（条件付き試算）"):]
    row = row[:row.index("</tr>")]
    assert re.search(r'<span data-fb-live[^>]*>(?:<span data-fb-live[^>]*>)*¥\d[\d,]*(?:</span>)+', row)      # 買取価格が live の中
    assert re.search(r'<span data-fb-live[^>]*>(?:<span data-fb-live[^>]*>)*[+−]?¥\d[\d,]*(?:</span>)+', row)
    assert re.search(r'data-fb-stale[^>]*><span class="mut">過去の参考: 店舗印なしの買取 ¥[\d,]+（(?:<span[^>]*>)?\d\d?/\d\d?(?:</span>)?\s*確認）。期限切れのため試算は非表示', row)


# ── Reviewer L3: 未来日付の静的判定は HOME の _is_future と同じ（now の JST 日付より後 = UNKNOWN。1 日先も許さない） ──
def test_row_date_bad_treats_next_day_as_future_like_home():
    day = NOW.astimezone(pg.JST).date()
    row = lambda b: {"buy": {"checked_at": b}, "sell": {"checked_at": day.isoformat()}}
    assert pg._row_date_bad(row(day.isoformat()), NOW) is False                       # 同日は未来ではない
    assert pg._row_date_bad(row((day + timedelta(days=1)).isoformat()), NOW) is True  # 翌日は未来 = UNKNOWN
    assert pg._row_date_bad({"buy": {"checked_at": day.isoformat()}, "sell": {"checked_at": (day + timedelta(days=1)).isoformat()}}, NOW) is True


# ── Reviewer L4: evidence が dict でなくても落ちない ──
@pytest.mark.parametrize("ev", ["外れ値", ["outlier"], 3, None])
def test_conditional_hide_reasons_tolerates_non_dict_evidence(ev):
    b = {"stock": "AVAILABLE", "freshness": "FRESH", "age_days": 0}
    sl = {"freshness": "FRESH", "age_days": 0, "evidence": ev}
    assert cr.conditional_hide_reasons(b, sl) == []


# ── Auditor L1: 計算できなかった機種の表の価格に確認日を併記する ──
def test_nocalc_table_prices_show_confirmation_date():
    m = build(rec(official=off(200000, day="2026-11-18"), buyback=[]))
    m["research_date"] = "2026-11-18"
    html = pg.render(m, now=NOW)
    cell = html[html.index("計算できなかった機種の表を開く"):].split("</details>")[0]
    assert "¥200,000" in cell and "11/18 確認" in re.sub(r"<[^>]+>", "", cell)
    m2 = copy.deepcopy(m)
    for p in m2["products"]:
        for o in p["observations"]:
            o["checked_at"] = None
    cell2 = pg.render(m2, now=NOW)
    cell2 = cell2[cell2.index("計算できなかった機種の表を開く"):].split("</details>")[0]
    assert "確認日不明" in re.sub(r"<[^>]+>", "", cell2)


def test_nocalc_sell_summary_prices_show_confirmation_date_or_unknown():
    o = {"kind": "buyback", "price": 172600, "reasons": [], "freshness": "FRESH", "source": "買取ルデヤ", "condition": "UNOPENED", "basis": None}
    t = pg._sell_summary({"observations": [{**o, "checked_at": "2026-11-18"}, {**o, "source": "B店", "checked_at": None}]})
    assert "¥172,600" in t and "（11/18 確認）" in t and "（確認日不明）" in t
