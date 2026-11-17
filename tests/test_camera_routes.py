# -*- coding: utf-8 -*-
"""camera_routes（利益ルート A〜D）のテスト。同一性・状態・売値の種別・成約・手数料・鮮度・判定。"""
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from pathlib import Path

from src.research import camera_routes as cr

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=JST)
CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "camera_routes.yaml").read_text(encoding="utf-8"))
SHIP0 = lambda pid, url, price: {"fee": 0, "source": "test"}
FIXED = lambda: 1800


def rec(product="RICOH GR IV HDF", *, official=None, retail=(), buyback=(), listing=(), sold=()):
    return {"product": product, "product_id": "p1", "official": official, "retail": list(retail), "buyback": list(buyback),
            "listing": list(listing), "sold": list(sold)}


def off(price=200000, stock="AVAILABLE", day="2026-11-18"):
    return {"shop": "公式", "price_jpy": price, "price_kind": "OFFICIAL_RETAIL", "stock": stock, "url": "https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0&pid=S0001566&cat=002010",
            "checked_at": day, "purchase_shipping_jpy": 0, "stock_evidence": "購入ボタンあり"}


_HOST = {"買取A": "www.kaitorishouten-co.jp", "買取B": "www.netoff.co.jp", "買取C": "www.sofmap.com", "買取D": "www.janpara.co.jp"}


def _bb_url(shop):
    h = _HOST.get(shop, "www.kaitorishouten-co.jp")
    n = abs(hash(shop)) % 90000 + 10000
    if "kaitorishouten" in h:
        return f"https://{h}/products/detail/{n}"
    if "netoff" in h:
        return f"https://{h}/kaden/detail/{n}"
    return f"https://{h}/p/{n}"


def bb(shop="買取A", price=240000, cond="UNOPENED", title="RICOH GR IV HDF", upd="2026-11-17", day="2026-11-18", page=True, **kw):
    return {"shop": shop, "item_title": title, "price_jpy": price, "condition": cond, "url": _bb_url(shop), "is_product_page": page,
            "checked_at": day, "source_updated_at": upd, **kw}


def lst(price=230000, cond="NEW", title="RICOH GR IV HDF", ok=True, market="店B中古", day="2026-11-18"):
    return {"market": market, "item_title": title, "price_jpy": price, "condition": cond, "url": "https://www.mapcamera.com/item/12345678", "checked_at": day,
            "purchasable_now": ok, "shipping_jpy": 1000, "shipping_url": "https://www.mapcamera.com/ship"}


def _sold_url(market, n):
    if market == "ラクマ":
        return f"https://item.fril.jp/abcdef{n}1234567"
    return f"https://jp.mercari.com/item/m1234567{n:04d}1"


def sold(price, day, market="メルカリ", cond="NEW", title="RICOH GR IV HDF", n=0):
    return {"market": market, "item_title": title, "price_jpy": price, "condition": cond, "sold_at": day, "url": _sold_url(market, n)}


def build(r, registered=("RICOH GR IV HDF",), cfg=CFG):
    return cr.build_market([r], NOW, cfg, registered_names=set(registered), official_shipping_fn=SHIP0, fixed_cost_fn=FIXED)


def route(m, t):
    return next(x for x in m["routes"] if x["route_type"] == t)


# ---- 同一性 ----
@pytest.mark.parametrize("product,title,ok", [
    ("RICOH GR IV", "コンパクトデジタルカメラ RICOH GR IV", True),
    ("RICOH GR IV", "RICOH GR IV HDF", False),
    ("RICOH GR IV", "RICOH GR IV Monochrome", False),
    ("RICOH GR IV", "RICOH GR IIIx", False),
    ("RICOH GR IV HDF", "RICOH GR IV", False),
    ("FUJIFILM X100VI", "FUJIFILM X100V", False),
    ("FUJIFILM X100VI", "FUJIFILM X100VI [シルバー]2025版", False),
    ("FUJIFILM X100VI", "FUJIFILM X100VI [ブラック] デジタルカメラ", True),
    ("Nikon Z8", "Z 8 ボディ", True),
    ("Nikon Zf", "デジタル一眼カメラ Z f ボディ", True),
    ("Canon EOS R5 Mark II", "Canon EOS R5 Mark III", False),
    ("SONY α7R V", "ソニー α7R IV", False),
    ("SONY α7R V", "SONY α7R V ILCE-7RM5", True),
    ("Nikon Z8", "", False),
    ("Nikon Z8", "買取価格", False),
])
def test_identity(product, title, ok):
    assert cr.identity_ok(product, title)[0] is ok


def test_identity_wrong_row_is_not_used_in_route():
    m = build(rec(official=off(), buyback=[bb(title="RICOH GR IV", price=300000)]))
    r = route(m, "A")
    assert r["profit_status"] == cr.NOT_CALCULATED and r["sell"] is None


# ---- ROUTE A ----
def test_route_a_net_and_costs_no_double_fee():
    m = build(rec(official=off(200000), buyback=[bb(price=240000)]))
    r = route(m, "A")
    assert r["profit_status"] == cr.PROFITABLE
    c = r["costs"]
    assert c["selling_fee"] == 0 and c["selling_fee_applies"] is False        # 買取に販売手数料は無い（二重に引かない）
    assert r["net_profit"] == 240000 - 200000 - 0 - 1800 - 0 - 0
    assert m["products"][0]["best_route"] == "A"
    assert not any(cr.quality_checks(m, NOW, "2026-11-18", CFG).values())


