"""Market Research Foundation（調査候補・買取起点の発見・TCG の種別と取得元の分類・定価の台帳）のテスト。

調査候補は確定の利益ではない。確定の判定（eligibility）は変えず、外れた商品のうち生の価格差がある商品を運営者向けに残す。
通信はしない（データはすべて架空）。
"""
from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research import candidates as rc  # noqa: E402
from src.research import catalog as rcat  # noqa: E402
from src.research import interfaces as rif  # noqa: E402

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=JST)
PRODUCTS = [{"id": "p1", "name": "調査用ダミー商品XYZ", "genre": "camera", "jan": "4900000000011", "part_numbers": []}]


def _off(**kw):
    base = {"product_id": "p1", "price_role": "official", "price_type": "official_price", "canonical_price_type": "RETAIL",
            "price": 100000, "source_id": "official", "condition": "new_unopened", "link_type": "official_top",
            "is_fresh": True, "freshness_basis": "config_unknown_date", "accessory_flag": False, "wrong_model_flag": False,
            "is_exact_product_match": False}
    base.update(kw)
    return base


def _sell(**kw):
    base = {"product_id": "p1", "price_role": "sell", "price_type": "buyback_price", "canonical_price_type": "BUYBACK_CASH",
            "price": 150000, "source_id": "s1", "source_name": "店A", "condition": "new_unopened",
            "is_exact_product_match": False, "link_type": "shop_home", "is_fresh": False,
            "freshness_basis": "observed_stale", "accessory_flag": False, "wrong_model_flag": False,
            "rejection_reason": "stale_over_14d", "observed_at": "2026-08-01T00:00:00+09:00"}
    base.update(kw)
    return base


def _good_sell(**kw):
    base = dict(is_exact_product_match=True, link_type="item", is_fresh=True, freshness_basis="observed",
                rejection_reason="", observed_at="2026-10-22T12:00:00+09:00")
    base.update(kw)
    return _sell(**base)


def _build(obs, *, ev="CONFIGURED_REFERENCE", verified=(), meta=None, prev=None, products=None, **kw):
    return rc.build(products=products or PRODUCTS, observations=obs, msrp_evidence={"p1": ev}, official_meta=meta or {},
                    verified_pids=set(verified), now=NOW, prev_state=prev, **kw)


def _first(rep):
    return rep["candidates"][0]


# ── 調査候補: 残す・確定にしない ─────────────────────────────────────────────────

def test_raw_positive_spread_is_retained_as_research_candidate():
    rep, _ = _build([_off(), _sell()])
    c = _first(rep)
    assert c["status"] == rc.RESEARCH_CANDIDATE and c["raw_spread"] == 50000 and c["known_cost_spread"] > 0
    assert c["shipping_unknown"] is True and c["raw_net_spread"] is None            # 送料不明は純の差を出さない（純利益と誤認させない）
    assert c["known_costs"] > 0 and c["known_cost_spread"] == c["raw_spread"] - c["known_costs"]
    assert rep["counts"]["research_candidates"] == 1 and rep["counts"]["verified"] == 0


@pytest.mark.parametrize("obs, ev, missing", [
    ([_off(), _good_sell()], "CONFIGURED_REFERENCE", rc.OFFICIAL_UNVERIFIED),       # 公式が未確認
    ([_off(), _sell(is_exact_product_match=True, link_type="item")], "VERIFIED_CURRENT", rc.SELL_STALE),   # 売値が古い
    ([_off(), _good_sell(link_type="shop_home")], "VERIFIED_CURRENT", rc.GENERIC_SELL_URL),                 # 売値の URL が店のトップ
    ([_off(), _good_sell(is_exact_product_match=False)], "VERIFIED_CURRENT", rc.IDENTITY_UNCONFIRMED),      # 照合が未了
])
def test_gate_failures_are_not_confirmed_but_stay_as_candidates(obs, ev, missing):
    rep, _ = _build(obs, ev=ev)
    c = _first(rep)
    assert c["status"] == rc.RESEARCH_CANDIDATE                      # 確定にしない・捨てない
    assert missing in c["missing_requirements"]


def test_verified_only_when_existing_gate_passed():
    obs = [_off(), _good_sell()]
    assert _first(_build(obs, ev="VERIFIED_CURRENT")[0])["status"] == rc.RESEARCH_CANDIDATE   # 自分では VERIFIED にしない
    assert _first(_build(obs, ev="VERIFIED_CURRENT", verified={"p1"})[0])["status"] == rc.VERIFIED


def test_verified_candidate_carries_no_exclusion_reasons_besides_advisory():
    c = _first(_build([_off(), _good_sell()], ev="VERIFIED_CURRENT", verified={"p1"})[0])
    assert set(c["missing_requirements"]) <= rc.ADVISORY


def test_no_spread_is_rejected_and_one_sided_is_discovered():
    assert _first(_build([_off(price=200000), _good_sell()], ev="VERIFIED_CURRENT")[0])["status"] == rc.REJECTED
    assert _first(_build([_off()])[0])["status"] == rc.DISCOVERED
    assert rc.NO_SELL_SIDE in _first(_build([_off()])[0])["exclusion_reasons"]


def test_net_negative_after_known_costs_is_not_a_research_candidate():
    from src.market import profit_formula as pf
    sell = 100000 + pf.fixed_costs() - 1                      # 差はあるが、分かっている費用を引くと赤字
    c = _first(_build([_off(), _good_sell(price=sell)], ev="VERIFIED_CURRENT")[0])
    assert c["raw_spread"] > 0 and c["status"] == rc.DISCOVERED and rc.NET_NEGATIVE in c["exclusion_reasons"]


def test_suspiciously_large_spread_is_low_confidence():
    c = _first(_build([_off(), _sell(price=400000)])[0])
    assert c["status"] == rc.RESEARCH_CANDIDATE and rc.PRICE_ANOMALY_SUSPECTED in c["missing_requirements"]
    assert c["confidence"] == "low"


def test_stale_high_price_is_kept_when_confirmed_price_has_no_spread():
    obs = [_off(price=300000), _good_sell(price=260000, source_id="s2", source_name="店B"), _sell(price=445000)]
    c = _first(_build(obs, ev="VERIFIED_CURRENT")[0])
    assert c["status"] == rc.RESEARCH_CANDIDATE and c["observed_sell_price"] == 445000
    assert rc.SELL_STALE in c["missing_requirements"] and "古い" in c["note"]


def test_secondary_route_when_official_not_sold():
    shop = {"product_id": "p1", "price_role": "buy", "price_type": "shop_sale_price", "canonical_price_type": "UNKNOWN",
            "price": 90000, "source_id": "shop_x", "condition": "new_unopened", "link_type": "search", "is_fresh": True,
            "freshness_basis": "observed", "accessory_flag": False, "wrong_model_flag": False,
            "is_exact_product_match": False}
    rep, _ = _build([_off(), shop, _good_sell()], ev="VERIFIED_CURRENT", meta={"p1": {"official_not_sold": True}})
    c = _first(rep)
    assert c["route_type"] == rc.SECONDARY_TO_BUYBACK and c["observed_buy_price"] == 90000
    assert rc.OFFICIAL_NOT_SOLD in c["missing_requirements"] and rc.BUY_NOT_ITEM_LEVEL in c["missing_requirements"]
    assert c["status"] == rc.RESEARCH_CANDIDATE


def test_accessory_or_wrong_model_sell_rows_are_not_used():
    rep, _ = _build([_off(), _sell(accessory_flag=True), _sell(wrong_model_flag=True, price=999999)])
    assert _first(rep)["status"] == rc.DISCOVERED and rc.NO_SELL_SIDE in _first(rep)["exclusion_reasons"]


# ── ID・重複・台帳・優先度 ───────────────────────────────────────────────────────

def test_candidate_id_is_stable_across_price_changes_and_dedupes():
    rep1, st = _build([_off(), _sell()])
    rep2, st2 = _build([_off(), _sell(price=160000)], prev=st)
    a, b = _first(rep1), _first(rep2)
    assert a["candidate_id"] == b["candidate_id"] and a["discovered_at"] == b["discovered_at"]
    assert len(rep2["candidates"]) == 1 and len(st2) == 1
    # ID は商品だけで決まる（経路・買う店・売る店が変わっても同じ。別の商品は別の ID）
    assert rc.candidate_id(rc.RETAIL_TO_BUYBACK, "p1", "official", "s1") == rc.candidate_id(rc.SECONDARY_TO_BUYBACK, "p1", "shopX", "s9")
    assert rc.candidate_id(rc.RETAIL_TO_BUYBACK, "p1") != rc.candidate_id(rc.RETAIL_TO_BUYBACK, "p2")


def test_discovered_at_is_kept_and_last_seen_is_updated():
    _, st = _build([_off(), _sell()])
    later = NOW + timedelta(days=2)
    rep, _st = rc.build(products=PRODUCTS, observations=[_off(), _sell()], msrp_evidence={"p1": "CONFIGURED_REFERENCE"},
                        official_meta={}, verified_pids=set(), now=later, prev_state=st)
    c = _first(rep)
    assert c["discovered_at"] == NOW.isoformat(timespec="seconds") and c["last_seen_at"] == later.isoformat(timespec="seconds")


def test_unseen_candidates_become_stale_then_dropped():
    _, st = _build([_off(), _sell()])
    rep, st2 = rc.build(products=[], observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(),
                        now=NOW + timedelta(days=3), prev_state=st)
    assert [c["status"] for c in rep["candidates"]] == [rc.STALE] and rep["counts"]["stale"] == 1
    assert rep["candidates"][0]["discovered_at"] == NOW.isoformat(timespec="seconds")      # 日時を付け替えない
    rep3, st3 = rc.build(products=[], observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(),
                         now=NOW + timedelta(days=rc.STALE_RETENTION_DAYS + 1), prev_state=st2)
    assert rep3["candidates"] == [] and st3 == {}


