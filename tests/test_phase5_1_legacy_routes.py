"""Phase 5.1: 旧UI（通常の URL）の利益ルート・利益案件にも、新UIと同じ確定の判定を使うことのテスト。

判定の正本は src/content/ui/opportunity.py（eligibility / route_reasons / deal_reasons）の1か所。
旧UIのせどりタブ・ランキング・Hero・初心者・AI Opportunities（BUY）・通知・新UIの HOME と一覧が、
同じルート・同じ案件について同じ答えを出すことを確かめる。

GR IV の観測2件は、本番の生成物（2026-10-04 01:37 の自動更新）にあった値と同じ形（公開の価格・URL）。
それ以外のデータはテスト用の架空のもの。
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.content.ui import home
from src.content.ui import opportunity as opp
from src.content.ui import route_view as rtv
from src.models.beginner_deal import BeginnerDealModel as BeginnerDeal
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 4, 1, 30, tzinfo=JST)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RF = _load("route_fixtures_p51", Path(__file__).with_name("route_fixtures.py"))
GPR = _load("gpr_p51", ROOT / "scripts" / "generate_profit_routes.py")
GAO = _load("gao_p51", ROOT / "scripts" / "generate_ai_opportunities.py")
GNO = _load("gno_p51", ROOT / "scripts" / "generate_notifications.py")


def _gen(**attrs):
    """LP 生成器（DB を使わない部分だけを呼ぶ）。"""
    from src.content.daily_lp_generator import DailyLPGenerator
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g.settings = {}
    g._msrp_evidence = {}
    g._product_info = {}
    g._gate_now = NOW
    for k, v in attrs.items():
        setattr(g, k, v)
    return g


# ── 各面の答え（同じルートについて） ──────────────────────────────────────────

def _surfaces(r: dict, now: datetime = NOW) -> dict:
    """1件のルートを、新UI・旧UI・AI・通知・HOME に通したときに「確定として出たか」。"""
    pr = {"main_routes": [r], "reference_routes": [], "zero_route_diagnostics": {}}
    s = opp.build(deals=[], routes=[r], product_genres={}, now=now)
    legacy_html = _gen(_gate_now=now)._profit_routes_section(pr)
    ai = GAO.build_candidates(pr, now)
    gno_now, GNO.NOW = GNO.NOW, now
    try:
        snap = GNO._snapshot({"todays_opportunities": [{"product_id": r["product_id"], "kind": "main",
                                                         "action": "BUY", "buy_now": "BUY"}]}, {}, pr)
    finally:
        GNO.NOW = gno_now
    m = home.build_home_model(tcg_report={}, opportunities={}, profit_routes=pr, legacy_lotteries=[], now=now)
    return {
        "new_ui": bool(s.eligible),
        "new_ui_routes": bool(rtv.build(s)),
        "canonical": not opp.route_reasons(r, now),
        "legacy_sedori": f"¥{r['buy_price']:,}" in legacy_html,
        "legacy_count": "検証済み利益ルート: <b>1件</b>" in legacy_html,
        "ai": bool(ai),
        "notify": bool(snap["ops"]) and bool(snap["main_products"]),
        "home": m.counts["high_profit"] == 1,
    }


def _all_same(d: dict) -> bool:
    return len(set(d.values())) == 1


BUY = 123457    # 旧UIの HTML で見分けるための仕入れ値


def _safe(**kw):
    return RF.safe_route(NOW, "prod_p", buy=BUY, sell=160000, **kw)


# ── 安全なルートは、どの面でも同じく確定（否定対照） ─────────────────────────────

@pytest.mark.parametrize("r", [
    _safe(),
    _safe(sell_type="SOLD_MEDIAN"),
    RF.secondary(_safe()),
    RF.secondary(_safe(sell_type="SOLD_MEDIAN")),
], ids=["retail_buyback", "retail_sold_median", "secondary_buyback", "secondary_sold_median"])
def test_legacy_accepts_same_safe_route_as_new_ui(r):
    got = _surfaces(r)
    assert all(got.values()), got


# ── 条件を1つずつ崩すと、どの面でも同じく外れる（旧UI・新UIの乖離が無い） ──────────────────

_SEARCH = "https://www.amazon.co.jp/s?k=RICOH%20GR%20IV"
MUTATIONS = [
    ("buy_identity_false", dict(buy_exact_match=False), "buy_identity_unverified"),
    ("sell_identity_false", dict(sell_exact_match=False), "sell_identity_unverified"),
    ("identity_missing", dict(buy_exact_match=None), "buy_identity_unverified"),
    ("retail_search_url", dict(buy_link_type="search", buy_url=_SEARCH), "buy_url_not_item_level"),
    ("retail_unknown_link", dict(buy_link_type="unknown"), "buy_url_not_item_level"),
    ("secondary_search_url", dict(buy_canonical_type="LISTING", buy_condition="used_a", sell_condition="used_a",
                                  buy_item_url=_SEARCH), "buy_not_item_level"),
    ("secondary_category_url", dict(buy_canonical_type="LISTING", buy_condition="used_a", sell_condition="used_a",
                                    buy_item_url="https://jp.mercari.com/search?category_id=1"), "buy_not_item_level"),
    ("secondary_shop_top", dict(buy_canonical_type="LISTING", buy_condition="used_a", sell_condition="used_a",
                                buy_item_url="https://jp.mercari.com/"), "buy_not_item_level"),
    ("secondary_dummy_item", dict(buy_canonical_type="LISTING", buy_condition="used_a", sell_condition="used_a",
                                  buy_item_url="https://jp.mercari.com/item/m00000000001"), "buy_not_item_level"),
    ("condition_new_vs_used", dict(sell_condition="used_a"), "condition_mismatch"),
    ("condition_new_vs_unused", dict(sell_condition="unused"), "condition_mismatch"),
    ("condition_new_vs_opened", dict(sell_condition="new_opened"), "condition_mismatch"),
    ("condition_unknown", dict(sell_condition="付属品のみ"), "condition_mismatch"),
    ("tcg_shrink_vs_tape", dict(buy_condition="SEALED_SHRINK", sell_condition="TAPE_CUT"), "condition_mismatch"),
    ("buy_shipping_unknown", dict(buy_shipping=None), "costs_unknown"),
    ("buy_required_unknown", dict(buy_required_cost=None), "costs_unknown"),
    ("sell_fee_unknown", dict(platform_fee=None), "costs_unknown"),
    ("payment_fee_unknown", dict(payment_fee=None), "costs_unknown"),
    ("sell_shipping_unknown", dict(shipping_cost=None), "costs_unknown"),
    ("sell_required_unknown", dict(safety_margin=None), "costs_unknown"),
    ("breakdown_inconsistent", dict(buy_shipping=2000), "breakdown_mismatch"),
    ("profit_inflated", dict(net_profit=60000, roi=60000 / BUY), "breakdown_mismatch"),
    ("sell_listing", dict(sell_canonical_type="LISTING"), "sell_type_listing"),
    ("sell_unknown", dict(sell_canonical_type="UNKNOWN"), "sell_type_unknown"),
    ("sell_sold_unaggregated", dict(sell_canonical_type="SOLD"), "sell_type_sold"),
    ("sell_trade_in", dict(sell_canonical_type="TRADE_IN"), "sell_type_trade_in"),
    ("buy_sold", dict(buy_canonical_type="SOLD"), "buy_type_sold"),
    ("buy_unknown_type", dict(buy_canonical_type="UNKNOWN"), "buy_type_unknown"),
    ("buy_evidence_unverified", dict(buy_price_evidence="CONFIGURED_REFERENCE"), "buy_configured_reference"),
    ("stale_buy", dict(buy_observed_at=(NOW - timedelta(days=15)).isoformat()), "stale_buy_price"),
    ("stale_sell", dict(sell_observed_at=(NOW - timedelta(days=15)).isoformat()), "stale_sell_price"),
    ("rejected", dict(rejection_reason="suspicious_price"), "route_flagged"),
    ("low_confidence", dict(route_confidence="low"), "route_low_confidence"),
]


@pytest.mark.parametrize("mutate, reason", [(m, r) for _id, m, r in MUTATIONS], ids=[i for i, _m, _r in MUTATIONS])
def test_mutation_excluded_on_every_surface(mutate, reason):
    r = _safe(**mutate)
    assert reason in opp.route_reasons(r, NOW)
    got = _surfaces(r)
    assert not any(got.values()), got


SOLD_MUTATIONS = [
    ("samples_2", dict(sell_sample_count=2), "insufficient_sold_samples"),
    ("period_missing", dict(sell_period=""), "insufficient_sold_samples"),
    ("sold_to_listing", dict(sell_canonical_type="LISTING"), "sell_type_listing"),
    ("sold_to_unknown", dict(sell_canonical_type="UNKNOWN"), "sell_type_unknown"),
]


@pytest.mark.parametrize("mutate, reason", [(m, r) for _id, m, r in SOLD_MUTATIONS],
                         ids=[i for i, _m, _r in SOLD_MUTATIONS])
def test_sold_median_mutation_excluded_on_every_surface(mutate, reason):
    r = _safe(sell_type="SOLD_MEDIAN", **mutate)
    assert reason in opp.route_reasons(r, NOW)
    assert not any(_surfaces(r).values())


def test_sold_median_three_samples_is_accepted_everywhere():
    got = _surfaces(_safe(sell_type="SOLD_MEDIAN", sell_sample_count=3))
    assert all(got.values()), got


def test_legacy_new_ui_parity_over_all_mutations():
    """全部の変異について、新UIの掲載可否と旧UI・AI・通知・HOME の可否が一致する（安全基準の乖離が無い）。"""
    cases = [_safe(), RF.secondary(_safe())] + [_safe(**m) for _i, m, _r in MUTATIONS] + \
        [_safe(sell_type="SOLD_MEDIAN", **m) for _i, m, _r in SOLD_MUTATIONS]
    for r in cases:
        got = _surfaces(r)
        assert _all_same(got), (r, got)


# ── 本番に出ていた GR IV の偽ルート（Amazon の検索結果の価格 → フジヤカメラ） ──────────────────

def _gr4_obs(now: datetime) -> list[dict]:
    t = now.isoformat()
    sell = {"is_exact_product_match": False, "is_body_only": True, "product_match_confidence": "medium",
            "product_match_reason": "unverified_title_price_band_pending", "accessory_flag": False,
            "wrong_model_flag": False, "product_id": "prod_gr4", "product_name": "RICOH GR IV",
            "source_id": "src_fujiya", "source_name": "フジヤカメラ", "market_type": "domestic_buyback",
            "price_role": "sell", "price_type": "buyback_price", "canonical_price_type": "BUYBACK_CASH",
            "sample_count": None, "sold_median_eligible": False, "sold_period_start": "", "sold_period_end": "",
            "condition": "new_unopened", "price": 151000, "observed_at": t, "confidence": "high",
            "source_url": "https://www.fujiya-camera.co.jp/shop/purchase/list.aspx?keyword=RICOH%20GR%20IV",
            "item_url": "", "link_type": "search", "extraction_method": "auto_scraped", "collector_method": "",
            "age_days": 0.0, "observed_age_days": 0.0, "is_fresh": True, "freshness_basis": "observed",
            "is_usable_for_beginner": True, "is_usable_for_pro": True, "rejection_reason": ""}
    buy = dict(sell, source_id="amazon_jp_new", source_name="Amazon JP (新品出品)", market_type="domestic_retail",
               price_role="buy", price_type="shop_sale_price", canonical_price_type="LISTING", sample_count=6,
               price=107491, confidence="medium",
               source_url="https://www.amazon.co.jp/s?k=RICOH%20GR%20IV%20%E3%82%AB%E3%83%A1%E3%83%A9"
                          "&rh=p_n_condition-type%3A1294724011&s=price-asc-rank",
               link_type="unknown", extraction_method="resale_market_manual", is_usable_for_beginner=False)
    return [buy, sell]


def _generate(tmp_path, monkeypatch, obs: list[dict]) -> dict:
    """generate_profit_routes.main() を、一時フォルダの正規化データで実行して出力を返す。"""
    npo = tmp_path / "npo.json"
    npo.write_text(json.dumps({"observations": obs}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(GPR, "NPO_PATH", npo)
    monkeypatch.setattr(GPR, "OUT_DIR", tmp_path / "profit_routes")
    assert GPR.main() == 0
    return json.loads((tmp_path / "profit_routes" / "latest.json").read_text(encoding="utf-8"))


def test_gr4_false_route_is_excluded_everywhere(tmp_path, monkeypatch):
    now = datetime.now(tz=JST)
    pr = _generate(tmp_path, monkeypatch, _gr4_obs(now))
    # 生成の段階で確定ルートにしない（理由つきで除外の記録に残す）
    assert pr["main_routes"] == [] and pr["summary"]["main_route_count"] == 0
    ex, = pr["excluded_routes"]
    assert ex["buy_price"] == 107491 and ex["net_profit"] == 39009 and ex["excluded_kind"] == "main"
    assert {"buy_identity_unverified", "sell_identity_unverified", "buy_not_item_level"} <= set(
        ex["exclusion_reasons"])
    assert pr["zero_route_diagnostics"]["prod_gr4"]["main_blocked_reason"].startswith("候補はあるが確定の条件")
    # 旧UI（せどりタブの利益ルート欄）に ¥107,491・+¥39,009 が出ない
    html = _gen(_gate_now=now)._profit_routes_section(pr)
    assert "107,491" not in html and "39,009" not in html and "検証済み利益ルート: <b>0件</b>" in html
    # 生成物を古い形（除外の記録が無く main に入ったまま）で渡しても、描画時の判定で出さない
    html_old = _gen(_gate_now=now)._profit_routes_section({"main_routes": [ex], "reference_routes": [ex]})
    assert "107,491" not in html_old and "39,009" not in html_old
    # 新UI（利益商品・せどりルート）・HOME の件数
    s = opp.build(deals=[], routes=[ex], product_genres={}, now=now)
    assert not s.eligible and not rtv.build(s)
    m = home.build_home_model(tcg_report={}, opportunities={}, profit_routes={"main_routes": [ex]},
                              legacy_lotteries=[], now=now)
    assert m.counts["high_profit"] == 0
    # AI Opportunities（ランキング・今日のおすすめ・BUY）にも通知にも使わない
    assert GAO.build_candidates({"main_routes": [ex], "reference_routes": [ex]}, now) == []
    snap = GNO._snapshot({"todays_opportunities": [{"product_id": "prod_gr4", "kind": "main", "action": "BUY",
                                                     "buy_now": "BUY", "net_profit": 39009}]},
                         {}, {"main_routes": [ex]})
    assert snap["ops"] == {} and snap["main_products"] == []


def test_safe_observations_still_make_a_route_at_generation(tmp_path, monkeypatch):
    """否定対照: 商品の照合済み・商品ページのリンク・購入送料と費用が分かる観測なら、確定ルートとして作られる。"""
    now = datetime.now(tz=JST)
    buy, sell = _gr4_obs(now)
    buy.update(is_exact_product_match=True, canonical_price_type="RETAIL", link_type="item",
               item_url="https://www.example-store.jp/item/gr4", shipping=0, required_cost=0,
               source_name="カメラ店X", source_id="shop_x", confidence="high")
    sell.update(is_exact_product_match=True)
    pr = _generate(tmp_path, monkeypatch, [buy, sell])
    r, = pr["main_routes"]
    assert pr["excluded_routes"] == [] and not opp.route_reasons(r, now)
    assert f"¥{r['buy_price']:,}" in _gen(_gate_now=now)._profit_routes_section(pr)


# ── 参考ルート: 売却側の古さだけが理由のもの。ランキング・BUY には使わない ─────────────────────

def test_reference_route_needs_same_identity_and_cost_rules():
    stale = (NOW - timedelta(days=20)).isoformat()
    ref = _safe(sell_type="SOLD", sell_observed_at=stale, reference_route=True,
                rejection_reason="overseas_sold_stale(20d)")
    assert opp.route_reasons(ref, NOW) and not opp.reference_route_reasons(ref, NOW)   # 参考としてだけ出せる
    for bad in (dict(buy_exact_match=False), dict(buy_shipping=None), dict(sell_condition="used_a"),
                dict(buy_canonical_type="LISTING", buy_condition="used_a", sell_condition="used_a",
                     buy_item_url=_SEARCH), dict(net_profit=90000)):
        assert opp.reference_route_reasons(dict(ref, **bad), NOW), bad
    # 参考ルートは AI Opportunities で BUY にならない（WATCH）・通知にも使わない
    pr = {"main_routes": [], "reference_routes": [ref]}
    c, = GAO.build_candidates(pr, NOW)
    assert c["kind"] == "reference" and GAO._buy_decision(c, 100) != "BUY"
    assert GNO._snapshot({"todays_opportunities": [{"product_id": ref["product_id"], "kind": "reference"}]},
                         {}, pr)["ops"] == {}
    # 旧UIでは「参考利益ルート」として出し、確定の件数には数えない
    html = _gen()._profit_routes_section(pr)
    assert "検証済み利益ルート: <b>0件</b>" in html and "参考ルート: <b>1件</b>" in html
    assert "pr-main-card" not in html


# ── DB のせどりルート（旧UIの Pro ルート）も同じ判定 ─────────────────────────────────────

def test_db_sedori_routes_use_the_canonical_gate():
    from src.models.sale_price import SedoriRouteModel
    m = SedoriRouteModel(id="r1", product_id="prod_gr4", product_name="RICOH GR IV", buy_shop_name="メルカリ",
                         buy_price=107491, buy_url="https://jp.mercari.com/search?keyword=gr4",
                         buy_condition="new_unopened", buy_price_type="flea_sold_price",
                         sell_shop_name="フジヤカメラ", sell_price=151000, sell_price_type="buyback_price",
                         net_profit=39009)
    d = _gen()._sedori_route_dict(m)
    assert d["buy_canonical_type"] == "SOLD" and d["sell_canonical_type"] == "BUYBACK_CASH"
    why = opp.route_reasons(d, NOW)
    # DB には照合結果・確認時刻・手数料の内訳が無い → 推測で埋めず、確定にしない
    assert {"buy_type_sold", "buy_identity_unverified", "sell_identity_unverified", "stale_buy_price",
            "costs_unknown"} <= set(why)


# ── 定価→買取の案件（ランキング・Hero・初心者ルート一覧・利益あり） ────────────────────────────

def _deal(pid, net, *, official=100000, shop="買取店A", **kw):
    return BeginnerDeal(id=pid, product_id=pid, product_name=f"商品{pid}", category="camera",
                        official_price_jpy=official, best_buyback_price=official + net + 4500,
                        best_buyback_shop=shop, net_profit_jpy=net, net_profit_rate=net / official,
                        buyback_condition="新品未開封", user_level="beginner_easy", **kw)


def _bybp(*deals, age_h=2):
    at = (NOW - timedelta(hours=age_h)).isoformat()
    return {d.product_id: [{"shop_name": d.best_buyback_shop, "buyback_price": d.best_buyback_price,
                            "observed_at": at}] for d in deals}


def test_deal_gate_matches_new_ui():
    ok, ref, stale = _deal("p_ok", 20000), _deal("p_ref", 30000), _deal("p_stale", 40000)
    ev = {"p_ok": "VERIFIED_DATED", "p_ref": "CONFIGURED_REFERENCE", "p_stale": "VERIFIED_DATED"}
    g = _gen(_msrp_evidence=ev)
    bybp = _bybp(ok, ref) | _bybp(stale, age_h=24 * 20)       # p_stale の買取価格は20日前
    gated = {d.product_id: g._canonical_deal_gate(d, bybp) for d in (ok, ref, stale)}
    # 新UIの判定と同じ答え
    new_ui = opp.build(deals=g._nu_profit_deals([ok, ref, stale], bybp), routes=[], product_genres={}, now=NOW)
    assert {v.product_id for v in new_ui.eligible} == {"p_ok"}
    assert gated["p_ok"].net_profit_jpy == 20000                                     # 確定: そのまま
    assert gated["p_ref"].net_profit_jpy == 30000 and g._msrp_is_reference(gated["p_ref"])  # 参考差額として残る
    st = gated["p_stale"]                                                            # 監視中へ降格
    assert st.net_profit_jpy == 0 and st.user_level == "monitoring" and st.best_buyback_price == 0
    assert "UNCONFIRMED:買取価格の確認が14日より前か、確認時刻が不明" in st.notes
    # ランキング: 確定だけに順位。参考差額・降格した案件は出さない
    deals = list(gated.values())
    rank = g._tab_ranking(deals, [], [])
    panel = rank.split('id="rtab-all">', 1)[1].split("</div>\n", 1)[0]
    assert "商品p_ok" in panel and "商品p_ref" not in panel and "商品p_stale" not in panel
    # Hero: 最高利益は確定の +¥20,000（参考の +¥30,000・降格した +¥40,000 は使わない）
    hero = g._section_hero("2026-10-04", "01:30", NOW, NOW, all_deals=deals, beginner_display_count=1)
    assert "+¥20,000" in hero and "30,000" not in hero and "40,000" not in hero


def test_beginner_route_list_excludes_reference_and_unconfirmed():
    ok, ref = _deal("p_ok", 20000), _deal("p_ref", 30000)
    g = _gen(_msrp_evidence={"p_ok": "VERIFIED_DATED", "p_ref": "CONFIGURED_REFERENCE"})
    html = g._tab_sedori([], beginner_deals=[ok, ref])
    assert "商品p_ok" in html and "商品p_ref" not in html


def test_monitoring_card_shows_unconfirmed_reason():
    g = _gen(_msrp_evidence={"p_stale": "VERIFIED_DATED"})
    d = _deal("p_stale", 40000)
    gated = g._canonical_deal_gate(d, _bybp(d, age_h=24 * 20))
    html = g._deal_card_monitoring(gated, [])
    assert "買取価格の確認が14日より前か、確認時刻が不明" in html and "40,000" not in html


# ── 通知: 確定ルートの判定を通っていない過去の利益ルート通知は LP に出さない ────────────────────────

def test_legacy_notifications_hide_unchecked_route_events(tmp_path):
    base = tmp_path / "notifications"
    (base / "history").mkdir(parents=True)
    old = {"type": "ROI_UP", "priority": "Medium", "created_at": "2026-09-30 23:29 JST",
           "message": "⬆️ ROI改善\nFUJIFILM X100VI\nROI 25% → 38%"}
    checked = {"type": "NEW_MAIN", "priority": "High", "created_at": "2026-10-04 12:00 JST",
               "message": "🆕 新しい利益ルート成立\n商品A", "route_checked": True}
    health = {"type": "HEALTH_ALERT", "priority": "Critical", "created_at": "2026-10-04 12:00 JST",
              "message": "⚠️ データ品質低下"}
    (base / "latest.json").write_text(json.dumps({"events": [checked, health], "channels": []}), encoding="utf-8")
    (base / "history" / "2026-09-30.json").write_text(json.dumps({"events": [old]}), encoding="utf-8")
    html = _gen()._notifications_html(base)
    assert "商品A" in html and "データ品質低下" in html and "X100VI" not in html and "38%" not in html


def test_new_notifications_are_marked_route_checked(tmp_path, monkeypatch):
    """generate_notifications は確定ルートの商品だけから通知を作り、印を付ける。"""
    safe = RF.safe_route(datetime.now(tz=JST), "p_new")
    for name in ("profit_routes", "ai_opportunities", "notifications"):
        (tmp_path / "exports" / name).mkdir(parents=True)
    (tmp_path / "exports/profit_routes/latest.json").write_text(json.dumps({"main_routes": [safe]}), "utf-8")
    (tmp_path / "exports/ai_opportunities/latest.json").write_text(json.dumps({"todays_opportunities": [
        {"product_id": "p_new", "kind": "main", "action": "BUY", "buy_now": "BUY", "product": "商品p_new",
         "net_profit": safe["net_profit"], "roi": safe["roi"], "buy_price": safe["buy_price"]}]}), "utf-8")
    (tmp_path / "exports/notifications/prev_snapshot.json").write_text(json.dumps(
        {"main_products": [], "ops": {}}), "utf-8")
    monkeypatch.setattr(GNO, "ROOT", tmp_path)
    monkeypatch.setattr(GNO, "OUT", tmp_path / "exports" / "notifications")
    monkeypatch.setattr(GNO, "HIST", tmp_path / "exports" / "notifications" / "history")
    monkeypatch.setattr(GNO, "_deliver", lambda events: {"discord": "dry_run"})
    assert GNO.main() == 0
    out = json.loads((tmp_path / "exports/notifications/latest.json").read_text(encoding="utf-8"))
    assert [e["type"] for e in out["events"]] == ["NEW_MAIN"]
    assert all(e["route_checked"] is True for e in out["events"])


# ── 判定を二重に書かない（旧UIの入口が正本を呼んでいる） ─────────────────────────────────

@pytest.mark.parametrize("path, needle", [
    ("scripts/generate_profit_routes.py", "_opp.route_reasons("),
    ("scripts/generate_profit_routes.py", "_opp.reference_route_reasons("),
    ("scripts/generate_ai_opportunities.py", "_opp.confirmed_routes("),
    ("scripts/generate_ai_opportunities.py", "_opp.reference_routes("),
    ("scripts/generate_notifications.py", "_opp.confirmed_routes("),
    ("src/content/daily_lp_generator.py", "_ui_opp.confirmed_routes("),
    ("src/content/daily_lp_generator.py", "_ui_opp.reference_routes("),
    ("src/content/daily_lp_generator.py", "_ui_opp.deal_reasons("),
    ("src/content/daily_lp_generator.py", "_ui_opp.route_reasons("),
    ("src/content/ui/home.py", "_opp.confirmed_routes("),
])
def test_legacy_entrypoints_call_the_canonical_gate(path, needle):
    assert needle in (ROOT / path).read_text(encoding="utf-8")


def test_no_second_copy_of_route_identity_rules():
    """商品の照合・状態・URL の条件は opportunity.py だけに書く（旧UI・スクリプトに同じ条件を書かない）。"""
    for path in ("src/content/daily_lp_generator.py", "scripts/generate_ai_opportunities.py",
                 "scripts/generate_notifications.py", "scripts/generate_profit_routes.py"):
        src = (ROOT / path).read_text(encoding="utf-8")
        for needle in ('get("buy_exact_match")', 'get("sell_exact_match")', "is_item_url(", "_cond_family(",
                       "breakdown_ok"):
            assert needle not in src, (path, needle)


# ── レビューの指摘への回帰テスト ─────────────────────────────────────────────

def test_monitoring_deal_revived_by_enrich_is_gated_before_merge():
    """DB では監視中（赤字）でも、補完で古い買取価格から利益ありに戻った版が、統合で判定後の版に勝たない。"""
    g = _gen(_msrp_evidence={"p_mon": "VERIFIED_DATED", "p_ok": "VERIFIED_DATED"})
    revived = _deal("p_mon", 38200)                      # 補完後の版（20日前の買取で利益あり）
    ok = _deal("p_ok", 20000)
    bybp = _bybp(revived, age_h=24 * 20) | _bybp(ok)
    all_d, easy, watch, mon, adv = g._gate_and_merge_deals([ok], [], [], [revived], [], bybp)
    by = {d.product_id: d for d in all_d}
    assert by["p_mon"].net_profit_jpy == 0 and by["p_mon"].user_level == "monitoring"
    assert by["p_ok"].net_profit_jpy == 20000
    rank = g._tab_ranking(all_d, [], [])
    hero = g._section_hero("2026-10-04", "01:30", NOW, NOW, all_deals=all_d, beginner_display_count=1)
    sedori = g._tab_sedori([], beginner_deals=all_d)
    for html in (rank, hero, sedori):
        assert "38,200" not in html
    # 新UIには判定前の版を渡す（新UIが同じ判定で外し、理由を診断に残す）
    assert {d.product_id: d.net_profit_jpy for d in g._nu_source_deals}["p_mon"] == 38200
    s = opp.build(deals=g._nu_profit_deals(g._nu_source_deals, bybp), routes=[], product_genres={}, now=NOW)
    assert {v.product_id for v in s.eligible} == {"p_ok"}
    assert "stale_sell_price" in next(v for v in s.ineligible if v.product_id == "p_mon").reasons


def test_pro_confirmed_deals_are_gated():
    """Pro タブの「Pro向け確定案件」も同じ判定。確定だけ（参考差額・古い買取の案件は出さない）。"""
    ev = {"p_ok": "VERIFIED_DATED", "p_ref": "CONFIGURED_REFERENCE", "p_stale": "VERIFIED_DATED"}
    g = _gen(_msrp_evidence=ev)
    deals = [_deal("p_ok", 20000), _deal("p_ref", 30000), _deal("p_stale", 40000)]
    bybp = _bybp(deals[0], deals[1]) | _bybp(deals[2], age_h=24 * 30)
    *_rest, adv = g._gate_and_merge_deals([], [], [], [], deals, bybp)
    assert [d.product_id for d in adv] == ["p_ok"]


def test_search_result_url_is_not_classified_as_item():
    from src.market.normalized_prices import classify_link_type
    assert classify_link_type("https://iosys.co.jp/items/search/?q=iphone", True, "buy") == "search"
    assert classify_link_type("https://www.example.jp/item/list?keyword=gr", True, "buy") == "search"
    assert classify_link_type("https://iosys.co.jp/items/1234567", True, "buy") == "item"     # 否定対照


def test_reference_route_never_uses_listing_or_unknown_sell():
    stale = (NOW - timedelta(days=20)).isoformat()
    ref = _safe(sell_type="SOLD", sell_observed_at=stale, reference_route=True, rejection_reason="x")
    assert not opp.reference_route_reasons(ref, NOW)
    for t in ("LISTING", "UNKNOWN", "TRADE_IN"):
        assert opp.reference_route_reasons(dict(ref, sell_canonical_type=t), NOW), t


def test_simfree_new_is_new_condition():
    r = _safe(buy_condition="new_unopened_simfree", sell_condition="new_unopened")
    assert not opp.route_reasons(r, NOW)
    assert rtv.build(opp.build(deals=[], routes=[r], product_genres={}, now=NOW))[0].route_type == \
        rtv.RETAIL_TO_BUYBACK
    assert "condition_mismatch" in opp.route_reasons(dict(r, sell_condition="new_opened"), NOW)


def test_ai_dashboard_rechecks_routes_at_render(tmp_path, monkeypatch):
    """AI の生成物が古いまま残っても、描画時に判定を通らないルートの候補・おすすめ・今日やることを出さない。"""
    now = datetime.now(tz=JST)
    gr4 = RF.safe_route(now, "prod_gr4", buy=107491, sell=151000)
    safe = RF.safe_route(now, "p_safe", buy=BUY, sell=160000)
    # 生成時点では両方とも確定だった AI のファイルを、実際の generate_ai_opportunities で作る
    (tmp_path / "exports" / "profit_routes").mkdir(parents=True)
    (tmp_path / "exports/profit_routes/latest.json").write_text(
        json.dumps({"main_routes": [gr4, safe], "reference_routes": []}), encoding="utf-8")
    monkeypatch.setattr(GAO, "ROOT", tmp_path)
    monkeypatch.setattr(GAO, "OUT", tmp_path / "exports" / "ai_opportunities")
    monkeypatch.setattr(GAO, "_price_trend", lambda pid: {"7d": "→", "30d": "→", "90d": "→"})
    assert GAO.main() == 0
    d = json.loads((tmp_path / "exports/ai_opportunities/latest.json").read_text(encoding="utf-8"))
    assert {o["product_id"] for o in d["todays_opportunities"]} == {"prod_gr4", "p_safe"}
    assert "107,491" in "".join(d["today_tasks"]) or d["daily_recommendation"]["product"] == "商品prod_gr4"
    # その後、GR IV のルートは照合未了で確定から外れた（AI のファイルは古いまま残った）
    gr4_now = dict(gr4, buy_exact_match=False)
    html = _gen(_gate_now=now)._ai_dashboard_section(d, {"main_routes": [gr4_now, safe], "reference_routes": []})
    assert "商品prod_gr4" not in html and "107,491" not in html and f"{gr4['net_profit']:,}" not in html
    assert "商品p_safe" in html
    assert re.search(r"Main Routes: <b[^>]*>1</b>", html)
    # 否定対照: ルートが確定のままなら両方出る
    html_ok = _gen(_gate_now=now)._ai_dashboard_section(d, {"main_routes": [gr4, safe], "reference_routes": []})
    assert "商品prod_gr4" in html_ok and re.search(r"Main Routes: <b[^>]*>2</b>", html_ok)