def test_route_a_buy_requires_all_conditions():
    two = [bb("買取A", 240000), bb("買取B", 238000)]
    m = build(rec(official=off(200000), buyback=two))
    r = route(m, "A")
    assert r["decision"] == cr.BUY and r["executable"] and r["confidence"] == "high"
    # 買取が 1 店だけ → BUY にしない
    assert route(build(rec(official=off(200000), buyback=[bb()])), "A")["decision"] != cr.BUY
    # 未登録 → BUY にしない
    assert route(build(rec(official=off(200000), buyback=two), registered=()), "A")["decision"] != cr.BUY
    # 外れ値（最高が 2 位より 15% 超高い）→ BUY にしない
    assert route(build(rec(official=off(200000), buyback=[bb("買取A", 300000), bb("買取B", 238000)])), "A")["decision"] != cr.BUY
    # 買取の更新日が不明 → BUY にしない
    assert route(build(rec(official=off(200000), buyback=[bb("買取A", 240000, upd=None), bb("買取B", 238000, upd=None)])), "A")["decision"] != cr.BUY


@pytest.mark.parametrize("stock,dec", [("LOTTERY_DEPENDENT", cr.WAIT), ("RESERVATION", cr.WAIT), ("OUT_OF_STOCK", cr.WAIT), ("UNKNOWN", cr.WATCH)])
def test_profitable_but_not_buyable_is_never_buy(stock, dec):
    m = build(rec(official=off(200000, stock=stock), buyback=[bb("買取A", 240000), bb("買取B", 238000)]))
    r = route(m, "A")
    assert r["profit_status"] == cr.PROFITABLE and r["decision"] == dec and not r["executable"]


def test_roi_below_threshold_is_wait_not_buy():
    r = route(build(rec(official=off(230000), buyback=[bb("買取A", 240000), bb("買取B", 239000)])), "A")
    assert r["profit_status"] == cr.PROFITABLE and r["decision"] == cr.WAIT


def test_no_profit_is_skip():
    r = route(build(rec(official=off(260000), buyback=[bb()])), "A")
    assert r["profit_status"] == cr.NO_PROFIT and r["decision"] == cr.SKIP


def test_condition_mismatch_not_calculated():
    for cond in ("LIKE_NEW", "USED", "UNKNOWN"):
        r = route(build(rec(official=off(100000), buyback=[bb(price=240000, cond=cond)])), "A")
        assert r["profit_status"] == cr.NOT_CALCULATED and "condition_mismatch" in r["reasons"]


def test_stale_buyback_not_executable():
    r = route(build(rec(official=off(200000), buyback=[bb(upd="2026-10-01", day="2026-11-18")])), "A")
    assert r["profit_status"] == cr.NOT_CALCULATED       # 店の価格が古いなら売値にしない
    old = route(build(rec(official=off(200000, day="2026-10-01"), buyback=[bb()])), "A")
    assert old["profit_status"] == cr.NOT_CALCULATED


def test_future_checked_at_is_unknown_freshness():
    o = cr.observations(rec(buyback=[bb(day="2026-12-31", upd=None)]), NOW, CFG)[0]
    assert o["freshness"] == cr.UNKNOWN_FRESHNESS


def test_purchase_shipping_unknown_not_calculated():
    m = cr.build_market([rec(official={**off(200000), "purchase_shipping_jpy": None}, buyback=[bb()])], NOW, CFG,
                        registered_names={"RICOH GR IV HDF"}, official_shipping_fn=lambda *a: {"fee": None}, fixed_cost_fn=FIXED)
    r = route(m, "A")
    assert r["profit_status"] == cr.NOT_CALCULATED and "purchase_shipping_unknown" in r["reasons"]


def test_open_price_official_is_not_a_buy_price():
    o = dict(off(), price_kind="OPEN_PRICE", price_jpy=None)
    assert route(build(rec(official=o, buyback=[bb()])), "A")["profit_status"] == cr.NOT_CALCULATED


# ---- 二次流通・成約 ----
def test_listing_high_never_used_as_sell():
    r = rec(official=off(100000), listing=[lst(230000), lst(900000, market="店C")])
    m = build(r)
    sec = m["products"][0]["secondary"]["listing"]["NEW"]
    assert sec["low"] == 230000 and sec["high"] == 900000
    for x in m["routes"]:
        assert x["sell"] is None or x["sell"]["price_type"] in cr.SELL_TYPES
    assert not any(cr.quality_checks(m, NOW, "2026-11-18", CFG).values())


def test_sold_insufficient_samples_not_calculated():
    r = rec(official=off(200000), sold=[sold(250000, "2026-11-10", n=1), sold(260000, "2026-11-11", n=2)])
    b = route(build(r), "B")
    assert b["profit_status"] == cr.NOT_CALCULATED and b["sell"] is None and "sold_insufficient" in b["reasons"]


def test_sold_median_route_b_with_fee_and_evidence():
    r = rec(official=off(200000), sold=[sold(250000, "2026-11-10", n=1), sold(260000, "2026-11-11", n=2), sold(270000, "2026-11-12", n=3)])
    m = build(r)
    b = route(m, "B")
    assert b["sell"]["price_type"] == cr.SOLD_MEDIAN and b["sell"]["price"] == 260000
    assert b["sell"]["evidence"]["sample_count"] == 3 and b["sell"]["evidence"]["period"]
    assert b["costs"]["selling_fee"] == 26000 and b["costs"]["selling_fee_rate"] == 0.10          # メルカリ 10%
    assert b["net_profit"] == 260000 - 200000 - 0 - 1500 - 26000 - 0
    assert b["decision"] != cr.BUY                                                                  # 二次流通の売値は自動の BUY にしない
    assert not any(cr.quality_checks(m, NOW, "2026-11-18", CFG).values())


