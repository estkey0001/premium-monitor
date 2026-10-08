"""Phase 16（判断待ちの商品と公式直販価格）のテスト。

希望小売価格（定価・MSRP）と公式直販価格（OFFICIAL_DIRECT）を分け、オープン価格に架空の希望小売価格を作らない。
公式直販価格は、同一性・容量・ボディー/キット・版・購入ページ・送料・販売の形・在庫の表し方・確認日がそろうときだけ
確定の仕入れ値に使う。JAN が一致してもセット・版・限定品が違えば同じ商品にしない。quality_checker は存在しない
テーブル名を引かない。各テストには、誤りを入れると失敗する否定対照も付ける。
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
TODAY = "2026-10-09"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


AUDIT = _load("p16_audit", ROOT / "scripts" / "audit_official_sources.py")
RECHECK = _load("p16_recheck", ROOT / "scripts" / "recheck_official.py")
DC = _load("p16_deploy_check", ROOT / "scripts" / "deploy_check.py")
PRODUCTS = {p["id"]: p for p in yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))["products"]}
CAMERAS = ("prod_x100vi", "prod_z8", "prod_r5ii")


@pytest.fixture(autouse=True)
def _audit_now(monkeypatch):
    monkeypatch.setattr(AUDIT, "NOW", datetime(2026, 10, 9, 12, 30, tzinfo=JST))


@pytest.fixture
def reg():
    """登録表（テストの中で書き換えても元に戻す）。"""
    from src.market import official_registry as r
    from src.market import official_shipping as osh
    saved = (copy.deepcopy(r.OFFICIAL_DIRECT_OFFERS), copy.deepcopy(r.VERIFIED_URLS),
             copy.deepcopy(osh.PRODUCT_SHIPPING))
    yield r
    r.OFFICIAL_DIRECT_OFFERS.clear(); r.OFFICIAL_DIRECT_OFFERS.update(saved[0])      # noqa: E702
    r.VERIFIED_URLS.clear(); r.VERIFIED_URLS.update(saved[1])                        # noqa: E702
    osh.PRODUCT_SHIPPING.clear(); osh.PRODUCT_SHIPPING.update(saved[2])              # noqa: E702


def _gate(reg, pid, product=None):
    return reg.official_direct_gate(pid, PRODUCTS[pid] if product is None else product, TODAY)


def _dc(name: str) -> dict:
    return {r["check"]: r for r in DC._check_phase16_official_direct()}[name]


# ── 価格の意味（MSRP と公式直販価格を分ける・オープン価格に希望小売価格を作らない） ─────────────

def test_msrp_and_official_direct_are_separate(reg):
    assert reg.price_kind_of("prod_ps5_pro") == "msrp" and reg.price_kind_of("prod_switch2") == "msrp"
    assert reg.price_kind_of("prod_gr4", "src_ricoh_imaging") == "msrp"          # 公式ストアが「定価」と明記
    for pid in CAMERAS + ("prod_iphone17_256", "prod_airpods_pro3"):
        assert reg.price_kind_of(pid) == "official_direct", pid
    assert "定価" not in reg.PRICE_KIND_LABELS["official_direct"]
    # 正本の種別（price_types）を再利用する（新しい種別を増やさない）
    from src.market import price_types as pt
    assert {v[0] for v in reg.PRICE_SEMANTICS.values()} <= set(pt.ALL_PRICE_TYPES)


def test_open_price_has_no_msrp(reg):
    for pid in CAMERAS:
        assert reg.MSRP_OF[pid] == "open_price"
        assert reg.VERIFIED_URLS[pid]["price_kind"] != "msrp"
    assert _dc("price_semantics")["level"] == "ok"


def test_mutation_official_direct_to_msrp_is_detected(reg):
    reg.VERIFIED_URLS["prod_z8"]["price_kind"] = "msrp"
    assert _dc("price_semantics")["level"] == "error"
    assert not _gate(reg, "prod_z8")[0]                     # 公式直販価格として扱わない


def test_product_detail_says_official_direct_not_teika():
    from src.content.ui.product_detail import PriceRow
    from src.market import price_types as pt
    row = PriceRow(role="buy", source="x", price=1, price_type=pt.RETAIL, quality="VERIFIED", official=True,
                   retail_kind="official_direct")
    assert row.type_label == "公式直販価格"
    row.retail_kind = "msrp"
    assert row.type_label == "定価"


def test_deal_label_is_official_direct_for_cameras():
    from src.content.ui import opportunity as opp
    v = opp.from_deal({"product_id": "prod_r5ii", "official_price": 654500, "sell_price": 1, "net_profit": 0,
                       "msrp_evidence": "VERIFIED_CURRENT"})
    assert v.buy_price_label == "公式直販価格"
    # 確認済みの根拠が無い値（再確認で外れた後の設定値 590,000円など）は公式直販価格と呼ばない（監査 M-1）
    v = opp.from_deal({"product_id": "prod_z8", "official_price": 590000, "sell_price": 1, "net_profit": 0,
                       "msrp_evidence": "CONFIGURED_REFERENCE"})
    assert v.buy_price_label == "参考価格"
    from src.market.official_registry import official_price_label
    assert official_price_label("prod_z8", 575300) == "公式直販価格" and official_price_label("prod_z8", 590000) == "参考価格"
    assert official_price_label("prod_ps5_pro", 137980) == "定価"
    assert official_price_label("prod_z8", None) == "参考価格"                     # 価格が無ければ参考（再監査 Low-3）
    v = opp.from_deal({"product_id": "prod_ps5_pro", "official_price": 137980, "sell_price": 1, "net_profit": 0})
    assert v.buy_price_label == "定価"


# ── 公式直販価格の判定 ────────────────────────────────────────────────────

@pytest.mark.parametrize("pid", CAMERAS + ("prod_iphone17_256", "prod_airpods_pro3"))
def test_official_direct_exact_identity_passes(reg, pid):
    ok, why = _gate(reg, pid)
    assert ok, why


def test_camera_identity_is_confirmed_by_official_model_and_jan(reg):
    assert reg.identity_state(PRODUCTS["prod_z8"])[0] == "IDENTITY_CONFIRMED"
    assert PRODUCTS["prod_z8"]["jan_code"] == reg.IDENTITY_EVIDENCE["prod_z8"]["jan_code"] == "4960759909947"
    assert PRODUCTS["prod_r5ii"]["jan_code"] == reg.IDENTITY_EVIDENCE["prod_r5ii"]["jan_code"] == "4549292229141"
    assert reg.identity_state(PRODUCTS["prod_x100vi"])[0] == "IDENTITY_CONFIRMED"
    # X100VI は色ごとに JAN が別（色を区別しない商品なので JAN を登録しない。型番で確認）
    assert not PRODUCTS["prod_x100vi"].get("jan_code")


@pytest.mark.parametrize("change,reason", [
    ({"jan_code": "4549292000000"}, "jan_mismatch"),                       # 別の JAN
    ({"model_number": "EOS R6 Mark II"}, "model_mismatch"),                 # 別の型番
    ({"model_number": "", "jan_code": ""}, "identity_not_confirmed"),       # 商品名だけ
    ({"name": "Canon EOS R5 Mark II RF24-105L レンズキット"}, "body_kit_mismatch"),   # キットの商品にボディーの価格
    ({"name": "Canon EOS R5 Mark II 256GB"}, "capacity_mismatch"),
])
def test_wrong_identity_kit_capacity_rejected(reg, change, reason):
    ok, why = _gate(reg, "prod_r5ii", dict(PRODUCTS["prod_r5ii"], **change))
    assert not ok and reason in why


@pytest.mark.parametrize("change,reason", [
    ({"body_kit": "kit"}, "body_kit_mismatch"),                               # mutation: body → kit
    ({"edition": "海外版"}, "edition_unknown"),
    ({"sale_mode": "LOTTERY"}, "sale_mode_not_purchasable"),
    ({"sale_mode": "ENDED"}, "sale_mode_not_purchasable"),
    ({"stock": "AVAILABLE"}, "stock_semantics_unknown"),
    ({"stock_semantics": ""}, "stock_semantics_unknown"),
    ({"checked_on": "2026-10-20"}, "verified_at_in_future"),
    ({"checked_on": ""}, "no_verified_at"),
    ({"price": 600000}, "no_current_price"),                                # 記録と違う価格
    ({"url": "https://kakaku.com/item/K0001"}, "not_official_shop"),         # 第三者の価格を公式にしない
    ({"rejected": ["会員限定の特価"]}, "rejected:会員限定の特価"),
])
def test_missing_evidence_makes_reference(reg, change, reason):
    reg.OFFICIAL_DIRECT_OFFERS["prod_r5ii"] = dict(reg.OFFICIAL_DIRECT_OFFERS["prod_r5ii"], **change)
    ok, why = _gate(reg, "prod_r5ii")
    assert not ok and reason in why


def test_shipping_required_not_zero(reg):
    """送料が分からなければ使わない（0円とみなさない。mutation: shipping unknown → 0）。"""
    from src.market import official_shipping as osh
    osh.PRODUCT_SHIPPING.pop("prod_z8")
    ok, why = _gate(reg, "prod_z8")
    assert not ok and "shipping_unknown" in why
    assert osh.purchase_shipping("prod_z8", reg.VERIFIED_URLS["prod_z8"]["url"], 575300)["fee"] is None


def test_shipping_records_are_conservative(reg):
    from src.market import official_shipping as osh
    # ニコンダイレクトは会員のログイン時だけ無料。会員の前提を置かず 550円で計算する
    assert osh.purchase_shipping("prod_z8")["fee"] == 550
    assert osh.purchase_shipping("prod_r5ii")["fee"] == 0 and osh.purchase_shipping("prod_x100vi")["fee"] == 0


def test_no_automatic_promotion_without_evidence(reg):
    """公式ストアに価格があるだけでは確定にしない（証拠の無い公式直販価格は参考）。"""
    reg.VERIFIED_URLS["prod_zf"] = {"source": "src_nikon_direct", "url": "https://nij.nikon.com/shop/g/g4960759906908/",
                                    "link_type": "item", "price": 290000, "conf": "high", "checked_on": "2026-10-08",
                                    "price_kind": "official_direct"}
    ok, why = _gate(reg, "prod_zf")
    assert not ok and why == ("no_official_direct_evidence",)


def test_register_verified_writes_price_only_when_gate_passes(reg, tmp_path):
    c = _seeded(tmp_path)
    rows = {r["id"]: dict(r) for r in c.execute("SELECT id, official_price, official_price_updated_at FROM products")}
    for pid in CAMERAS:
        assert rows[pid]["official_price"] == reg.VERIFIED_URLS[pid]["price"]
        assert rows[pid]["official_price_updated_at"] == "2026-10-08"       # 確認日（実行日ではない）
    # 判定を通らない（キット）にすると価格を書かない
    reg.OFFICIAL_DIRECT_OFFERS["prod_r5ii"]["body_kit"] = "kit"
    reg_rows = AUDIT.register_verified(c, AUDIT._products(c))
    r5 = next(r for r in reg_rows if r["product_id"] == "prod_r5ii")
    assert r5["official_price"] is None and r5["official_direct_eligible"] is False
    assert str(r5["price_rejection"]).startswith("official_direct_gate:")
    assert c.execute("SELECT official_price FROM products WHERE id='prod_r5ii'").fetchone()[0] is None


# ── 在庫（今すぐ行動できるのは在庫ありの明示があるときだけ） ──────────────────────────

def test_stock_required_for_actionable():
    from src.content.ui import opportunity as opp
    from src.market.opportunity_diagnostics import ACTIONABLE_AVAILABILITY
    kw = {"kind": "official_to_buyback", "category": "camera", "product_name": "x"}
    unknown = opp.OpportunityView(id="x", product_id="prod_z8", buy_stock="UNKNOWN", **kw)
    assert unknown.availability not in ACTIONABLE_AVAILABILITY                # 在庫未確認は数えない
    out = opp.OpportunityView(id="y", product_id="prod_x100vi", buy_stock="OUT_OF_STOCK", **kw)
    assert out.availability not in ACTIONABLE_AVAILABILITY
    ok = opp.OpportunityView(id="z", product_id="prod_r5ii", buy_stock="IN_STOCK", **kw)
    assert ok.availability in ACTIONABLE_AVAILABILITY


def test_mutation_stock_unknown_to_available_is_detected(monkeypatch):
    from src.content.ui import opportunity as opp
    assert opp.stock_from("", "") != "IN_STOCK"                 # Z8 は在庫の記録が無い（在庫未確認）
    monkeypatch.setattr(opp, "stock_from", lambda s, m: "IN_STOCK")
    assert _dc("official_direct_safety")["level"] == "error"


def test_camera_stock_records(reg):
    from src.market.stock_state import stock_state
    assert stock_state(reg.VERIFIED_URLS["prod_r5ii"]["stock"], "") == "IN_STOCK"      # カートに入れる（押せる）
    assert stock_state(reg.VERIFIED_URLS["prod_x100vi"]["stock"], "") == "OUT_OF_STOCK"
    assert "stock" not in reg.VERIFIED_URLS["prod_z8"]                                  # 在庫の欄が空 → 記録しない
    assert AUDIT._stock_record_is_current(reg.VERIFIED_URLS["prod_r5ii"]["stock_checked_at"],
                                          datetime(2026, 10, 9, 12, 0, tzinfo=JST))
    assert not AUDIT._stock_record_is_current(reg.VERIFIED_URLS["prod_r5ii"]["stock_checked_at"],
                                              datetime(2026, 10, 16, 12, 0, tzinfo=JST))  # 7日を過ぎたら書かない


def test_sale_ended_is_excluded(reg):
    for pid in ("prod_gr3", "prod_switch2_mk", "prod_ps5_de"):
        assert pid not in reg.VERIFIED_URLS and pid not in reg.OFFICIAL_DIRECT_OFFERS
    reg.OFFICIAL_DIRECT_OFFERS["prod_gr3"] = dict(reg.OFFICIAL_DIRECT_OFFERS["prod_r5ii"])
    assert not reg.official_direct_gate("prod_gr3", PRODUCTS["prod_gr3"], TODAY)[0]


# ── カメラ（RICOH の版を混ぜない） ──────────────────────────────────────────

def test_ricoh_variants_are_distinct(reg):
    codes = {pid: reg.IDENTITY_EVIDENCE[pid]["model_number"] for pid in ("prod_gr4", "prod_gr4_hdf", "prod_gr4_mono")}
    assert codes == {"prod_gr4": "S0001551", "prod_gr4_hdf": "S0001566", "prod_gr4_mono": "S0001580"}
    assert "S0001522" not in codes.values()                  # 30周年記念キットは別の商品
    for pid, code in codes.items():
        assert PRODUCTS[pid]["model_number"] == code and reg.identity_state(PRODUCTS[pid])[0] == "IDENTITY_CONFIRMED"
    # RICOH の公式ストアは「定価」と明記（抽選販売）。公式直販価格の判定には入れない
    assert all(pid not in reg.OFFICIAL_DIRECT_OFFERS for pid in codes)


def test_ricoh_collector_picks_card_by_code():
    """GR IV の商品コードを登録したので、30周年記念キットのカードと取り違えない。"""
    from src.collectors.official.ricoh import RicohOfficialCollector
    html = "".join(
        f'<div class="product__item--detail"><a href="/Form/Product/ProductDetail.aspx?shop=0&pid={c}">{n}</a>'
        f'<span class="product__price--numeric">¥{p:,}</span><span class="product__status-text">SOLD OUT</span></div>'
        for c, n, p in (("S0001522", "RICOH GR IV 30th Anniversary Edition Kit【1年保証】", 259800),
                        ("S0001551", "RICOH GR IV【1年保証】", 211800),
                        ("S0001566", "RICOH GR IV HDF【1年保証】", 222000)))
    col = RicohOfficialCollector.__new__(RicohOfficialCollector)
    prod = SimpleNamespace(**PRODUCTS["prod_gr4"])
    r = col._parse(html, prod, "https://ricohimagingstore.com/x")
    assert r["price"] == 211800 and r["raw"]["matched_card"]["product_code"] == "S0001551"


def test_camera_table_has_required_fields(reg):
    rows = {r["product_id"]: r for r in reg.official_direct_audit(list(PRODUCTS.values()), TODAY)}
    for pid in CAMERAS:
        r = rows[pid]
        assert r["eligible"] and r["msrp"] == "open_price" and r["price"] == reg.VERIFIED_URLS[pid]["price"]
        assert r["url"].startswith("https://") and r["verified_at"] == "2026-10-08"
        assert r["shipping_fee"] is not None and r["stock"] in ("IN_STOCK", "OUT_OF_STOCK", "UNKNOWN")
    assert rows["prod_x100vi"]["stock"] == "OUT_OF_STOCK" and rows["prod_z8"]["stock"] == "UNKNOWN"


# ── 判断待ちの3商品 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("pid,min_candidates", [("prod_ps5_de", 3), ("prod_xbox_sx", 3), ("prod_switch2_mk", 2)])
def test_ambiguous_products_stay_needs_user_decision(reg, pid, min_candidates):
    assert reg.identity_state(PRODUCTS[pid])[0] == "NEEDS_USER_DECISION"
    assert len(reg.USER_DECISIONS[pid]["candidates"]) >= min_candidates
    assert not PRODUCTS[pid].get("model_number") and not PRODUCTS[pid].get("jan_code")    # 推測で登録しない
    assert not reg.official_direct_gate(pid, PRODUCTS[pid], TODAY)[0]


def test_switch2_bundle_stays_separate_from_single():
    from src.collectors.buyback_kaitori_shouten import match_rows
    for row in ("Nintendo Switch 2 マリオカート ワールドセット 日本語・国内専用",
                "Nintendo Switch 2（日本語・国内専用）選べるソフト セット"):
        assert not match_rows([(row, 60000, "https://www.kaitorishouten-co.jp/products/detail/1")], "switch2")


# ── JAN とセット（楽天・Yahoo を戻したとき用） ──────────────────────────────────

def _resolver():
    from src.market.product_identity_resolver import ProductIdentityResolver
    return ProductIdentityResolver({"prod_switch2": {"name": "Nintendo Switch 2", "jan_code": "4902370553024"},
                                    "prod_r5ii": {"name": "Canon EOS R5 Mark II", "jan_code": "4549292229141",
                                                  "model_number": "EOS R5 Mark II"}})


@pytest.mark.parametrize("title,pid,jan,conflict", [
    ("Nintendo Switch 2 マリオカート ワールド セット", "prod_switch2", "4902370553024", "bundle_mismatch"),
    ("Nintendo Switch 2 本体 多言語対応", "prod_switch2", "4902370553024", "edition_mismatch"),
    ("【海外版】Nintendo Switch 2", "prod_switch2", "4902370553024", "edition_mismatch"),
    ("Nintendo Switch 2 選べるソフト セット", "prod_switch2", "4902370553024", "bundle_mismatch"),
    ("Canon EOS R5 Mark II RF24-105L IS USM レンズキット", "prod_r5ii", "4549292229141", "bundle_mismatch"),
    ("Canon EOS R5 Mark II 限定モデル", "prod_r5ii", "4549292229141", "limited_mismatch"),
])
def test_jan_exact_with_bundle_or_edition_mismatch_is_rejected(title, pid, jan, conflict):
    r = _resolver().resolve(source_title=title, jan=jan, link_type="item", expected_product_id=pid)
    assert r.identity_confidence == "low" and r.variant_conflict == conflict


def test_jan_exact_single_item_stays_high():
    r = _resolver().resolve(source_title="Nintendo Switch 2 本体", jan="4902370553024", link_type="item",
                            expected_product_id="prod_switch2")
    assert r.identity_confidence == "high" and r.variant_conflict is None


def test_marketplace_reenable_rejects_bundle_listing(monkeypatch):
    """楽天・Yahoo を有効にしても、JAN が一致するセットの出品を単体の相場に入れない。"""
    api = _load("p16_api", ROOT / "scripts" / "collect_api_prices.py")
    items = [{"title": "Nintendo Switch 2 本体", "jan": "4902370553024", "listed_price": 60000, "url": "https://x/1"},
             {"title": "Nintendo Switch 2 マリオカート ワールド セット", "jan": "4902370553024",
              "listed_price": 70000, "url": "https://x/2"}]
    monkeypatch.setattr(api, "kill_switch_on", lambda a: False)
    monkeypatch.setattr(api, "is_configured", lambda a: True)
    monkeypatch.setitem(api.market_apis.FETCHERS, "rakuten", lambda kw, **k: [dict(i) for i in items])
    res = api.collect_for_api("rakuten", {"prod_switch2": {"name": "Nintendo Switch 2", "keywords": ["Switch 2"]}},
                              _resolver(), ["prod_switch2"], dry_run=True)
    titles = [o["extracted_title"] for o in res["observations"]]
    assert titles == ["Nintendo Switch 2 本体"] and res["health"]["rejected"] == 1


def test_mutation_jan_overrides_bundle_is_detected(monkeypatch):
    from src.market import product_identity_resolver as pir
    monkeypatch.setattr(pir, "variant_conflict", lambda s, p: None)
    assert _dc("bundle_jan_safety")["level"] == "error"


# ── quality_checker（存在しないテーブル名） ─────────────────────────────────────

def _qc_db(with_url: bool):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE product_source_config (product_id TEXT, source_id TEXT, target_url TEXT, extra_config TEXT)")
    if with_url:
        c.execute("INSERT INTO product_source_config VALUES ('p1','src_x','https://example.jp/item',"
                  "'{\"verified\": true, \"link_type\": \"item\"}')")
    return SimpleNamespace(db=SimpleNamespace(connection=c))


def _beginner_issues(repo):
    from src.pipeline.quality_checker import QualityChecker
    qc = QualityChecker(repository=repo)
    fake = SimpleNamespace(id="s1", product_id="p1", product_name="X", user_level="beginner_easy",
                           official_price_jpy=1000, domestic_buyback_price_jpy=10000, sale_method="normal",
                           difficulty_score=0.1)

    class _Conn:
        def __init__(self, real):
            self.real = real

        def execute(self, sql, params=()):
            if "market_snapshots" in sql:
                return SimpleNamespace(fetchall=lambda: [fake.__dict__])
            return self.real.execute(sql, params)
    qc.db = SimpleNamespace(connection=_Conn(repo.db.connection))
    import src.models.market_snapshot as ms
    orig = ms.MarketSnapshotModel
    ms.MarketSnapshotModel = lambda **kw: SimpleNamespace(**kw)
    try:
        return qc.check_beginner_quality()[0]
    finally:
        ms.MarketSnapshotModel = orig


def test_quality_checker_reads_real_table():
    import inspect

    from src.pipeline import quality_checker as qc
    src = inspect.getsource(qc.QualityChecker.check_beginner_quality)
    assert "FROM product_source_configs" not in src and "verified_official_item_url" in src
    # 確認済みの購入ページがあれば問題にしない・無ければ「公式購入URLが未設定」（以前は一度も働かなかった）
    assert "公式購入URLが未設定" not in _beginner_issues(_qc_db(True))["issues"]
    assert "公式購入URLが未設定" in _beginner_issues(_qc_db(False))["issues"]


def test_quality_checker_no_false_downgrade():
    """URL の無いことだけでは降格しない（降格は問題が2つ以上）。表を読めないときは問題に数えない。"""
    r = _beginner_issues(_qc_db(False))
    assert r["issues"] == ["公式購入URLが未設定"] and r["should_downgrade"] is False

    class _Broken:
        def execute(self, sql, params=()):
            raise sqlite3.OperationalError("no such table: product_source_config")
    from src.market.beginner_deal_scanner import verified_official_item_url
    with pytest.raises(sqlite3.OperationalError):
        verified_official_item_url(_Broken(), "p1")


def test_quality_checker_and_scanner_share_official_url_rule():
    """quality_checker と初心者向けの案件（「買う」リンク）が同じ判定を使う（公式 URL・送料の後退なし）。"""
    from src.market import official_registry as r
    from src.market.official_shipping import purchase_shipping
    for pid, v in r.VERIFIED_URLS.items():
        old = "https://www.apple.com/jp/shop/" if v["source"] == "src_apple_jp" else ""
        assert purchase_shipping(pid, v["url"], v.get("price")) == purchase_shipping(pid, old, v.get("price")), pid


# ── 同一性の更新で時刻を変えない・再確認 ──────────────────────────────────────────

def _seeded(tmp_path):
    """CI と同じ手順（init-db → seed → 公式の登録）の DB。"""
    import src.cli as cli
    from src.db.database import Database
    path = tmp_path / "pm.db"
    Database(db_path=str(path)).init_schema()
    orig = cli._get_db
    cli._get_db = lambda: Database(db_path=str(path))
    try:
        cli.seed.callback()
    finally:
        cli._get_db = orig
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    AUDIT.register_verified(c, AUDIT._products(c))
    return c


def test_identity_update_does_not_refresh_timestamps(tmp_path):
    c = _seeded(tmp_path)
    from src.market import official_registry as r
    rows = {x["id"]: dict(x) for x in c.execute(
        "SELECT id, jan_code, model_number, official_price_updated_at, official_stock_observed_at FROM products")}
    # 型番・JAN を登録しただけの商品（GR IV 系・Z8 の JAN）に、実行日の時刻が入らない
    for pid in ("prod_gr4", "prod_gr4_hdf", "prod_gr4_mono"):
        assert rows[pid]["model_number"] == r.IDENTITY_EVIDENCE[pid]["model_number"]
        assert rows[pid]["official_price_updated_at"] in (None, "")
        assert rows[pid]["official_stock_observed_at"] in (None, "")
    # 確認日は記録の値そのもの（実行時刻ではない）
    for pid, v in r.VERIFIED_URLS.items():
        if rows.get(pid, {}).get("official_price_updated_at"):
            assert rows[pid]["official_price_updated_at"] == v["checked_on"], pid
    assert rows["prod_z8"]["official_stock_observed_at"] in (None, "")          # 在庫の記録が無い


def _apply(results):
    calls = []

    class _C:
        def execute(self, sql, params=()):
            calls.append((sql, params))
            return SimpleNamespace(fetchone=lambda: None)

        def commit(self):
            pass
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "latest.json"
        p.write_text(json.dumps({"results": results}), encoding="utf-8")
        applied = AUDIT.apply_recheck(_C(), {"prod_r5ii": {"model_number": "EOS R5 Mark II"},
                                              "prod_z8": {"model_number": "Z8"}}, p)
    return applied, [c for c in calls if c[0].lstrip().upper().startswith("UPDATE")]


def _res(pid, status, price, at="2026-10-09T12:00:00+09:00", stock=""):
    v = AUDIT.VERIFIED_URLS[pid]
    return {"product_id": pid, "status": status, "price": price, "recorded_price": v["price"], "stock": stock,
            "observed_at": at, "url": v["url"], "model": PRODUCTS[pid]["model_number"]}


def test_price_changed_is_review_required_not_auto_confirmed():
    applied, ups = _apply([_res("prod_r5ii", "changed", 600000)])
    assert applied[0]["review_status"] == "REVIEW_REQUIRED"
    assert any("official_price=NULL" in s for s, _ in ups)                     # 新しい価格を確定にしない
    assert not any(600000 in p for _, p in ups)
    assert any("REVIEW_REQUIRED" in s for s, _ in ups)


def test_future_and_failed_recheck_do_not_refresh():
    for r in (_res("prod_z8", "unchanged", 575300, at="2026-10-20T09:00:00+09:00"),
              _res("prod_z8", "failed", None), _res("prod_z8", "blocked", None)):
        assert _apply([r])[1] == []


def test_recheck_unchanged_camera_uses_observed_date():
    applied, ups = _apply([_res("prod_z8", "unchanged", 575300, stock="在庫あり")])
    assert [p for s, p in ups if "official_price_updated_at=?" in s] == [("2026-10-09", "prod_z8", 575300)]
    assert any(a["action"] == "stock_observed" for a in applied)        # ニコンの在庫の欄の明示の表示


def test_recheck_schema_top_level_and_compat(tmp_path, monkeypatch):
    """再確認の反映は出力の上の階層（recheck_applied）。互換のために success_rate の下にも残す。"""
    c = _seeded(tmp_path)
    c.close()
    rp = tmp_path / "recheck.json"
    rp.write_text(json.dumps({"results": [_res("prod_r5ii", "unchanged", 654500)]}), encoding="utf-8")
    monkeypatch.setattr(AUDIT, "DB_PATH", tmp_path / "pm.db")
    monkeypatch.setattr(AUDIT, "OUT", tmp_path / "out")
    monkeypatch.setattr(AUDIT, "RECHECK_PATH", rp)
    AUDIT.main()
    out = json.loads((tmp_path / "out" / "latest.json").read_text(encoding="utf-8"))
    assert out["recheck_applied"] and out["recheck_applied"] == out["success_rate"]["recheck_applied"]
    reg_rows = {r["product_id"]: r for r in out["registered"]}
    assert reg_rows["prod_r5ii"]["official_direct_eligible"] is True and reg_rows["prod_r5ii"]["official_price"] == 654500


# ── 再確認の読み取り（キヤノン・ニコン） ──────────────────────────────────────────

CANON_HTML = ('<html><head><meta charset="Shift_JIS"><script type="application/ld+json">'
              '{"@context":"https://schema.org","@type":"Product","description":"改行\n入り",'
              '"name":"EOS R5 Mark II・ボディー（レンズは付きません）",'
              '"offers":{"url":"https://store.canon.jp/online/g/g6536C001/","priceCurrency":"JPY","price":"654500"}}'
              '</script></head><body><button class="btn_cart_l_ " type="submit" '
              "onclick=\"dataLayerPushAdd('6536C001')\">カートに入れる</button></body></html>")
NIKON_HTML = ('<div>NIKKOR Z 24-70mm f/2.8 S II ニコンダイレクト販売価格 371,800円 338,000円 製品情報を見る</div>'
              '<div>ニコンダイレクト販売価格 575,300円 523,000円 2023/05/26 発売 JANコード： 4960759909947</div>'
              '<dl class="block-goods-stock"><dt>在庫</dt><dd id="spec_stock_msg"></dd></dl>')


def test_canon_parser():
    assert RECHECK.parse_canon_store(CANON_HTML, "6536C001") == {"model_found": True, "price": 654500,
                                                                  "stock": "", "ended": False}
    # 静的な HTML のカートのボタンは在庫の根拠にしない（押せるボタンでも在庫を記録しない。監査 M-2）
    assert RECHECK.parse_canon_store(CANON_HTML, "6536C001")["stock"] == ""
    assert RECHECK.parse_canon_store(CANON_HTML, "6536C011")["price"] is None       # レンズキットのコード
    kit = CANON_HTML.replace("ボディー（レンズは付きません）", "RF24-105L IS USM レンズキット")
    assert RECHECK.parse_canon_store(kit, "6536C001")["price"] is None              # ボディーでない


def test_nikon_parser():
    r = RECHECK.parse_nikon_direct(NIKON_HTML, "4960759909947")
    assert r == {"model_found": True, "price": 575300, "stock": "", "ended": False}   # 空の在庫の欄は記録しない
    assert RECHECK.parse_nikon_direct(NIKON_HTML, "4960759909948")["price"] is None   # 別の JAN
    instock = NIKON_HTML.replace('<dd id="spec_stock_msg"></dd>', '<dd id="spec_stock_msg">在庫あり</dd>')
    assert RECHECK.parse_nikon_direct(instock, "4960759909947")["stock"] == "在庫あり"
    ended = NIKON_HTML.replace('<dd id="spec_stock_msg"></dd>', '<dd id="spec_stock_msg">販売終了</dd>')
    assert RECHECK.parse_nikon_direct(ended, "4960759909947")["ended"] is True


def test_recheck_targets_and_redirect(monkeypatch):
    ts = {t["product_id"]: t for t in RECHECK._targets()}
    assert ts["prod_r5ii"]["match"] == "6536C001" and ts["prod_z8"]["match"] == "4960759909947"
    assert ts["prod_r5ii"]["model"] == "EOS R5 Mark II"           # 反映の照合は型番（apply_recheck と同じ）
    out = RECHECK.recheck(datetime(2026, 10, 9, 12, 0, tzinfo=JST),
                          fetch=lambda url: (CANON_HTML, "") if "canon" in url else
                          (NIKON_HTML, "") if "nikon" in url else (None, "moved"))
    st = {r["product_id"]: r["status"] for r in out}
    assert st["prod_r5ii"] == "unchanged" and st["prod_z8"] == "unchanged"
    assert st["prod_ps5_pro"] == "failed" and st["prod_airpods_pro3"] == "failed"   # リダイレクトは失敗扱い


def test_fetch_decodes_declared_charset(monkeypatch):
    import io
    import urllib.request

    from src.collectors import polite
    monkeypatch.setattr(polite, "robots_allowed", lambda url: True)
    monkeypatch.setattr(polite, "polite_wait", lambda url, sid=None: 0)
    body = '<meta charset="Shift_JIS"><p>ボディー</p>'.encode("shift_jis")

    class _R(io.BytesIO):
        headers = SimpleNamespace(get_content_charset=lambda: None)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Opener:
        def open(self, req, timeout=None):
            return _R(body)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: _Opener())
    h, why = RECHECK._fetch("https://store.canon.jp/online/g/g6536C001/")
    assert why == "" and "ボディー" in h


# ── 集計・運営者向け ──────────────────────────────────────────────────────

def test_coverage_metrics_split_price_kinds():
    m = _load("p16_metrics", ROOT / "scripts" / "production_coverage_metrics.py")
    products = [{"product_id": "prod_ps5_pro", "evidence": "VERIFIED_CURRENT", "source": "src_sony_store"},
                {"product_id": "prod_r5ii", "evidence": "VERIFIED_CURRENT", "source": "src_canon_official"},
                {"product_id": "prod_gr4", "evidence": "VERIFIED_CURRENT", "source": "src_ricoh_imaging"},
                {"product_id": "prod_z8", "evidence": "CONFIGURED_REFERENCE", "source": "src_nikon_direct"},
                {"product_id": "prod_ps5_de", "evidence": "CONFIGURED_REFERENCE", "source": "src_sony_store"}]
    got = m._price_kind_metrics(products, {"actionable": {"products": [{"product_id": "prod_r5ii"}]}})
    assert got == {"verified_msrp": 2, "official_direct_verified": 1, "official_direct_actionable": 1,
                   "ambiguous_variants": 1}


def test_admin_shows_official_direct_not_msrp():
    from src.content.ui import admin
    from src.market import official_registry as r
    html = admin._official_direct_html(r.official_direct_audit(list(PRODUCTS.values()), TODAY))
    assert "公式直販価格" in html and "希望小売価格（定価）ではない" in html and "オープン価格" in html
    assert "NaN" not in html and "None" not in html and html.count("商品詳細") == len(r.OFFICIAL_DIRECT_OFFERS)


# ── レビュー・監査の指摘への対応 ─────────────────────────────────────────────

def test_description_alone_does_not_confirm_identity(reg):
    """説明文（JAN の代わり）だけで同一性を確定しない（レビュー H-1）。"""
    ok, why = _gate(reg, "prod_airpods_pro3", dict(PRODUCTS["prod_airpods_pro3"], model_number=""))
    assert not ok and "identity_not_confirmed" in why and "model_not_exact" in why
    ok, why = _gate(reg, "prod_iphone17_256", {"id": "prod_iphone17_256", "name": "iPhone 17"})   # 容量なし
    assert not ok


def test_iphone_identity_uses_variant_part_numbers(reg):
    p = PRODUCTS["prod_iphone17_256"]
    assert not p.get("model_number") and not p.get("jan_code")
    assert reg.identity_state(p)[0] == "IDENTITY_CONFIRMED"
    skus = reg.IDENTITY_EVIDENCE["prod_iphone17_256"]["variant_skus"]
    assert len(skus) == 5 and {c for c, _col, _p in skus.values()} == {"256GB"}
    # 商品名の機種が違えば（iPhone 17 Pro）使わない（再レビュー R-1）
    assert reg.identity_state(dict(p, name="iPhone 17 Pro 256GB SIMフリー"))[0] == "AMBIGUOUS"
    # 512GB の番号（194,800円）が混ざれば同じ商品と言えない
    reg.IDENTITY_EVIDENCE["prod_iphone17_256"] = dict(reg.IDENTITY_EVIDENCE["prod_iphone17_256"],
                                                      variant_skus={**skus, "MG6D4J/A": ("512GB", "Black", 194800)})
    try:
        assert reg.identity_state(p)[0] == "AMBIGUOUS" and not _gate(reg, "prod_iphone17_256")[0]
    finally:
        reg.IDENTITY_EVIDENCE["prod_iphone17_256"] = dict(reg.IDENTITY_EVIDENCE["prod_iphone17_256"], variant_skus=skus)


@pytest.mark.parametrize("title,product,conflict", [
    ("【期間限定ポイント5倍】iPhone 17 256GB SIMフリー 本体", "iPhone 17 256GB SIMフリー", None),
    ("AirPods Pro 3 MFHP4J/A 数量限定 送料無料", "AirPods Pro 3", None),
    ("PlayStation 5 Pro 記念セール", "PlayStation 5 Pro", None),
    ("iPhone 17 256GB 本体 フルセット 付属品完備", "iPhone 17 256GB", None),
    ("Kitty 柄 ケース付き iPhone 17", "iPhone 17", None),
    ("FUJIFILM X100VI 数量限定モデル", "FUJIFILM X100VI", "limited_mismatch"),
    ("Canon EOS R5 Mark II kit", "Canon EOS R5 Mark II", "bundle_mismatch"),
])
def test_ad_phrases_do_not_trigger_conflict(title, product, conflict):
    """広告・付属品の言い回しでセット・限定と誤判定しない（レビュー M-1・監査 L-4）。"""
    from src.market.product_identity_resolver import variant_conflict
    assert variant_conflict(title, product) == conflict


def test_official_direct_expires_in_14_days():
    """公式直販価格は14日を過ぎたら確認済みでない（固定の定価は180日。レビュー M-2）。"""
    from src.market import price_evidence as pe
    from src.market.normalized_prices import OFFICIAL_DIRECT_STALE_DAYS, OFFICIAL_STALE_DAYS, official_stale_days
    assert official_stale_days("prod_z8") == OFFICIAL_DIRECT_STALE_DAYS == 14
    assert official_stale_days("prod_ps5_pro") == OFFICIAL_STALE_DAYS == 180
    z8 = SimpleNamespace(id="prod_z8", official_price=575300, official_price_updated_at="2026-10-08", retail_price=590000)
    ps5 = SimpleNamespace(id="prod_ps5_pro", official_price=137980, official_price_updated_at="2026-10-08",
                          retail_price=119980)
    later = datetime(2026, 10, 30, 12, 0, tzinfo=JST)
    assert pe.classify_product_msrp(z8, later) == pe.STALE
    assert pe.classify_product_msrp(ps5, later) == pe.VERIFIED_DATED
    assert pe.classify_product_msrp(z8, datetime(2026, 10, 12, 12, 0, tzinfo=JST)) == pe.VERIFIED_CURRENT


def test_admin_audit_reflects_recheck_and_staleness(reg):
    """運営者向けの判定は、再確認の結果と期限も見る（監査 M-3）。"""
    prods = list(PRODUCTS.values())
    v = reg.VERIFIED_URLS["prod_z8"]
    changed = [{"product_id": "prod_z8", "status": "changed", "url": v["url"], "recorded_price": v["price"],
                "price": 600000, "observed_at": "2026-10-09T12:00:00+09:00"}]
    rows = {r["product_id"]: r for r in reg.official_direct_audit(prods, TODAY, changed)}
    assert not rows["prod_z8"]["eligible"] and "recheck_changed" in rows["prod_z8"]["reasons"]
    stale = {r["product_id"]: r for r in reg.official_direct_audit(prods, "2026-10-30")}
    assert not stale["prod_x100vi"]["eligible"] and "verified_at_stale" in stale["prod_x100vi"]["reasons"]
    # 記録と同じ価格の unchanged の再確認があれば、その日から数える
    fresh = [{"product_id": "prod_x100vi", "status": "unchanged", "url": reg.VERIFIED_URLS["prod_x100vi"]["url"],
              "recorded_price": 315700, "price": 315700, "observed_at": "2026-10-29T12:00:00+09:00"}]
    rows = {r["product_id"]: r for r in reg.official_direct_audit(prods, "2026-10-30", fresh)}
    assert rows["prod_x100vi"]["eligible"] and rows["prod_x100vi"]["verified_at"] == "2026-10-29"


def test_shipping_record_from_other_shop_is_rejected(reg):
    from src.market import official_shipping as osh
    osh.PRODUCT_SHIPPING["prod_r5ii"] = dict(osh.PRODUCT_SHIPPING["prod_r5ii"], source="src_nikon_direct")
    ok, why = _gate(reg, "prod_r5ii")
    assert not ok and "shipping_source_mismatch" in why


def test_recheck_stock_not_written_for_unverified_row(reg, tmp_path):
    """判定を通らない行（verified が外れた行）には、再確認の在庫も書かない（再監査 Low-2）。"""
    c = _seeded(tmp_path)
    c.execute("UPDATE products SET official_stock_status='', official_stock_observed_at='' WHERE id='prod_z8'")
    c.execute("UPDATE product_source_config SET extra_config=json_set(extra_config,'$.verified',json('false')) "
              "WHERE product_id='prod_z8'")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pth = Path(td) / "r.json"
        pth.write_text(json.dumps({"results": [_res("prod_z8", "unchanged", 575300, stock="在庫あり")]}), encoding="utf-8")
        applied = AUDIT.apply_recheck(c, AUDIT._products(c), pth)
    assert not any(a["action"] == "stock_observed" for a in applied)
    assert c.execute("SELECT official_stock_status FROM products WHERE id='prod_z8'").fetchone()[0] in ("", None)


def test_gate_failure_also_drops_purchase_link_and_stock(reg, tmp_path):
    """判定を通らない公式直販の行は、購入ページ・在庫の記録にも使わない（監査 L-7）。"""
    c = _seeded(tmp_path)
    c.execute("UPDATE products SET official_stock_status='', official_stock_observed_at='' WHERE id='prod_r5ii'")
    reg.OFFICIAL_DIRECT_OFFERS["prod_r5ii"]["sale_mode"] = "LOTTERY"
    AUDIT.register_verified(c, AUDIT._products(c))
    from src.market.beginner_deal_scanner import verified_official_item_url
    assert verified_official_item_url(c, "prod_r5ii") == ""
    row = c.execute("SELECT official_price, official_stock_status FROM products WHERE id='prod_r5ii'").fetchone()
    assert row[0] is None and row[1] in (None, "")


def test_text_outputs_use_price_kind_label():
    from src.content import community_message_generator as cm
    from src.content import daily_lp_generator as dl
    from src.content import note_generator as ng
    for mod in (cm, dl, ng):
        assert mod._official_label("prod_r5ii", 654500) == "公式直販価格"
        assert mod._official_label("prod_r5ii", 620000) == "参考価格"         # 設定値の参考価格
        assert mod._official_label("prod_ps5_pro", 137980) == "定価"


APPLE_PARTS = ''.join(f'{{"partNumber":"{s}","price":{{"fullPrice":{p}.00}},"category":"iphone","name":"{n}"}},'
                      for s, p, n in (("MG674J/A", 159800, "256GB Black"), ("MG684J/A", 159800, "256GB White"),
                                      ("MG6D4J/A", 194800, "512GB Black")))


def test_apple_parts_parser():
    assert RECHECK.parse_apple_parts(APPLE_PARTS, "MG674J/A,MG684J/A")["price"] == 159800
    assert RECHECK.parse_apple_parts(APPLE_PARTS, "MG674J/A,MG6D4J/A")["price"] is None      # 価格が違う番号
    assert RECHECK.parse_apple_parts(APPLE_PARTS, "MG674J/A,MG694J/A")["price"] is None      # 無い番号


FUJI_HTML = ('<meta name="keywords" content="FUJIFILM,X100VI,X100VIS,4547410554281,デジタルカメラ">'
             '<div>X100VI X100VI 315,700円 （税込）</div><div>FUJIFILM X100V用レザーケース 10,340円（税込）</div>'
             '<div>カラーを選択 シルバー 在庫なし ブラック 在庫なし フジフイルムモール購入者限定特典</div>')


def test_fuji_mall_parser():
    r = RECHECK.parse_fuji_mall(FUJI_HTML, "4547410554281|X100VI")
    assert r == {"model_found": True, "price": 315700, "stock": "在庫なし（全色）", "ended": False}
    assert RECHECK.parse_fuji_mall(FUJI_HTML, "4547410554298|X100VI")["model_found"] is False   # 別の JAN
    mixed = FUJI_HTML.replace("ブラック 在庫なし", "ブラック 在庫あり")
    assert RECHECK.parse_fuji_mall(mixed, "4547410554281|X100VI")["stock"] == ""                # 色で違えば記録しない
    from src.market.stock_state import stock_state
    assert stock_state("在庫なし（全色）", "") == "OUT_OF_STOCK"
    # 区切りが無い・色の欄に在庫の表示が無い・予約の語がある形では、おすすめ商品の「在庫あり」を拾わない（再監査 Medium）
    no_delim = FUJI_HTML.replace("フジフイルムモール購入者限定特典", "") + "<div>おすすめ ケース 在庫あり</div>"
    assert RECHECK.parse_fuji_mall(no_delim, "4547410554281|X100VI")["stock"] == ""
    no_state = FUJI_HTML.replace("シルバー 在庫なし ブラック 在庫なし", "シルバー ブラック") \
        .replace("限定特典", "限定特典 おすすめ 在庫あり")
    assert RECHECK.parse_fuji_mall(no_state, "4547410554281|X100VI")["stock"] == ""
    resv = FUJI_HTML.replace("シルバー 在庫なし ブラック 在庫なし", "シルバー 予約受付中 ブラック 在庫あり")
    assert RECHECK.parse_fuji_mall(resv, "4547410554281|X100VI")["stock"] == ""
    twice = FUJI_HTML.replace("シルバー 在庫なし ブラック 在庫なし フジフイルムモール購入者限定特典",
                              "シルバー ブラック</div><div>カラーを選択 A 在庫あり B 在庫あり フジフイルムモール購入者")
    assert RECHECK.parse_fuji_mall(twice, "4547410554281|X100VI")["stock"] == ""                # 別の商品の欄を読まない
    one = FUJI_HTML.replace(" ブラック 在庫なし", "")
    assert RECHECK.parse_fuji_mall(one, "4547410554281|X100VI")["stock"] == ""                  # 1色だけ


def test_recheck_covers_all_official_direct_and_unmapped_hosts_wait_longer(monkeypatch):
    from src.collectors import polite
    ts = {t["product_id"]: t for t in RECHECK._targets()}
    from src.market import official_registry as r
    assert {p for p, v in r.VERIFIED_URLS.items() if v.get("price_kind") == "official_direct"} <= set(ts)
    monkeypatch.setattr(polite, "source_id_for_url", lambda url: "")
    assert RECHECK._host_interval("https://nij.nikon.com/shop/g/g4960759909947/") >= 120   # 60秒に落とさない


def test_fetch_reads_shift_jis_as_cp932(monkeypatch):
    import io
    import urllib.request
    monkeypatch.setattr(__import__("src.collectors.polite", fromlist=["x"]), "robots_allowed", lambda url: True)
    monkeypatch.setattr(__import__("src.collectors.polite", fromlist=["x"]), "polite_wait", lambda url, sid=None: 0)
    body = '<meta charset="Shift_JIS"><p>①ボディー</p>'.encode("cp932")          # ① は Windows の拡張文字

    class _R(io.BytesIO):
        headers = SimpleNamespace(get_content_charset=lambda: None)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: SimpleNamespace(open=lambda req, timeout=None: _R(body)))
    h, _ = RECHECK._fetch("https://store.canon.jp/online/g/g6536C001/")
    assert "①ボディー" in h
