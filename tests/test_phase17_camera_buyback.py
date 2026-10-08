"""Phase 17（カメラの新品の買取）のテスト。

買取商店のカメラの一覧の構造化データ（JAN）で1行だけを照合し、新品の買取だけを確定の売値に使う。新品同様（used_s）・
中古・古い価格・店のトップ・検索結果は確定にしない。ボディー/キット・色/版・GR IV の版を分ける。取得に失敗しても前回の
行の時刻・価格を変えない。抽選・在庫なし・在庫未確認は今すぐ行動できるに数えない。各テストに否定の対照を付ける。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=JST)
PRODUCTS = {p["id"]: p for p in yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))["products"]}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


UBP = _load("p17_ubp", ROOT / "scripts" / "update_buyback_prices.py")
DC = _load("p17_dc", ROOT / "scripts" / "deploy_check.py")


def _ld(name: str, jan: str, price: int, n: int) -> str:
    return ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
            f'"name":"{name}","url":"https://www.kaitorishouten-co.jp/products/detail/{n}","gtin13":"{jan}",'
            f'"offers":{{"@type":"Offer","price":{price},"priceCurrency":"JPY",'
            f'"url":"https://www.kaitorishouten-co.jp/products/detail/{n}"}}}}</script>')


# 2026-10-08 の買取商店のカメラの一覧（構造化データ）の並びを写した合成の HTML
CAMERA_PAGE = "".join([
    _ld("デジタルカメラ FUJIFILM X100VI [シルバー]", "4547410528282", 280000, 19384),
    _ld("デジタルカメラ FUJIFILM X100VI [シルバー]2025版", "4547410554281", 260000, 22388),
    _ld("デジタルカメラ FUJIFILM X100VI [ブラック]", "4547410529494", 256000, 19385),
    _ld("デジタルカメラ FUJIFILM X100VI [ブラック] 2025版", "4547410554267", 250000, 22255),
    _ld("コンパクトデジタルカメラ RICOH GR IV", "4549212311291", 200000, 24408),
    _ld("コンパクトデジタルカメラ RICOH GR IV HDF", "4549212311871", 240000, 26434),
    _ld("コンパクトデジタルカメラ RICOH GR IV Monochrome", "4549212311994", 227000, 25561),
    _ld("コンパクトデジタルカメラ RICOH GR IV 30th Anniversary Edition Kit", "4549212312000", 300000, 26999),
    _ld("Z 8 ボディ", "4960759909947", 420000, 16562),
    _ld("ミラーレス一眼カメラ Canon EOS R5 Mark II RF24-105L IS USM レンズキット", "4549292229226", 570000, 20464),
    _ld("ミラーレス一眼カメラ Canon EOS R5 Mark II ボディ", "4549292229141", 450000, 20463),
])
EXPECTED = {"x100vi": (260000, 22388), "gr4": (200000, 24408), "gr4_hdf": (240000, 26434),
            "gr4_mono": (227000, 25561), "z8": (420000, 16562), "r5ii": (450000, 20463)}


def _collector():
    from src.collectors.buyback_kaitori_shouten import KaitoriShoutenCsvCollector
    return KaitoriShoutenCsvCollector()


# ── 取得（JAN で1行だけ） ─────────────────────────────────────────────────

@pytest.mark.parametrize("alias", sorted(EXPECTED))
def test_exact_item_accepted(alias):
    c = _collector()
    price, detail = EXPECTED[alias]
    assert c._parse_price(CAMERA_PAGE, alias, "") == price
    assert c._parse_detail_url(CAMERA_PAGE, "https://x/") == f"https://www.kaitorishouten-co.jp/products/detail/{detail}"


@pytest.mark.parametrize("name,alias", [
    ("Z 8 ボディ（中古）", "z8"), ("Z 8 ボディ 未使用品", "z8"), ("Nikon Z 8 ボディ FTZ II 同梱", "z8"),
    ("ミラーレス一眼カメラ Canon EOS R5 Mark II ボディ 中古", "r5ii"),
    ("ミラーレス一眼カメラ Canon EOS R5 Mark II ボディ バッテリー付き", "r5ii")])
def test_body_with_condition_or_bundle_rejected(name, alias):
    """ボディーで終わらない名前（状態・同梱の表記）は、JAN が同じでも使わない（レビュー M1）。"""
    from src.collectors.buyback_kaitori_shouten import JAN_RULES
    assert _collector()._parse_price(_ld(name, JAN_RULES[alias]["jan"], 400000, 8), alias, "") is None


def test_wrong_kit_rejected():
    """R5 II のレンズキット・Z8 のキットはボディーの買取にしない（JAN が同じでも名前で外す）。"""
    from src.collectors.buyback_kaitori_shouten import match_jan_rows, parse_jsonld_rows
    kit = _ld("Canon EOS R5 Mark II RF24-105L レンズキット", "4549292229141", 570000, 1)
    assert match_jan_rows(parse_jsonld_rows(kit), "r5ii") == []
    z8kit = _ld("Z 8 ボディ 24-120 レンズキット", "4960759909947", 500000, 2)
    assert match_jan_rows(parse_jsonld_rows(z8kit), "z8") == []
    assert _collector()._parse_price(kit, "r5ii", "") is None


def test_wrong_edition_or_color_rejected():
    """X100VI は公式で買う版（シルバー 2025版）の JAN だけ。色・版の違う行は使わない。"""
    from src.collectors.buyback_kaitori_shouten import JAN_RULES
    from src.market import official_registry as reg
    assert JAN_RULES["x100vi"]["jan"] in reg.IDENTITY_EVIDENCE["prod_x100vi"]["colors"].values()
    only_others = "".join(x for x in CAMERA_PAGE.split("</script>") if "2025版" not in x or "ブラック" in x)
    only_others = only_others.replace('"gtin13":"4547410554281"', '"gtin13":"0000000000000"') + "</script>"
    assert _collector()._parse_price(only_others, "x100vi", "") is None
    # JAN が同じでも名前が別の版なら使わない
    mismatch = _ld("デジタルカメラ FUJIFILM X100VI [ブラック] 2025版", "4547410554281", 250000, 3)
    assert _collector()._parse_price(mismatch, "x100vi", "") is None


def test_gr4_variants_separated():
    from src.collectors.buyback_kaitori_shouten import match_jan_rows, parse_jsonld_rows
    rows = parse_jsonld_rows(CAMERA_PAGE)
    got = {a: [r["name"] for r in match_jan_rows(rows, a)] for a in ("gr4", "gr4_hdf", "gr4_mono")}
    assert all(len(v) == 1 for v in got.values())
    assert "HDF" not in got["gr4"][0] and "Monochrome" not in got["gr4"][0]
    assert not any("Anniversary" in v[0] for v in got.values())
    # 30周年記念キットに GR IV の JAN が付いていても使わない
    anniv = _ld("RICOH GR IV 30th Anniversary Edition Kit", "4549212311291", 300000, 9)
    assert match_jan_rows(parse_jsonld_rows(anniv), "gr4") == []


@pytest.mark.parametrize("name,jan,alias", [
    ("Z 8 ボディ", "4960759909948", "z8"),                                        # 名前は合うが JAN が違う
    ("ミラーレス一眼カメラ Canon EOS R5 Mark II ボディ", "4549292229226", "r5ii"),   # キットの JAN
    ("デジタルカメラ FUJIFILM X100VI [シルバー]2025版", "4547410528282", "x100vi"),  # 旧版の JAN
    ("コンパクトデジタルカメラ RICOH GR IV", "4549212311871", "gr4"),               # HDF の JAN
])
def test_wrong_jan_rejected(name, jan, alias):
    """商品名が合っていても JAN が違えば使わない（名前だけで同じ商品にしない）。"""
    assert _collector()._parse_price(_ld(name, jan, 400000, 7), alias, "") is None


def test_same_jan_different_price_is_ambiguous():
    """同じ JAN に違う価格が並べば、どれも選ばない（同じ価格だから同じ商品とも、高いほうとも決めない）。"""
    c = _collector()
    html = _ld("Z 8 ボディ", "4960759909947", 420000, 1) + _ld("Z 8 ボディ", "4960759909947", 430000, 2)
    assert c._parse_price(html, "z8", "") is None and c.last_failure_reason == "ambiguous_rows"


def test_non_new_condition_or_currency_rejected():
    """構造化データが新品でない・円でない行は使わない（監査 M1）。"""
    from src.collectors.buyback_kaitori_shouten import parse_jsonld_rows
    used = _ld("Z 8 ボディ", "4960759909947", 420000, 1).replace(
        '"@type":"Product",', '"@type":"Product","itemCondition":"https://schema.org/UsedCondition",')
    assert parse_jsonld_rows(used) == []
    usd = _ld("Z 8 ボディ", "4960759909947", 4200, 1).replace('"priceCurrency":"JPY"', '"priceCurrency":"USD"')
    assert parse_jsonld_rows(usd) == []
    new = _ld("Z 8 ボディ", "4960759909947", 420000, 1).replace(
        '"@type":"Product",', '"@type":"Product","itemCondition":"https://schema.org/NewCondition",')
    assert len(parse_jsonld_rows(new)) == 1


def test_ambiguous_rows_do_not_cut_off_shop():
    from src.collectors.polite import CUTOFF_IGNORED
    assert "ambiguous_rows" in CUTOFF_IGNORED


def test_detail_url_required():
    from src.collectors.buyback_kaitori_shouten import parse_jsonld_rows
    bad = _ld("Z 8 ボディ", "4960759909947", 420000, 1).replace("/products/detail/1", "/category/2/108")
    assert parse_jsonld_rows(bad) == []
    assert _collector()._parse_price(bad, "z8", "") is None


def test_targets_and_requests():
    """カメラの6商品は買取商店だけ。一覧は2ページ（同じ実行では使い回す）。"""
    from src.collectors.buyback_kaitori_shouten import PRODUCT_URLS
    cams = {p["product_alias"]: p for p in UBP.TARGET_PRODUCTS if p["product_alias"] in EXPECTED}
    assert set(cams) == set(EXPECTED)
    assert all(p["shops"] == ["kaitori_shouten"] and p["condition"] == "new_unopened" for p in cams.values())
    assert len({PRODUCT_URLS[a] for a in EXPECTED}) == 2
    for a in EXPECTED:
        assert UBP.PRODUCT_GENRES[a] == "camera" and UBP.OFFICIAL_PRICES[a] > 0


# ── 売る側の確定（新品だけ・新しい・商品ページ） ───────────────────────────────────

def _obs(url="https://www.kaitorishouten-co.jp/products/detail/16562", data_source="auto_scraped", **kw):
    """取り込みの観測（normalized_prices.build_observations の買取の行と同じ引数）。"""
    from src.market.normalized_prices import _extraction_method, classify_link_type, make_observation
    base = dict(product_id="prod_z8", product_name="Nikon Z8", source_id="src_kaitori_shouten",
                source_name="買取商店", market_type="domestic_buyback", price_role="sell",
                price_type="buyback_price", condition="new_unopened", price=420000,
                observed_at="2026-10-09T09:00:00+09:00", confidence="high", source_url=url, item_url=url,
                link_type=classify_link_type(url, True, "sell"), extraction_method=_extraction_method(data_source),
                price_context="買取価格")
    base.update(kw)
    return make_observation(NOW, **base)


def test_fresh_new_camera_buyback_accepted():
    from src.market.normalized_prices import sell_confirmation_reasons
    assert sell_confirmation_reasons(_obs()) == []


@pytest.mark.parametrize("change,reason", [
    ({"condition": "used_s"}, "condition_mismatch"),                         # 新品同様は中古
    ({"condition": "used_a"}, "condition_mismatch"),
    ({"observed_at": "2026-09-01T09:00:00+09:00"}, "stale_sell_price"),       # 14日より古い
    ({"url": "https://www.kaitorishouten-co.jp/"}, "sell_url_not_item_level"),  # 店のトップ
])
def test_used_stale_shop_home_rejected(change, reason):
    from src.market.normalized_prices import sell_confirmation_reasons
    assert reason in sell_confirmation_reasons(_obs(**change))


def test_used_s_is_never_new():
    from src.content.ui.opportunity import _cond_family
    from src.models.sale_price import CONDITION_LABELS
    assert _cond_family("used_s") == "used" and _cond_family("new_unopened") == "new"
    assert "中古" in CONDITION_LABELS["used_s"] and "新品同様" in CONDITION_LABELS["used_s"]


def test_conditional_price_still_rejected():
    """条件つきの価格（ネットオフのクーポン・集荷など）は取らないまま（Phase 11 の規則を維持）。"""
    t = (ROOT / "tests" / "test_phase11_data.py").read_text(encoding="utf-8")
    assert "def test_netoff_conditional_campaign_price_not_taken" in t
    from src.collectors.buyback_kaitori_shouten import parse_jsonld_rows
    # 構造化データに価格が無い（条件つきで表示される）行は使わない
    no_price = _ld("Z 8 ボディ", "4960759909947", 1, 1).replace('"price":1', '"price":"要問合せ"')
    assert parse_jsonld_rows(no_price) == []


# ── 失敗したときに時刻・価格を変えない ─────────────────────────────────────────

def test_failure_keeps_previous_row_without_refresh():
    prev = {"product_alias": "z8", "buyback_shop": "kaitori_shouten", "buyback_price": "420000",
            "observed_at": "2026-10-08T16:00:00+09:00", "data_source": "auto_scraped"}
    failed = {"product_alias": "z8", "buyback_shop": "kaitori_shouten", "buyback_price": "0",
              "observed_at": "2026-10-09T16:00:00+09:00", "data_source": "fetch_failed"}
    reasons = {("z8", "kaitori_shouten"): "connection_error"}
    assert UBP.keep_manual_on_failure([failed], [prev], reasons) == [prev]   # 前回のまま（時刻を進めない）
    # 理由が分からない失敗では残さない
    assert UBP.keep_manual_on_failure([failed], [prev]) == [failed]
    # カメラ以外（既存の商品）の自動取得の行は、これまでどおり残さない
    other = dict(prev, product_alias="ps5_pro")
    assert UBP.keep_manual_on_failure([dict(failed, product_alias="ps5_pro")], [other],
                                      {("ps5_pro", "kaitori_shouten"): "connection_error"})[0]["data_source"] == "fetch_failed"
    # 成功したときは新しい行
    ok = dict(failed, buyback_price="425000", data_source="auto_scraped")
    assert UBP.keep_manual_on_failure([ok], [prev]) == [ok]


@pytest.mark.parametrize("reason,data_source", [
    ("product_not_listed", "product_not_listed"), ("ambiguous_rows", "fetch_failed"),
    ("price_not_found", "fetch_failed"), ("suspicious_rejected", "suspicious_rejected")])
def test_refuting_failure_does_not_keep_previous(reason, data_source):
    """掲載が無い・同じ JAN に違う価格・異常値の隔離など、前回の価格を否定する失敗では前回の行を残さない（レビュー H1）。"""
    prev = {"product_alias": "gr4_hdf", "buyback_shop": "kaitori_shouten", "buyback_price": "240000",
            "observed_at": "2026-10-08T16:00:00+09:00", "data_source": "auto_scraped"}
    failed = {"product_alias": "gr4_hdf", "buyback_shop": "kaitori_shouten", "buyback_price": "0",
              "observed_at": "2026-10-09T16:00:00+09:00", "data_source": data_source}
    out = UBP.keep_manual_on_failure([failed], [prev], {("gr4_hdf", "kaitori_shouten"): reason})
    assert out == [failed]
    # ブロック・robots の禁止など、取りに行けない状態でも残さない（監査 H1）
    for blocked in ("site_blocked", "rate_limited_429", "robots_disallowed", "http_403"):
        assert UBP.keep_manual_on_failure([dict(failed, data_source="fetch_failed")], [prev],
                                          {("gr4_hdf", "kaitori_shouten"): blocked})[0]["data_source"] == "fetch_failed"
    # 一時的な取得の失敗（通信・HTTP）なら前回のまま
    for transient in ("connection_error", "http_503", "timeout"):
        assert UBP.keep_manual_on_failure([dict(failed, data_source="fetch_failed")], [prev],
                                          {("gr4_hdf", "kaitori_shouten"): transient}) == [prev]


# ── 利益と今すぐ行動できるか ─────────────────────────────────────────────────

def _deal(**kw):
    d = {"product_id": "prod_gr4_hdf", "title": "RICOH GR IV HDF", "genre": "camera", "brand": "RICOH",
         "official_price": 222000, "sell_price": 240000, "sell_shop": "買取商店",
         "sell_checked_at": "2026-10-09T09:00:00+09:00", "official_checked_at": "2026-10-09T08:00:00+09:00",
         "msrp_evidence": "VERIFIED_CURRENT", "sell_identity_verified": True, "purchase_shipping": 0,
         "purchase_shipping_status": "FREE_VERIFIED", "condition": "new_unopened",
         "sell_url": "https://www.kaitorishouten-co.jp/products/detail/26434", "user_level": "beginner_watch"}
    from src.content.ui import opportunity as opp
    v0 = opp.from_deal(d)
    d["net_profit"] = d["sell_price"] - d["official_price"] - sum(a for _l, a in v0.cost_lines)
    d.update(kw)
    return d


def test_official_price_and_fresh_sell_make_opportunity_but_lottery_not_actionable():
    from src.content.ui import opportunity as opp
    from src.market.opportunity_diagnostics import ACTIONABLE_AVAILABILITY
    d = _deal(sale_method="lottery", stock_status="SOLD OUT")
    assert d["net_profit"] > 0
    assert opp.deal_reasons(d, NOW) == ()                                   # 確定の利益案件
    v = opp.from_deal(d)
    assert v.availability == "LOTTERY" and v.availability not in ACTIONABLE_AVAILABILITY


@pytest.mark.parametrize("stock,actionable", [
    ("在庫なし（全色）", False), ("", False), ("カートに入れる", True)])
def test_positive_profit_needs_stock_to_be_actionable(stock, actionable):
    from src.content.ui import opportunity as opp
    from src.market.opportunity_diagnostics import ACTIONABLE_AVAILABILITY
    d = _deal(stock_status=stock, stock_checked_at="2026-10-09T10:00:00+09:00" if stock else "")
    v = opp.from_deal(d)
    opp._apply_stock_freshness(v, NOW)
    assert (v.availability in ACTIONABLE_AVAILABILITY) is actionable


def test_no_profit_when_sell_below_official_direct():
    """R5 II（公式直販 654,500円）・Z8（575,300円＋送料550円）は、今の新品の買取では利益が出ない。"""
    from src.market.official_shipping import purchase_shipping
    assert 450000 < 654500 and 420000 < 575300 + purchase_shipping("prod_z8")["fee"]
    from src.content.ui import opportunity as opp
    d = _deal(product_id="prod_r5ii", official_price=654500, sell_price=450000, net_profit=-206300)
    assert "no_profit" in opp.deal_reasons(d, NOW)


def test_ricoh_shipping_recorded():
    from src.market.official_shipping import purchase_shipping
    for pid in ("prod_gr4", "prod_gr4_hdf", "prod_gr4_mono"):
        s = purchase_shipping(pid)
        assert s["fee"] == 0 and s["source"] == "src_ricoh_imaging" and s["checked_on"] == "2026-10-08"


# ── 集計・運営者向け・deploy-check ─────────────────────────────────────────────

def test_camera_summary_counts():
    from src.market.opportunity_diagnostics import _camera_summary
    prods = [{"id": "prod_z8", "genre": "camera"}, {"id": "prod_ps5_pro", "genre": "game"}]
    obs = [_obs(), _obs(condition="used_s", source_name="フジヤカメラ", price=289000),
           _obs(observed_at="2026-08-22T12:00:00+09:00", price=400000)]
    got = _camera_summary(prods, obs, [{"product_id": "prod_z8", "eligible": False}], [])
    assert (got["fresh_new"], got["stale_new"], got["used_reference"], got["confirmed_sells"]) == (1, 1, 1, 1)
    assert got["confirmed_products"][0]["price"] == 420000 and got["profitable"] == 0 and got["actionable"] == 0


def test_admin_shows_camera_coverage():
    from src.content.ui import admin
    html = admin._data_coverage_html(admin.build_data_coverage(
        {"camera": {"fresh_new": 6, "stale_new": 18, "used_reference": 27, "confirmed_sells": 6, "profitable": 1}}, {}))
    assert "カメラの買取" in html and "新品同様も中古" in html and "NaN" not in html
    # 診断に camera が無い（Phase 17 より前）ときは行を出さない（0件と区別する。レビュー L1）
    assert "カメラの買取" not in admin._data_coverage_html(admin.build_data_coverage({"buyback": {}}, {}))


def test_deploy_check_camera_ok_and_mutation_detected(monkeypatch):
    assert DC._check_phase17_camera_sell()[0]["level"] == "ok"
    from src.collectors import buyback_kaitori_shouten as ks
    # キットを外さない（名前の条件をボディーに限らず、除外の語も無くす）
    monkeypatch.setitem(ks.JAN_RULES, "r5ii", dict(ks.JAN_RULES["r5ii"], pattern=r"EOS\s?R5\s?Mark\s?II", exclude=[]))
    assert DC._check_phase17_camera_sell()[0]["level"] == "error"