def test_sold_without_individual_evidence_or_old_period_is_ignored():
    rows = [sold(250000, "2026-11-10", n=1), sold(260000, "2026-11-11", n=2), sold(270000, "2025-01-01", n=3)]      # 3 件目は期間外
    assert route(build(rec(official=off(200000), sold=rows)), "B")["profit_status"] == cr.NOT_CALCULATED
    rows2 = [{**sold(250000 + i, "2026-11-10", n=i), "url": ""} for i in range(3)]                                 # 個別の根拠なし
    assert route(build(rec(official=off(200000), sold=rows2)), "B")["profit_status"] == cr.NOT_CALCULATED


def test_unconfirmed_fee_market_not_calculated_not_zero():
    rows = [sold(250000 + i, f"2026-11-1{i}", market="ラクマ", n=i) for i in range(3)]
    b = route(build(rec(official=off(200000), sold=rows)), "B")
    assert b["profit_status"] == cr.NOT_CALCULATED and "fee_unconfirmed" in b["reasons"]


def test_sold_condition_family_not_mixed():
    rows = [sold(250000 + i, f"2026-11-1{i}", cond="USED", n=i) for i in range(3)]          # 中古の成約
    assert route(build(rec(official=off(200000), sold=rows)), "B")["profit_status"] == cr.NOT_CALCULATED   # 新品の仕入れには使わない


def test_route_c_listing_low_to_buyback_needs_compatible_condition():
    m = build(rec(listing=[lst(200000, "NEW")], buyback=[bb(price=240000, cond="UNOPENED")]))
    c = route(m, "C")
    assert c["profit_status"] == cr.PROFITABLE and c["buy"]["price_type"] == cr.LISTING_LOW
    assert c["costs"]["purchase_shipping"] == 1000 and c["net_profit"] == 240000 - 200000 - 1000 - 1800
    used = route(build(rec(listing=[lst(150000, "USED")], buyback=[bb(price=240000, cond="UNOPENED")])), "C")
    assert used["profit_status"] == cr.NOT_CALCULATED                                           # 中古の最安を新品の仕入れ値にしない
    assert route(build(rec(listing=[lst(200000, "NEW", ok=False)], buyback=[bb()])), "C")["profit_status"] == cr.NOT_CALCULATED


def test_route_d_listing_low_to_sold_median():
    rows = [sold(260000 + i, f"2026-11-1{i}", n=i) for i in range(3)]
    d = route(build(rec(listing=[lst(200000)], sold=rows)), "D")
    assert d["profit_status"] == cr.PROFITABLE and d["costs"]["selling_fee"] == 26000


# ---- 品質の検出（壊したら 0 でなくなること） ----
def test_quality_detects_violations():
    m = build(rec(official=off(200000), buyback=[bb("買取A", 240000), bb("買取B", 238000)]))
    r = route(m, "A")
    r["sell"]["price_type"] = cr.LISTING_HIGH
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG)["listing_high_used_as_sell"] == 1
    r["sell"]["price_type"] = cr.BUYBACK_PRICE
    r["costs"]["selling_fee"] = 500
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG)["double_count_fee"] >= 1
    r["costs"]["selling_fee"] = 0
    r["buy"]["condition"] = "USED"
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG)["wrong_condition"] == 1
    r["buy"]["condition"] = "NEW"
    r["sell"]["freshness"] = cr.STALE
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG)["stale_price_used_as_fresh"] >= 1


def test_quality_detects_fake_checked_at_and_missing_fee():
    m = build(rec(official=off(200000), buyback=[bb()]))
    m["products"][0]["observations"][0]["checked_at"] = "2027-01-01"
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG)["fake_checked_at"] >= 1
    rows = [sold(250000 + i, f"2026-11-1{i}", n=i) for i in range(3)]
    m2 = build(rec(official=off(200000), sold=rows))
    route(m2, "B")["costs"]["selling_fee"] = 0
    assert cr.quality_checks(m2, NOW, "2026-11-18", CFG)["missing_fee"] >= 1


# ---- イベント ----
def test_diff_events():
    old = build(rec(official=off(230000), buyback=[bb("買取A", 230000)]))
    new = build(rec(official=off(230000), buyback=[bb("買取A", 240000), bb("買取B", 238000)]))
    ev = {e["type"] for e in cr.diff_events(old, new)}
    assert "BUYBACK_SURGE" in ev
    assert cr.diff_events(None, new) == []
    lo = build(rec(official=off(260000), buyback=[bb("買取A", 240000)]))      # NO_PROFIT
    hi = build(rec(official=off(200000), buyback=[bb("買取A", 240000)]))      # PROFITABLE
    assert any(e["type"] == "LOSS_TO_PROFIT" for e in cr.diff_events(lo, hi))
    assert any(e["type"] == "PROFIT_TO_LOSS" for e in cr.diff_events(hi, lo))
    b = build(rec(official=off(200000), buyback=[bb("買取A", 240000), bb("買取B", 238000)]))
    w = build(rec(official=off(200000, stock="OUT_OF_STOCK"), buyback=[bb("買取A", 240000), bb("買取B", 238000)]))
    assert any(e["type"] == "BUY_TO_WAIT" for e in cr.diff_events(b, w))
    assert any(e["type"] == "WAIT_TO_BUY" for e in cr.diff_events(w, b))


# ---- 独立レビューの指摘の回帰 ----
@pytest.mark.parametrize("product,title", [
    ("Nikon Z8", "Nikon Z8 II"), ("Nikon Zf", "Nikon Zf Gold"), ("RICOH GR III", "RICOH GR III x"),
    ("RICOH GR IV", "RICOH GR IV Highlight Diffusion Filter"), ("Canon EOS R3", "Canon EOS R3 ジャンク"),
    ("RICOH GR IV", "RICOH GR IV 訳あり 動作未確認"), ("Leica M11", "Leica M11 Monochrom")])