def test_priority_is_deterministic_and_prefers_fresh_confirmed_identity():
    p2 = {"id": "p2", "name": "別", "genre": "camera", "jan": "", "part_numbers": []}
    obs = [_off(), _good_sell(price=130000), _off(product_id="p2"), _sell(product_id="p2", price=250000)]
    rep, _ = rc.build(products=PRODUCTS + [p2], observations=obs, msrp_evidence={"p1": "CONFIGURED_REFERENCE", "p2": "CONFIGURED_REFERENCE"},
                      official_meta={}, verified_pids=set(), now=NOW)
    rows = [c for c in rep["candidates"] if c["status"] == rc.RESEARCH_CANDIDATE]
    assert [c["product_identity"]["product_id"] for c in rows] == ["p1", "p2"]            # 差の小さい p1 が先（p2 は古い・店のトップ・異常）
    assert rows[0]["priority_score"] > rows[1]["priority_score"] and rows[0]["priority_rank"] == 1
    again, _ = rc.build(products=PRODUCTS + [p2], observations=obs, msrp_evidence={"p1": "CONFIGURED_REFERENCE", "p2": "CONFIGURED_REFERENCE"},
                        official_meta={}, verified_pids=set(), now=NOW)
    assert [c["candidate_id"] for c in again["candidates"]] == [c["candidate_id"] for c in rep["candidates"]]


def test_priority_formula_has_no_prediction_inputs():
    src = (ROOT / "src" / "research" / "candidates.py").read_text(encoding="utf-8")
    assert not re.search(r"predict|forecast|sklearn|torch|numpy", src)               # 予測・学習の部品を使わない
    pri = src[src.index("def priority_of"):src.index("def _label")]
    assert "estimated" not in pri and "predicted" not in pri


# ── 買取起点の発見 ──────────────────────────────────────────────────────────────

def test_catalog_matches_by_jan_or_part_number_only_not_by_name():
    catalog = [{"shop": "kaitori_shouten", "name": "調査用ダミー商品XYZ", "jan": "4900000000011", "price": 150000, "url": "u1", "observed_at": "2026-10-23T11:00:00+09:00"},
               {"shop": "kaitori_shouten", "name": "調査用ダミー商品XYZ", "jan": "", "price": 150000, "url": "u2", "observed_at": "2026-10-23T11:00:00+09:00"},
               {"shop": "kaitori_shouten", "name": "未知のカメラ", "jan": "4900000009999", "price": 300000, "url": "u3", "observed_at": "2026-10-23T11:00:00+09:00"},
               {"shop": "kaitori_shouten", "name": "iPhone X 256GB MK244J/A", "jan": "", "price": 380000, "url": "u4", "observed_at": "2026-10-23T11:00:00+09:00"}]
    prods = PRODUCTS + [{"id": "pi", "name": "iPhone", "genre": "iphone", "jan": "", "part_numbers": ["MK244J/A"]}]
    matched, unmatched = rc.match_catalog(catalog, prods, {})
    assert {m["url"]: m["canonical_product_id"] for m in matched} == {"u1": "p1", "u4": "pi"}
    assert {u["url"] for u in unmatched} == {"u2", "u3"}                                    # 名前だけでは一致にしない


def test_unmatched_catalog_rows_become_discovered_product_candidates_never_canonical():
    catalog = [{"shop": "s", "name": "未知", "jan": "4900000009999", "price": 300000, "url": "u3", "observed_at": "2026-10-23T11:00:00+09:00"}]
    rep, _ = _build([_off(), _sell()], catalog=catalog, identity={})
    dp = rep["product_candidates"][0]
    assert dp["kind"] == "DISCOVERED_PRODUCT_CANDIDATE" and dp["status"] == rc.DISCOVERED
    assert "CANONICAL_UNREGISTERED" in dp["missing_requirements"] and dp["candidate_id"].startswith("dp_")
    assert rep["buyback_first"]["new_product_candidates"] == 1
    # 台帳（正本）には入っていない
    assert all(c["product_identity"]["product_id"] == "p1" for c in rep["candidates"])


def test_catalog_candidate_list_is_bounded():
    catalog = [{"shop": "s", "name": f"x{i}", "jan": "", "price": 10000 + i, "url": f"u{i}", "observed_at": "2026-10-23T11:00:00+09:00"}
               for i in range(rc.CATALOG_LIST_LIMIT + 50)]
    _, un = rc.match_catalog(catalog, PRODUCTS, {})
    assert len(rc.discovered_products(un, NOW)) == rc.CATALOG_LIST_LIMIT


LIST_HTML = """<html><body><table><tr><th>品目</th><th>新品買取</th><th>中古買取</th></tr>
<tr><td><a href="/products/detail/1">iPhone Test MK244J/A</a></td><td class="num">¥380,000</td><td class="num">¥300,000</td></tr>
<tr><td><a href="/products/detail/2">別の商品</a></td><td class="num">¥50,000</td><td class="num">¥40,000</td></tr></table></body></html>"""


def test_catalog_capture_reads_listing_once_and_saves_only_when_rows_exist(tmp_path):
    from src.collectors import buyback_kaitori_shouten as ks
    ks.CATALOG_ROWS.clear()
    ks.capture_catalog("https://www.kaitorishouten-co.jp/category/1/748", LIST_HTML)
    ks.capture_catalog("https://www.kaitorishouten-co.jp/category/1/748", "<html></html>")      # 同じ URL は1回だけ
    rows = rcat.collect_rows(NOW)
    assert {r["name"] for r in rows} == {"iPhone Test MK244J/A", "別の商品"} and {r["price"] for r in rows} == {380000, 50000}
    path = tmp_path / "buyback_catalog.json"
    assert rcat.save(path, rows, NOW) is True
    before = path.read_text(encoding="utf-8")
    ks.CATALOG_ROWS.clear()
    assert rcat.save(path, rcat.collect_rows(NOW + timedelta(days=1)), NOW + timedelta(days=1)) is False
    assert path.read_text(encoding="utf-8") == before                                       # 取れなかった日は前回のまま（日時を偽らない）


# ── 指標・設計の窓口 ─────────────────────────────────────────────────────────────

def test_coverage_metrics_are_counted_from_data():
    rep, _ = _build([_off(), _sell()], tcg={"source_coverage": {"configured_sources": 17}, "active_events": 0,
                                            "msrp_verified": 15, "source_candidates": 14})
    m = rep["metrics"]
    assert m["canonical_products"] == 1 and m["research_candidates"] == 1 and m["suppressed_positive_spread"] == 1
    assert m["official_verified_coverage"] == {"verified": 0, "total": 1}
    assert m["marketplace_sold_coverage"]["valid_sold_rows"] == 0
    assert m["tcg_msrp_verified"] == 15 and m["tcg_active_events"] == 0


def test_sold_record_requires_evidence():
    ok = rif.SoldRecord("yahoo", "t", 1000, "2026-10-01T00:00:00+09:00", "https://page.auctions.yahoo.co.jp/jp/auction/x1234567890",
                        source_kind="official_api")
    assert rif.valid_sold_record(ok) == []
    assert "no_sold_at" in rif.valid_sold_record(rif.SoldRecord("m", "t", 1000, "", "https://x.example/item/1", source_kind="official_api"))
    assert "no_item_url" in rif.valid_sold_record(rif.SoldRecord("m", "t", 1000, "2026-10-01T00:00:00+09:00", "https://www.mercari.com/search?keyword=a",
                                                                 source_kind="official_api"))
    assert "source_kind_unknown" in rif.valid_sold_record(rif.SoldRecord("m", "t", 1000, "2026-10-01T00:00:00+09:00", ok.item_url))


# ── 運営者向けの画面にだけ出る・通知・顧客の画面には出ない ─────────────────────────────

def _ui():
    sys.path.insert(0, str(ROOT / "tests"))
    import test_ui_phase9 as U
    return U


def _report(**kw):
    rep, _ = _build([_off(), _sell(item_url="https://shop.example/item/1", source_url="https://shop.example/")], **kw)
    return rep


def _summary(rep=None):
    return rc.public_summary(rep or _report())


def test_public_admin_page_shows_only_counts_not_individual_candidates():
    """管理画面は公開サイトに埋め込まれる（誰でも開ける）。確定していない価格差・商品・店・候補の ID は出さない。"""
    U = _ui()
    from src.content.ui import admin
    rep = _report()
    data = copy.deepcopy(U.ADMIN)
    data["research"] = _summary(rep)
    html = U._admin_html(admin_data=data)
    panel = U._panel(html, "research")
    c = _first(rep)
    assert "調査候補" in panel and "確定の利益ではありません" in panel and "1件" in panel
    assert "公式の価格が未確認" in panel and "売値が古い" in panel and "カメラ" in panel          # 理由別・ジャンル別の件数
    for leak in (c["candidate_id"], "調査用ダミー商品XYZ", "+¥50,000", "¥150,000", "店A", "shop_home"):
        assert leak not in panel, leak
    assert not re.search(r"rc_[0-9a-f]{12}", panel) and not re.search(r"[+−]¥\d", panel) and not re.search(r"¥\d{2,3},\d{3}", panel)
    assert 'data-nu-ad-panel="research"' in html and ("research", "調査候補") in admin.SECTIONS
    assert not re.search(r"¥0(?![0-9,])", panel)
    assert not re.search(r"rc_[0-9a-f]{12}", html) and "調査用ダミー商品XYZ" not in html            # ページ全体にも出ない


def test_admin_rejects_a_report_with_individual_candidates():
    """個別の候補を含む報告（private の latest.json）を渡されても、公開側の管理画面は受け付けない。"""
    from src.content.ui import admin
    assert admin.build_research(_report()) is None
    assert admin.build_research(_summary()) is not None
    poisoned = dict(_summary(), candidates=[{"candidate_id": "rc_000000000000"}])
    assert admin.build_research(poisoned) is None
    assert not hasattr(admin, "RESEARCH_DETAIL_PUBLIC")                      # 個別の候補を出す切り替えを残さない


def test_research_is_not_in_customer_facing_pages():
    U = _ui()
    from src.content.ui import admin, shell
    data = copy.deepcopy(U.ADMIN)
    data["research"] = _summary()
    root = shell.render_root(U._ctx(admin_data=data))
    public = re.sub(r"<script>.*?</script>", "", admin.without_admin(root), flags=re.S)   # 運営の切り替えの JS は別
    assert "調査候補" not in public and "RESEARCH_CANDIDATE" not in public and "RESEARCH_SUMMARY" not in public
    assert "research_candidate_count" not in public and not re.search(r"rc_[0-9a-f]{12}", public)


