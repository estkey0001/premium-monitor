"""Phase 0.2: 出品価格（LISTING）・成約価格（SOLD）・買取価格を取り違えないことのテスト。

ヤフオクの HTML は実ページの構造をまねた合成のもの（実際の出品内容は含めない）。
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.market import price_types as pt

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=JST)
ITEM = "https://auctions.yahoo.co.jp/jp/auction/k1234567890"


def _route_fixtures():
    """確定として出してよいルートの雛形（tests/route_fixtures.py）。"""
    import importlib.util as _ilu
    from pathlib import Path as _P
    spec = _ilu.spec_from_file_location("route_fixtures", _P(__file__).with_name("route_fixtures.py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _yahoo_page(items) -> str:
    """ヤフオクの「出品中の一覧」をまねた HTML。属性に無関係な数字（カテゴリ ID など）も入れる。"""
    lis = []
    for i, (title, price) in enumerate(items):
        lis.append(
            f'<li class="Product"><div class="Product__image">'
            f'<a class="Product__imageLink" data-auction-category="2084261651" data-auction-id="x{i}abc"'
            f' data-auction-price="{price}" data-auction-title="{title}"'
            f' data-cl-params="catid:2084261651;cid:x{i}abc;st:1790859359;end:1791118559;"'
            f' href="https://auctions.yahoo.co.jp/jp/auction/x{i}abc">img</a>'
            f'<a data-auc-ya="23632;watch_button_click" data-cid="40054ec1c3">ウォッチ</a></div>'
            f'<div class="Product__detail"><span class="Product__price">現在{price:,}円</span>'
            f'<span class="Product__time">01日</span></div></li>')
    return ("<html><head><title>Yahoo!オークション - 一覧</title></head><body>"
            '<div data-auction-categoryidpath="0,23632,23636,236322">'
            + "".join(lis) + "</div>" + "x" * 400 + "</body></html>")


# ── ヤフオク: 出品中の一覧は LISTING ────────────────────────────────────────

def test_yahoo_listing_is_not_labelled_sold(monkeypatch):
    crp = _load_script("collect_resale_prices")
    C = crp.YahooAuctionResaleCollector
    assert C.PRICE_TYPE == pt.LISTING
    assert not pt.is_sold_label(C.SHOP_NAME)             # 「落札」「sold」を名乗らない
    html = _yahoo_page([("RICOH GR IV 新品未開封", 240000), ("RICOH GR IV 新品 未使用", 250000),
                        ("RICOH GR IV 新品", 260000)])
    monkeypatch.setattr(crp, "_fetch_html", lambda url, **kw: html)
    r = C().collect("gr4", ["RICOH GR IV"])
    assert r["price_type"] == pt.LISTING and r["listing_count"] == 3 and r["price_jpy"] == 250000


def test_yahoo_parser_ignores_attribute_numbers_and_used_or_other_variants(monkeypatch):
    """修正前はページ全体から数字を拾い、カテゴリ ID（23632 等）や中古・別型の出品が混ざっていた。"""
    crp = _load_script("collect_resale_prices")
    C = crp.YahooAuctionResaleCollector
    html = _yahoo_page([("RICOH GR IV Monochrome 新品", 330000), ("[美品 | シャッター数672回] RICOH GR IV", 263000),
                        ("【新品同様】 RICOH GR IV", 308000), ("RICOH GR IV 中古", 250000),
                        ("RICOH GR IV 新品未開封", 245000)])
    items = C._parse_items(html)
    assert sorted(it["price"] for it in items) == [245000, 250000, 263000, 308000, 330000]   # 属性の数字は拾わない
    monkeypatch.setattr(crp, "_fetch_html", lambda url, **kw: html)
    r = C().collect("gr4", ["RICOH GR IV"])
    assert r["listing_count"] == 1 and r["price_jpy"] == 245000                              # 新品・同じ型だけ
    # 条件に合う出品が無ければ値を作らない
    monkeypatch.setattr(crp, "_fetch_html", lambda url, **kw: _yahoo_page([("RICOH GR IV 中古", 250000)]))
    assert C().collect("gr4", ["RICOH GR IV"]) is None


def test_failed_yahoo_fetch_does_not_refresh_observation(monkeypatch):
    crp = _load_script("collect_resale_prices")
    monkeypatch.setattr(crp, "_fetch_html", lambda url, **kw: None)
    saved = []
    monkeypatch.setattr(crp, "_save_sale_price", lambda **kw: saved.append(kw))
    assert crp.YahooAuctionResaleCollector().collect("gr4", ["RICOH GR IV"]) is None
    assert saved == []
    # 保存は「取得に成功したとき」だけ（run_collection の各店は `if result:` の中で保存する）
    src = (ROOT / "scripts/collect_resale_prices.py").read_text(encoding="utf-8")
    block = src.split("# ──── ヤフオク ────", 1)[1].split("# ────", 1)[0]
    assert "if result:" in block and block.index("if result:") < block.index("_save_sale_price(")


def test_every_resale_save_records_price_type():
    src = (ROOT / "scripts/collect_resale_prices.py").read_text(encoding="utf-8")
    calls = [c for c in src.split("_save_sale_price(\n")[1:] if c.lstrip().startswith("repo=repo")]
    assert len(calls) == 6                                        # eBay・Amazon・メルカリ・ヤフオク・楽天・ラクマ
    for c in calls:
        head = c.split(")\n", 1)[0]
        assert "price_type=" in head and "sample_count=" in head
    assert 'price_type="SOLD"' not in src          # 集計値・出品を1件の成約（SOLD）として保存しない


# ── 種別・根拠・成約中央値 ─────────────────────────────────────────────────

def test_canonical_types_and_unknown_legacy():
    assert pt.canonical("flea_listing_price") == pt.LISTING
    assert pt.canonical("buyback_price") == pt.BUYBACK_CASH
    assert pt.canonical("trade_in_price") == pt.TRADE_IN
    assert pt.canonical("official_price") == pt.RETAIL
    for legacy in ("", None, "ヤフオク (新品/未使用落札)", "sold", "落札"):
        assert pt.canonical(legacy) == pt.UNKNOWN      # 名前に「落札」とあっても SOLD にしない
    assert pt.label(pt.LISTING) == "出品価格" and pt.label(pt.SOLD) == "成約価格"


@pytest.mark.parametrize("url, sold_at, ok", [
    (ITEM, "2026-10-01T20:00:00+09:00", True),
    ("https://auctions.yahoo.co.jp/jp/auction/x000000001", "2026-10-01", False),   # ダミー
    ("https://jp.mercari.com/item/m00000000001", "2026-10-01", False),             # ダミー
    ("https://auctions.yahoo.co.jp/search/search?p=GR", "2026-10-01", False),      # 検索結果
    ("https://www.ebay.com/sch/i.html?_nkw=GR&LH_Sold=1", "2026-10-01", False),    # 検索結果
    (ITEM, "", False),                                                             # 成約日時なし
])
def test_sold_item_requires_sold_evidence(url, sold_at, ok):
    assert pt.has_sold_evidence(url, sold_at) is ok


def _samples(n, price_type=pt.SOLD, sold_at="2026-09-20T10:00:00+09:00", url=ITEM, identity="gr4"):
    return [pt.MarketSample(price=200000 + i * 1000, price_type=price_type, identity=identity,
                            condition="new_unopened", item_url=url, sold_at=sold_at) for i in range(n)]


def test_sold_median_requires_minimum_samples():
    period = dict(identity="gr4", period_start="2026-09-01", period_end="2026-10-03")
    ok = pt.sold_median(_samples(3), **period)
    assert ok["status"] == "ok" and ok["sample_count"] == 3 and ok["median"] == 201000
    assert ok["min"] == 200000 and ok["max"] == 202000 and ok["period_start"] and ok["period_end"]
    assert pt.is_sold_median_eligible(ok)
    two = pt.sold_median(_samples(2), **period)                  # 3 → 2 件
    assert two["status"] == "insufficient_samples" and two["median"] is None
    assert not pt.is_sold_median_eligible(two)
    assert pt.MIN_SOLD_SAMPLES == 3


def test_listing_median_cannot_populate_sold_median():
    period = dict(identity="gr4", period_start="2026-09-01", period_end="2026-10-03")
    r = pt.sold_median(_samples(10, price_type=pt.LISTING), **period)
    assert r["sample_count"] == 0 and r["status"] == "insufficient_samples"
    stats = pt.listing_stats(_samples(4, price_type=pt.LISTING), identity="gr4")
    assert stats["price_type"] == pt.LISTING and stats["listing_count"] == 4
    assert stats["median_listing"] == 201500 and "median" not in stats      # 成約の中央値とは別の項目


def test_sold_requires_sold_at_for_period_aggregation():
    period = dict(identity="gr4", period_start="2026-09-01", period_end="2026-10-03")
    assert pt.sold_median(_samples(5, sold_at=""), **period)["sample_count"] == 0
    assert pt.sold_median(_samples(5, sold_at="2026-08-01"), **period)["sample_count"] == 0   # 期間外
    assert pt.sold_median(_samples(5), identity="gr4", period_start="", period_end="")["status"] == "no_period"
    assert pt.sold_median(_samples(5, identity="gr4_mono"), **period)["sample_count"] == 0     # 別の型


# ── 正規化（NPO）: 保存された種別で分類し、根拠の無い成約を使わない ─────────────────

@pytest.mark.parametrize("name, stored, url, sold_at, expect_type, expect_reject", [
    ("ヤフオク (出品中・新品/未使用)", pt.LISTING, "https://auctions.yahoo.co.jp/search/search?p=x", "",
     "flea_listing_price", ""),
    ("ヤフオク (新品/未使用落札)", pt.UNKNOWN, "https://auctions.yahoo.co.jp/search/search?p=x", "",
     "flea_listing_price", "sold_label_without_evidence"),
    ("ヤフオク", pt.SOLD, "https://auctions.yahoo.co.jp/jp/auction/x000000001", "2026-10-01",
     "flea_listing_price", "sold_without_evidence"),
    ("ヤフオク", pt.SOLD, ITEM, "2026-10-01T20:00:00+09:00", "flea_sold_price", ""),
    ("eBay (新品落札)", pt.SOLD_MEDIAN, "https://www.ebay.com/sch/i.html", "",
     "overseas_listing_price", "sold_aggregate_not_buy_price"),
    ("じゃんぱら", pt.UNKNOWN, "https://www.janpara.co.jp/sale/", "", "shop_sale_price", ""),
])
def test_npo_classifies_by_stored_type(name, stored, url, sold_at, expect_type, expect_reject):
    from src.market.normalized_prices import classify_sale_price_type
    ptype, _m, reject = classify_sale_price_type(name, "new_unopened", stored, item_url=url, sold_at=sold_at)
    assert (ptype, reject) == (expect_type, expect_reject)


def _npo_db(tmp_path, rows):
    from src.db.database import Database
    db = Database(str(tmp_path / "n.db"))
    db.init_schema()
    c = db.connection
    c.execute("INSERT INTO products (id, name, genre, brand, retail_price, is_active, created_at, updated_at) "
              "VALUES ('prod_gr4','RICOH GR IV','camera','RICOH',194800,1,'2026-10-01','2026-10-01')")
    for i, (name, ptype, url, sold_at) in enumerate(rows):
        c.execute("INSERT INTO sale_prices (id, product_id, product_alias, shop_name, shop_id, sale_price, condition,"
                  " url, link_verified, observed_at, data_source, is_active, price_type, sold_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (f"s{i}", "prod_gr4", "gr4", name, f"sh{i}", 240000, "new_unopened", url, 0,
                   NOW.isoformat(), "resale_market", 1, ptype, sold_at))
    c.commit()
    return c


def test_unknown_legacy_price_type_is_not_assumed_sold(tmp_path):
    from src.market.normalized_prices import build_observations
    c = _npo_db(tmp_path, [("ヤフオク (新品/未使用落札)", "UNKNOWN", "https://auctions.yahoo.co.jp/search/search", "")])
    # 種別の列が無かった時代の行（列の既定値 UNKNOWN）も同じ
    c.execute("INSERT INTO sale_prices (id, product_id, product_alias, shop_name, shop_id, sale_price, condition,"
              " url, link_verified, observed_at, data_source, is_active) VALUES"
              " ('legacy','prod_gr4','gr4','メルカリ sold','m',230000,'new_unopened','',0,?, 'manual',1)",
              (NOW.isoformat(),))
    c.commit()
    obs = [o for o in build_observations(c, now=NOW) if o["price_role"] == "buy"]
    assert len(obs) == 2
    for o in obs:
        assert o["price_type"] != "flea_sold_price" and o["canonical_price_type"] == pt.UNKNOWN
        assert not o["is_usable_for_pro"] and o["rejection_reason"] == "sold_label_without_evidence"


def test_sold_with_evidence_becomes_flea_sold(tmp_path):
    """否定対照: 根拠（商品ページの URL と成約日時）のある成約は成約として扱う。"""
    from src.market.normalized_prices import build_observations
    c = _npo_db(tmp_path, [("ヤフオク", "SOLD", ITEM, "2026-10-01T20:00:00+09:00")])
    o, = [o for o in build_observations(c, now=NOW) if o["price_role"] == "buy"]
    assert o["price_type"] == "flea_sold_price" and o["canonical_price_type"] == pt.SOLD
    assert o["sold_at"] and o["is_usable_for_pro"]


def test_migration_keeps_existing_rows_and_defaults_unknown(tmp_path):
    """種別の列が無い既存の DB に、行を壊さず列を足す。既存の行は UNKNOWN。"""
    from src.db.database import Database
    p = tmp_path / "old.db"
    db = Database(str(p))
    db.init_schema()
    c = db.connection
    c.execute("DELETE FROM schema_migrations WHERE version='019_sale_price_type'")
    c.execute("CREATE TABLE sp_old AS SELECT id, product_id, product_alias, shop_name, shop_id, sale_price, condition,"
              " url, link_verified, observed_at, data_source, is_active FROM sale_prices")
    c.execute("DROP TABLE sale_prices")
    c.execute("ALTER TABLE sp_old RENAME TO sale_prices")
    c.execute("INSERT INTO sale_prices VALUES ('a','','gr4','ヤフオク (新品/未使用落札)','y',240000,'new_unopened','',0,"
              "'2026-09-01T00:00:00+09:00','resale_market',1)")
    c.commit()
    db.init_schema()                                                   # 019 を適用
    row = sqlite3.connect(str(p)).execute("SELECT sale_price, price_type, sold_at FROM sale_prices").fetchone()
    assert row == (240000, "UNKNOWN", "")


# ── 利益: 出品価格からは確定利益・BUY を作らない ──────────────────────────────

def _obs(**kw):
    o = {"is_usable_for_pro": True, "price_role": "sell", "price_type": "buyback_price",
         "canonical_price_type": pt.BUYBACK_CASH, "confidence": "high", "collector_method": "",
         "source_mode": "", "sold_median_eligible": False}
    o.update(kw)
    return o


def test_listing_data_cannot_produce_sold_based_profit():
    gpr = _load_script("generate_profit_routes")
    assert gpr._sell_ok(_obs())                                                          # 買取は可
    assert not gpr._sell_ok(_obs(canonical_price_type=pt.LISTING))                       # 出品は不可
    assert not gpr._sell_ok(_obs(canonical_price_type=pt.UNKNOWN))
    ovs = _obs(price_type="overseas_sold_price", canonical_price_type=pt.SOLD, collector_method="api")
    assert not gpr._sell_ok(ovs)                         # API でも成約中央値の条件（件数・期間）が無ければ不可
    assert gpr._sell_ok({**ovs, "sold_median_eligible": True})
    # ルートには売値の種別が残る
    buy = {"source_name": "店A", "source_id": "a", "product_id": "p", "product_name": "P", "price": 100000,
           "price_type": "flea_listing_price", "canonical_price_type": pt.LISTING, "condition": "new_unopened",
           "observed_at": NOW.isoformat(), "freshness_basis": "observed", "confidence": "high"}
    sell = dict(buy, source_name="店B", source_id="b", price=140000, price_type="buyback_price",
                canonical_price_type=pt.BUYBACK_CASH)
    r = gpr._make_route(buy, sell, NOW)
    assert r["buy_canonical_type"] == pt.LISTING and r["sell_canonical_type"] == pt.BUYBACK_CASH


def test_listing_data_cannot_produce_sold_based_buy():
    from src.content.ui import home
    base = {"product": "GR IV", "action": "BUY", "kind": "main", "confidence": "high", "priority": 1,
            "buy_price": 100000, "sell_price": 140000, "net_profit": 30000, "roi": 0.3,
            "buy_source": "店A", "sell_source": "店B",
            "buy_price_evidence": "VERIFIED_CURRENT", "sell_price_evidence": "VERIFIED_CURRENT"}
    safe = _route_fixtures().safe_route
    for sell_type in (pt.LISTING, pt.SOLD, pt.UNKNOWN, None):
        o = dict(base, sell_canonical_type=sell_type)
        m = home.build_home_model(tcg_report={}, opportunities={"todays_opportunities": [o]},
                                  profit_routes={"main_routes": [safe(NOW, sell_canonical_type=sell_type)]},
                                  legacy_lotteries=[], now=NOW)
        assert m.counts["high_profit"] == 0 and not [a for a in m.opp_cards if a.action == "BUY"]
    for sell_type in (pt.BUYBACK_CASH, pt.SOLD_MEDIAN):     # 否定対照（確定の条件をすべて満たすルート）
        o = dict(base, sell_canonical_type=sell_type)
        m = home.build_home_model(tcg_report={}, opportunities={"todays_opportunities": [o]},
                                  profit_routes={"main_routes": [safe(NOW, sell_type=sell_type)]},
                                  legacy_lotteries=[], now=NOW)
        assert m.counts["high_profit"] == 1 and [a for a in m.opp_cards if a.action == "BUY"]


# ── 手動の成約 CSV: ダミー URL・成約日時なしは成約にしない ─────────────────────────

def test_manual_dummy_url_cannot_qualify_as_sold_evidence(tmp_path, monkeypatch):
    from src.db.database import Database
    fs = _load_script("collect_flea_sold_prices")
    db = Database(str(tmp_path / "f.db"))
    db.init_schema()
    db.connection.execute("INSERT INTO products (id, name, genre, brand, retail_price, is_active, keywords,"
                          " created_at, updated_at) VALUES ('prod_gr4','RICOH GR IV','camera','RICOH',194800,1,"
                          "'[]','2026-10-01','2026-10-01')")
    db.connection.commit()
    fresh = (datetime.now(JST) - timedelta(days=1)).isoformat()
    csv = ("product_alias,source,price,condition,title,item_url,observed_at,sold_at\n"
           f"gr4,yahoo_auction,230000,new_unopened,RICOH GR IV 新品,https://auctions.yahoo.co.jp/jp/auction/x000000001,{fresh},{fresh}\n"
           f"gr4,yahoo_auction,231000,new_unopened,RICOH GR IV 新品,{ITEM},{fresh},\n"
           f"gr4,yahoo_auction,232000,new_unopened,RICOH GR IV 新品,{ITEM},{fresh},{fresh}\n")
    (tmp_path / "flea.csv").write_text(csv, encoding="utf-8")
    monkeypatch.setattr(fs, "CSV_PATH", tmp_path / "flea.csv")
    monkeypatch.setattr(fs, "DB_PATH", tmp_path / "f.db")
    monkeypatch.setattr(fs, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr("sys.argv", ["x", "--sources", "yahoo"])
    assert fs.main() == 0
    out = json.loads((tmp_path / "out/yahoo_sold.json").read_text(encoding="utf-8"))
    items = {it["price"]: it for it in out["products"]["gr4"]["items"]}
    assert items[230000]["rejection_reason"].startswith("no_sold_evidence") and "dummy_url" in items[230000]["rejection_reason"]
    assert "no_sold_at" in items[231000]["rejection_reason"]
    assert items[232000]["rejection_reason"] == "" and items[232000]["price_type"] == pt.SOLD
    rows = sqlite3.connect(str(tmp_path / "f.db")).execute(
        "SELECT sale_price, price_type, sold_at FROM sale_prices").fetchall()
    assert rows == [(232000, "SOLD", fresh)]                         # 根拠のある1件だけを SOLD で保存


def test_current_manual_flea_sold_csv_has_no_sold_evidence():
    """今の data/manual_flea_sold_prices.csv はダミー URL・成約日時なしで、どの行も成約にならない。"""
    import csv as _csv
    with open(ROOT / "data/manual_flea_sold_prices.csv", encoding="utf-8") as f:
        rows = list(_csv.DictReader(ln for ln in f if not ln.lstrip().startswith("#")))
    assert rows and all(pt.sold_evidence_reasons(r["item_url"], r.get("sold_at")) for r in rows)


# ── 表示・deploy-check ────────────────────────────────────────────────────

def test_basis_display_marks_sold_without_evidence():
    assert pt.basis_display("成約価格") == "成約価格（根拠未確認）"
    assert pt.basis_display("海外sold") == "海外sold（根拠未確認）"
    assert pt.basis_display("出品価格") == "出品価格"
    assert pt.basis_display("成約価格", has_evidence=True) == "成約価格"


def _dc(tmp_path, monkeypatch, npo=None, pr=None):
    dc = _load_script("deploy_check")
    root = tmp_path / "root"
    for sub in ("exports/normalized_price_observations", "exports/profit_routes", "data", "config"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "data/manual_buyback_prices.csv").write_text(
        "product_alias,buyback_shop,buyback_price,condition,url,observed_at,data_source,link_verified,confidence\n",
        encoding="utf-8")
    (root / "config/product_source_configs.yaml").write_text("configs: []\n", encoding="utf-8")
    if npo is not None:
        (root / "exports/normalized_price_observations/latest.json").write_text(json.dumps(npo), encoding="utf-8")
    if pr is not None:
        (root / "exports/profit_routes/latest.json").write_text(json.dumps(pr), encoding="utf-8")
    (root / "scripts").symlink_to(ROOT / "scripts")
    monkeypatch.setattr(dc, "PROJECT_ROOT", root)
    return {r["check"]: r["level"] for r in dc._check_data_correctness()}


def test_deploy_check_detects_listing_as_sold(tmp_path, monkeypatch):
    bad = {"generated_at": "2026-10-03 12:00 JST", "observations": [
        {"price_role": "buy", "price_type": "flea_sold_price", "canonical_price_type": "SOLD", "product_id": "p",
         "source_name": "ヤフオク (新品/未使用落札)", "source_url": "https://auctions.yahoo.co.jp/search/search",
         "item_url": "", "sold_at": "", "is_usable_for_pro": True}]}
    pr = {"main_routes": [{"product_id": "p", "sell_source": "メルカリ", "sell_canonical_type": "LISTING"}]}
    lv = _dc(tmp_path, monkeypatch, npo=bad, pr=pr)
    assert lv["sold_price_has_evidence"] == "error"
    assert lv["main_route_sell_type_confirmed"] == "error"
    leak = {"generated_at": "x", "observations": [
        {"price_role": "buy", "price_type": "flea_listing_price", "canonical_price_type": "UNKNOWN", "product_id": "p",
         "source_name": "メルカリ sold", "is_usable_for_pro": True}]}
    assert _dc(tmp_path / "b", monkeypatch, npo=leak)["sold_label_without_evidence_unused"] == "error"
    # 否定対照: 根拠のある成約・買取が売値の main route は ok
    good = {"generated_at": "x", "observations": [
        {"price_role": "buy", "price_type": "flea_sold_price", "canonical_price_type": "SOLD", "product_id": "p",
         "source_name": "ヤフオク", "item_url": ITEM, "sold_at": "2026-10-01T20:00:00+09:00", "is_usable_for_pro": True}]}
    pr_ok = {"main_routes": [{"product_id": "p", "sell_source": "買取A", "sell_canonical_type": "BUYBACK_CASH"}]}
    lv = _dc(tmp_path / "c", monkeypatch, npo=good, pr=pr_ok)
    assert lv["sold_price_has_evidence"] == "ok" and lv["main_route_sell_type_confirmed"] == "ok"
    assert lv["sold_label_without_evidence_unused"] == "ok"


def test_ebay_aggregate_is_not_eligible_sold_median():
    """eBay の成約の中央値は件数はあるが成約日時・期間を持たないので、確定利益の売値にならない。"""
    assert not pt.is_sold_median_eligible({"price_type": pt.SOLD_MEDIAN, "status": "ok", "sample_count": 5,
                                           "period_start": "", "period_end": ""})


def test_repository_persists_price_type(tmp_path):
    from src.db.database import Database
    from src.db.repository import Repository
    from src.models.sale_price import SalePriceModel
    db = Database(str(tmp_path / "r.db"))
    db.init_schema()
    db.connection.execute("INSERT INTO products (id, name, genre, brand, retail_price, is_active, created_at,"
                          " updated_at) VALUES ('prod_gr4','GR IV','camera','RICOH',1,1,'2026-10-01','2026-10-01')")
    repo = Repository(db)
    repo.insert_sale_price(SalePriceModel(id="a", product_id="prod_gr4", product_alias="gr4", shop_name="ヤフオク (出品中・新品/未使用)",
                                          shop_id="y", sale_price=245000, observed_at=NOW, price_type="LISTING",
                                          sample_count=4))
    repo.insert_sale_price(SalePriceModel(id="b", product_id="prod_gr4", product_alias="gr4", shop_name="x", shop_id="z",
                                          sale_price=1000, observed_at=NOW, price_type="sold"))   # 正本以外の値
    got = {s.id: s for s in repo.list_sale_prices(product_alias="gr4", active_only=False)}
    assert (got["a"].price_type, got["a"].sample_count) == ("LISTING", 4)
    assert got["b"].price_type == "UNKNOWN"                                  # 推測で SOLD にしない


@pytest.mark.parametrize("empty_shown", [True, False])
def test_deploy_check_accepts_zero_candidates_only_with_empty_state(tmp_path, monkeypatch, empty_shown):
    """成約データが0件で候補が無い日は、空の状態（成約価格 未取得 / 想定利益 算出前）が出ていれば ok。
    出ていなければ従来どおり error（#622 #624 #625）。成約0件は #595 warning（出品で埋めない）。"""
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "exports").mkdir()
    for child in (ROOT / "exports").iterdir():                  # 読むだけ。2つだけ差し替える
        if child.name not in ("ai_opportunities", "profit_routes", "normalized_price_observations"):
            (root / "exports" / child.name).symlink_to(child)
    for n, payload in (("ai_opportunities", {"todays_opportunities": [], "generated_at": "x"}),
                       ("profit_routes", {"main_routes": [], "reference_routes": [], "summary": {},
                                          "zero_route_diagnostics": {}, "missing_data_priority": []}),
                       ("normalized_price_observations", {"generated_at": "x", "observations": []})):
        (root / "exports" / n).mkdir()
        (root / "exports" / n / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    body = "本日は候補がありません。成約価格が未取得の商品は、想定利益を算出前としています。" if empty_shown else ""
    (root / "docs/index.html").write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    for n in ("config", "data", "src", "scripts"):
        (root / n).symlink_to(ROOT / n)
    dc = _load_script("deploy_check")
    monkeypatch.setattr(dc, "PROJECT_ROOT", root)
    monkeypatch.setattr(dc, "PUBLIC_DIR", root / "docs")
    monkeypatch.setattr(dc, "__file__", str(root / "scripts" / "deploy_check.py"))   # 一部の検査は __file__ から root を決める
    lv = {r["check"]: r["level"] for r in dc.check()}
    want = "ok" if empty_shown else "error"
    assert (lv["ai_action"], lv["ai_timeline"], lv["ai_expected_prices"]) == (want, want, want)
    assert lv["npo_has_flea_sold"] == "warning"
    assert lv["lp_zero_stale_reason"] == "ok"                   # 参考ルートが無ければ説明する stale も無い


@pytest.mark.parametrize("title, keyword, ok", [
    ("Nintendo Switch 有機ELモデル 2024年購入 新品未開封", "Nintendo Switch 2", False),   # 「2」が「2024」に一致しない
    ("Nintendo Switch2 本体 新品未開封", "Nintendo Switch 2", True),
    ("RICOH GR IV デジタルカメラ 新品未開封", "RICOH GR IV", True),
    ("RICOH GR IV 新品 UNUSED", "RICOH GR IV", True),                               # 「used」は「unused」に一致しない
    ("RICOH GR IV Monochrome 新品", "RICOH GR IV", False),
    ("iPhone17 Pro Max[256GB] SIMフリー 新品未開封", "iPhone 17 Pro 256GB", False),   # Pro の検索に Pro Max を入れない
    ("iPhone 17 Pro 512GB 新品未開封", "iPhone 17 Pro 256GB", False),
    ("iPhone 17 Pro 256GB SIMフリー 新品未開封", "iPhone 17 Pro 256GB", True),
    ("PlayStation 5 新品未開封", "PlayStation 5 Pro", False),
    ("富士フイルム X100V 新品未開封", "富士フイルム X100VI", False),
    ("RICOH GR IIIx 新品", "RICOH GR IV", False),
    ("富士フイルムX100VI 新品未開封", "富士フイルム X100VI", True),                    # 日本語と英数字の境目
    ("新品未開封RICOH GR IV", "RICOH GR IV", True),
])
def test_yahoo_title_matching_uses_word_boundaries(title, keyword, ok):
    crp = _load_script("collect_resale_prices")
    assert crp.YahooAuctionResaleCollector._matches(title, keyword) is ok


def test_sedori_sell_options_only_confirmed_sell_types():
    """せどりルート（sedori_route_calculator）の売値にも、確定利益の売値の条件を効かせる。"""
    from src.market.normalized_prices import pro_sell_options
    base = {"product_id": "p", "price_role": "sell", "is_usable_for_pro": True}
    obs = [dict(base, price=300000, price_type="overseas_sold_price", canonical_price_type=pt.SOLD,
                sold_median_eligible=False),
           dict(base, price=200000, price_type="buyback_price", canonical_price_type=pt.BUYBACK_CASH),
           dict(base, price=310000, price_type="overseas_sold_price", canonical_price_type=pt.SOLD,
                sold_median_eligible=True)]
    assert [o["price"] for o in pro_sell_options(obs, "p")] == [310000, 200000]


def test_ebay_aggregate_is_not_saved_as_sold_median():
    src = (ROOT / "scripts/collect_resale_prices.py").read_text(encoding="utf-8")
    assert 'price_type="SOLD_MEDIAN"' not in src


def test_future_sold_at_is_not_evidence():
    future = (datetime.now(JST) + timedelta(days=10)).isoformat()
    assert "sold_at_in_future" in pt.sold_evidence_reasons(ITEM, future)


def test_legacy_sold_label_is_relabelled_for_display():
    msg = "📉 価格下落 / FUJIFILM X100VI / ヤフオク (新品/未使用落札) ¥343,637 → ¥312,000"
    out = pt.relabel_legacy(msg)
    assert "落札" not in out and "ヤフオク (出品中・新品/未使用)" in out
    src = (ROOT / "src/content/daily_lp_generator.py").read_text(encoding="utf-8")
    assert "_pt.relabel_legacy(e.get(\"message\")" in src        # 最新通知の表示で使う