def test_identity_rejects_extended_models_and_junk(product, title):
    assert cr.identity_ok(product, title)[0] is False


def test_route_c_junk_listing_is_not_used_and_c_is_never_auto_buy():
    junk = route(build(rec(listing=[lst(30000, "USED", title="RICOH GR IV HDF ジャンク 部品取り")], buyback=[bb("買取A", 200000, cond="USED"), bb("買取B", 198000, cond="USED")])), "C")
    assert junk["profit_status"] == cr.NOT_CALCULATED
    ok = route(build(rec(listing=[lst(150000, "NEW")], buyback=[bb("買取A", 240000), bb("買取B", 238000)])), "C")
    assert ok["profit_status"] == cr.PROFITABLE and ok["decision"] != cr.BUY and "secondary_route_not_auto_buy" in ok["reasons"]


def test_sold_duplicate_urls_do_not_inflate_samples():
    one = sold(260000, "2026-11-10", n=1)
    r = route(build(rec(official=off(200000), sold=[dict(one), dict(one), dict(one)])), "B")
    assert r["profit_status"] == cr.NOT_CALCULATED


def test_sold_colors_are_not_mixed():
    rows = [sold(400000, "2026-11-10", n=1, title="RICOH GR IV HDF [シルバー]"), sold(280000, "2026-11-11", n=2, title="RICOH GR IV HDF [ブラック]"),
            sold(270000, "2026-11-12", n=3, title="RICOH GR IV HDF [ブラック]")]
    m = build(rec(official=off(200000), sold=rows))
    groups = m["products"][0]["secondary"]["sold"]
    assert all(g["sample_count"] < 3 and not g["eligible"] for g in groups.values())      # 色ごとに 3 件に届かない
    assert route(m, "B")["profit_status"] == cr.NOT_CALCULATED


def test_sold_route_freshness_uses_latest_sold_date():
    rows = [sold(260000 + i, f"2026-09-0{i + 1}", n=i) for i in range(3)]             # 最新の成約が 76 日前
    b = route(build(rec(official=off(200000), sold=rows)), "B")
    assert b["profit_status"] == cr.PROFITABLE and b["sell"]["freshness"] == cr.STALE and not b["executable"]
    assert b["sell"]["checked_at"] == "2026-09-03"


def test_stock_with_lottery_words_is_not_available_and_old_stock_is_not_buy():
    m = build(rec(official={**off(200000), "stock_evidence": "抽選販売（応募受付中）"}, buyback=[bb("買取A", 240000), bb("買取B", 238000)]))
    assert route(m, "A")["decision"] == cr.WAIT
    old = build(rec(official=off(200000, day="2026-11-12"), buyback=[bb("買取A", 240000), bb("買取B", 238000)]))     # 在庫の確認が 6 日前
    r = route(old, "A")
    assert r["decision"] != cr.BUY and not r["executable"]


def test_retail_shipping_is_not_borrowed_from_official_table():
    retail = [{"shop": "ヨドバシ", "item_title": "RICOH GR IV HDF", "price_jpy": 200000, "condition": "NEW", "stock": "AVAILABLE",
               "url": "https://www.yodobashi.com/product/100000001/", "checked_at": "2026-11-18"}]
    r = route(build(rec(retail=retail, buyback=[bb("買取A", 240000), bb("買取B", 238000)])), "A")
    assert r["profit_status"] == cr.NOT_CALCULATED and "purchase_shipping_unknown" in r["reasons"]


def test_quality_is_independent_of_route_labels():
    rows = [sold(250000 + i, f"2026-11-1{i}", n=i) for i in range(3)]
    base_m = lambda: build(rec(official=off(200000), buyback=[bb("買取A", 240000), bb("買取B", 238000)], sold=rows))
    # 売値を観測に無い値へ差し替え、純利益も整合させる → 検出
    m = base_m(); a = route(m, "A")
    a["sell"]["price"] = 999999; a["net_profit"] = 999999 - a["buy"]["price"] - a["costs"]["outbound_shipping"] - a["costs"]["purchase_shipping"]
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG, fixed_cost=1800)["listing_high_used_as_sell"] >= 1
    # 二次流通の手数料を改ざん → 検出
    m = base_m(); b = route(m, "B")
    b["costs"]["selling_fee"] = 7; b["net_profit"] = b["sell"]["price"] - b["buy"]["price"] - b["costs"]["outbound_shipping"] - 7
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG, fixed_cost=1800)["double_count_fee"] >= 1
    # 発送費の水増し（純利益は整合）→ 検出
    m = base_m(); a = route(m, "A")
    a["costs"]["outbound_shipping"] += 3000; a["net_profit"] -= 3000
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG, fixed_cost=1800)["double_count_fee"] >= 1
    # 色の食い違い → 検出
    m = base_m(); b = route(m, "B"); b["buy"]["color"] = "silver"; b["sell"]["color"] = "black"
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG, fixed_cost=1800)["wrong_condition"] >= 1
    # 古い日付のまま FRESH のラベル → 検出
    m = base_m(); a = route(m, "A"); a["buy"]["checked_at"] = "2020-01-01"
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG, fixed_cost=1800)["stale_price_used_as_fresh"] >= 1


# ---- 再レビューの指摘の回帰 ----
def _two_shops():
    return [bb("買取A", 240000), bb("買取B", 238000)]


def test_shop_count_uses_domain_not_name():
    rows = [{**bb("買取A", 240000), "shop": n, "url": f"https://www.kaitorishouten-co.jp/products/detail/{i + 1}"} for i, n in enumerate(["買取A", "買取A 本店", "買取Ａ"])]
    r = route(build(rec(official=off(200000), buyback=rows)), "A")
    assert r["sell"]["evidence"]["shops"] == 1 and r["decision"] != cr.BUY