def test_research_empty_state_without_artifact():
    U = _ui()
    html = U._admin_html(admin_data=copy.deepcopy(U.ADMIN))
    assert "調査候補の集計がまだ生成されていません" in U._panel(html, "research")


def test_research_candidates_never_reach_notifications():
    for f in sorted((ROOT / "src" / "notifiers").glob("*.py")):
        t = f.read_text(encoding="utf-8")
        assert "src.research" not in t and "exports/research" not in t and "build_research" not in t, f.name
    for f in sorted((ROOT / "src" / "research").glob("*.py")):
        imports = "\n".join(ln for ln in f.read_text(encoding="utf-8").splitlines() if re.match(r"\s*(from|import)\s", ln))
        assert not re.search(r"notifiers|outbox|telegram|discord|requests|urllib", imports, re.I), f.name
    gen = (ROOT / "src" / "content" / "daily_lp_generator.py").read_text(encoding="utf-8")
    assert 'ctx.admin_data["research"]' in gen
    assert not re.search(r"_write_actionable_notifications\([^)]*research", gen)


def test_research_report_is_operator_only_and_not_a_notification_record():
    rep = _report()
    assert rep["audience"] == "operator" and rep["type"] == "RESEARCH_CANDIDATES"
    assert "確定の利益ではない" in rep["note"]
    assert "external_sends" not in rep and "notification" not in json.dumps(rep, ensure_ascii=False).lower().replace("notification safety", "")


# ── 公開と非公開の境界（個別の調査候補を公開しない） ─────────────────────────────────

LEAK_RE = re.compile(r"\b(?:rc|dp)_[0-9a-f]{12}\b|(?:candidate_id|observed_buy_price|observed_sell_price|raw_spread|"
                     r"raw_net_spread|known_cost_spread|priority_rank|missing_requirements)\"?\s*[:=]")


def test_public_summary_contains_counts_only():
    summ = _summary()
    assert summ["type"] == "RESEARCH_SUMMARY" and summ["audience"] == "public_aggregate"
    assert summ["research_candidate_count"] == 1 and summ["positive_raw_spread_count"] >= 1
    assert summ["reason_counts"] and summ["genre_counts"] == {"camera": 1} and summ["confidence_counts"]
    for k in ("official_verified_coverage", "buyback_exact_coverage", "marketplace_sold_coverage", "tcg_source_coverage"):
        assert k in summ
    assert not rc.find_private_keys(summ)
    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
        else:
            yield o
    assert all(isinstance(x, (int, float, bool, type(None), str)) for x in walk(summ))
    assert not any(isinstance(v, list) for v in summ.values())                # 候補の行の一覧を持たない


def test_public_summary_has_no_product_name_id_price_spread_or_url():
    rep = _build([_off(), _sell(item_url="https://shop.example/item/1")], catalog=[{"shop": "店A", "name": "未知の商品QQ", "jan": "4900000009999", "price": 777777,
                                                "url": "https://shop.example/p/1", "observed_at": "2026-10-23T11:00:00+09:00"}], identity={})[0]
    txt = json.dumps(rc.public_summary(rep), ensure_ascii=False)
    c = _first(rep)
    assert c["source_url"]["sell"] == "https://shop.example/item/1"                    # 元の候補には URL がある（公開の集計に出ない確認）
    for leak in ("調査用ダミー商品XYZ", "未知の商品QQ", c["candidate_id"], "rc_", "dp_", "150000", "777777", "50000", "店A",
                 "https://", "shop.example", "shop_home", "p1", "4900000009999"):
        assert leak not in txt, leak
    assert not LEAK_RE.search(txt)


def test_public_summary_refuses_to_publish_if_a_private_field_slips_in(monkeypatch):
    rep = _report()
    monkeypatch.setattr(rc, "PRIVATE_KEYS", rc.PRIVATE_KEYS | {"reason_counts"})
    with pytest.raises(ValueError):
        rc.public_summary(rep)


def test_private_research_generation_still_works_and_stays_private(tmp_path):
    rep, state = _build([_off(), _sell()], catalog=[{"shop": "s", "name": "x", "jan": "", "price": 1, "url": "u", "observed_at": "2026-10-23T11:00:00+09:00"}])
    priv, pub = tmp_path / "private", tmp_path / "public"
    summ = rc.write_outputs(rep, state, priv, pub)
    detail = json.loads((priv / "latest.json").read_text(encoding="utf-8"))
    assert detail["type"] == "RESEARCH_CANDIDATES" and detail["candidates"][0]["candidate_id"] == _first(rep)["candidate_id"]
    assert json.loads((priv / "state.json").read_text(encoding="utf-8"))["candidates"]
    assert sorted(p.name for p in pub.iterdir()) == ["summary.json"]               # 公開側は集計1ファイルだけ
    on_disk = (pub / "summary.json").read_text(encoding="utf-8")
    assert json.loads(on_disk) == summ and not LEAK_RE.search(on_disk) and "調査用ダミー商品XYZ" not in on_disk


def test_nothing_is_written_when_the_summary_would_leak(tmp_path, monkeypatch):
    rep, state = _build([_off(), _sell()])
    monkeypatch.setattr(rc, "PRIVATE_KEYS", rc.PRIVATE_KEYS | {"reason_counts"})
    with pytest.raises(ValueError):
        rc.write_outputs(rep, state, tmp_path / "p", tmp_path / "q")
    assert not (tmp_path / "p").exists() and not (tmp_path / "q").exists()


def test_private_dir_is_gitignored_and_never_staged_by_the_workflow():
    import subprocess
    ig = subprocess.run(["git", "check-ignore", "-q", ".private/research/latest.json"], cwd=ROOT)
    assert ig.returncode == 0                                                          # 個別の調査候補は .gitignore 済み
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    add = wf[wf.index("git add docs/"):]
    add = add[:add.index("|| true")]
    assert ".private" not in add and "exports/research/" in add                        # 集計だけが commit の対象
    assert not re.search(r"git add\s+(?:-[A-Za-z-]+\s+)*(?:\.|-A|--all)(?:\s|$)", wf) and not re.search(r"git add[^\n]*\s-f(?:\s|$)", wf)
    import yaml
    steps = yaml.safe_load(wf)["jobs"]["update-lp"]["steps"]
    cache = [st for st in steps if str(st.get("uses") or "").startswith("actions/cache")]
    assert cache and all(".private/research" not in str((st.get("with") or {}).get("path")) for st in cache)   # 平文でキャッシュしない
    assert any((st.get("with") or {}).get("path") == ".private/ledger.enc" for st in cache)                  # 暗号化した台帳だけ
    tracked = subprocess.run(["git", "ls-files", ".private"], cwd=ROOT, capture_output=True, text=True).stdout
    assert tracked.strip() == ""
    pub = sorted(p.name for p in (ROOT / "exports" / "research").iterdir() if p.is_file())
    assert set(pub) <= {"summary.json", ".gitkeep"}                                    # 公開の置き場に個別の候補は無い


def test_public_html_and_json_in_repo_have_no_research_detail():
    for f in sorted((ROOT / "docs").rglob("*")):
        if f.is_file() and f.suffix in (".html", ".md", ".json", ".txt"):
            assert not LEAK_RE.search(f.read_text(encoding="utf-8", errors="ignore")), f.name
    sj = ROOT / "exports" / "research" / "summary.json"
    if sj.exists():
        assert not rc.find_private_keys(json.loads(sj.read_text(encoding="utf-8"))) and not LEAK_RE.search(sj.read_text(encoding="utf-8"))


def test_generator_writes_detail_only_to_the_private_dir():
    gen = (ROOT / "src" / "content" / "daily_lp_generator.py").read_text(encoding="utf-8")
    body = gen[gen.index("def _write_research_candidates"):gen.index("def _write_opportunity_diagnostics")]
    assert "_research_private_dir()" in body and "write_outputs(report, state, priv, self._research_dir())" in body
    assert 'ctx.admin_data["research"]' in gen and "ctx.admin_data[\"research\"] = research" in gen
    assert "latest.json" not in body.replace("normalized_price_observations", "").split("write_outputs")[-1]
    upd = (ROOT / "scripts" / "update_buyback_prices.py").read_text(encoding="utf-8")
    assert ".private" in upd and 'RESEARCH_PRIVATE_DIR' in upd


def test_shipping_unknown_never_shows_a_net_spread_but_known_shipping_does(monkeypatch):
    c = _first(_build([_off(), _sell()])[0])
    assert c["shipping_unknown"] is True and c["raw_net_spread"] is None and rc.PURCHASE_SHIPPING_UNKNOWN in c["missing_requirements"]
    monkeypatch.setattr(rc, "_shipping_fee", lambda pid, url, price: 1000)
    k = _first(_build([_off(), _sell()])[0])
    assert k["shipping_unknown"] is False and k["raw_net_spread"] == k["known_cost_spread"] == k["raw_spread"] - k["known_costs"]


def test_workflow_commits_public_summary_dir_and_creates_it_first():
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    assert "exports/research/" in wf and "mkdir -p exports/ops exports/research" in wf
    assert (ROOT / "exports" / "research" / ".gitkeep").exists()


def test_deploy_check_market_research_passes():
    from scripts import deploy_check as dc
    res = dc._check_market_research()
    assert [r["level"] for r in res] == ["ok"], res


# ── TCG: イベント種別・取得元の分類・候補・定価 ───────────────────────────────────────

NOW_TCG = datetime(2026, 10, 23, 12, 0, tzinfo=JST)


def _ev(et, **kw):
    base = {"event_type": et, "source_type": "RETAILER_OFFICIAL", "application_start": "2026-10-20T10:00:00+09:00",
            "application_end": "2026-10-25T10:00:00+09:00", "sale_start": "2026-10-20T10:00:00+09:00"}
    base.update(kw)
    return base


def test_tcg_event_types_include_entry_routes_release_and_review():
    from src.tcg import models as m
    for name in ("STORE_LOTTERY", "APP_LOTTERY", "WEB_LOTTERY", "IN_STORE_QR", "RELEASE", "REVIEW_REQUIRED",
                 "LOTTERY", "PREORDER", "FIRST_COME", "RESTOCK"):
        assert name in m.EVENT_TYPES, name


