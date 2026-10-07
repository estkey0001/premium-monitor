"""Phase 2.1（利益商品のデータ）のテスト。

公式定価の確認・在庫の根拠・成約中央値の集計期間・利益商品の内部診断（0件の理由）を確かめる。
データはテスト用の架空のもの（本番の生成物には入らない）。
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from src.content.ui import opportunity as opp
from src.market import opportunity_diagnostics as diag
from src.market import price_evidence as pe
from src.market.normalized_prices import make_observation
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=JST)


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _iso(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


# ── 公式定価 ─────────────────────────────────────────────────────

def test_verified_official_price_becomes_eligible_input():
    """公式で確認した定価（確認日付き）は確定利益の仕入れ値に使える。"""
    p = SimpleNamespace(id="prod_ps5_pro", retail_price=137980, official_price=137980,
                        official_price_updated_at=datetime(2026, 10, 3, tzinfo=JST))
    assert pe.is_profit_eligible(pe.classify_product_msrp(p, NOW))   # 確認から日が浅いので VERIFIED_CURRENT
    m = _script("audit_official_sources")
    v = m.VERIFIED_URLS["prod_ps5_pro"]
    # 確認した値・URL・日付（実行日ではなく、表に書いた確認日）
    assert v["price"] == 137980 and v["checked_on"] == "2026-10-08" and "store.sony.jp" in v["url"]   # Phase 14 で再確認
    assert m.VERIFIED_URLS["prod_switch2"]["price"] == 59980


def test_official_not_sold_keeps_products_loadable(tmp_path, monkeypatch):
    """販売終了で確認済み定価を外した商品も、商品の一覧として読み込める（LP の生成を止めない）。"""
    import sqlite3
    from src.db.database import Database
    from src.db.repository import Repository
    db = Database(str(tmp_path / "a.db"))
    db.init_schema()
    c = db.connection
    c.execute("INSERT INTO products (id,name,genre,brand,retail_price,official_price,official_price_source,"
              "official_price_updated_at,is_active,created_at,updated_at) VALUES ('prod_iphone17pro_256',"
              "'iPhone 17 Pro 256GB','iphone','Apple',179800,194800,'src_apple_jp','2026-08-23',1,"
              "'2026-10-01T00:00:00','2026-10-01T00:00:00')")
    c.commit()
    m = _script("audit_official_sources")
    ac = sqlite3.connect(str(tmp_path / "a.db"))
    ac.row_factory = sqlite3.Row
    products = {"prod_iphone17pro_256": {"name": "iPhone 17 Pro 256GB", "model_number": "", "retail_price": 179800}}
    monkeypatch.setattr(m, "_upsert_config", lambda *a, **k: None)
    m.register_verified(ac, products)
    p, = Repository(db).list_products()
    assert p.official_price is None and p.official_price_source == "" and p.is_discontinued is True
    assert pe.classify_product_msrp(p, NOW) == pe.CONFIGURED_REFERENCE


def test_unknown_verification_date_stays_reference():
    """設定値（確認日なし）の定価は参考価格のまま。確認済みにしない。"""
    p = SimpleNamespace(id="prod_x", retail_price=49980, official_price=None, official_price_updated_at=None)
    assert pe.classify_product_msrp(p, NOW) == pe.CONFIGURED_REFERENCE
    # 公式で販売終了・後継機に交代した商品は、確認済みの表から外れている
    m = _script("audit_official_sources")
    for pid in ("prod_iphone17pro_256", "prod_iphone17pm_256", "prod_ipad_pro_m4_11", "prod_switch2_mk"):
        assert pid in m.OFFICIAL_NOT_SOLD and pid not in m.VERIFIED_URLS


# ── 買取（売り先）──────────────────────────────────────────────────

def _bb(pid, price, *, basis="observed", ctype="BUYBACK_CASH", ptype="buyback_price", **kw):
    o = {"product_id": pid, "price_role": "sell", "price_type": ptype, "canonical_price_type": ctype,
         "price": price, "freshness_basis": basis, "source_name": "買取店A", "observed_at": _iso(hours=1)}
    o.update(kw)
    return o


def test_fresh_buyback_is_usable_and_stale_buyback_excluded():
    fresh = diag._data_reasons("p", pe.VERIFIED_DATED, [_bb("p", 200000)])
    stale = diag._data_reasons("p", pe.VERIFIED_DATED, [_bb("p", 200000, basis="observed_stale")])
    assert "stale_buyback" not in fresh and fresh == ["no_profit"]     # 新しい買取があり、案件が無い = 純利益0以下
    assert "stale_buyback" in stale


def test_trade_in_is_not_cash_buyback():
    r = diag._data_reasons("p", pe.VERIFIED_DATED,
                           [_bb("p", 200000, ctype="TRADE_IN", ptype="trade_in_price")])
    assert "unknown_type" in r and "no_profit" not in r
    o = make_observation(NOW, product_id="p", price_role="sell", price_type="trade_in_price", price=1,
                         observed_at=_iso(hours=1))
    assert o["canonical_price_type"] != "BUYBACK_CASH"


# ── 在庫 ────────────────────────────────────────────────────────

def test_ricoh_unknown_stock_is_not_in_stock():
    from src.collectors.official.ricoh import ricoh_stock_from_status
    assert ricoh_stock_from_status(None) is None
    assert ricoh_stock_from_status("") is None
    assert ricoh_stock_from_status("予約受付中") is None          # SOLD OUT 以外でも在庫ありとは限らない
    assert ricoh_stock_from_status("抽選受付中") is None
    assert ricoh_stock_from_status("SOLD OUT") is False
    assert ricoh_stock_from_status("在庫あり") is True


def test_generic_stock_needs_explicit_evidence():
    from src.collectors.official._generic import stock_from_text
    assert stock_from_text("ご注文について 購入手続き カートに入れる") is None   # 案内文・ボタンは根拠にしない
    assert stock_from_text("入荷待ち ご注文について") is False                   # 品切れを先に見る
    assert stock_from_text("在庫あり") is True


def test_price_availability_is_not_stock_availability(tmp_path):
    """価格が取れても、在庫の表示が無ければ在庫の確認日時は入らない（在庫未確認）。"""
    from src.db.database import Database
    from src.db.repository import Repository
    db = Database(str(tmp_path / "s.db"))
    db.init_schema()
    c = db.connection
    for pid in ("p1", "p2"):
        c.execute("INSERT INTO products (id,name,genre,brand,retail_price,is_active,created_at,updated_at) "
                  "VALUES (?,?,'camera','RICOH',100000,1,'2026-10-01T00:00:00','2026-10-01T00:00:00')", (pid, pid))
    c.commit()
    repo = Repository(db)
    repo.mark_official_price_candidate("p1", 100000, "src_ricoh_imaging", stock_status="", observed_at=NOW)
    repo.mark_official_price_candidate("p2", 100000, "src_ricoh_imaging", stock_status="在庫あり", observed_at=NOW)
    rows = {r["id"]: r for r in c.execute(
        "SELECT id, official_price_updated_at, official_stock_status, official_stock_observed_at FROM products")}
    assert rows["p1"]["official_price_updated_at"] and rows["p1"]["official_stock_observed_at"] == ""
    assert rows["p2"]["official_stock_observed_at"] == rows["p2"]["official_price_updated_at"]
    st, unsupported = diag._stock_state({"official_stock_status": "在庫あり", "official_stock_observed_at": ""}, NOW)
    assert st == "UNKNOWN" and unsupported is True


def test_view_availability_types():
    base = {"product_id": "p", "title": "X", "genre": "camera", "official_price": 100000,
            "official_checked_at": _iso(days=30), "msrp_evidence": "VERIFIED_DATED", "sale_method": "normal",
            "sell_shop": "買取店A", "sell_identity_verified": True, "sell_price": 120000, "sell_checked_at": _iso(hours=1), "net_profit": 18200,
            "user_level": "beginner_easy", "purchase_shipping": 0, "purchase_shipping_status": "FREE_VERIFIED"}
    cases = [({"stock_status": "在庫あり", "stock_checked_at": _iso(days=1)}, "BUY_NOW"),
             ({"stock_status": "在庫あり", "stock_checked_at": ""}, "PROFIT_STOCK_UNKNOWN"),
             ({"stock_status": ""}, "PROFIT_STOCK_UNKNOWN"),
             ({"stock_status": "在庫あり", "sale_method": "lottery"}, "LOTTERY")]
    for extra, want in cases:
        v, = opp.build(deals=[{**base, **extra}], routes=[], product_genres={}, now=NOW).eligible
        assert v.availability == want, (extra, v.availability)
    assert opp.AVAILABILITY_LABELS["PROFIT_STOCK_UNKNOWN"] == "利益あり・在庫未確認"


def test_generator_passes_stock_check_time_not_price_time():
    from src.content.daily_lp_generator import DailyLPGenerator
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g._product_info = {"p": {"genre": "camera", "official_checked_at": _iso(days=1), "stock_checked_at": ""}}
    g._msrp_evidence = {"p": pe.VERIFIED_DATED}
    g._is_resale_shop = lambda shop: False
    d = SimpleNamespace(product_id="p", product_name="X", net_profit_jpy=10000, best_buyback_shop="買取店A",
                        best_buyback_price=120000, official_price_jpy=108200, stock_status="在庫あり",
                        sale_method="normal", user_level="beginner_easy")
    out, = g._nu_profit_deals([d], {})
    assert out["stock_checked_at"] == "" and out["official_checked_at"]


# ── 成約中央値の集計期間 ─────────────────────────────────────────────

def test_sold_period_persisted_when_evidenced():
    o = make_observation(NOW, product_id="p", price_role="sell", price_type="sold_price", price=60000,
                         observed_at=_iso(hours=1), sold_median_eligible=True, sample_count=5,
                         sold_period_start="2026-09-03T00:00:00+09:00", sold_period_end="2026-10-02T23:59:59+09:00",
                         sold_median_min=55000, sold_median_max=64000)
    assert o["sold_median_eligible"] is True and o["sold_median_min"] == 55000
    r = _script("generate_profit_routes")
    assert r._sold_period_text(o) == "2026-09-03〜2026-10-02"


def test_unknown_sold_period_not_fabricated():
    o = make_observation(NOW, product_id="p", price_role="sell", price_type="sold_price", price=60000,
                         observed_at=_iso(hours=1), sold_median_eligible=True, sample_count=5)
    assert o["sold_median_eligible"] is False                      # 期間が無ければ成約中央値として使わない
    assert o["sold_period_start"] == o["sold_period_end"] == ""
    assert _script("generate_profit_routes")._sold_period_text(o) == ""
    few = make_observation(NOW, product_id="p", price_role="sell", price_type="sold_price", price=60000,
                           observed_at=_iso(hours=1), sold_median_eligible=True, sample_count=2,
                           sold_period_start="2026-09-03", sold_period_end="2026-10-02")
    assert few["sold_median_eligible"] is False


# ── 診断（0件の理由）・HOME との一致 ───────────────────────────────────

def _deal(pid, name, genre, off, sell, **kw):
    d = {"product_id": pid, "title": name, "genre": genre, "official_price": off,
         "official_checked_at": _iso(days=1), "msrp_evidence": "VERIFIED_DATED", "stock_status": "",
         "sale_method": "normal", "sell_shop": "買取店A", "sell_identity_verified": True, "sell_price": sell, "sell_checked_at": _iso(hours=1),
         "net_profit": sell - off - 1800, "user_level": "beginner_easy", "purchase_shipping": 0, "purchase_shipping_status": "FREE_VERIFIED"}
    d.update(kw)
    return d


def _products():
    return [{"id": i, "name": i, "genre": g} for i, g in (
        ("p_ok", "game_console"), ("p_ref", "game_console"), ("p_nosell", "iphone"),
        ("p_stale", "camera"), ("p_loss", "camera"), ("p_cfgdeal", "pc"))]


def _diag_report():
    from src.content.ui import shell
    deals = [_deal("p_ok", "PS5 Pro", "game_console", 137980, 192000),
             _deal("p_cfgdeal", "設定値の定価", "pc", 100000, 130000, msrp_evidence="CONFIGURED_REFERENCE")]
    ev = {"p_ok": pe.VERIFIED_DATED, "p_ref": pe.CONFIGURED_REFERENCE, "p_nosell": pe.VERIFIED_DATED,
          "p_stale": pe.VERIFIED_DATED, "p_loss": pe.VERIFIED_DATED, "p_cfgdeal": pe.CONFIGURED_REFERENCE}
    obs = [_bb("p_ok", 192000), _bb("p_ref", 60000), _bb("p_stale", 90000, basis="observed_stale"),
           _bb("p_loss", 80000), _bb("p_nosell", 0)]
    ctx = shell.ShellContext(tcg_report={"lotteries": [], "events": []}, opportunities={},
                             profit_routes={"main_routes": []}, legacy_lotteries=[], updated_text="", now=NOW,
                             profit_deals=deals, product_genres={p["id"]: p["genre"] for p in _products()})
    _m, catalog = shell.build_catalog(ctx)
    return diag.build(products=_products(), msrp_evidence=ev, official_meta={}, observations=obs,
                      opportunity_set=catalog.opportunity_set, home_count=catalog.count("opportunities"),
                      list_count=len(catalog.items["opportunities"]), sold_exports={}, now=NOW)


def test_zero_reason_diagnostics():
    r = _diag_report()
    assert r["candidate_count"] == 6 and r["eligible_count"] == 1
    assert r["primary_reasons"] == {"unverified_buy_price": 2, "no_sell_price": 1, "stale_buyback": 1,
                                    "no_profit": 1}
    assert r["category_counts"]["game"] == {"candidates": 2, "eligible": 1,
                                            "primary_reasons": {"unverified_buy_price": 1}}
    assert r["route_types"]["RETAIL_TO_BUYBACK"] == {"candidates": 6, "eligible": 1}
    assert r["stock_excluded"] == 0 and r["buyback"]["failed_rows"] == 1


def test_home_list_count_parity_in_diagnostics():
    r = _diag_report()
    assert r["home_parity"] == {"home": 1, "list": 1, "eligible": 1, "ok": True}


# ── レビュー指摘の再発防止（在庫・販売終了・公式ドメイン）─────────────────────

def test_manual_stock_check_is_recorded_with_time():
    """人が公式ページで在庫の表示も確認したときは、確認した時刻つきで在庫を記録する。"""
    m = _script("audit_official_sources")

    class Conn:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=()):
            self.calls.append((sql, params))
            return SimpleNamespace(fetchone=lambda: None)

        def commit(self):
            pass

    c = Conn()
    # 確認から7日を過ぎた在庫の記録は書かない（Phase 14）ので、実行日に左右されないよう CI の時刻を確認の直後に固定する
    m.NOW = datetime(2026, 10, 8, 3, 0, tzinfo=JST)
    m.register_verified(c, {"prod_ps5_pro": {"name": "PlayStation 5 Pro", "model_number": "CFI-7100B01",
                                             "retail_price": 137980}})
    stock = [p for sql, p in c.calls if "official_stock_observed_at" in sql]
    assert stock == [("入荷待ち", "2026-10-08T02:34:48+09:00", "prod_ps5_pro", "2026-10-08T02:34:48+09:00")]   # Phase 14 で再確認
    assert opp.stock_from("入荷待ち", "normal") == "OUT_OF_STOCK"


def test_old_ui_does_not_treat_unknown_stock_as_in_stock():
    from src.market.beginner_deal_scanner import BeginnerDealScanner
    from src.market.stock_state import is_explicit_in_stock
    s = BeginnerDealScanner.__new__(BeginnerDealScanner)
    for unknown in ("", "入荷待ち", "在庫なし", "予約受付中"):
        level, _a = s._classify("normal", unknown, 0.1, 20000, 21800)
        assert level != "beginner_easy", unknown
        assert not is_explicit_in_stock(unknown)
    level, _a = s._classify("normal", "在庫あり", 0.1, 20000, 21800)
    assert level == "beginner_easy"


def test_product_detail_labels_discontinued_reference_price():
    """旧UIの「参考定価（公式販売終了）」の後継: 商品詳細の公式ストアの行で、販売終了の商品の定価は参考と書く。"""
    from datetime import datetime as _dt
    from src.content.ui import product_detail as pd
    from src.tcg.models import JST as _JST
    now = _dt(2026, 10, 5, 12, 0, tzinfo=_JST)
    off = {"price_role": "official", "price": 50000, "freshness_basis": "config_unknown_date", "observed_at": ""}
    row = lambda sale, basis="config_unknown_date", at="": pd._official_row(   # noqa: E731
        "a", {"brand": "X", "official_price": 50000, "official_url": "", "sale_method": sale},
        [dict(off, freshness_basis=basis, observed_at=at)], None, now, None)
    assert row("discontinued").note == "公式の販売は終了（定価は参考）" and row("discontinued").quality == pd.REFERENCE
    assert row("normal").note == "定価の確認日が分からない設定値（参考）"
    ok = row("normal", "verified", "2026-10-01")
    assert ok.note == "" and ok.type_label == "定価" and ok.quality == pd.VERIFIED


def test_official_domain_is_not_substring_match():
    from src.market.official_price_validator import is_official_domain
    assert is_official_domain("src_nintendo_store", "https://www.nintendo.com/jp/hardware/")
    assert not is_official_domain("src_nintendo_store", "https://evilnintendo.com/")
    assert is_official_domain("src_sony_store", "https://pur.store.sony.jp/ps5/")


def test_secondary_scanner_keeps_official_stock_and_sale_method():
    """海外売却スキャナーが案件の行を上書きしても、公式の在庫表示・販売方式を消さない。"""
    from src.market.primary_to_secondary_scanner import PrimaryToSecondaryScanner
    from src.models.product import ProductModel
    s = PrimaryToSecondaryScanner.__new__(PrimaryToSecondaryScanner)
    s._get_official_url = lambda p: ""
    p = ProductModel(id="prod_ps5_pro", name="PlayStation 5 Pro", genre="game_console", brand="Sony",
                     retail_price=137980, official_price=137980, official_stock_status="入荷待ち",
                     created_at=NOW, updated_at=NOW)
    d = s._make_monitoring(p, 137980, 0, "海外価格なし")
    assert d.stock_status == "入荷待ち" and d.sale_method == "soldout"


def test_english_out_of_stock_marks():
    from src.market.stock_state import stock_state
    assert stock_state("NOT IN STOCK") == "OUT_OF_STOCK"
    assert stock_state("Out of stock") == "OUT_OF_STOCK"
    assert stock_state("In stock") == "IN_STOCK"