def test_carried_and_stale_rows_do_not_count_as_shops():
    rows = [bb("買取A", 240000), {**bb("買取B", 238000), "carried": True}]
    r = route(build(rec(official=off(200000), buyback=rows)), "A")
    assert r["sell"]["evidence"]["shops"] == 1 and r["decision"] != cr.BUY


@pytest.mark.parametrize("url", ["https://kakaku.com/item/1", "https://compare.example/x", "http://evil.example/kaitorishouten-co.jp", ""])
def test_buyback_host_allowlist(url):
    rows = [{**bb("買取A", 240000), "url": url}, {**bb("買取B", 238000), "url": url}]
    r = route(build(rec(official=off(200000), buyback=rows)), "A")
    assert r["profit_status"] == cr.NOT_CALCULATED


def test_sold_url_variants_count_once():
    base = "https://jp.mercari.com/item/m123456789"
    rows = [{**sold(250000, "2026-11-10"), "url": u} for u in (base, base + "/", base + "#a", base + "?x=1")]
    assert route(build(rec(official=off(200000), sold=rows)), "B")["profit_status"] == cr.NOT_CALCULATED


@pytest.mark.parametrize("extra", [{"stock_evidence": "在庫切れ"}, {"note": "sold out"}, {"availability": "https://schema.org/OutOfStock"},
                                   {"note": "waitlist"}, {"note": "Lottery sale only"}, {"note": "売り切れ"}, {"note": "メーカー欠品"},
                                   {"note": "購入制限"}, {"note": "受注生産"}])
def test_available_is_denied_by_any_negative_wording(extra):
    r = route(build(rec(official={**off(200000), **extra}, buyback=_two_shops())), "A")
    assert r["decision"] != cr.BUY and not r["executable"]


def test_negated_out_of_stock_wording_is_allowed():
    r = route(build(rec(official={**off(200000), "stock_evidence": "購入ボタンあり・在庫切れ表示なし"}, buyback=_two_shops())), "A")
    assert r["decision"] == cr.BUY


@pytest.mark.parametrize("title", ["RICOH GR IV HDF 液晶割れ", "RICOH GR IV HDF 傷あり", "RICOH GR IV HDF 現状品", "RICOH GR IV HDF 要修理",
                                   "RICOH GR IV HDF SDカード付属", "RICOH GR IV HDF お得セット", "RICOH GR IV HDF 展示品", "RICOH GR IV HDF 開封済み"])
def test_condition_wording_rejected(title):
    assert cr.identity_ok("RICOH GR IV HDF", title)[0] is False


@pytest.mark.parametrize("title", ["RICOH GR IV ＨＤＦ", "RICOH GR IV ハイライトディフュージョンフィルター"])
def test_nfkc_and_kana_variants_for_plain_model(title):
    assert cr.identity_ok("RICOH GR IV", title)[0] is False


@pytest.mark.parametrize("title", ["Canon EOS R6 マーク2", "Canon EOS R6 Ⅱ", "Canon EOS R6 mk2", "Canon EOS R6 ２", "Canon EOS R6 海外モデル", "Canon EOS R6 US版", "Canon EOS R6 並行品"])
def test_model_continuations_and_overseas(title):
    assert cr.identity_ok("Canon EOS R6", title)[0] is False


def test_roi_over_100_is_never_buy():
    r = route(build(rec(official=off(60000), buyback=_two_shops())), "A")          # 60,000 円の仕入れ・買取 240,000 円
    assert r["decision"] != cr.BUY


def test_buy_gate_is_reverified_by_quality_checks():
    m = build(rec(official=off(200000), buyback=_two_shops()))
    assert route(m, "A")["decision"] == cr.BUY and not any(cr.quality_checks(m, NOW, "2026-11-18", CFG, fixed_cost=1800).values())
    next(o for o in m["products"][0]["observations"] if o["kind"] == "buyback" and o["source"] == "買取B")["carried"] = True   # 観測を壊す（自己申告は直さない）
    assert cr.quality_checks(m, NOW, "2026-11-18", CFG, fixed_cost=1800)["stale_price_used_as_fresh"] >= 1


def test_secondary_market_is_chosen_by_net_after_fee():
    rows = [sold(300000 + i, f"2026-11-1{i}", market="ラクマ", n=i) for i in range(3)] + [sold(250000 + i, f"2026-11-1{i}", market="メルカリ", n=i + 10) for i in range(3)]
    b = route(build(rec(official=off(200000), sold=rows)), "B")
    assert b["profit_status"] == cr.PROFITABLE and b["sell"]["source"] == "メルカリ"      # 手数料が未確認のラクマは選ばない


# ---- 3 回目のレビューの回帰 ----
def test_same_company_two_domains_is_one_shop():
    rows = [{**bb("買取A", 240000), "shop": "キタムラ", "url": "https://shop.kitamura.jp/p/1"},
            {**bb("買取B", 238000), "shop": "キタムラ", "url": "https://www.kitamura.co.jp/p/2"}]
    m = build(rec(official=off(200000), buyback=rows))
    r = route(m, "A")
    assert r["sell"]["evidence"]["shops"] == 1 and r["decision"] != cr.BUY
    assert cr.count_shops(m["products"][0], "NEW")[0] == 1


@pytest.mark.parametrize("url", ["https://www.yodobashi.com/?word=GR4", "https://www.yodobashi.com/category/1/", "https://www.mapcamera.com/ec/search?q=gr4",
                                 "https://www.biccamera.com/bc/category/001/", "https://www.yodobashi.com/"])