@pytest.mark.parametrize("et", ["STORE_LOTTERY", "APP_LOTTERY", "WEB_LOTTERY", "IN_STORE_QR"])
def test_tcg_entry_route_lotteries_use_the_lottery_status_flow(et):
    from src.tcg import freshness as fr
    from src.tcg import models as m
    assert m.base_event_type(et) == m.EVENT_LOTTERY
    assert fr.compute_status(_ev(et), NOW_TCG) == fr.compute_status(_ev("LOTTERY"), NOW_TCG) == m.ST_OPEN
    assert fr.compute_status(_ev(et), NOW_TCG) != m.ST_AVAILABLE_NOW                 # 抽選の受付中は「今買える」ではない
    assert fr.ttl_for(et) is None


def test_tcg_review_required_and_release_are_never_available_now():
    from src.tcg import freshness as fr
    from src.tcg import models as m
    # 同じ形の通常販売なら「今買える」になる（比較の基準。これが崩れたら下の検査が意味を持たない）
    assert fr.compute_status(_ev("GENERAL_SALE", sale_start="2026-10-23T09:00:00+09:00", application_start=None,
                                 application_end=None), NOW_TCG) == m.ST_AVAILABLE_NOW
    for et in ("REVIEW_REQUIRED", "RELEASE"):
        for start in ("2026-10-23T09:00:00+09:00", None):          # 48時間以内（通常の販売なら「今買える」になる形）
            ev = _ev(et, sale_start=start, application_start=None, application_end=None)
            assert fr.compute_status(ev, NOW_TCG) != m.ST_AVAILABLE_NOW
            assert not fr.available_now(ev, NOW_TCG)
    assert fr.compute_status(_ev("REVIEW_REQUIRED"), NOW_TCG) == m.ST_UNVERIFIED
    assert fr.compute_status(_ev("RELEASE", sale_start="2026-10-24T00:00:00+09:00"), NOW_TCG) in (m.ST_STARTING_SOON, m.ST_COMING_SOON)


def test_tcg_new_lottery_kinds_trigger_lottery_notification_candidates_like_lottery_only_when_official():
    from src.tcg import alerts as al
    ev = _ev("APP_LOTTERY", status="OPEN", stale=False)
    assert al.notification_kind(ev) == al.notification_kind(dict(ev, event_type="LOTTERY")) == al.KIND_LOTTERY_OPEN
    assert al.notification_kind(dict(ev, source_type="COMMUNITY_REPORT")) is None            # 未確認は候補にしない
    assert al.notification_kind(dict(ev, event_type="REVIEW_REQUIRED")) is None
    assert al.notification_kind(dict(ev, event_type="RELEASE")) is None


def test_tcg_future_types_are_known_but_not_active():
    from src.tcg import models as m
    assert m.TCG_TYPES == ("POKEMON", "ONE_PIECE")
    assert set(m.FUTURE_TCG_TYPES) == {"YUGIOH", "DUEL_MASTERS"} and set(m.FUTURE_TCG_TYPES) <= set(m.KNOWN_TCG_TYPES)
    assert not (set(m.FUTURE_TCG_TYPES) & set(m.TCG_TYPES))


def test_lottery_entry_kind_from_explicit_fields_only():
    from src.tcg.lottery.schema import entry_kind
    assert entry_kind({"event_type": "PREORDER"}) == "PREORDER"
    assert entry_kind({"event_type": "LOTTERY", "store_specific": True}) == "STORE_LOTTERY"
    assert entry_kind({"event_type": "LOTTERY", "app_required": True}) == "APP_LOTTERY"
    assert entry_kind({"event_type": "LOTTERY", "online_only": True}) == "WEB_LOTTERY"
    assert entry_kind({"event_type": "LOTTERY"}) == "LOTTERY"                                # 推測しない


def test_tcg_source_classes_and_blocked_sources_stay_blocked():
    from src.tcg.lottery import registry as reg
    base = {"official_url": "https://x/", "collection_method": "HTML"}
    cases = [({"adapter": "a", "state": reg.ST_NO_ACTIVE_LOTTERY}, reg.SC_WORKING),
             ({"adapter": "a", "state": reg.ST_SOURCE_BLOCKED}, reg.SC_IMPLEMENTED_BUT_BLOCKED),
             ({"adapter": "a", "state": reg.ST_SOURCE_UNREACHABLE}, reg.SC_UNREACHABLE),
             ({"adapter": None, "state": reg.ST_SOURCE_NOT_MONITORED, "reachable": True}, reg.SC_ACCESSIBLE_UNIMPLEMENTED),
             ({"adapter": None, "state": reg.ST_SOURCE_BLOCKED, "reachable": False}, reg.SC_UNREACHABLE),
             ({"adapter": None, "state": reg.ST_SOURCE_UNREACHABLE}, reg.SC_UNREACHABLE),
             ({"adapter": None, "state": reg.ST_SOURCE_NOT_MONITORED, "reachable": True, "policy_excluded": "規約"}, reg.SC_UNSUPPORTED),
             ({"adapter": None, "state": "x", "official_url": ""}, reg.SC_UNSUPPORTED)]
    for row, want in cases:
        assert reg.source_class({**base, **row}) == want, row
    # 遮断された取得元を「実装の候補（到達できる）」に分類しない
    assert reg.source_class({**base, "adapter": None, "state": reg.ST_SOURCE_BLOCKED, "reachable": True, "blocked": True}) == reg.SC_UNREACHABLE


def test_tcg_registry_classification_and_amazon_is_policy_excluded():
    from src.tcg.lottery import registry as reg
    amazon = reg.SOURCE_BY_ID["AMAZON"]
    assert amazon["policy_excluded"]
    assert reg.source_class({**amazon, "state": reg.ST_SOURCE_NOT_MONITORED, "reachable": True}) == reg.SC_UNSUPPORTED
    cov = reg.coverage_summary([{**amazon, "state": reg.ST_SOURCE_NOT_MONITORED, "reachable": True}])
    assert cov["source_classes"][reg.SC_UNSUPPORTED] == 1 and set(cov["source_classes"]) == set(reg.SOURCE_CLASSES)


def test_tcg_source_candidates_are_unverified_and_not_registered():
    from src.tcg.lottery import registry as reg
    d = reg.load_source_candidates()
    assert d["count"] >= 10 and d["status"] == "CANDIDATE_UNVERIFIED"
    known = {s["source_id"] for s in reg.LOTTERY_SOURCES} | {s["retailer"] for s in reg.LOTTERY_SOURCES}
    assert all(c["id"] not in known and c["name"] not in known for c in d["candidates"])    # 登録済みを候補に重ねない
    assert all(c["verified"] is False for c in d["candidates"])                              # 未確認のまま
    assert reg.load_source_candidates(Path("/nonexistent.yaml"))["count"] == 0


def test_tcg_msrp_ledger_excludes_pack_prices_and_keeps_identity():
    from src.tcg.msrp import build_msrp
    reg = [{"product_id": "box", "name": "BOX", "tcg": "POKEMON", "retail_price": 27500, "retail_price_basis": "product_unit",
            "official_url": "https://www.pokemon-card.com/x/", "box_opportunity_eligible": True, "release_date": "2026-09-16"},
           {"product_id": "pack", "name": "拡張パック", "tcg": "POKEMON", "retail_price": None, "retail_price_basis": "pack", "pack_price": 360},
           {"product_id": "nourl", "name": "n", "tcg": "POKEMON", "retail_price": 1800, "retail_price_basis": "product_unit", "official_url": ""},
           {"product_id": "fake", "name": "f", "tcg": "POKEMON", "retail_price": 7200, "retail_price_basis": "pack",
            "official_url": "https://x/"}]
    m = build_msrp(reg, "2026-10-23T00:00:00+09:00")
    assert [v["product_id"] for v in m["verified"]] == ["box"]
    v = m["verified"][0]
    assert v["official_url"] and v["checked_at"] and v["source"] == "official_product_api" and v["basis"] == "product_unit"
    assert {e["product_id"]: e["reason"] for e in m["excluded"]} == {"pack": "PACK_PRICE_ONLY", "nourl": "NO_OFFICIAL_URL",
                                                                    "fake": "PACK_PRICE_ONLY"}
    assert m["counts"] == {"verified": 1, "excluded": 3, "box_eligible": 1, "carried_over": 0}
    assert "利益の計算には使っていない" in m["note"]


def test_tcg_missing_dates_stay_review_required_without_ocr():
    # 日程の無い告知は日程を推測せず、要確認のまま（画像を読んで日付を確定しない）
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py"))
    assert not re.search(r"pytesseract|easyocr|tesseract|image_to_string", src)
    from src.tcg import freshness as fr
    from src.tcg import models as m
    ev = {"event_type": "REVIEW_REQUIRED", "source_type": "OFFICIAL", "sale_start": None, "application_start": None}
    assert fr.compute_status(ev, NOW_TCG) == m.ST_UNVERIFIED


# ── レビュー・監査の指摘への対応 ───────────────────────────────────────────────────

def test_candidate_id_is_stable_when_best_sell_shop_changes_or_is_missing():
    """最高値の店が日ごとに入れ替わっても、売値が無い日があっても、同じ商品は同じ ID（重複・新規扱いにしない）。"""
    a, st = _build([_off(), _sell(source_id="sA", source_name="店A", price=150000)])
    b, st2 = _build([_off(), _sell(source_id="sB", source_name="店B", price=160000)], prev=st)
    n, st3 = _build([_off()], prev=st2)
    ids = {_first(a)["candidate_id"], _first(b)["candidate_id"], _first(n)["candidate_id"]}
    assert len(ids) == 1 and len(st3) == 1
    assert _first(b)["discovered_at"] == _first(a)["discovered_at"]
    assert _first(b)["source"]["sell"] == "店B"                      # 売る側の店は属性として持つ


def test_rejected_high_price_is_not_chosen_over_a_usable_stale_row():
    """品質の判定で外れた高値（疑わしい価格）ではなく、古いだけの行を調べる価値のある代表にする。"""
    obs = [_off(), _sell(price=200000, source_id="sA", source_name="店A", rejection_reason="suspicious_price"),
           _sell(price=120000, source_id="sB", source_name="店B")]
    c = _first(_build(obs)[0])
    assert c["observed_sell_price"] == 120000 and c["source"]["sell"] == "店B"
    assert rc.SELL_REJECTED not in c["missing_requirements"] and rc.SELL_STALE in c["missing_requirements"]
    only = _first(_build([_off(), _sell(price=200000, rejection_reason="suspicious_price")])[0])
    assert rc.SELL_REJECTED in only["missing_requirements"] and only["confidence"] == "low"       # それしか無いときだけ


