# -*- coding: utf-8 -*-
"""抽選 collector が同じ取得 HTML から販売価格も読む仕組み: カードラボ・ホビーステーションの実文面（価格・日程の事実行だけの最小 fixture）と、
台帳（手動）との統合（collector 優先・食い違いの検証エラー・フォールバック・単位と同一性の採用条件・受付中→終了の遷移）。通信はしない。"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.collectors.tcg.lottery import clabo, hbst
from src.collectors.tcg.lottery.base import product_code_of
from src.content import tcg_hub_page as page_mod
from src.tcg import retailer_box as rb
from src.tcg.lottery.products import resolve_product
from src.tcg.lottery.schema import LotteryEvent
from src.tcg.models import JST
from tests.test_tcg_buyback import NOW
from tests.test_tcg_retailer_box import REG, ent, hub

ROOT = Path(__file__).resolve().parent
CL = ROOT / "fixtures" / "tcg_price_facts"      # 価格・日程の事実行だけの最小の fixture（clabo / hbst の fixture は合成のみの方針なので分ける）
HB = CL
REGISTRY = json.loads((ROOT.parent / "exports/tcg/pokemon_registry.json").read_text(encoding="utf-8"))["products"]
POKEMON = [p for p in REGISTRY if p["tcg"] == "POKEMON"]
ONE_PIECE = [p for p in REGISTRY if p["tcg"] == "ONE_PIECE"]
MASTER = {(p["tcg"], p["product_id"]): p for p in REGISTRY}


def _clabo_body(name):
    a = clabo.CardLaboLotteryAdapter()
    html = (CL / name).read_text(encoding="utf-8")
    return a, clabo.normalize_body(a.to_text(re.search(r"<article.*?</article>", html, re.S).group(0)))


def _clabo_events(name, store, slug, url, tcg, published, title):
    a, body = _clabo_body(name)
    evs = a.build_from_article(title=title, body=body, url=url, published_at=published, tcg_hint=tcg, store_name=store, store_id=slug,
                               targets=clabo.parse_targets(body) or None)
    return evs


def _resolve(evs, reg):
    for e in evs:
        e.update({k: v for k, v in resolve_product(e["product_name"], reg).items() if k != "release_date"})
    return evs


IKE_URL = "https://www.c-labo.jp/shop/ikebukuro/blog/624925/"
NAM_URL = "https://www.c-labo.jp/shop/namba2nd/blog/624599/"


def ike():
    return _resolve(_clabo_events("detail_ikebukuro_eb05.html", "カードラボ池袋店", "ikebukuro", IKE_URL, "ONE_PIECE", "2026-11-20T00:00:00+09:00",
                                  "【池袋店】『ONE PIECE Heroines Edition vol.2【EB-05】』再販抽選販売のお知らせ"), ONE_PIECE)


def namba():
    return _resolve(_clabo_events("detail_namba_op18.html", "カードラボ販売買取センターNAMBA店", "namba2nd", NAM_URL, "ONE_PIECE",
                                  "2026-11-16T00:00:00+09:00", "【11月21日発売】『ブースターパック 神の支配【OP-18】』抽選販売のお知らせ"), ONE_PIECE)


def hbst_body():
    return hbst.parse_detail((HB / "detail_hadou_two.html").read_text(encoding="utf-8"))


def hbst_events(body=None, targets="auto"):
    d = hbst_body()
    body = d["body"] if body is None else body
    a = hbst.HobbyStationLotteryAdapter()
    tg = hbst.parse_prices(body) if targets == "auto" else targets
    evs = a.build_from_article(title=d["title"], body=body, url="https://www.hbst.net/?p=412193", published_at="2026-11-24T00:00:00+09:00",
                               entry_url=None, result_url=None, tcg_hint="POKEMON", targets=tg or None)
    return _resolve(evs, POKEMON)


# ---------------------------------------------------------------- カードラボ
def test_clabo_real_wording_gives_code_unit_and_price_with_and_without_comma():
    _, b1 = _clabo_body("detail_ikebukuro_eb05.html")
    _, b2 = _clabo_body("detail_namba_op18.html")
    t1, t2 = clabo.parse_targets(b1), clabo.parse_targets(b2)
    assert len(t1) == 1 and t1[0]["product_code"] == "EB-05" and t1[0]["price_unit"] == "BOX" and t1[0]["retail_price"] == 5760
    assert len(t2) == 1 and t2[0]["product_code"] == "OP-18" and t2[0]["price_unit"] == "BOX" and t2[0]["retail_price"] == 5760   # 5760円（カンマなし）


def test_clabo_events_carry_price_unit_and_exact_identity():
    for evs, code in ((ike(), "EB-05"), (namba(), "OP-18")):
        assert len(evs) == 1
        e = evs[0]
        assert e["retail_price"] == 5760 and e["price_unit"] == "BOX" and e["product_code"] == code
        assert e["product_match"] == "exact" and e["product_id"]
        assert e["application_end_date"] and e["purchase_end_date"] and e["store_specific"] is True


@pytest.mark.parametrize("text,unit,price", [
    ("〈対象商品〉 発売日：2026年10月31日(土) テスト商品 お一人様 20pack：7,200円（税込）", "PACK", None),
    ("〈対象商品〉 発売日：2026年10月31日(土) テスト商品 お一人様 3セット：7,200円（税込）", "SET", None),
    ("〈対象商品〉 発売日：2026年10月31日(土) テスト商品 お一人様 2BOX：11,520円（税込）", "BOX", None),
    ("〈対象商品〉 発売日：2026年10月31日(土) テスト商品 お一人様 10パック：3,000円（税込）", "PACK", None),
    ("〈対象商品〉 発売日：2026年10月31日(土) テスト商品 お一人様 1BOX：5,760円（税込）", "BOX", 5760),
])
def test_clabo_packs_sets_and_multiple_quantities_have_no_price(text, unit, price):
    t = clabo.parse_targets(text)
    assert len(t) == 1 and t[0]["retail_price"] == price and t[0]["price_unit"] == unit


# ---------------------------------------------------------------- ホビーステーション
def test_hbst_two_product_subject_gives_no_product_name():
    assert hbst.product_of("【2026.11.24】抽選販売「ポケモンカードゲームMEGA 拡張パック二種（再販）」") == ""
    assert hbst.product_of("抽選販売「拡張パック3種（再販）」") == ""
    assert hbst.product_of("【2026.10.20】抽選販売「ポケモンカードゲーム テスト拡張パック A（再販）」")      # 単独の商品は従来どおり


def test_hbst_parse_prices_pairs_each_product_with_its_price_and_box_from_each_n_box():
    d = hbst_body()
    rows = hbst.parse_prices(d["body"])
    # 複数商品の価格ブロックで BOX の表記が商品ごとに無い（「当選者は各2BOXまで」だけ）ので、単位は確定しない（UNKNOWN）
    assert [(r["retail_price"], r["price_unit"]) for r in rows] == [(5400, "UNKNOWN"), (6000, "UNKNOWN")]
    assert [r["product_name"] for r in rows] == ["拡張パック「ムニキスゼロ」", "拡張パック「ハドウシーカー」"]    # 本文に書かれた種別（拡張パック）を付ける
    only = hbst.parse_prices(d["body"], POKEMON)                       # registry を渡すと、同一性 none のムニキスゼロは除く
    assert [r["product_name"] for r in only] == ["拡張パック「ハドウシーカー」"]


def test_hbst_unit_is_box_only_with_explicit_box_or_each_n_box():
    body = hbst_body()["body"]
    no_each = body.replace("当選者は各2BOXまでご購入いただけます。", "")
    assert {r["price_unit"] for r in hbst.parse_prices(no_each)} == {"UNKNOWN"}              # 「各N BOX」が無ければ確定しない（入数から逆算しない）
    got = {r["product_name"]: r["price_unit"] for r in hbst.parse_prices(no_each.replace("ハドウシーカー6,000円", "ハドウシーカー BOX 6,000円"))}
    assert got["拡張パック「ハドウシーカー」"] == "BOX" and got["拡張パック「ムニキスゼロ」"] == "UNKNOWN"      # 商品名の直後の BOX 表記は、その商品だけ BOX
    assert hbst.parse_prices("・販売価格：各7,200円（税込） ■応募") == []                     # 「各」は商品との対応が曖昧
    assert hbst.parse_prices("・販売価格：各種 7,200円（税込） ■応募") == []
    assert hbst.parse_prices("30パック入り 7,200円") == []                                   # 入数・販売価格の行が無い


def test_hbst_events_split_per_product_and_only_exact_box_price_is_adoptable():
    evs = hbst_events()
    by = {e["product_name"]: e for e in evs}
    assert set(by) == {"拡張パック「ムニキスゼロ」", "拡張パック「ハドウシーカー」"}
    assert by["拡張パック「ムニキスゼロ」"]["product_match"] == "none" and by["拡張パック「ハドウシーカー」"]["product_match"] == "exact"
    rows = {r["shop"]: r for r in map(rb.row_from_event, evs)}
    assert [rb.adoptable(r) for r in map(rb.row_from_event, evs)].count(True) == 0        # 単位が確定しない価格は採用しない
    c = rb.classify(rb.row_from_event(by["拡張パック「ムニキスゼロ」"]), MASTER, NOW)
    assert c["kind"] == "REJECTED" and "exact" in c["reason"]
    assert rows


# ---------------------------------------------------------------- 同一性・単位
def _ev(**kw):
    e = LotteryEvent(tcg="POKEMON", product_name="拡張パック「ハドウシーカー」", retailer="X", retailer_name="X店", retail_price=6000, price_unit="BOX",
                     application_end_date="2026-11-22", purchase_start_date="2026-11-25", purchase_end_date="2026-11-30",
                     source_url="https://shop.example/x", observed_at=NOW.isoformat()).to_dict()
    e.update({"product_id": "box", "product_match": "exact", "verified": True})      # collector の実イベントは base が verified=True で作る
    e.update(kw)
    return e


@pytest.mark.parametrize("kw,ok", [
    ({}, True),                                                     # JAN が無くても exact + BOX + 正の価格なら採用
    ({"product_match": "partial", "product_id": None}, False),
    ({"product_match": "ambiguous", "product_id": None}, False),
    ({"product_match": "none", "product_id": None}, False),
    ({"price_unit": "PACK"}, False), ({"price_unit": "SET"}, False), ({"price_unit": "UNKNOWN"}, False),
    ({"retail_price": 0}, False), ({"retail_price": -1}, False),
])
def test_adoption_needs_exact_box_and_positive_price(kw, ok):
    r = rb.row_from_event(_ev(**kw))
    if not r:                                                          # 価格が無効なら行そのものを作らない
        assert not ok
        return
    assert rb.adoptable(r) is ok
    assert (rb.classify(r, {("POKEMON", "box"): {}}, NOW)["kind"] == "REJECTED") is (not ok)
    assert r["jan"] is None


def test_pack_price_times_count_never_becomes_box_price():
    r = rb.row_from_event(_ev(price_unit="PACK", retail_price=240))
    c = rb.classify(r, {("POKEMON", "box"): {}}, NOW)
    assert c["kind"] == "REJECTED" and rb.adoptable(r) is False
    assert rb.row_from_event(_ev(retail_price=None)) is None


# ---------------------------------------------------------------- 統合
def _crow(**kw):
    return rb.row_from_event(_ev(**kw))


def _led(**kw):
    return ent(source_url="https://shop.example/x", **kw)


def test_collector_wins_and_price_mismatch_is_reported():
    c = _crow(retail_price=6000, application_end_date=(NOW + timedelta(days=1)).strftime("%Y-%m-%d"), purchase_start_date=None, purchase_end_date=None)
    c["retailer"], c["shop"] = "店", "テスト店"
    rows, errs = rb.merge_rows([c], [_led(price_jpy=5800)])
    assert len(rows) == 1 and rows[0]["source"] == "collector" and rows[0]["price_jpy"] == 6000
    assert [e["kind"] for e in errs] == ["PRICE_MISMATCH"] and errs[0]["collector_price"] == 6000 and errs[0]["manual_price"] == 5800
    assert errs[0]["collector_adopted"] is True and errs[0]["resolution"] == "reference_only"
    # M3: 価格が食い違う行は、どちらも確かでないので利益計算に使わず参考止まり
    cl = rb.classify(rows[0], {("POKEMON", "box"): {}}, NOW)
    assert cl["kind"] == rb.K_REFERENCE and "食い違" in cl["reason"] and cl["executable"] is False


def test_manual_ledger_is_the_fallback_when_collector_row_is_not_adoptable_or_missing():
    led = _led()
    rows, errs = rb.merge_rows([], [led])
    assert rows[0]["source"] == "manual" and errs == []
    rows, errs = rb.merge_rows([_crow(price_unit="UNKNOWN", retail_price=7200)], [led])      # 単位不明の collector は台帳を上書きしない
    assert len(rows) == 1 and rows[0]["source"] == "manual" and rows[0]["price_jpy"] == 6000
    assert errs and errs[0]["collector_adopted"] is False
    rows, errs = rb.merge_rows([_crow()], [])                                                # 台帳に無い collector の行はそのまま
    assert len(rows) == 1 and rows[0]["source"] == "collector"


def test_schedule_mismatch_is_reported_and_collector_schedule_is_used():
    c = _crow(application_end_date="2026-11-22", purchase_end_date="2026-11-30")
    led = _led(apply_end="2026-11-23", purchase_end="2026-11-30")
    rows, errs = rb.merge_rows([c], [led])
    assert rows[0]["apply_end"] == "2026-11-22"
    assert "apply_end" in [e["field"] for e in errs if e["kind"] == "SCHEDULE_MISMATCH"]
    assert "purchase_end" not in [e["field"] for e in errs if e["kind"] == "SCHEDULE_MISMATCH"]


def test_real_four_ledger_rows_match_collector_rows_by_url_even_when_shop_names_differ():
    led = rb.load_ledger()
    coll = [rb.row_from_event(e) for e in ike() + namba() + hbst_events()]
    coll = [c for c in coll if c]
    rows, errs = rb.merge_rows(coll, led)
    src = {r["source_url"]: r["source"] for r in rows}
    assert src[IKE_URL] == "collector" and src[NAM_URL] == "collector" and src["https://www.hbst.net/?p=412193"] == "collector"
    assert src["https://www.sanyodo.co.jp/news/evt_20261104-20261115"] == "manual"        # 三洋堂は collector なし → 手動台帳のまま
    assert [e for e in errs if e["kind"] == "PRICE_MISMATCH"] == []                         # 実ページの価格は台帳と一致
    assert len([r for r in rows if r["source"] == "collector" and rb.adoptable(r)]) == 2        # ハドウシーカー（単位が確定しない）は採用しない
    assert not [r for r in rows if r.get("product_id") is None and r["source"] == "manual"]


def test_collector_verified_at_is_the_observed_day_not_generation_time():
    ev = _ev(observed_at="2026-11-19T10:00:00+09:00")
    assert rb.row_from_event(ev)["verified_at"] == "2026-11-19"
    ev2 = _ev(); ev2["observed_at"] = ""
    r = rb.row_from_event(ev2)
    assert r["verified_at"] is None and rb.classify(r, {("POKEMON", "box"): {}}, NOW)["kind"] == "REJECTED"    # 確認日が無い行は採用しない
    old = rb.row_from_event(_ev(observed_at=(NOW - timedelta(days=15)).isoformat()))
    assert rb.classify(old, {("POKEMON", "box"): {}}, NOW)["kind"] != rb.K_CONDITIONAL                          # 14 日 stale は条件付きにしない


def test_state_transition_open_to_winners_only_to_closed_conditional_then_reference():
    c = _crow(application_end_date=None, application_end="2026-11-22T23:59:00+09:00", purchase_start_date="2026-11-25", purchase_end_date="2026-11-30")
    c["tcg"], c["product_id"] = "POKEMON", "box"
    master = {("POKEMON", "box"): {}}
    t0 = NOW
    k = [(rb.classify(c, master, t0 + d)["accept_state"], rb.classify(c, master, t0 + d)["kind"]) for d in
         (timedelta(0), timedelta(days=2), timedelta(days=10))]
    assert k == [("OPEN", rb.K_CONDITIONAL), ("WINNERS_ONLY", rb.K_REFERENCE), ("CLOSED", rb.K_REFERENCE)]
    w = rb.classify(c, master, t0 + timedelta(days=2))
    assert "すでに当選した人向け" in w["winners_only_note"] and "新規応募不可" in w["accept_label"]
    assert rb.classify(c, master, t0)["winners_only_note"] is None


def test_hub_shows_conditional_profit_only_while_open_and_never_executable():
    c = _crow(application_end_date=None, application_end=(NOW + timedelta(days=1)).isoformat(),
              purchase_start_date=(NOW + timedelta(days=10)).strftime("%Y-%m-%d"), purchase_end_date=(NOW + timedelta(days=16)).strftime("%Y-%m-%d"))
    c["tcg"] = "POKEMON"
    h = hub([c])
    o = h["retailer_opportunities"][0]
    assert o["retailer"]["source"] == "collector" and o["executable"] is False and o["profit"]["net_profit"] == 3000
    assert o["retailer"]["price_class"] == "LOTTERY" and o["retailer"]["price_class_label"] == "抽選販売価格"
    later = hub([c], now=NOW + timedelta(days=2))                     # 応募終了後: 新規応募できる案件として出さない・利益なし
    assert later["retailer_opportunities"] == [] and later["retailer_references"][0]["kind"] == "REFERENCE_ONLY"
    assert "net_profit" not in later["retailer_references"][0]


def test_retailer_price_never_enters_official_msrp():
    msrp = [{"product_id": "box", "tcg": "POKEMON", "product_type": "EXPANSION_PACK", "retail_price": 5400, "price_text": "5,400円",
             "basis": "product_unit", "checked_at": NOW.isoformat(), "official_url": "https://www.pokemon-card.com/x"}]
    c = _crow(application_end=(NOW + timedelta(days=1)).isoformat(), application_end_date=None)
    h = hub([c], msrp=msrp)
    assert h["retailer_opportunities"] == [] and h["opportunities"][0]["profit"]["acquisition_cost"] == 5400      # 公式定価が優先・販売店価格で上書きしない
    ms = json.loads((ROOT.parent / "exports/tcg/msrp.json").read_text(encoding="utf-8"))
    assert not any(v.get("product_id") in {r["product_id"] for r in rb.rows_from_events([e for e in ike() + namba() + hbst_events()])} for v in ms["verified"])


@pytest.mark.parametrize("method,state,cls", [
    ("LOTTERY", rb.S_OPEN, "LOTTERY"), ("LOTTERY", rb.S_WINNERS, "LOTTERY"), ("LOTTERY", rb.S_CLOSED, "ENDED_REFERENCE"),
    ("PREORDER", rb.S_UNKNOWN, "PREORDER"), ("NORMAL", rb.S_UNKNOWN, "REGULAR"), ("NORMAL", rb.S_CLOSED, "ENDED_REFERENCE"), (None, rb.S_UNKNOWN, "UNKNOWN"),
])
def test_price_class_from_sale_method_and_state(method, state, cls):
    assert rb.price_class(method, state) == cls and rb.PRICE_CLASS_LABEL[cls]
    assert "メーカー希望小売価格" not in {rb.PRICE_CLASS_LABEL[cls] for cls in ("LOTTERY", "ENDED_REFERENCE", "PREORDER", "REGULAR")}


def test_preorder_event_is_never_a_lottery_state():
    r = _crow(event_type="PREORDER")
    assert r["sale_method"] == "PREORDER" and rb.accept_state(r, NOW) == rb.S_UNKNOWN


def test_product_code_needs_exactly_one_bracketed_code():
    assert product_code_of("ブースターパック 神の支配【OP-18】") == "OP-18"
    assert product_code_of("商品 OP-18 の説明") is None and product_code_of("") is None


def test_build_hub_reads_collector_prices_from_published_lottery_items_and_reports_validation_errors(monkeypatch):
    """retailer_rows を渡さない通常の経路: 公開済みの抽選イベント（items）の価格 + 手動台帳 → 統合。追加の取得は無い（既存イベントを読むだけ）。"""
    import src.tcg.buyback as m
    from tests.test_tcg_buyback import CFG, art, page
    from src.tcg import buyback as bb
    from src.tcg.hub import product_view as pv
    monkeypatch.setattr(m, "load_config", lambda *a, **k: CFG)
    rows = [{**r, "page_asof": NOW.isoformat()} for r in bb.parse_rudeya(page(art("拡張パック BOX", 9000, "4500000000222")), "u", NOW)["rows"]]
    ev = _ev(application_end=(NOW + timedelta(days=1)).isoformat(), application_end_date=None,
             purchase_start_date=(NOW + timedelta(days=10)).strftime("%Y-%m-%d"), purchase_end_date=(NOW + timedelta(days=16)).strftime("%Y-%m-%d"))
    h = pv.build_hub({"items": [ev]}, REG, {"verified": []}, NOW, {"rows": rows})
    assert [o["retailer"]["source"] for o in h["retailer_opportunities"]] == ["collector"]
    assert isinstance(h["retailer_validation_errors"], list)


# ---------------------------------------------------------------- 独立レビューの指摘の回帰
@pytest.mark.parametrize("kw", [{"conflict": True}, {"verified": False}, {"status": "ENDED", "application_end_date": "2026-11-01"}])
def test_conflict_unverified_or_not_applicable_event_is_never_open_conditional(kw):
    """M1: 日程の食い違い・未検証・応募できる状態でないイベントは、BOX・exact・将来の締切でも受付中（条件付きの利益）にしない。"""
    base = dict(application_end=(NOW + timedelta(days=1)).isoformat(), application_end_date=None,
                purchase_start_date=(NOW + timedelta(days=10)).strftime("%Y-%m-%d"), purchase_end_date=(NOW + timedelta(days=16)).strftime("%Y-%m-%d"))
    ok = _crow(**base)
    assert rb.classify(ok, {("POKEMON", "box"): {}}, NOW)["kind"] == rb.K_CONDITIONAL      # 対照: 正常なイベントは受付中
    r = _crow(**{**base, **kw}) if "application_end_date" not in kw else _crow(**{**base, "application_end": None, **kw})
    c = rb.classify(r, {("POKEMON", "box"): {}}, NOW)
    assert c["kind"] == rb.K_REFERENCE and c["accept_state"] != rb.S_OPEN and c["reason"] and "利益は出さない" in c["reason"]
    h = hub([r])
    assert h["retailer_opportunities"] == [] and h["retailer_references"]


@pytest.mark.parametrize("body", [
    "・販売価格：拡張パック「ハドウシーカー」 1BOX 7,200円 / 2BOX 14,400円 ■応募方法",
    "・販売価格：拡張パック「ハドウシーカー」 30パック 7,200円 ■応募方法",
    "・販売価格：拡張パック「ハドウシーカー」 1パック 180円 1BOX 5,400円 ■応募方法",
])
def test_hbst_price_names_cut_by_digits_are_rejected_and_fall_back_to_subject(body):
    """M4: 数字で名前が切れた「BOX」「パック」は商品名にしない。価格が 1 つも読めなければ空（呼び出し側が件名由来にフォールバック）。"""
    rows = hbst.parse_prices(body, POKEMON)
    assert not any(r["product_name"].strip() in ("BOX", "パック", "セット", "枚") for r in rows)
    assert rows == []                                              # 有効な価格なし → 件名由来（collect は `or` で件名の商品名にする）
    assert hbst.parse_prices(body) == []                           # registry なしでも単位語は商品名にしない


def test_hbst_collect_passes_registry_to_parse_prices():
    """M4: collect は registry を必ず通す（registry なしの呼び出しが残っていない）。registry は exports から読める。"""
    import inspect
    assert hbst._registry()
    assert 'build_targets(title, d["body"], _registry())' in inspect.getsource(hbst.HobbyStationLotteryAdapter.collect)


def test_clabo_box_price_below_floor_is_not_adopted():
    """L7: 1,000 円未満の BOX 価格（パック価格・桁落ちの疑い）は採用しない。下限以上は採用する。"""
    low = clabo.parse_targets("〈対象商品〉 発売日：2026年10月31日(土) テスト商品 お一人様 1BOX：576円（税込）")
    assert low[0]["retail_price"] is None and low[0]["price_unit"] == "BOX"
    ok = clabo.parse_targets("〈対象商品〉 発売日：2026年10月31日(土) テスト商品 お一人様 1BOX：5,760円（税込）")
    assert ok[0]["retail_price"] == 5760
    a = clabo.parse_targets("対象商品 テスト商品名 お一人様1BOX：900円")
    assert all(t["retail_price"] is None for t in a)


# ---------------------------------------------------------------- 同じ商品・同じ店の複数回の抽選（並び順に依存しない）
N1125 = datetime(2026, 11, 25, 10, 0, tzinfo=JST)


def _round_rows():
    def mk(url, a0, a1, p0, p1):
        r = _crow(application_start_date=a0, application_end_date=a1, purchase_start_date=p0, purchase_end_date=p1, source_url=url,
                  verified=True, status="OPEN")
        r["retailer"], r["shop"] = "カードラボ", "カードラボ池袋店"
        return r
    old = mk("https://shop.example/a", "2026-11-01", "2026-11-05", "2026-11-08", "2026-11-10")      # 応募終了・購入期間も終了
    new = mk("https://shop.example/b", "2026-11-24", "2026-11-30", None, None)                       # 受付中
    led = ent(product_id="box", retailer="カードラボ", shop="カードラボ池袋店", source_url="https://shop.example/led", price_jpy=5760,
              apply_start="2026-11-01", apply_end="2026-11-05", purchase_start="2026-11-08", purchase_end="2026-11-10")
    return old, new, led


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_merge_keeps_the_open_round_regardless_of_order_and_no_false_schedule_mismatch(order):
    old, new, led = _round_rows()
    old["price_jpy"] = new["price_jpy"] = 5760
    rows, errs = rb.merge_rows([[old, new][i] for i in order], [led], N1125)
    assert len(rows) == 1 and rows[0]["source_url"] == "https://shop.example/b"            # 受付中の回を落とさない
    assert rb.accept_state(rows[0], N1125) == rb.S_OPEN
    assert [e for e in errs if e["kind"] == "SCHEDULE_MISMATCH"] == []                       # 別回（応募期間が違う）は台帳の旧日程と比較しない


def test_merge_still_flags_schedule_mismatch_for_the_same_round():
    old, _new, led = _round_rows()
    old["price_jpy"] = 5760
    led2 = {**led, "apply_end": "2026-11-06"}                                                # 同じ回（応募期間が近い）で終了日だけ違う
    _r, errs = rb.merge_rows([old], [led2], N1125)
    assert [e["field"] for e in errs if e["kind"] == "SCHEDULE_MISMATCH"] == ["apply_end"]


def test_merge_without_open_round_prefers_the_latest_apply_end():
    old, new, led = _round_rows()
    old["price_jpy"] = new["price_jpy"] = 5760
    later = N1125.replace(month=12, day=20)
    for order in ((old, new), (new, old)):
        rows, _e = rb.merge_rows(list(order), [led], later)
        assert rows[0]["source_url"] == "https://shop.example/b"


# ---------------------------------------------------------------- hbst: 「各N BOX」の確定条件・BOX 価格の下限
def test_hbst_each_box_does_not_make_every_product_in_a_multi_price_block_box():
    body = "■販売価格：商品A 1,650円 商品B 5,400円 ■各1BOX ■応募方法"
    got = {p["product_name"]: p for p in hbst.parse_prices(body)}
    assert got["商品A"]["price_unit"] == "UNKNOWN" and got["商品B"]["price_unit"] == "UNKNOWN"
    r = rb.row_from_event({**_ev(retail_price=1650, price_unit=got["商品A"]["price_unit"])})
    assert rb.adoptable(r) is False


def test_hbst_box_is_confirmed_by_unit_next_to_price_or_name_not_by_purchase_limit():
    one = hbst.parse_prices("■販売価格：拡張パック「テスト弾」 5,400円（1BOX） ■応募方法")
    assert [p["price_unit"] for p in one] == ["BOX"] and one[0]["retail_price"] == 5400
    near = {p["product_name"]: p["price_unit"] for p in hbst.parse_prices("■販売価格：商品A BOX 5,400円 商品B 5,500円 ■各1BOX")}
    assert near["商品A"] == "BOX" and near["商品B"] == "UNKNOWN"


def test_hbst_box_price_below_floor_is_not_adopted_and_floor_is_shared_with_clabo():
    assert hbst.MIN_BOX_PRICE_JPY == clabo.MIN_BOX_PRICE_JPY == 1000
    assert hbst.parse_prices("■販売価格：拡張パック「テスト弾」 BOX 0,999円") == []         # 桁区切りの誤記で 1,000 円未満になった BOX 価格（パック単価・桁落ちの疑い）
    assert [p["price_unit"] for p in hbst.parse_prices("■販売価格：拡張パック「テスト弾」 0,999円 ■各1BOX")] in ([], ["UNKNOWN"])      # 購入数の制限だけでは BOX にしない（UNKNOWN は台帳でも採用されない）


# ---------------------------------------------------------------- clabo: 販売期間の見出しは当選者向けだけ購入期間にする
def test_clabo_only_winner_sale_periods_become_purchase_period():
    base = "抽選期間\n応募期間：2026年11月20日〜2026年11月25日\n"
    for non_winner in ("通常販売期間", "予約販売期間", "一般販売期間", "当選者でない方の店頭販売期間"):
        out = clabo.normalize_body(base + non_winner + "：2026年12月01日〜2026年12月10日")
        assert "購入期間：2026年12月01日" not in out and non_winner + "：" in out
    for winner in ("販売期間", "当選者店頭販売期間", "当選者販売期間", "当選者の方店頭販売期間", "当選者の方の店頭販売期間"):
        assert "購入期間：2026年12月01日" in clabo.normalize_body(base + winner + "：2026年12月01日〜2026年12月10日")
    a = clabo.CardLaboLotteryAdapter()
    evs = a.build_from_article(title="抽選販売のお知らせ", body=clabo.normalize_body(base + "通常販売期間：2026年12月01日〜2026年12月10日"),
                               url="https://www.c-labo.jp/shop/x/blog/1/", published_at="2026-11-20T00:00:00+09:00", tcg_hint="POKEMON",
                               store_name="カードラボ池袋店", store_id="x", targets=None)
    assert all(str(e.get("purchase_start_date") or "")[:10] != "2026-12-01" for e in evs)


def test_hbst_unregistered_product_keeps_an_unlinked_subject_event_and_funnel_record():
    """M2: 複数商品の告知で、registry に無い商品（ムニキスゼロ）の抽選を捨てない。登録済み（ハドウシーカー）は価格つき、
    未登録分は件名由来の未紐付けイベント（価格なし・product_match=none）で残る。funnel にも記録される。"""
    d = hbst_body()
    tg = hbst.build_targets(d["title"], d["body"], POKEMON)
    named = {t["product_name"]: t["retail_price"] for t in tg}
    assert named["拡張パック「ハドウシーカー」"] == 6000
    assert any(t["retail_price"] is None and "二種" in t["product_name"] for t in tg)      # 未紐付け（価格なし）
    a = hbst.HobbyStationLotteryAdapter()
    evs = a.build_from_article(title=d["title"], body=d["body"], url="https://www.hbst.net/?p=412193", published_at="2026-11-24T00:00:00+09:00",
                               entry_url=None, result_url=None, tcg_hint="POKEMON", targets=tg)
    assert len(evs) == 2 and a.funnel.accepted_sales_events == 2
    rs = _resolve(evs, POKEMON)
    priced = [e for e in rs if e.get("retail_price")]
    unlinked = [e for e in rs if not e.get("retail_price")]
    assert len(priced) == 1 and priced[0]["product_match"] == "exact"
    assert len(unlinked) == 1 and unlinked[0]["product_match"] == "none"


def test_hbst_all_registered_products_add_no_unlinked_duplicate():
    d = hbst_body()
    only = d["body"].replace("ムニキスゼロ5,400円（税込） ", "")
    tg = hbst.build_targets(d["title"], only, POKEMON)
    assert [t["product_name"] for t in tg] == ["拡張パック「ハドウシーカー」"]


# ---------------------------------------------------------------- 別回・受付中と言えない collector 行（L1/L2）
def _d(days):
    return (NOW + timedelta(days=days)).strftime("%Y-%m-%d")


def _open_ledger(**kw):
    return _led(apply_start=_d(-1), apply_end=_d(2), purchase_start=_d(10), purchase_end=_d(16), **kw)


def _cr(**kw):
    base = dict(retail_price=6000, application_start_date=_d(-1), application_end_date=_d(2), purchase_start_date=_d(10), purchase_end_date=_d(16))
    base.update(kw)
    c = _crow(**base)
    c["retailer"], c["shop"] = "店", "テスト店"
    return c


def test_other_round_collector_row_is_not_a_price_mismatch_and_does_not_replace_open_ledger_row():
    """L1: 旧回の collector 行（応募終了済み・6,100 円）は、新回の台帳（受付中・6,000 円）と価格を比べない。受付中の台帳の行も消さない。"""
    old = _cr(retail_price=6100, application_start_date=_d(-30), application_end_date=_d(-25), purchase_start_date=_d(-20), purchase_end_date=_d(-15))
    rows, errs = rb.merge_rows([old], [_open_ledger()], NOW)
    assert not [e for e in errs if e["kind"] == "PRICE_MISMATCH"]
    assert len(rows) == 1 and rows[0]["source"] == "manual" and rb.accept_state(rows[0], NOW) == rb.S_OPEN
    assert [e["kind"] for e in errs] == ["COLLECTOR_NOT_OPEN"] and "別の回" in errs[0]["message"]


def test_other_round_price_difference_is_ignored_when_ledger_is_the_old_round():
    old_led = _led(apply_start=_d(-30), apply_end=_d(-25), purchase_start=_d(-20), purchase_end=_d(-15), price_jpy=6100)
    rows, errs = rb.merge_rows([_cr()], [old_led], NOW)
    assert not [e for e in errs if e["kind"] == "PRICE_MISMATCH"]
    assert rows[0]["source"] == "collector"


@pytest.mark.parametrize("kw,why", [
    ({"application_end_date": None, "purchase_start_date": None, "purchase_end_date": None}, "応募終了日"),
    ({"verified": False}, "未検証"),
    ({"conflict": True}, "食い違"),
])
def test_collector_row_that_cannot_be_called_open_keeps_the_open_ledger_row(kw, why):
    """L2: apply_end なし・未検証・conflict の collector 行は、台帳の受付中の行を置き換えない（利益が消えない）。理由を検証エラーに出す。"""
    c = _cr(**kw)
    rows, errs = rb.merge_rows([c], [_open_ledger()], NOW)
    assert len(rows) == 1 and rows[0]["source"] == "manual"
    assert rb.classify(rows[0], {("POKEMON", "box"): {}}, NOW)["kind"] == rb.K_CONDITIONAL
    assert [e["kind"] for e in errs] == ["COLLECTOR_NOT_OPEN"] and why in errs[0]["message"]


def test_open_collector_row_still_replaces_ledger_row_and_same_round_price_mismatch_goes_reference_only():
    rows, errs = rb.merge_rows([_cr(retail_price=6500)], [_open_ledger()], NOW)
    assert rows[0]["source"] == "collector" and rows[0]["price_conflict"] == {"collector_price": 6500, "manual_price": 6000}
    assert [e["kind"] for e in errs] == ["PRICE_MISMATCH"] and errs[0]["resolution"] == "reference_only"
    assert rb.classify(rows[0], {("POKEMON", "box"): {}}, NOW)["kind"] == rb.K_REFERENCE
    rows2, errs2 = rb.merge_rows([_cr()], [_open_ledger()], NOW)                      # 価格が一致すれば従来どおり利益に使える
    assert errs2 == [] and rb.classify(rows2[0], {("POKEMON", "box"): {}}, NOW)["kind"] == rb.K_CONDITIONAL


def test_m3_mismatch_shows_on_the_page_and_price_conflict_row_has_no_profit(monkeypatch):
    """M3: 台帳と自動取得の価格食い違いは、hub の辞書だけでなく tcg.html の販売店 BOX 節にも出る（店・商品・種別・双方の値・扱い）。
    価格が食い違う行は利益計算に使わない（参考止まり）。食い違いが 0 件なら節を出さない。"""
    import src.tcg.buyback as m
    from tests.test_tcg_buyback import CFG, art, page
    from src.content import tcg_hub_page as page_mod
    from src.tcg import buyback as bb
    from src.tcg.hub import product_view as pv
    monkeypatch.setattr(m, "load_config", lambda *a, **k: CFG)
    rows = [{**r, "page_asof": NOW.isoformat()} for r in bb.parse_rudeya(page(art("拡張パック BOX", 9000, "4500000000222")), "u", NOW)["rows"]]
    ev = _ev(application_end=(NOW + timedelta(days=1)).isoformat(), application_end_date=None, retail_price=6500, retailer="店", retailer_name="テスト店",
             purchase_start_date=(NOW + timedelta(days=10)).strftime("%Y-%m-%d"), purchase_end_date=(NOW + timedelta(days=16)).strftime("%Y-%m-%d"))
    monkeypatch.setattr(rb, "load_ledger", lambda *a, **k: [_open_ledger()])
    h = pv.build_hub({"items": [ev]}, REG, {"verified": []}, NOW, {"rows": rows})
    assert "PRICE_MISMATCH" in [e["kind"] for e in h["retailer_validation_errors"]]
    assert h["retailer_opportunities"] == []                                       # 利益に使わない
    assert any("食い違" in (r.get("reason") or "") for r in h["retailer_references"])
    html = page_mod.render(h)
    sec = html[html.index("台帳と自動取得の食い違い（"):]
    sec = sec[:sec.index("</details>")]
    assert "テスト店" in sec and "拡張パック BOX" in sec and "価格" in sec and "6,000" in sec and "6,500" in sec and "公式ページで確認してください" in sec
    monkeypatch.setattr(rb, "load_ledger", lambda *a, **k: [])
    h0 = pv.build_hub({"items": []}, REG, {"verified": []}, NOW, {"rows": rows})
    assert "台帳と自動取得の食い違い" not in page_mod.render(h0)                       # 0 件なら出さない


@pytest.mark.parametrize("label", [
    "落選者・未当選の方の販売期間", "余剰分の店頭販売期間", "抽選に外れた方の店頭販売期間", "当選者以外の店頭販売期間",
    "店頭のみ販売期間", "商品販売期間", "未当選者販売期間", "落選者の方の販売期間", "余剰販売期間",
])
def test_clabo_unknown_prefixed_sale_period_is_never_the_winner_purchase_period(label):
    """M1: 許可リスト（当選者向けと明確な見出しの完全一致）に無い前置きの販売期間は、書き換えない（fail-open にしない）。"""
    base = "抽選期間\n応募期間：2026年11月20日〜2026年11月25日\n"
    for sep in ("", "。"):                       # 行頭・句点の直後
        out = clabo.normalize_body(base + sep + label + "：2026年12月01日〜2026年12月10日")
        assert "購入期間：2026年12月01日" not in out and label + "：" in out
    out = clabo.normalize_body(base + "※" + "販売期間" + "：2026年12月01日〜2026年12月10日")      # 行頭でない（前置き記号つき）も書き換えない
    assert "購入期間：2026年12月01日" not in out
    if label == "商品販売期間":
        return                      # 共通の解析器（src/tcg/lottery/parse.py）が「商品販売期間」を購入期間の見出しとして読む。clabo の書き換えとは別（要確認として報告）
    a = clabo.CardLaboLotteryAdapter()
    evs = a.build_from_article(title="抽選販売のお知らせ", body=clabo.normalize_body(base + label + "：2026年12月01日〜2026年12月10日"),
                               url="https://www.c-labo.jp/shop/x/blog/1/", published_at="2026-11-20T00:00:00+09:00", tcg_hint="POKEMON",
                               store_name="カードラボ池袋店", store_id="x", targets=None)
    assert all(str(e.get("purchase_start_date") or "")[:10] != "2026-12-01" for e in evs)


def test_clabo_real_page_labels_still_read_purchase_period():
    """実ページ由来の fixture（池袋『販売期間：』・難波『当選者店頭販売期間：』）は購入期間を読める。"""
    _a, ike_body = _clabo_body("detail_ikebukuro_eb05.html")
    _a, nam_body = _clabo_body("detail_namba_op18.html")
    assert "購入期間：2026年11月24日" in ike_body and "購入期間：2026年11月21日" in nam_body


def test_terms_status_wording_is_consistent_for_clabo_and_hbst():
    """Auditor M1: 規約の確認状況の記述が、registry の note と collector の docstring で食い違わない
    （robots.txt は対象ページを禁止していない・利用規約の本文は未読で、許可も禁止も未確認）。"""
    from src.tcg.lottery.registry import LOTTERY_SOURCES
    notes = {s["source_id"]: s["note"] for s in LOTTERY_SOURCES}
    for sid, mod in (("CARD_LABO", clabo), ("HOBBY_STATION", hbst)):
        assert "利用規約の本文は未読で、許可も禁止も未確認" in notes[sid] and "読み取れなかった" not in notes[sid] and "見当たらない" not in notes[sid]
        assert "利用規約の本文は未読で、許可も禁止も未確認" in mod.__doc__ and "robots.txt" in notes[sid] and "確認日" in notes[sid]


# ---------------------------------------------------------------- Reviewer M1: 購入数の制限は価格の単位ではない
_TWO = "■販売価格：商品A 5,400円 商品B 5,400円 ※当選者様は各2BOXまで{tail}"


@pytest.mark.parametrize("tail", [" ■応募方法", " 応募方法", ""])
def test_hbst_purchase_limit_never_makes_multi_price_block_box_regardless_of_block_boundary(tail):
    rows = hbst.parse_prices(_TWO.format(tail=tail))
    assert [r["price_unit"] for r in rows] == ["UNKNOWN", "UNKNOWN"] and len(rows) == 2


def test_hbst_two_products_with_limit_note_inside_block_are_unknown_not_box():
    rows = hbst.parse_prices("■販売価格：A商品 5,400円 B商品 5,400円 ※当選者様は各2BOXまで ■応募方法")
    assert [r["price_unit"] for r in rows] == ["UNKNOWN", "UNKNOWN"]


@pytest.mark.parametrize("body,unit", [
    ("■販売価格：拡張パック「テスト弾」 1BOX 6,000円 ■応募方法", "BOX"),
    ("■販売価格：拡張パック「テスト弾」（BOX）6,000円 ■応募方法", "BOX"),
    ("■販売価格：拡張パック「テスト弾」 6,000円（1BOX） ■応募方法", "BOX"),
    ("■販売価格：拡張パック「テスト弾」 6,000円 1BOX ■応募方法", "BOX"),
    ("■販売価格：拡張パック「テスト弾」 6,000円 ■各1BOX ■応募方法", "UNKNOWN"),
    ("■販売価格：拡張パック「テスト弾」 6,000円 ※当選者様は各2BOXまで ■応募方法", "UNKNOWN"),
    ("■販売価格：拡張パック「テスト弾」 6,000円 お一人様1BOXまで ■応募方法", "UNKNOWN"),
    ("■販売価格：拡張パック「テスト弾」 6,000円 ※1BOXまで ■応募方法", "UNKNOWN"),
])
def test_hbst_single_price_box_only_with_unit_right_after_price(body, unit):
    rows = hbst.parse_prices(body)
    assert [r["price_unit"] for r in rows] == [unit]


def test_hbst_per_product_box_mark_confirms_only_that_product():
    rows = {r["product_name"]: r["price_unit"] for r in hbst.parse_prices("■販売価格：商品A 1BOX 6,000円 商品B 5,400円 ※各2BOXまで ■応募方法")}
    assert rows == {"商品A": "BOX", "商品B": "UNKNOWN"}


# ---------------------------------------------------------------- Reviewer L1: 同じ collector 行を 2 回出さない
def test_merge_rows_emits_same_collector_row_once_for_two_ledger_rows():
    c = _crow()
    c["id"] = "collector-1"
    l1 = _led(price_jpy=6000, apply_end="2026-11-22", purchase_end="2026-11-30")
    l2 = _led(price_jpy=6000, apply_end="2026-11-22", purchase_end="2026-11-30")
    rows, _ = rb.merge_rows([c], [l1, l2])
    assert [r for r in rows if r.get("source") == "collector"].__len__() == 1
    assert len(rows) == 1


# ---------------------------------------------------------------- 独立レビューの指摘（M1・L1・L5）
def _same_round_collector(**kw):
    c = _crow(retail_price=6000, application_end_date=(NOW + timedelta(days=1)).strftime("%Y-%m-%d"), purchase_start_date=None, purchase_end_date=None, **kw)
    c["retailer"], c["shop"] = "店", "テスト店"
    return c


def test_m1_box_confirmed_mismatch_with_unadoptable_collector_makes_ledger_reference_only():
    """単位 BOX 確定の collector 価格が台帳と食い違う（collector 側が同一性などで採用できなくても）なら、台帳の行も参考止まり。"""
    c = _same_round_collector()
    c["product_match"] = "partial"                         # 採用できない（exact でない）が単位は BOX 確定
    assert rb.adoptable(c) is False
    rows, errs = rb.merge_rows([c], [_led(price_jpy=7200)])
    assert len(rows) == 1 and rows[0]["source"] == "manual" and rows[0].get("price_conflict")
    assert errs[0]["kind"] == "PRICE_MISMATCH" and errs[0]["resolution"] == "reference_only"
    cl = rb.classify(rows[0], {("POKEMON", "box"): {}}, NOW)
    assert cl["kind"] == rb.K_REFERENCE and cl["executable"] is False
    html = page_mod._rb_mismatch(errs)
    assert "利益計算に使わず参考止まり" in html and "台帳の値を維持" not in html


def test_m1_unit_unknown_mismatch_keeps_ledger_and_wording_matches_behavior():
    """単位 UNKNOWN の collector 価格との食い違いは INFO で記録するだけ。台帳は条件付き利益の対象のまま。文言も実挙動どおり。"""
    c = _same_round_collector(price_unit="UNKNOWN")
    rows, errs = rb.merge_rows([c], [_led(price_jpy=7200)])
    assert len(rows) == 1 and rows[0]["source"] == "manual" and rows[0]["price_jpy"] == 7200 and not rows[0].get("price_conflict")
    assert errs[0]["kind"] == "PRICE_MISMATCH" and errs[0]["resolution"] == "ledger_kept_unit_unknown" and errs[0]["severity"] == "INFO"
    cl = rb.classify(rows[0], {("POKEMON", "box"): {}}, NOW)
    assert cl["kind"] == rb.K_CONDITIONAL
    html = page_mod._rb_mismatch(errs)
    assert "単位が確認できない自動取得の価格と食い違っています。台帳の値を維持しました" in html
    assert "利益計算に使わず参考止まりにしました" not in html


@pytest.mark.parametrize("tail,unit", [
    (" ※BOX特典なし", "UNKNOWN"), (" ボックス購入者のみ", "UNKNOWN"), (" BOXの中身", "UNKNOWN"), (" BOX付き", "UNKNOWN"),
    ("", "UNKNOWN"), (" BOX", "BOX"), ("（税込）/BOX", "BOX"), (" ／ボックス", "BOX"), (" 1BOXあたり", "BOX"), (" 1ボックスにつき", "BOX"),
])
def test_l1_price_unit_box_must_follow_the_yen_directly(tail, unit):
    rows = hbst.parse_prices(f"販売価格：拡張パック「テスト」 6,000円{tail}")
    assert [r["price_unit"] for r in rows] == [unit]


def test_l5_bare_sales_period_with_general_sale_qualifier_is_not_rewritten():
    body = "抽選期間：11/1〜11/5\n当選者販売期間：11/10〜\n販売期間：11/15〜11/20 (先着販売)"
    out = clabo.normalize_body(body)
    assert "購入期間：11/10〜" in out and "販売期間：11/15〜11/20 (先着販売)" in out and out.count("購入期間：") == 1
    for q in ("（先着）", "一般販売", "(通常販売)", "（予約）"):
        assert "購入期間：" not in clabo.normalize_body(f"抽選期間：11/1〜11/5\n当選者の購入\n販売期間：11/15〜11/20 {q}")
    assert "購入期間：11/10" in clabo.normalize_body("抽選期間：11/1〜11/5\n販売期間：11/10〜11/12")      # 修飾が無ければ従来どおり


# ---------------------------------------------------------------- Reviewer M2: BOX 確定は許可リスト方式
@pytest.mark.parametrize("tail", [
    "BOXセット", "BOX+特典", "BOX未開封", "BOX在庫", "BOXの数", "BOX1個まで", "BOXs", "BOXの中身", "BOX特典なし", "BOX購入者のみ", "BOXのみ", "BOX限定",
    "ボックスセット", "1BOX特典付き", "1BOX在庫あり", "BOX2個", "BOXA", "BOXでき", "BOXでの購入", " BOX セット", " BOX 在庫", "※BOX特典なし", " ※BOX特典なし",
    "（税込）※BOX特典なし", "ボックス購入者のみ", " BOX+特典付き",
])
def test_hbst_box_unit_not_confirmed_when_followed_by_other_words(tail):
    rows = hbst.parse_prices(f"販売価格：拡張パック「テスト」 6,000円{tail}")
    assert [r["price_unit"] for r in rows] == ["UNKNOWN"], tail


@pytest.mark.parametrize("tail", [
    "（1BOX）", "/BOX", " 1BOXあたり", " 1BOX あたり", " 1BOX につき", " 1BOXにつき", " BOX。", " BOX", " BOX ", " 1ボックス", "(BOX)", "／ボックス", " BOX、",
    " BOXで", " BOXです", " BOXとなります", " BOX ■応募方法", " BOX・", " BOX/", "（税込）/1BOX",
])
def test_hbst_box_unit_confirmed_for_allowed_endings(tail):
    rows = hbst.parse_prices(f"販売価格：拡張パック「テスト」 6,000円{tail}")
    assert [r["price_unit"] for r in rows] == ["BOX"], tail


def test_hbst_box_unit_allowlist_applies_with_newline_and_symbol_boundaries():
    for tail in ("1BOX\n", "1BOX\n※BOX特典なし", "1BOX ■応募方法", "1BOX ▼注意", "1BOX ◆注意", "1BOX ●注意"):
        pat = hbst._PRICE_UNIT_AFTER
        assert pat.search(" " + tail), tail
    for tail in ("BOX\nセット", "BOXs\n", "BOX1個まで"):
        assert not hbst._PRICE_UNIT_AFTER.search(" " + tail), tail
    rows = hbst.parse_prices("■販売価格：拡張パック「テスト」 6,000円 1BOX\n※BOX特典なし ■応募方法")
    assert [r["price_unit"] for r in rows] == ["BOX"]


def test_hbst_real_fixture_two_prices_stays_unknown():
    body = "■販売価格：拡張パック「ハドウシーカー」6,000円 拡張パック「ムニキスゼロ」5,400円 BOX ■応募方法"
    assert {r["price_unit"] for r in hbst.parse_prices(body)} == {"UNKNOWN"}


# ---------------------------------------------------------------- Reviewer L4: 素の「販売期間」は抽選期間の見出しの直後だけ購入期間にする
def test_clabo_bare_sales_period_rewritten_only_right_after_lottery_heading():
    ok = "〈抽選期間〉\n応募期間：11/1〜11/5\n当選発表：11/6〜11/7\n販売期間：11/10〜11/12"
    assert "購入期間：11/10" in clabo.normalize_body(ok)
    assert "購入期間：11/10" in clabo.normalize_body("抽選期間：11/1〜11/5\n販売期間：11/10〜11/12")
    # 見出しも当選の語もない素の販売期間（抽選期間の見出しが離れている・間に別の行がある）は書き換えない
    far = "〈抽選期間〉\n応募期間：11/1〜11/5\n当選発表：11/6〜11/7\n※注意\n販売期間：11/10〜11/12"
    assert "購入期間：" not in clabo.normalize_body(far)
    assert "購入期間：" not in clabo.normalize_body("抽選期間：11/1〜11/5\n商品説明\n販売期間：11/10〜11/12")
    # 当選の語が近くにあっても、構造の根拠が無ければ書き換えない
    assert "購入期間：" not in clabo.normalize_body("抽選期間：11/1〜11/5\n当選者の方のみ\n販売期間：11/10〜11/12")
    # 行の途中（「。」の後）・一般向けの語・次の行の一般向けの語
    assert "購入期間：" not in clabo.normalize_body("抽選期間：11/1〜11/5\n応募期間：11/1。販売期間：11/10〜11/12")
    assert "購入期間：" not in clabo.normalize_body(ok + " （先着）")
    assert "購入期間：" not in clabo.normalize_body(ok + "\n先着販売期間：11/20〜")
    # 抽選期間の見出しが無い記事は何も書き換えない
    assert "購入期間：" not in clabo.normalize_body("応募期間：11/1〜11/5\n当選発表：11/6〜11/7\n販売期間：11/10〜11/12")