def test_search_and_list_pages_are_not_item_pages(url):
    retail = [{"shop": "ヨドバシ", "item_title": "RICOH GR IV HDF", "price_jpy": 200000, "condition": "NEW", "stock": "AVAILABLE", "url": url,
               "checked_at": "2026-11-18", "shipping_jpy": 0, "shipping_url": "https://www.yodobashi.com/ship/guide"}]
    r = route(build(rec(retail=retail, buyback=_two_shops())), "A")
    assert r["profit_status"] == cr.NOT_CALCULATED


@pytest.mark.parametrize("title,cond", [("【中古】RICOH GR IV HDF Aランク", "NEW"), ("RICOH GR IV HDF 中古品 美品", "NEW"), ("RICOH GR IV HDF (USED)", "UNOPENED"),
                                        ("RICOH GR IV HDF 新品同様", "NEW")])
def test_title_condition_contradiction_is_rejected(title, cond):
    retail = [{"shop": "ヨドバシ", "item_title": title, "price_jpy": 200000, "condition": cond, "stock": "AVAILABLE",
               "url": "https://www.yodobashi.com/product/100000001/", "checked_at": "2026-11-18", "shipping_jpy": 0, "shipping_url": "https://www.yodobashi.com/ship/guide"}]
    r = route(build(rec(retail=retail, buyback=_two_shops())), "A")
    assert r["profit_status"] == cr.NOT_CALCULATED


@pytest.mark.parametrize("title", ["RICOH GR IV HDF junk", "RICOH GR IV HDF Junk", "RICOH GR IV HDF ＪＵＮＫ", "RICOH GR IV HDF ｾｯﾄ", "RICOH GR IV HDF ｹｰｽ付",
                                   "RICOH GR IV HDF ftz", "RICOH GR IV HDF 難アリ", "RICOH GR IV HDF ｼﾞｬﾝｸ品"])
def test_junk_words_with_case_width_kana_variants(title):
    assert cr.identity_ok("RICOH GR IV HDF", title)[0] is False


@pytest.mark.parametrize("extra", [{"stock_evidence": "SOLD-OUT"}, {"stock_evidence": "OUT-OF-STOCK"}, {"stock_evidence": "在庫無"},
                                   {"stock_evidence": "在庫0"}, {"note": "Currently unavailable"}])
def test_more_negative_stock_wordings(extra):
    r = route(build(rec(official={**off(200000), **extra}, buyback=_two_shops())), "A")
    assert r["decision"] != cr.BUY


@pytest.mark.parametrize("ev", ["ページに日付なし", "予約・抽選の表示なし", "購入ボタンあり・在庫切れ表示なし"])
def test_negated_wordings_do_not_block_available(ev):
    assert cr.stock_of({"stock": "AVAILABLE", "stock_evidence": ev + " 購入ボタンあり"}) == cr.AVAILABLE


@pytest.mark.parametrize("url", ["https://evil.example\\@kaitorishouten-co.jp/x", "https://evil.example\\.kaitorishouten-co.jp/", "https://user@kaitorishouten-co.jp/x",
                                 "https://kaitorishouten-co.jp.evil.example/x", "https://evil.example/?u=kaitorishouten-co.jp", "https://kaitorishouten-co.jp/a b",
                                 "https://kaitorishouten-co.jp%40evil.example/x"])
def test_url_confusion_is_rejected(url):
    assert cr.domain_of(url) in ("", "evil.example") and cr._host_reason("buyback", url, CFG)


def test_shipping_needs_separate_allowed_evidence_url():
    o = {"kind": "official", "product_id": "zz", "url": "https://www.sony.jp/p/1", "price": 1, "shipping_jpy": 0, "shipping_url": "https://www.sony.jp/p/1"}
    assert cr._shipping(o, lambda *a: {"fee": None}, CFG["allowed_hosts"])[0] is None                 # 商品ページ自身は送料の根拠にならない
    o["shipping_url"] = "https://www.sony.jp/shipping/"
    assert cr._shipping(o, lambda *a: {"fee": None}, CFG["allowed_hosts"]) == (0, "research")
    o["shipping_url"] = "https://blog.example/ship"
    assert cr._shipping(o, lambda *a: {"fee": None}, CFG["allowed_hosts"])[0] is None


def test_sold_market_and_fee_come_from_url_host_not_label():
    rows = [{**sold(250000 + i, f"2026-11-1{i}", n=i), "market": "Yahooフリマ"} for i in range(3)]       # 実際は Mercari の URL
    b = route(build(rec(official=off(200000), sold=rows)), "B")
    assert b["sell"]["source"] == "メルカリ" and b["costs"]["selling_fee_rate"] == 0.10


def test_utc_z_date_is_converted_to_jst():
    assert cr.freshness({"checked_at": "2026-11-18T20:00:00Z"}, NOW, CFG)[0] == cr.UNKNOWN_FRESHNESS      # JST では 11-19 05:00（未来）


# ---- 4 回目のレビューの回帰 ----
@pytest.mark.parametrize("upd", ["2026/11/01", "2026年10月1日", "11/01", "先週", "不明"])
def test_unparseable_or_slash_update_dates_never_make_old_price_fresh(upd):
    f = cr.freshness({"checked_at": "2026-11-18", "source_updated_at": upd}, NOW, CFG)[0]
    assert f in (cr.STALE, cr.UNKNOWN_FRESHNESS)
    r = route(build(rec(official=off(200000), buyback=[bb("買取A", 240000, upd=upd), bb("買取B", 238000, upd=upd)])), "A")
    assert r["decision"] != cr.BUY