def test_stale_only_rows_are_not_labelled_as_quality_rejected():
    c = _first(_build([_off(), _sell()])[0])                          # rejection_reason は stale_over_14d
    assert rc.SELL_STALE in c["missing_requirements"] and rc.SELL_REJECTED not in c["missing_requirements"]


def test_suspicious_spread_never_ranks_above_a_normal_candidate():
    p2 = {"id": "p2", "name": "別", "genre": "camera", "jan": "", "part_numbers": []}
    obs = [_off(), _good_sell(price=130000), _off(product_id="p2"), _good_sell(product_id="p2", price=260000, source_id="s2")]
    ev = {"p1": "CONFIGURED_REFERENCE", "p2": "CONFIGURED_REFERENCE"}
    rep, _ = rc.build(products=PRODUCTS + [p2], observations=obs, msrp_evidence=ev, official_meta={}, verified_pids=set(), now=NOW)
    rows = {c["product_identity"]["product_id"]: c for c in rep["candidates"]}
    assert rc.PRICE_ANOMALY_SUSPECTED in rows["p2"]["missing_requirements"]
    assert rows["p2"]["priority"] == "low" and rows["p2"]["confidence"] == "low"
    assert rows["p1"]["priority_score"] > rows["p2"]["priority_score"]
    queue = [c["product_identity"]["product_id"] for c in rep["candidates"] if c["status"] == rc.RESEARCH_CANDIDATE]
    assert queue[0] == "p1"


def test_verified_status_follows_the_existing_gate_even_without_display_prices():
    """確定の関門を通った商品が、表示用の買値・売値が読めなくても VERIFIED から漏れない。"""
    rep, _ = _build([], verified={"p1"})
    c = _first(rep)
    assert c["status"] == rc.VERIFIED and c["note"] and rep["counts"]["verified"] == 1
    rep2, _ = _build([_off()], verified={"p1"})
    assert _first(rep2)["status"] == rc.VERIFIED
    assert _first(_build([_off()])[0])["status"] == rc.DISCOVERED     # 関門を通っていなければ VERIFIED にならない


def test_catalog_matches_apple_part_numbers_from_official_identity_evidence():
    ident = {"pi": {"model_name": "iPhone", "variant_skus": {"MG674J/A": ("256GB", "Black", 159800)}, "model_number": ""}}
    prods = [{"id": "pi", "name": "iPhone", "genre": "iphone", "jan": "", "part_numbers": []}]     # 商品の登録に部品番号が無い
    matched, un = rc.match_catalog([{"shop": "s", "name": "iPhone 17 256GB MG674J/A", "jan": "", "price": 1, "url": "u"}], prods, ident)
    assert [m["canonical_product_id"] for m in matched] == ["pi"] and un == []
    m2, u2 = rc.match_catalog([{"shop": "s", "name": "iPhone 17 256GB MZZZZJ/A", "jan": "", "price": 1, "url": "u"}], prods, ident)
    assert m2 == [] and len(u2) == 1


def test_catalog_save_keeps_pages_that_were_not_fetched_and_ignores_empty_pages(tmp_path):
    from src.collectors import buyback_kaitori_shouten as ks
    path = tmp_path / "c.json"
    row = lambda page, name, t: {"shop": "kaitori_shouten", "name": name, "jan": "", "price": 10000, "url": f"u-{name}",  # noqa: E731
                                 "page": page, "observed_at": t}
    day1 = NOW.isoformat(timespec="seconds")
    assert rcat.save(path, [row("A", "a1", day1), row("B", "b1", day1)], NOW)
    later = NOW + timedelta(days=1)
    day2 = later.isoformat(timespec="seconds")
    assert rcat.save(path, [row("A", "a2", day2)], later)              # ページ A だけ取れた日
    rows = {r["name"]: r["observed_at"] for r in json.loads(path.read_text(encoding="utf-8"))["rows"]}
    assert set(rows) == {"a2", "b1"} and rows["b1"] == day1 and rows["a2"] == day2    # B は前回のまま・日時も変えない
    ks.CATALOG_ROWS.clear()
    ks.capture_catalog("https://x/p", "<html></html>")                 # 空のページは記録しない
    assert "https://x/p" not in ks.CATALOG_ROWS
    ks.capture_catalog("https://x/p", LIST_HTML)                      # 後の正常な取得は無視されない
    assert "https://x/p" in ks.CATALOG_ROWS
    ks.CATALOG_ROWS.clear()


def test_msrp_ledger_is_not_overwritten_on_a_day_the_registry_is_empty(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("cte_msrp", ROOT / "scripts" / "collect_tcg_events.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
    (tmp_path / "msrp.json").write_text('{"verified": [{"product_id": "keep"}]}', encoding="utf-8")
    mod.build_exports([], [], [], [], mod.empty_lottery_payload("boom"))             # registry が空の日
    assert json.loads((tmp_path / "msrp.json").read_text(encoding="utf-8"))["verified"] == [{"product_id": "keep"}]
    reg = [{"product_id": "box", "name": "BOX", "tcg": "POKEMON", "retail_price": 27500, "retail_price_basis": "product_unit",
            "official_url": "https://www.pokemon-card.com/x/", "box_opportunity_eligible": True}]
    mod.build_exports([], [], [], reg, mod.empty_lottery_payload("boom"))             # 取れた日だけ書き直す
    assert [v["product_id"] for v in json.loads((tmp_path / "msrp.json").read_text(encoding="utf-8"))["verified"]] == ["box"]


def test_sns_sources_are_policy_excluded_not_implementation_candidates():
    from src.tcg.lottery import registry as reg
    d = reg.load_source_candidates()
    assert not any("X" in c["id"].split("_") for c in d["candidates"])
    assert {e["id"] for e in d["policy_excluded"]} >= {"OFFICIAL_X_POKEMON_CARD", "OFFICIAL_X_ONEPIECE_CARD"}
    assert all(e["reason"] for e in d["policy_excluded"])


def test_report_csv_cannot_declare_release_or_review_required():
    from src.tcg import models as m
    from src.tcg import reports
    base = {"tcg": "POKEMON", "product_name": "x", "store_chain": "GEO", "store_name": "s", "prefecture": "東京都",
            "reported_at": "2026-10-23T10:00:00+09:00", "text": "再入荷しました", "source": "community"}
    for declared in ("RELEASE", "REVIEW_REQUIRED"):
        ev = reports._row_to_event(dict(base, event_type=declared))
        assert ev is None or ev.event_type not in m.NEVER_AVAILABLE_NOW_EVENTS, declared      # 明示しても受け付けない
    ev = reports._row_to_event(dict(base, event_type="RESTOCK"))
    assert ev is not None and ev.event_type == "RESTOCK"                                       # 既存の種別は今までどおり


def test_entry_kind_does_not_infer_web_from_default_channel():
    from src.tcg.lottery.schema import entry_kind
    assert entry_kind({"event_type": "LOTTERY", "channel": "ONLINE"}) == "LOTTERY"
    assert entry_kind({"event_type": "LOTTERY", "online_only": True}) == "WEB_LOTTERY"


def test_new_event_types_have_alert_labels():
    src = (ROOT / "src" / "tcg" / "alerts.py").read_text(encoding="utf-8")
    for et in ("STORE_LOTTERY", "APP_LOTTERY", "WEB_LOTTERY", "IN_STORE_QR", "RELEASE", "REVIEW_REQUIRED"):
        assert f'"{et}"' in src


def test_naive_and_aware_datetimes_do_not_crash_the_ledger():
    _, st = _build([_off(), _sell()])
    naive_now = NOW.replace(tzinfo=None) + timedelta(days=2)
    rep, _ = rc.build(products=[], observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=naive_now, prev_state=st)
    assert [c["status"] for c in rep["candidates"]] == [rc.STALE]


def test_discovered_products_count_is_not_double_counted_with_official_discovery():
    rep, _ = _build([_off(), _sell()], discovery={"metrics": {"product_candidates": 39}},
                    catalog=[{"shop": "s", "name": "x", "jan": "", "price": 1, "url": "u", "observed_at": "2026-10-23T11:00:00+09:00"}])
    m = rep["metrics"]
    assert m["discovered_products"] == 1 and m["official_discovery_candidates"] == 39


def test_update_buyback_prices_respects_research_dir():
    src = (ROOT / "scripts" / "update_buyback_prices.py").read_text(encoding="utf-8")
    assert 'environ.get("RESEARCH_PRIVATE_DIR")' in src


def test_priority_label_is_low_for_suspicious_prices_regardless_of_score():
    assert rc._label(100, [rc.PRICE_ANOMALY_SUSPECTED]) == "low" and rc._label(100, [rc.SELL_REJECTED]) == "low"
    assert rc._label(100, []) == "high" and rc._label(40, []) == "medium" and rc._label(5, []) == "low"


# ── 監査・レビュー（公開と非公開の境界）への対応 ───────────────────────────────────────

def test_candidate_id_is_stable_when_cheapest_buy_shop_changes():
    def shop(sid, price):
        return {"product_id": "p1", "price_role": "buy", "price_type": "shop_sale_price", "canonical_price_type": "UNKNOWN",
                "price": price, "source_id": sid, "condition": "new_unopened", "link_type": "item", "is_fresh": True,
                "freshness_basis": "observed", "accessory_flag": False, "wrong_model_flag": False, "is_exact_product_match": True}
    meta = {"p1": {"official_not_sold": True}}
    a, st = _build([_off(), shop("shopA", 90000), _good_sell()], ev="VERIFIED_CURRENT", meta=meta)
    b, st2 = _build([_off(), shop("shopB", 85000), _good_sell()], ev="VERIFIED_CURRENT", meta=meta, prev=st)
    assert _first(a)["candidate_id"] == _first(b)["candidate_id"] and len(st2) == 1
    assert _first(b)["source"]["buy"] == "shopB" and _first(b)["discovered_at"] == _first(a)["discovered_at"]


def test_status_since_tracks_when_the_status_changed_not_when_first_seen():
    rep1, st = _build([_off(price=200000), _good_sell()], ev="VERIFIED_CURRENT")          # 価格差なし = REJECTED
    assert _first(rep1)["status"] == rc.REJECTED
    later = NOW + timedelta(days=5)
    rep2, st2 = rc.build(products=PRODUCTS, observations=[_off(), _sell()], msrp_evidence={"p1": "CONFIGURED_REFERENCE"},
                         official_meta={}, verified_pids=set(), now=later, prev_state=st)
    c = _first(rep2)
    assert c["status"] == rc.RESEARCH_CANDIDATE and c["discovered_at"] == NOW.isoformat(timespec="seconds")
    assert c["status_since"] == later.isoformat(timespec="seconds")                      # 調査候補になった日は discovered_at と別
    rep3, _ = rc.build(products=PRODUCTS, observations=[_off(), _sell()], msrp_evidence={"p1": "CONFIGURED_REFERENCE"},
                       official_meta={}, verified_pids=set(), now=later + timedelta(days=1), prev_state=st2)
    assert _first(rep3)["status_since"] == later.isoformat(timespec="seconds")           # 同じ状態の間は変わらない


@pytest.mark.parametrize("broken", [[], "x", {"a": "str"}, {"a": ["list"]}, {"rc_x": {"last_seen_at": 5, "snapshot": "s"}}, None, 3])
def test_broken_ledger_shapes_do_not_crash_and_are_treated_as_empty(broken):
    rep, st = _build([_off(), _sell()], prev=broken)
    assert len(rep["candidates"]) == 1 and isinstance(st, dict) and rep["ledger_state"] in rc.ALLOWED_LEDGER


def _gen(tmp_path, monkeypatch, *, state_text=None, obs=None):
    """_write_research_candidates を、小さな差し替えで実際に走らせる（公開側・非公開側の書き込みを確かめる）。"""
    from types import SimpleNamespace

    from src.content.daily_lp_generator import DailyLPGenerator
    monkeypatch.setenv("RESEARCH_DIR", str(tmp_path / "pub"))
    monkeypatch.setenv("RESEARCH_PRIVATE_DIR", str(tmp_path / "priv"))
    if state_text is not None:
        (tmp_path / "priv").mkdir(parents=True, exist_ok=True)
        (tmp_path / "priv" / "state.json").write_text(state_text, encoding="utf-8")
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g.repo = SimpleNamespace(list_products=lambda: [SimpleNamespace(id="p1", name="調査用ダミー商品XYZ", genre="camera",
                                                                      jan_code="", is_active=True)])
    g._msrp_evidence = {"p1": "CONFIGURED_REFERENCE"}
    g._official_meta = lambda: {}
    data = {("normalized_price_observations", "latest.json"): {"observations": obs or [_off(), _sell(item_url="https://shop.example/item/1")]}}
    monkeypatch.setattr(DailyLPGenerator, "_load_export_json", staticmethod(lambda *parts: data.get(tuple(parts), {})))
    ctx = SimpleNamespace(now=NOW)
    catalog = SimpleNamespace(opportunity_set=SimpleNamespace(eligible=[]))
    return g, ctx, catalog


def test_generator_writes_detail_only_to_private_and_summary_to_public(tmp_path, monkeypatch):
    g, ctx, catalog = _gen(tmp_path, monkeypatch)
    summ = g._write_research_candidates(ctx, catalog)
    assert summ["type"] == "RESEARCH_SUMMARY" and summ["research_candidate_count"] == 1 and summ["ledger_state"] == "fresh"
    assert sorted(p.name for p in (tmp_path / "pub").iterdir()) == ["summary.json"]
    assert sorted(p.name for p in (tmp_path / "priv").iterdir()) == ["latest.json", "state.json"]
    pub = (tmp_path / "pub" / "summary.json").read_text(encoding="utf-8")
    for leak in ("調査用ダミー商品XYZ", "shop.example", "150000", "rc_"):
        assert leak not in pub, leak
    priv = json.loads((tmp_path / "priv" / "latest.json").read_text(encoding="utf-8"))
    assert priv["candidates"][0]["source_url"]["sell"] == "https://shop.example/item/1"              # 個別の候補は private に残る
    # 2回目は台帳を引き継ぐ（restored・初めて見た日は変わらない）
    summ2 = g._write_research_candidates(ctx, catalog)
    assert summ2["ledger_state"] == "restored"


@pytest.mark.parametrize("state_text", ["{ broken json", '{"candidates": ["not", "a", "dict"]}', "[]", '"str"'])
def test_generator_survives_a_corrupt_ledger_and_reports_it(tmp_path, monkeypatch, state_text):
    g, ctx, catalog = _gen(tmp_path, monkeypatch, state_text=state_text)
    summ = g._write_research_candidates(ctx, catalog)
    assert summ is not None and summ["ledger_state"] == "corrupt" and summ["research_candidate_count"] == 1
    assert json.loads((tmp_path / "priv" / "state.json").read_text(encoding="utf-8"))["candidates"]   # 作り直した


def test_generator_writes_nothing_public_when_summary_would_leak(tmp_path, monkeypatch):
    g, ctx, catalog = _gen(tmp_path, monkeypatch)
    monkeypatch.setattr(rc, "PRIVATE_KEYS", rc.PRIVATE_KEYS | {"reason_counts"})
    assert g._write_research_candidates(ctx, catalog) is None                     # 失敗しても LP は止めない
    assert not (tmp_path / "pub").exists()


def test_public_summary_values_and_nested_dicts_are_allow_listed():
    rep = _report()
    rep["research_reasons"] = {"X100VI 買値130000": 1, rc.SELL_STALE: 2}
    rep["metrics"]["tcg_source_coverage"] = {"configured_sources": 17, "evil": "調査用ダミー商品XYZ", "source_classes": {"WORKING": 5, "x": 1}}
    rep["metrics"]["official_verified_coverage"] = {"verified": 11, "total": 47, "per_product": {"p1": 1}}
    for c in rep["candidates"]:
        c["genre"] = "Fujifilm X100VI 155000円"
        c["confidence"] = "調査用ダミー商品XYZ"
    summ = rc.public_summary(rep)
    assert summ["reason_counts"] == {rc.SELL_STALE: 2}                                     # 既知の語彙だけ
    assert summ["genre_counts"] == {"other": 1} and summ["confidence_counts"] == {}
    assert summ["tcg_source_coverage"] == {"configured_sources": 17, "source_classes": {"WORKING": 5}}
    assert summ["official_verified_coverage"] == {"verified": 11, "total": 47}
    txt = json.dumps(summ, ensure_ascii=False)
    assert "X100VI" not in txt and "調査用ダミー商品XYZ" not in txt and "evil" not in txt and "per_product" not in txt


def test_positive_raw_spread_counts_only_readable_positive_spreads():
    cands = [{"status": rc.VERIFIED, "raw_spread": -500}, {"status": rc.VERIFIED, "raw_spread": None},
             {"status": rc.VERIFIED, "raw_spread": 700}, {"status": rc.RESEARCH_CANDIDATE, "raw_spread": 1000},
             {"status": rc.DISCOVERED, "raw_spread": 50}, {"status": rc.REJECTED, "raw_spread": 100}]
    m = rc.coverage_metrics(products=[], candidates=cands, product_candidates=[], msrp_evidence={}, observations=[])
    assert m["raw_positive_spread"] == 3


def test_stale_catalog_rows_are_not_listed_as_new_discoveries():
    old = {"shop": "s", "name": "古い行", "jan": "", "price": 9, "url": "u1", "observed_at": "2026-08-01T00:00:00+09:00"}
    new = {"shop": "s", "name": "新しい行", "jan": "", "price": 8, "url": "u2", "observed_at": "2026-10-23T11:00:00+09:00"}
    bad = {"shop": "s", "name": "日時なし", "jan": "", "price": 7, "url": "u3", "observed_at": ""}
    assert [d["name"] for d in rc.discovered_products([old, new, bad], NOW)] == ["新しい行"]


def test_msrp_ledger_keeps_previous_rows_for_products_missing_today_without_touching_checked_at():
    from src.tcg.msrp import build_msrp
    prev = {"verified": [{"product_id": "old", "name": "旧", "tcg": "POKEMON", "retail_price": 1200, "checked_at": "2026-10-01T00:00:00+09:00",
                          "official_url": "https://www.pokemon-card.com/o/", "basis": "product_unit"}]}
    today = [{"product_id": "box", "name": "BOX", "tcg": "POKEMON", "retail_price": 27500, "retail_price_basis": "product_unit",
              "official_url": "https://www.pokemon-card.com/x/"}]
    m = build_msrp(today, "2026-10-23T00:00:00+09:00", prev)
    rows = {v["product_id"]: v for v in m["verified"]}
    assert set(rows) == {"box", "old"} and rows["old"]["carried_over"] is True
    assert rows["old"]["checked_at"] == "2026-10-01T00:00:00+09:00" and rows["box"]["checked_at"] == "2026-10-23T00:00:00+09:00"
    assert "carried_over" not in rows["box"]


def test_release_and_review_required_do_not_stay_forever():
    from src.tcg import freshness as fr
    from src.tcg import models as m
    old = _ev("RELEASE", sale_start="2026-08-01T00:00:00+09:00", application_start=None, application_end=None)
    assert fr.is_stale(old, NOW_TCG) is True
    recent = _ev("REVIEW_REQUIRED", sale_start="2026-10-20T00:00:00+09:00", application_start=None, application_end=None)
    assert fr.is_stale(recent, NOW_TCG) is False
    assert fr.compute_status(old, NOW_TCG) != m.ST_AVAILABLE_NOW


def test_docs_do_not_name_research_candidates():
    from scripts import deploy_check as dc
    assert dc._research_doc_name_leaks(ROOT) == []
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "config").mkdir()
        (root / "config" / "products.yaml").write_text("products:\n  - {id: p, name: 'ZZ-Camera 9000', keywords: ['ZZ9000']}\n", encoding="utf-8")
        (root / "internal").mkdir()
        (root / "internal" / "a.md").write_text("調査候補は ZZ-Camera 9000 が3件目\n別の行 ZZ9000\n", encoding="utf-8")
        assert dc._research_doc_name_leaks(root) == ["internal/a.md:1"]               # 調査候補と同じ行の商品名だけ検出


def test_workflow_ledger_is_encrypted_and_keyless_runs_do_not_persist():
    import yaml
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    steps = {st.get("name"): st for st in yaml.safe_load(wf)["jobs"]["update-lp"]["steps"]}
    for n in ("Decrypt research ledger", "Encrypt research ledger"):
        assert "openssl enc" in steps[n]["run"] and "RESEARCH_LEDGER_KEY" in str(steps[n]["env"])
    for n in ("Restore encrypted research ledger", "Decrypt research ledger", "Encrypt research ledger", "Save encrypted research ledger"):
        assert "research_key.outputs.enabled == 'true'" in steps[n]["if"]                # 鍵が無ければ何も引き継がない
    assert str(steps["Save encrypted research ledger"]["if"]).startswith("always()")        # ジョブが失敗した日も保存する
    assert steps["Research ledger key check"]["env"]["K"] == "${{ secrets.RESEARCH_LEDGER_KEY }}"


@pytest.mark.parametrize("broken", [[], "x", {"a": "str"}, {"a": ["list"]}, None, 3])
def test_apply_ledger_itself_tolerates_broken_ledgers(broken):
    cands = [{"candidate_id": "rc_x", "status": rc.RESEARCH_CANDIDATE, "product_identity": {}, "route_type": "r", "source": {}}]
    out, st = rc.apply_ledger(cands, broken, NOW)
    assert [c["candidate_id"] for c in out] == ["rc_x"] and set(st) == {"rc_x"}
    assert rc.sanitize_ledger(broken) == {}                                                       # 形の違う台帳は空として扱う
    assert rc.sanitize_ledger({"ok": {"x": 1}, "bad": "s", "worse": [1]}) == {"ok": {"x": 1}}


def test_stale_row_cannot_be_overwritten_by_ledger_contents():
    prev = {"rc_a": {"last_seen_at": (NOW - timedelta(days=1)).isoformat(), "discovered_at": 5,
                     "snapshot": {"status": "VERIFIED", "candidate_id": "zzz", "genre": "camera", "evil": "x"}}}
    out, _ = rc.apply_ledger([], prev, NOW)
    assert len(out) == 1 and out[0]["candidate_id"] == "rc_a" and out[0]["status"] == rc.STALE   # ID・状態は台帳の値で変わらない
    assert out[0]["discovered_at"] == "" and "evil" not in out[0] and out[0]["genre"] == "camera"


def test_release_and_review_required_without_any_date_basis_are_stale():
    from src.tcg import freshness as fr
    ev = {"event_type": "REVIEW_REQUIRED", "source_type": "OFFICIAL"}
    assert fr.is_stale(ev, NOW_TCG) is True and fr.compute_status(ev, NOW_TCG) != "AVAILABLE_NOW"


def test_positive_spread_breakdown_adds_up_in_summary_and_page():
    cands = [{"status": rc.VERIFIED, "raw_spread": 700}, {"status": rc.VERIFIED, "raw_spread": None},
             {"status": rc.RESEARCH_CANDIDATE, "raw_spread": 1000}, {"status": rc.DISCOVERED, "raw_spread": 50},
             {"status": rc.REJECTED, "raw_spread": -5}]
    m = rc.coverage_metrics(products=[], candidates=cands, product_candidates=[], msrp_evidence={}, observations=[])
    assert (m["raw_positive_spread"], m["verified_positive_spread"], m["suppressed_positive_spread"]) == (3, 1, 2)
    rep = {"candidates": [dict(c, genre="camera", confidence="low") for c in cands], "metrics": m,
           "counts": {"verified": 2}, "research_reasons": {}, "generated_at": "x"}
    summ = rc.public_summary(rep)
    assert summ["positive_raw_spread_count"] == summ["verified_positive_spread_count"] + summ["suppressed_positive_spread_count"]
    from src.content.ui import admin
    html = admin._research({"research": admin.build_research(summ)})
    assert "3件（確定の関門を通過 1件・通過していない 2件）" in html


# ── deploy-check #871 が、境界の退行を本当に検知する（一時のリポジトリで検査を走らせる） ─────────────────

def _tmp_repo(tmp_path):
    import shutil
    import subprocess
    root = tmp_path / "repo"
    for rel in ("src/research", "src/notifiers", "src/content/ui", ".github", "config", "internal", "ops", "exports/research"):
        shutil.copytree(ROOT / rel, root / rel, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "src" / "content").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "src" / "content" / "daily_lp_generator.py", root / "src" / "content" / "daily_lp_generator.py")
    (root / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "update_buyback_prices.py", root / "scripts" / "update_buyback_prices.py")
    shutil.copy(ROOT / ".gitignore", root / ".gitignore")
    (root / "docs").mkdir()
    shutil.copy(ROOT / "docs" / "HANDOFF.md", root / "docs" / "HANDOFF.md")
    shutil.copy(ROOT / "CLAUDE.md", root / "CLAUDE.md")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def _check(root):
    from scripts import deploy_check as dc
    r = dc._check_market_research(root)
    assert len(r) == 1
    return r[0]