def test_slash_date_of_today_is_fresh():
    assert cr.freshness({"checked_at": "2026-11-18", "source_updated_at": "2026/11/17"}, NOW, CFG)[0] == cr.FRESH


@pytest.mark.parametrize("url", ["https://www.kaitorishouten-co.jp/category/2/108", "https://www.netoff.co.jp/kaden/search?q=a7rv",
                                 "https://www.kaitorishouten-co.jp/products/", "https://www.netoff.co.jp/kaden/list/12"])
def test_buyback_list_pages_are_not_item_pages_even_if_claimed(url):
    rows = [{**bb("買取A", 240000), "url": url, "is_product_page": True}, {**bb("買取B", 238000), "url": url, "is_product_page": True}]
    assert route(build(rec(official=off(200000), buyback=rows)), "A")["profit_status"] == cr.NOT_CALCULATED


@pytest.mark.parametrize("url", ["https://www.kaitorishouten-co.jp/products/detail/12345", "https://www.netoff.co.jp/kaden/detail/24116",
                                 "https://www.yodobashi.com/product/100000001234567890/", "https://www.biccamera.com/bc/item/1234567/",
                                 "https://www.mapcamera.com/item/123456789", "https://www.fujiya-camera.co.jp/shop/g/gC2120120298205/"])
def test_real_item_urls_pass_the_allowlist(url):
    host = cr.domain_of(url)
    kind = "buyback" if host in CFG["allowed_hosts"]["buyback"] else "retail"
    assert cr._host_reason(kind, url, CFG) is None


@pytest.mark.parametrize("url", ["https://www.fujiya-camera.co.jp/shop/r/r1234/", "https://www.yodobashi.com/product/", "https://www.biccamera.com/bc/c/camera/",
                                 "https://www.mapcamera.com/item/", "https://www.yodobashi.com/category/19052/"])
def test_category_urls_are_rejected_for_known_shops(url):
    assert cr._host_reason("retail", url, CFG) == "not_item_page"


def test_yahoo_auction_sold_is_calculated_with_10_percent():
    rows = [{**sold(250000 + i, f"2026-11-1{i}", n=i), "market": "Yahoo!オークション", "url": f"https://page.auctions.yahoo.co.jp/jp/auction/x12345678{i}"} for i in range(3)]
    b = route(build(rec(official=off(200000), sold=rows)), "B")
    assert b["profit_status"] == cr.PROFITABLE and b["costs"]["selling_fee_rate"] == 0.10 and b["sell"]["source"] == "Yahoo!オークション"
    shops = [{**sold(250000 + i, f"2026-11-1{i}", n=i), "url": f"https://jp.mercari.com/shops/product/abc{i}"} for i in range(3)]
    assert route(build(rec(official=off(200000), sold=shops)), "B")["profit_status"] == cr.NOT_CALCULATED      # Shops の料率は未確認


def test_best_buy_candidate_is_chosen_among_those_with_known_shipping():
    unknown = {"shop": "ヨドバシ", "item_title": "RICOH GR IV HDF", "price_jpy": 190000, "condition": "NEW", "stock": "AVAILABLE",
               "url": "https://www.yodobashi.com/product/100000001/", "checked_at": "2026-11-18"}
    r = route(build(rec(official=off(200000), retail=[unknown], buyback=_two_shops())), "A")
    assert r["profit_status"] == cr.PROFITABLE and r["buy"]["price"] == 200000                 # 送料不明の安い候補に引きずられない


def test_buyback_shops_are_counted_by_the_sell_color():
    black = {**bb("買取A", 500000, title="Sony α7CR ボディ [ブラック]"), "item_title": "SONY α7CR ボディ ブラック"}
    silver = {**bb("買取B", 495000, title="Sony α7CR ボディ [シルバー]"), "item_title": "SONY α7CR ボディ シルバー"}
    m = build(rec("SONY α7CR", official=off(400000), buyback=[black, silver]), registered=("SONY α7CR",))
    r = route(m, "A")
    assert r["sell"]["evidence"]["shops"] == 1 and r["decision"] != cr.BUY


@pytest.mark.parametrize("ev", ["取得ツールの要約による", "ページ本文は文字化けしていた", "未検証", "推測"])
def test_self_admitted_unreliable_evidence_blocks_available(ev):
    assert cr.stock_of({"stock": "AVAILABLE", "stock_evidence": ev}) == cr.STOCK_UNKNOWN
    rows = [{**bb("買取A", 240000), "reason": ev}, {**bb("買取B", 238000), "reason": ev}]
    assert route(build(rec(official=off(200000), buyback=rows)), "A")["profit_status"] == cr.NOT_CALCULATED


@pytest.mark.parametrize("title", ["RICOH GR IV HDF 新古品", "RICOH GR IV HDF 良品", "RICOH GR IV HDF used", "RICOH GR IV HDF 未使用品", "RICOH GR IV HDF リファービッシュ",
                                   "RICOH GR IV HDF 台湾版"])
def test_more_condition_and_overseas_words(title):
    retail = [{"shop": "ヨドバシ", "item_title": title, "price_jpy": 200000, "condition": "NEW", "stock": "AVAILABLE",
               "url": "https://www.yodobashi.com/product/100000001/", "checked_at": "2026-11-18", "shipping_jpy": 0, "shipping_url": "https://www.yodobashi.com/ship/guide"}]
    assert route(build(rec(retail=retail, buyback=_two_shops())), "A")["profit_status"] == cr.NOT_CALCULATED