def _edit(root, rel, a, b):
    p = root / rel
    t = p.read_text(encoding="utf-8")
    assert a in t, (rel, a)
    p.write_text(t.replace(a, b, 1), encoding="utf-8")


WF = ".github/workflows/daily_lp.yml"


def test_deploy_check_871_passes_on_a_clean_copy(tmp_path):
    r = _check(_tmp_repo(tmp_path))
    assert r["level"] == "ok", r["message"]


@pytest.mark.parametrize("a, b, want", [
    ("          git add docs/ exports/lp/daily/", "          git add --force docs/ exports/lp/daily/", "強制"),
    ("          git add docs/ exports/lp/daily/", "          git add -Af docs/ exports/lp/daily/", "強制"),
    ("          git add docs/ exports/lp/daily/", "          git  add ./.private/research docs/ exports/lp/daily/", ".private"),
    ("                  exports/research/ \\\n", "                  exports/research/ .private/research/ \\\n", ".private"),
    ("          path: .private/ledger.enc\n          key: research-ledger-${{ github.run_id }}-${{ github.run_attempt }}\n          restore-keys: |",
     "          path: .private/*\n          key: research-ledger-${{ github.run_id }}-${{ github.run_attempt }}\n          restore-keys: |", "平文"),
    ("          path: .private/ledger.enc\n          key: research-ledger-${{ github.run_id }}-${{ github.run_attempt }}\n          restore-keys: |",
     "          path: ./.private/research\n          key: research-ledger-${{ github.run_id }}-${{ github.run_attempt }}\n          restore-keys: |", "平文"),
    ("          path: .private/ledger.enc\n          key: research-ledger-${{ github.run_id }}-${{ github.run_attempt }}\n          restore-keys: |",
     "          path: .priv*\n          key: research-ledger-${{ github.run_id }}-${{ github.run_attempt }}\n          restore-keys: |", "平文"),
    ("          path: |\n            exports/debug_camera/", "          path: |\n            .private/\n            exports/debug_camera/", "artifact"),
    ("          path: |\n            exports/debug_camera/", "          path: |\n            ./.private\n            exports/debug_camera/", "artifact"),
    ("          path: |\n            exports/debug_camera/", "          path: |\n            ./\n            exports/debug_camera/", "artifact"),
    ("          path: |\n            exports/debug_camera/", "          path: |\n            exports/**\n            exports/debug_camera/", "artifact"),
    ("          name: camera-playwright-debug\n", "          name: camera-playwright-debug\n          include-hidden-files: true\n", "隠しファイル"),
    ("-pbkdf2 -iter 600000 -salt -in ../ledger.tgz -out ../ledger.enc.tmp -pass env:RESEARCH_LEDGER_KEY",
     "-pbkdf2 -iter 600000 -salt -in ../ledger.tgz -out ../ledger.enc.tmp -k secret", "openssl"),
    ("-pbkdf2 -iter 600000 -salt -in ../ledger.tgz", "-pbkdf2 -iter 1000 -salt -in ../ledger.tgz", "openssl"),
    ("-pbkdf2 -iter 600000 -in .private/ledger.enc", "-pbkdf2 -iter 1000 -in .private/ledger.enc", "openssl"),            # 復号側
    ("-out \"$tmp/ledger.tgz\" -pass env:RESEARCH_LEDGER_KEY", "-out \"$tmp/ledger.tgz\" -k secret", "openssl"),            # 復号側
    ("          set -eo pipefail\n          cd .private/research", "          set -e\n          cd .private/research", "pipefail"),
    ("          set -o pipefail\n          mkdir -p .private/research", "          mkdir -p .private/research", "pipefail"),
    ("      - name: Encrypt research ledger\n        if: always() && steps.research_key.outputs.enabled == 'true'\n        continue-on-error: true\n",
     "      - name: Encrypt research ledger\n        if: always() && steps.research_key.outputs.enabled == 'true'\n", "continue-on-error"),
    ("      - name: Decrypt research ledger\n        if: steps.research_key.outputs.enabled == 'true'\n        continue-on-error: true\n",
     "      - name: Decrypt research ledger\n        if: steps.research_key.outputs.enabled == 'true'\n", "continue-on-error"),
    ("        id: research_key\n        continue-on-error: true\n", "        id: research_key\n", "continue-on-error"),
    ('if [ "${#K}" -ge 32 ]; then', 'if [ -n "$K" ]; then', "鍵の長さ"),
])
def test_deploy_check_871_detects_workflow_regressions(tmp_path, a, b, want):
    root = _tmp_repo(tmp_path)
    _edit(root, WF, a, b)
    r = _check(root)
    assert r["level"] == "error" and want in r["message"], r["message"]


def test_deploy_check_871_detects_gitignore_regression(tmp_path):
    root = _tmp_repo(tmp_path)
    _edit(root, ".gitignore", "\n.private/\n", "\n# .private/\n")                    # コメントにしても ignore されない
    r = _check(root)
    assert r["level"] == "error" and ".private" in r["message"]