def test_legit_wordings_are_not_over_rejected():
    assert cr.identity_ok("FUJIFILM X100VI", "富士フィルム FUJIFILM X100VI")[0] is True        # 「富士フィルム」はフィルム貼り付けではない
    assert cr.identity_ok("RICOH GR IV", "RICOH GR IV 傷なし")[0] is True
    assert cr.stock_of({"stock": "在庫あり", "stock_evidence": "注文受付中 購入ボタンあり"}) == cr.AVAILABLE


@pytest.mark.parametrize("stock", ["在庫未定", "購入できません", "販売停止"])
def test_more_unavailable_stock_wordings(stock):
    assert cr.stock_of({"stock": stock}) != cr.AVAILABLE


# ---- 5 回目のレビューの回帰 ----
def test_silver_color_is_detected_with_long_vowel_and_never_mixed():
    assert cr.color_of("FUJIFILM X100VI [シルバー]") == "silver" and cr.color_of("FUJIFILM X100VI [ブラック]") == "black"
    retail = [{"shop": "ヨドバシ", "item_title": "FUJIFILM X100VI [ブラック]", "price_jpy": 250000, "condition": "NEW", "stock": "AVAILABLE", "stock_evidence": "購入ボタンあり",
               "url": "https://www.yodobashi.com/product/100000001/", "checked_at": "2026-11-18", "shipping_jpy": 0, "shipping_url": "https://www.yodobashi.com/ship/guide"}]
    mk = lambda shop, price, title: {**bb(shop, price, title=title), "item_title": title}
    rows = [mk("買取A", 300000, "FUJIFILM X100VI [シルバー]"), mk("買取B", 295000, "FUJIFILM X100VI [シルバー]"), mk("買取C", 262000, "FUJIFILM X100VI [ブラック]")]
    r = route(build(rec("FUJIFILM X100VI", retail=retail, buyback=rows), registered=("FUJIFILM X100VI",)), "A")
    assert r["profit_status"] == cr.NOT_CALCULATED or (r["sell"]["price"] == 262000 and r["decision"] != cr.BUY)


def test_color_specified_buy_needs_a_buyback_with_the_same_color():
    retail = [{"shop": "ヨドバシ", "item_title": "FUJIFILM X100VI [ブラック]", "price_jpy": 250000, "condition": "NEW", "stock": "AVAILABLE", "stock_evidence": "購入ボタンあり",
               "url": "https://www.yodobashi.com/product/100000001/", "checked_at": "2026-11-18", "shipping_jpy": 0, "shipping_url": "https://www.yodobashi.com/ship/guide"}]
    nocolor = [{**bb("買取A", 300000, title="FUJIFILM X100VI"), "item_title": "FUJIFILM X100VI"}, {**bb("買取B", 298000, title="FUJIFILM X100VI"), "item_title": "FUJIFILM X100VI"}]
    r = route(build(rec("FUJIFILM X100VI", retail=retail, buyback=nocolor), registered=("FUJIFILM X100VI",)), "A")
    assert r["profit_status"] == cr.NOT_CALCULATED


def test_explicit_lottery_or_sold_out_stays_even_with_uncertain_words():
    assert cr.stock_of({"stock": "LOTTERY_DEPENDENT", "stock_evidence": "税の扱いは未確認"}) == cr.LOTTERY_DEPENDENT
    assert cr.stock_of({"stock": "OUT_OF_STOCK", "stock_evidence": "検索要約で確認"}) == cr.OUT_OF_STOCK


def test_available_needs_positive_evidence():
    assert cr.stock_of({"stock": "AVAILABLE"}) == cr.STOCK_UNKNOWN
    for ev in ("現在在庫がございません。購入ボタンは表示", "ご注文いただけません", "在庫が無い", "在庫 なし", "お届けまで2か月程度"):
        assert cr.stock_of({"stock": "AVAILABLE", "stock_evidence": ev}) != cr.AVAILABLE
    assert cr.stock_of({"stock": "AVAILABLE", "stock_evidence": "購入ボタンあり"}) == cr.AVAILABLE


@pytest.mark.parametrize("reason", ["20%UP キャンペーン適用後。最低保証 80,000 円", "期間限定", "アプリ限定価格", "最大 262,000 円", "条件付き"])
def test_campaign_or_conditional_buyback_is_not_used(reason):
    rows = [{**bb("買取A", 240000), "reason": reason}, {**bb("買取B", 238000), "reason": reason}]
    assert route(build(rec(official=off(200000), buyback=rows)), "A")["profit_status"] == cr.NOT_CALCULATED


@pytest.mark.parametrize("kind,url", [("official", "https://nij.nikon.com/shop/g/g12345/"), ("official", "https://pur.store.sony.jp/ichigan/products/ILCE-7RM5/ILCE-7RM5_purchase/"),
                                       ("buyback", "https://www.janpara.co.jp/sale/search/detail/?CHKNAM=1"), ("buyback", "https://raku-uru.sofmap.com/search/product_detail.aspx?id=1")])
def test_official_purchase_and_detail_pages_pass(kind, url):
    assert cr._host_reason(kind, url, CFG) is None


@pytest.mark.parametrize("title", ["RICOH GR IV 新品・未使用", "RICOH GR IV 【新品】 2025年発売", "RICOH GR IV 【数量限定】特価"])
def test_promotional_words_do_not_reject_a_new_item(title):
    assert cr.identity_ok("RICOH GR IV", title)[0] is True
    o = cr.observations(rec("RICOH GR IV", buyback=[{**bb("買取A", 200000), "item_title": title}]), NOW, CFG)[0]
    assert "title_condition_mismatch" not in o["reasons"]


def test_official_title_is_checked_when_given():
    o = {**off(200000), "item_title": "RICOH GR IIIx"}
    r = route(build(rec(official=o, buyback=_two_shops())), "A")
    assert r["profit_status"] == cr.NOT_CALCULATED