def test_deploy_check_871_detects_public_leaks(tmp_path):
    root = _tmp_repo(tmp_path)
    (root / "exports" / "research" / "latest.json").write_text("{}", encoding="utf-8")              # 公開の置き場に集計以外
    assert _check(root)["level"] == "error"
    (root / "exports" / "research" / "latest.json").unlink()
    (root / "exports" / "research" / "summary.json").write_text('{"x": "rc_0123456789ab"}', encoding="utf-8")
    assert _check(root)["level"] == "error"
    (root / "exports" / "research" / "summary.json").write_text('{"type": "RESEARCH_SUMMARY", "labels": 3}', encoding="utf-8")
    assert _check(root)["level"] == "ok"
    for leak in ('<td>iPhone 17 Pro 256GB</td>', '<td>¥150,000</td>', '<td>+¥50,000</td>'):          # 商品名だけ・価格だけ・価格差だけ
        (root / "docs" / "index.html").write_text(
            f'<div data-nu-ad-panel="research">{leak}</div><div data-nu-ad-panel="x">', encoding="utf-8")
        r = _check(root)
        assert r["level"] == "error" and "docs" in r["message"], leak
    (root / "docs" / "index.html").write_text('<div data-nu-ad-panel="research"><dd>3件</dd></div>', encoding="utf-8")
    assert _check(root)["level"] == "ok"


def test_doc_name_check_is_item_scoped_and_fail_closed(tmp_path):
    from scripts import deploy_check as dc
    root = tmp_path
    (root / "config").mkdir()
    (root / "internal").mkdir()
    (root / "config" / "products.yaml").write_text("products:\n  - {id: p, name: 'ZZ-Camera 9000', keywords: ['ZZ9000']}\n", encoding="utf-8")
    (root / "internal" / "a.md").write_text(
        "- 調査候補の件数は3件\n  折り返しの続き ZZ9000 が候補\n- 別の項目 ZZ-Camera 9000 の話（無関係）\n", encoding="utf-8")
    assert dc._research_doc_name_leaks(root) == ["internal/a.md:1"]               # 同じ項目の続き行は検出・次の項目は対象外
    (root / "internal" / "a.md").write_text("- 調査候補の件数\n- ZZ-Camera 9000 の別の話\n", encoding="utf-8")
    assert dc._research_doc_name_leaks(root) == []
    (root / "config" / "products.yaml").write_text(":::broken", encoding="utf-8")
    assert dc._research_doc_name_leaks(root) != []                                  # 読めないときは通さない


@pytest.mark.skipif(__import__("shutil").which("openssl") is None or __import__("shutil").which("tar") is None, reason="openssl / tar が無い")
def test_ledger_decrypt_step_rejects_bad_archives_and_keeps_good_ones(tmp_path):
    """ワークフローの復号 step のシェルを実際に動かす（正常・余計なファイル・シンボリックリンク・鍵の違い・壊れたファイル）。"""
    import os
    import subprocess

    import yaml
    steps = {st.get("name"): st for st in yaml.safe_load((ROOT / WF).read_text(encoding="utf-8"))["jobs"]["update-lp"]["steps"]}
    dec, enc = steps["Decrypt research ledger"]["run"], steps["Encrypt research ledger"]["run"]
    key = "test-key-0123456789abcdefghijklmnopqrstuv"

    def run(script, cwd, k=key):
        return subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env={**os.environ, "RESEARCH_LEDGER_KEY": k},
                              capture_output=True, text=True)

    def fresh(name):
        w = tmp_path / name
        (w / ".private" / "research").mkdir(parents=True)
        return w

    w = fresh("good")                                                                     # 正常: 暗号化 → 復号で元に戻る
    (w / ".private/research/state.json").write_text('{"candidates": {"a": {}}}', encoding="utf-8")
    (w / ".private/research/latest.json").write_text("{}", encoding="utf-8")
    assert run(enc, w).returncode == 0 and (w / ".private/ledger.enc").exists()
    subprocess.run(["rm", "-rf", str(w / ".private/research")])
    r = run(dec, w)
    assert r.returncode == 0 and json.loads((w / ".private/research/state.json").read_text())["candidates"] == {"a": {}}

    def corrupt_marker(w):
        return (w / ".private/research/state.json").read_text() == '{"corrupt": true}\n' and \
            sorted(p.name for p in (w / ".private/research").iterdir()) == ["state.json"]

    w = fresh("extra")                                                                   # 余計なファイルを含む → 展開しない
    x = tmp_path / "x"
    x.mkdir()
    (x / "evil.sh").write_text("evil", encoding="utf-8")
    (x / "state.json").write_text("{}", encoding="utf-8")
    subprocess.run(["tar", "-czf", str(tmp_path / "x.tgz"), "-C", str(x), "."], check=True)
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "600000", "-salt", "-in", str(tmp_path / "x.tgz"),
                    "-out", str(w / ".private/ledger.enc"), "-pass", f"pass:{key}"], check=True, capture_output=True)
    subprocess.run(["rm", "-rf", str(w / ".private/research")])
    assert run(dec, w).returncode == 0 and corrupt_marker(w) and not (w / ".private/research/evil.sh").exists()

    w = fresh("link")                                                                    # シンボリックリンク → 展開しない
    y = tmp_path / "y"
    y.mkdir()
    os.symlink("/etc/passwd", y / "state.json")
    subprocess.run(["tar", "-czf", str(tmp_path / "y.tgz"), "-C", str(y), "."], check=True)
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "600000", "-salt", "-in", str(tmp_path / "y.tgz"),
                    "-out", str(w / ".private/ledger.enc"), "-pass", f"pass:{key}"], check=True, capture_output=True)
    subprocess.run(["rm", "-rf", str(w / ".private/research")])
    assert run(dec, w).returncode == 0 and corrupt_marker(w)

    w = fresh("wrongkey")                                                                # 鍵が違う
    (w / ".private/research/state.json").write_text("{}", encoding="utf-8")
    assert run(enc, w).returncode == 0
    subprocess.run(["rm", "-rf", str(w / ".private/research")])
    assert run(dec, w, k="another-key-0123456789abcdefghijklmnop").returncode == 0 and corrupt_marker(w)

    w = fresh("garbage")                                                                 # 壊れたファイル
    (w / ".private/ledger.enc").write_bytes(os.urandom(300))
    assert run(dec, w).returncode == 0 and corrupt_marker(w)

    w = fresh("nofile")                                                                  # 台帳が無い（初回）→ 何も作らない
    assert run(dec, w).returncode == 0 and list((w / ".private/research").iterdir()) == []


@pytest.mark.skipif(__import__("shutil").which("openssl") is None or __import__("shutil").which("tar") is None, reason="openssl / tar が無い")
def test_ledger_encrypt_step_packs_only_allowed_files_and_never_leaves_a_partial_archive(tmp_path):
    import os
    import subprocess

    import yaml
    steps = {st.get("name"): st for st in yaml.safe_load((ROOT / WF).read_text(encoding="utf-8"))["jobs"]["update-lp"]["steps"]}
    enc, dec = steps["Encrypt research ledger"]["run"], steps["Decrypt research ledger"]["run"]
    key = "test-key-0123456789abcdefghijklmnopqrstuv"
    env = {**os.environ, "RESEARCH_LEDGER_KEY": key}

    def run(script, cwd, e=env):
        return subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env=e, capture_output=True, text=True)

    w = tmp_path / "w"
    (w / ".private" / "research").mkdir(parents=True)
    (w / ".private/research/state.json").write_text('{"candidates": {"a": {}}}', encoding="utf-8")
    (w / ".private/research/state.json.tmp").write_text("partial", encoding="utf-8")            # 書きかけの一時ファイル
    (w / ".private/research/other.txt").write_text("x", encoding="utf-8")                      # 許可していないファイル
    assert run(enc, w).returncode == 0
    names = subprocess.run(["tar", "-tzf", "-"], input=subprocess.run(
        ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "600000", "-in", str(w / ".private/ledger.enc"),
         "-pass", f"pass:{key}"], capture_output=True).stdout, capture_output=True).stdout.decode().split()
    assert sorted(n.lstrip("./") for n in names) == ["state.json"]                              # 許可した名前だけが入る
    assert not (w / ".private/ledger.enc.tmp").exists() and not (w / ".private/ledger.tgz").exists()
    subprocess.run(["rm", "-rf", str(w / ".private/research")])
    (w / ".private/research").mkdir()
    assert run(dec, w).returncode == 0                                                         # 往復できる（corrupt にならない）
    assert json.loads((w / ".private/research/state.json").read_text())["candidates"] == {"a": {}}
    # 梱包するものが無い日・置き場が無い日は何もしない（失敗にしない）
    e = tmp_path / "empty"
    (e / ".private" / "research").mkdir(parents=True)
    assert run(enc, e).returncode == 0 and not (e / ".private/ledger.enc").exists()
    (tmp_path / "w2").mkdir()
    assert run(enc, tmp_path / "w2").returncode == 0 and not (tmp_path / "w2" / ".private").exists()   # 置き場が無い日
    # 通常ファイルとディレクトリ以外（FIFO）を含む台帳は展開しない
    f = tmp_path / "fifo"
    (f / ".private" / "research").mkdir(parents=True)
    x = tmp_path / "xf"
    x.mkdir()
    os.mkfifo(x / "state.json")
    subprocess.run(["tar", "-czf", str(tmp_path / "xf.tgz"), "-C", str(x), "."], check=True)
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "600000", "-salt", "-in", str(tmp_path / "xf.tgz"),
                    "-out", str(f / ".private/ledger.enc"), "-pass", f"pass:{key}"], check=True, capture_output=True)
    assert run(dec, f).returncode == 0
    assert (f / ".private/research/state.json").read_text() == '{"corrupt": true}\n'


def test_key_check_step_requires_a_long_key():
    import subprocess

    import yaml
    st = {s_.get("name"): s_ for s_ in yaml.safe_load((ROOT / WF).read_text(encoding="utf-8"))["jobs"]["update-lp"]["steps"]}
    run = st["Research ledger key check"]["run"]

    def go(k):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            out.write_text("", encoding="utf-8")
            subprocess.run(["bash", "-e", "-c", run], env={**os.environ, "K": k, "GITHUB_OUTPUT": str(out)}, capture_output=True)
            return out.read_text(encoding="utf-8").strip()
    assert go("") == "enabled=false" and go("short-key") == "enabled=false" and go("x" * 31) == "enabled=false"
    assert go("y" * 32) == "enabled=true" and go("z" * 64) == "enabled=true"
