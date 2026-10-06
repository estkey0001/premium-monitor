"""Phase 0（データの正確さ・鮮度の偽装の防止）の回帰テスト。

2026-10-02 に公開 LP で見つかった誤りを、二度と出さないためのテスト。
各テストには「誤りを入れると失敗する」否定対照（negative control）も付ける。
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=JST)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── E1: 買取商店（見出しの「最高¥…」を商品の価格にしない） ───────────────────

KS_PAGE = """<html><body><div class="wrap">
<h1>スマホ 買取価格表</h1>
<h2>iPhone18 Pro Maxの買取価格表</h2><p class="num">新品買取 最高¥433,000／中古買取 最高¥345,000</p>
<ul>
<li><a href="/products/detail/1">iPhone 17 Pro Max 256GB コズミックオレンジ MFY94J/A SIMフリー</a> <span class="num">¥192,000</span></li>
<li><a href="/products/detail/2">iPhone 17 Pro Max 256GB シルバー MFY84J/A SIMフリー</a> <span class="num">¥191,000</span></li>
<li><a href="/products/detail/3">iPhone 17 Pro 256GB コズミックオレンジ MG864J/A SIMフリー</a> <span class="num">¥169,000</span></li>
<li><a href="/products/detail/4">iPhone 17 Pro 256GB ディープブルー MG874J/A SIMフリー</a> <span class="num">¥174,000</span></li>
<li><a href="/products/detail/5">iPhone 17 Pro 256GB シルバー MG854J/A au</a> <span class="num">¥180,000</span></li>
</ul>
<h2>カメラレンズの買取価格表</h2><p class="num">新品買取 最高¥900,000</p>
<ul>
<li><a href="/products/detail/7">Nintendo Switch 2 日本語・国内専用</a> <span class="num">¥53,300</span></li>
<li><a href="/products/detail/8">Nintendo Switch 2 マリオカート ワールドセット 日本語・国内専用</a> <span class="num">¥58,300</span></li>
<li><a href="/products/detail/9">マリオカート ワールド/Switch 2</a> <span class="num">¥8,100</span></li>
</ul></div></body></html>"""


def _ks():
    from src.collectors.buyback_kaitori_shouten import KaitoriShoutenCsvCollector
    return KaitoriShoutenCsvCollector()


def test_wrong_product_price_rejected():
    c = _ks()
    # Pro 256 は Pro の行だけから取る（Pro Max・キャリア版・見出しの最高値は使わない）
    assert c._parse_price(KS_PAGE, "iphone17pro256", "") == 174000
    assert c._parse_price(KS_PAGE, "iphone17pm256", "") == 192000
    # Switch 2 は本体だけ（セット品・ソフトを除く）
    assert c._parse_price(KS_PAGE, "switch2", "") == 53300


def test_same_model_wrong_capacity_rejected():
    c = _ks()
    # 512GB の行が無ければ未掲載。256GB の価格や見出しの価格で代用しない
    assert c._parse_price(KS_PAGE, "iphone17pro512", "") is None
    assert c.last_failure_reason == "product_not_listed"
    assert c._parse_price(KS_PAGE, "iphone17pm512", "") is None


def test_headline_only_page_gives_no_price():
    """否定対照: 商品行が無く見出しの「最高¥…」だけのページ → 価格なし（2026-10-02 の ¥435,000）。"""
    page = '<html><body><p class="num">新品買取 最高¥433,000</p><p>買取価格 ¥900,000</p></body></html>'
    c = _ks()
    for alias in ("iphone17pro256", "iphone17pm512", "switch2", "ps5_pro"):
        assert c._parse_price(page, alias, "") is None


# ── E1 の守り: 明らかな異常値を CSV に書く前に隔離する ─────────────────────────

def _row(alias, shop, price):
    return {"product_alias": alias, "buyback_shop": shop, "buyback_price": str(price),
            "condition": "new_unopened_simfree", "url": "u", "observed_at": NOW.isoformat(),
            "data_source": "auto_scraped", "link_verified": "true", "confidence": "high"}


def test_cross_product_same_price_quarantined():
    m = _load_script("update_buyback_prices")
    rows = [_row("iphone17pro256", "kaitori_shouten", 435000), _row("iphone17pm512", "kaitori_shouten", 435000),
            _row("iphone17pro256", "kaitori_itchome", 172000)]
    sus = m.compute_suspicious(rows, [])
    out = m.quarantine_suspicious(rows, sus)
    by = {(r["product_alias"], r["buyback_shop"]): r for r in out}
    assert by[("iphone17pro256", "kaitori_shouten")]["buyback_price"] == "0"
    assert by[("iphone17pro256", "kaitori_shouten")]["data_source"] == "suspicious_rejected"
    assert by[("iphone17pm512", "kaitori_shouten")]["buyback_price"] == "0"
    # 正常な行はそのまま
    assert by[("iphone17pro256", "kaitori_itchome")]["buyback_price"] == "172000"
    # 証拠（元の価格と理由）は一覧に残る
    assert any(s["price"] == 435000 and s.get("action") == "rejected" for s in sus)


def test_extreme_price_quarantined_but_market_move_kept():
    m = _load_script("update_buyback_prices")
    rows = [_row("switch2", "kaitori_shouten", 900000), _row("iphone17pm256", "geo_mobile", 230000)]
    prev = [_row("iphone17pm256", "geo_mobile", 180000)]     # 前回比 +27%（相場の変動はありうる）
    sus = m.compute_suspicious(rows, prev)
    out = {(r["product_alias"], r["buyback_shop"]): r for r in m.quarantine_suspicious(rows, sus)}
    assert out[("switch2", "kaitori_shouten")]["buyback_price"] == "0"      # 定価の18倍・ジャンル上限超え
    assert out[("iphone17pm256", "geo_mobile")]["buyback_price"] == "230000"  # 変動だけでは隔離しない


def test_quarantined_row_not_imported(tmp_path):
    """隔離した行（price=0, suspicious_rejected）は DB に入らない → 利益・ROI・ランキング・BUY に入らない。"""
    from src.db.database import Database
    from src.db.repository import Repository
    from src.market.buyback_csv_importer import BuybackCSVImporter
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    repo = Repository(db)
    from src.market.buyback_csv_importer import ALIAS_MAP
    pid = ALIAS_MAP.get("iphone17pro256", "prod_iphone17pro256")
    db.connection.execute("INSERT INTO products (id, name, genre, brand, retail_price, is_active, created_at, updated_at) "
                          "VALUES (?, 'iPhone 17 Pro 256GB', 'iphone', 'Apple', 179800, 1, 'x', 'x')", (pid,))
    db.connection.commit()
    imp = BuybackCSVImporter(repo)
    head = "product_alias,buyback_shop,buyback_price,condition,url,observed_at,data_source,link_verified,confidence\n"
    imp.import_csv(head + f"iphone17pro256,kaitori_shouten,0,new_unopened_simfree,u,{NOW.isoformat()},suspicious_rejected,false,low\n")
    n = db.connection.execute("SELECT COUNT(*) FROM buyback_prices").fetchone()[0]
    assert n == 0
    # 対照: 正常な行は取り込まれる（テストが空振りしていないことの確認）
    imp.import_csv(head + f"iphone17pro256,kaitori_itchome,172000,new_unopened_simfree,u,{NOW.isoformat()},auto_scraped,true,high\n")
    n = db.connection.execute("SELECT COUNT(*) FROM buyback_prices WHERE buyback_price > 0").fetchone()[0]
    assert n == 1


# ── E2: フジヤの下取り価格を現金買取にしない ─────────────────────────────────

FUJIYA_ITEM = ("FUJIFILM GFX100RF ブラック 富士フイルム 買取金額 新品同様 ￥474,000 良品 ￥473,000 "
               "下取は10%UP 新品同様 ￥521,400 良品 ￥520,300 買取申し込み")


def _cand(text, price):
    return {"price": price, "item_text": text, "near_buyback": True}


def test_trade_in_not_treated_as_cash_buyback():
    ucb = _load_script("update_camera_buyback")
    sel = ucb._select_camera_buyback([_cand(FUJIYA_ITEM, 521400), _cand(FUJIYA_ITEM, 474000)], "gfx100rf")
    assert sel["price"] == 474000
    assert sel["price_kind"] == "BUYBACK_CASH"


def test_trade_in_label_removed_is_detected():
    """否定対照: 「買取金額」の段が読めず下取の段しか無い → 価格を採用しない（最高値で代用しない）。"""
    ucb = _load_script("update_camera_buyback")
    text = FUJIYA_ITEM.replace("買取金額 新品同様 ￥474,000 良品 ￥473,000 ", "")
    sel = ucb._select_camera_buyback([_cand(text, 521400)], "gfx100rf")
    assert sel["price"] is None
    assert any(r["rejection_reason"] == "trade_in_or_conditional_only" for r in sel["rejected_candidates"])


@pytest.mark.parametrize("alias, text", [
    ("gr4", "GR IV 30th Anniversary Edition Kit（2026年10月21日発売予定） RICOH 買取金額 新品同様 ￥171,000"),
    ("gr3", "RICOH GR III Street Edition Special Limited Kit RICOH 買取金額 新品同様 ￥144,000"),
    ("x100vi", "FUJIFILM X100VI Limited Edition 富士フイルム 買取金額 新品同様 ￥200,000"),
    ("r5ii", "EOS R5 Mark II RF24-105L IS USM レンズキット Canon 買取金額 新品同様 ￥472,000"),
    ("gr3x", "RICOH GR IIIx HDF RICOH 買取金額 新品同様 ￥152,000"),
    ("q3", "ライカ Q3 43 19085 Leica 買取金額 新品同様 ￥860,000"),
    ("m11", "ライカ M11-P Safari 20236 Leica 買取金額 新品同様 ￥1,161,000"),
])
def test_special_edition_or_kit_not_matched(alias, text):
    ucb = _load_script("update_camera_buyback")
    assert ucb._strict_model_match(text, alias) is False


def test_standard_body_still_matched():
    ucb = _load_script("update_camera_buyback")
    assert ucb._strict_model_match("RICOH GR IV RICOH 買取金額 新品同様 ￥151,000", "gr4")
    assert ucb._strict_model_match("EOS R5 Mark II ボディー Canon 買取金額 新品同様 ￥372,000", "r5ii")
    assert ucb._strict_model_match("FUJIFILM GFX100RF ブラック 富士フイルム 買取金額", "gfx100rf")


# ── E3: RICOH の定価を別商品に割り当てない ───────────────────────────────────

def _ricoh_block(name, code, price):
    return (f'<div class="product__item--detail"><a href="/Form/Product/ProductDetail.aspx?shop=0&pid={code}">'
            f'{name}【1年保証】</a> 商品コード：{code} 定価 <span class="product__price--numeric">¥{price:,}</span>'
            f'<span class="product__status-text">抽選販売</span></div>')


RICOH_PAGE = "<html><body>" + "".join([
    _ricoh_block("RICOH GR IV 30th Anniversary Edition Kit", "S0001522", 259800),
    _ricoh_block("RICOH GR IV Monochrome", "S0001580", 299800),
    _ricoh_block("RICOH GR IV HDF", "S0001566", 222000),
    _ricoh_block("RICOH GR IV", "S0001551", 211800),
]) + "</body></html>"


def _ricoh_parse(page, keywords):
    from src.collectors.official.ricoh import RicohOfficialCollector
    c = RicohOfficialCollector.__new__(RicohOfficialCollector)
    return c._parse(page, SimpleNamespace(id="x", name="x", keywords=keywords, retail_price=None), "u")


def test_ricoh_products_keep_independent_bindings():
    assert _ricoh_parse(RICOH_PAGE, ["GR IV", "GR4", "GRIV"])["price"] == 211800
    assert _ricoh_parse(RICOH_PAGE, ["GR IV HDF", "S0001566"])["price"] == 222000
    assert _ricoh_parse(RICOH_PAGE, ["GR IV Monochrome", "S0001580"])["price"] == 299800


def test_ricoh_no_matching_card_gives_no_price():
    """否定対照: 一致するカードが無い → ページ先頭の価格（¥259,800）で代用しない。"""
    r = _ricoh_parse(RICOH_PAGE, ["GR IIIx", "GR3x"])
    assert r["price"] is None
    assert r["raw"]["price_method"] == "no_matching_card"


def test_ricoh_ambiguous_match_gives_no_price():
    page = "<html><body>" + _ricoh_block("RICOH GR IV", "S1", 211800) + _ricoh_block("RICOH GR IV", "S2", 199000) + "</body></html>"
    r = _ricoh_parse(page, ["GR IV"])
    assert r["price"] is None and r["raw"]["price_method"] == "ambiguous_cards"


# ── E4: 固定値・設定値の定価に毎日の日時を付けない ───────────────────────────────

class _FakeConn:
    def __init__(self):
        self.updates = []

    def execute(self, sql, params=()):
        if sql.startswith("UPDATE products"):
            self.updates.append(params)
        return SimpleNamespace(fetchone=lambda: None)

    def commit(self):
        pass


def test_fixed_msrp_does_not_refresh_observed_at(monkeypatch):
    m = _load_script("audit_official_sources")
    # 実行日を遠い未来にしても、確認日は表に書いた日のまま（実行日から作らない）
    from datetime import datetime as _dt
    monkeypatch.setattr(m, "NOW", _dt(2099, 1, 1, tzinfo=m.JST))
    monkeypatch.setattr(m, "TODAY", "2099-01-01")
    c = _FakeConn()
    products = {"prod_iphone17_256": {"name": "iPhone 17 256GB SIMフリー", "model_number": "",
                                      "retail_price": 159800}}
    m.register_verified(c, products)
    assert c.updates, "固定値の価格が反映されていない"
    for price, source, updated_at, pid in c.updates:
        assert updated_at == m.VERIFIED_URLS[pid].get("checked_on", m.VERIFIED_URLS_CHECKED_ON)   # 確認した日
        assert "2099" not in updated_at                                                          # 実行日ではない


def test_official_not_sold_drops_verified_price():
    """公式で販売終了・後継機に交代した商品は、過去の確認済み定価を外す（設定値の参考価格に戻る）。"""
    m = _load_script("audit_official_sources")
    c = _FakeConn()
    products = {"prod_iphone17pro_256": {"name": "iPhone 17 Pro 256GB SIMフリー", "model_number": "",
                                         "retail_price": 179800}}
    m.register_verified(c, products)
    assert "prod_iphone17pro_256" not in m.VERIFIED_URLS and "prod_iphone17pro_256" in m.OFFICIAL_NOT_SOLD
    assert c.updates == [("prod_iphone17pro_256",)]          # official_price を NULL にする UPDATE だけ


def _npo_db(tmp_path, official_updated_at):
    from src.db.database import Database
    db = Database(str(tmp_path / "n.db"))
    db.init_schema()
    c = db.connection
    c.execute("INSERT INTO products (id, name, genre, brand, retail_price, official_price, "
              "official_price_updated_at, is_active, created_at, updated_at) "
              "VALUES ('p1','A','camera','B',100000,120000,?,1,'x','x')", (official_updated_at,))
    c.execute("INSERT INTO products (id, name, genre, brand, retail_price, is_active, created_at, updated_at) "
              "VALUES ('p2','C','camera','B',50000,1,'x','x')")
    c.commit()
    return c


def test_page_generation_does_not_refresh_observation_time(tmp_path):
    from src.market.normalized_prices import build_observations
    c = _npo_db(tmp_path, "2026-08-23")
    obs = {o["product_id"]: o for o in build_observations(c, now=NOW) if o["price_role"] == "official"}
    assert obs["p1"]["observed_at"] == "2026-08-23"              # 確認日のまま
    assert obs["p1"]["observed_at"] != NOW.isoformat()
    assert obs["p1"]["is_fresh"] is True                        # 定価は 180日まで有効
    assert obs["p2"]["observed_at"] == ""                       # 設定値には日時を付けない
    assert "設定値" in obs["p2"]["price_context"]


def test_old_official_price_becomes_stale(tmp_path):
    from src.market.normalized_prices import build_observations
    c = _npo_db(tmp_path, "2025-12-01")
    obs = {o["product_id"]: o for o in build_observations(c, now=NOW) if o["price_role"] == "official"}
    assert obs["p1"]["is_fresh"] is False


# ── E5: 手動 CSV の「値は同じで日時だけ新しい」更新を検出する ──────────────────────

HDR = "product_alias,source,price_type,price,currency,condition,is_sold,url,observed_at,data_source,link_verified,price_basis\n"


def test_manual_unchanged_price_timestamp_refresh_detected():
    from src.market.freshness_guard import timestamp_only_updates
    old = HDR + "gr4,ebay,overseas,1850,USD,new,true,u,2026-07-22T10:00:00+09:00,manual_today,true,海外sold\n"
    new = HDR + "gr4,ebay,overseas,1850,USD,new,true,u,2026-08-22T10:00:00+09:00,manual_today,true,海外sold\n"
    v = timestamp_only_updates(old, new, "data/manual_market_prices.csv")
    assert len(v) == 1 and v[0].old_ts.startswith("2026-07-22")


def test_manual_changed_price_is_not_violation():
    """否定対照: 価格が変わった（実際に再取得した）更新は違反ではない。"""
    from src.market.freshness_guard import timestamp_only_updates
    old = HDR + "gr4,ebay,overseas,1850,USD,new,true,u,2026-07-22T10:00:00+09:00,manual_today,true,海外sold\n"
    new = HDR + "gr4,ebay,overseas,1790,USD,new,true,u,2026-08-22T10:00:00+09:00,manual_today,true,海外sold\n"
    assert timestamp_only_updates(old, new) == []


def test_auto_scraped_reobservation_is_not_violation():
    from src.market.freshness_guard import timestamp_only_updates
    h = "product_alias,buyback_shop,buyback_price,condition,url,observed_at,data_source,link_verified,confidence\n"
    old = h + "iphone17pro256,kaitori_itchome,172000,new,u,2026-10-01T12:00:00+09:00,auto_scraped,true,high\n"
    new = h + "iphone17pro256,kaitori_itchome,172000,new,u,2026-10-02T12:00:00+09:00,auto_scraped,true,high\n"
    assert timestamp_only_updates(old, new) == []


def test_current_head_has_no_new_timestamp_only_update():
    """作業ツリーの手動 CSV に、日時だけ新しくした変更が無い（コミット前の確認）。"""
    m = _load_script("audit_timestamp_only_updates")
    assert m.audit_worktree() == []


# ── E6: 取得に失敗した時刻を「最終更新」にしない ────────────────────────────────

def test_failed_collection_does_not_refresh_last_success(tmp_path):
    from src.db.database import Database
    from src.db.repository import Repository
    db = Database(str(tmp_path / "r.db"))
    db.init_schema()
    c = db.connection
    c.execute("INSERT INTO products (id, name, genre, brand, retail_price, is_active, created_at, updated_at) "
              "VALUES ('p','A','iphone','B',1,1,'x','x')")
    rows = [("a", 172000, "2026-10-01T12:00:00+09:00", "auto_scraped"),
            ("b", 0, "2026-10-02T12:00:00+09:00", "fetch_failed"),
            ("c", 0, "2026-10-02T12:05:00+09:00", "suspicious_rejected")]
    cols = {r[1] for r in c.execute("PRAGMA table_info(buyback_prices)").fetchall()}
    for rid, price, at, src in rows:
        data = {"id": rid, "product_id": "p", "shop_id": "s", "shop_name": "S", "buyback_price": price,
                "condition": "new", "observed_at": at, "data_source": src, "is_active": 1}
        data = {k: v for k, v in data.items() if k in cols}
        c.execute(f"INSERT INTO buyback_prices ({','.join(data)}) VALUES ({','.join('?' * len(data))})",
                  tuple(data.values()))
    c.commit()
    latest = Repository(db).get_latest_buyback_observed_at()
    assert latest is not None and latest.isoformat().startswith("2026-10-01T12:00")


# ── E7: required の店の取得失敗を「対象外」にしない ─────────────────────────────

def test_required_failed_source_remains_quality_failure():
    m = _load_script("generate_data_quality_dashboard")
    for required in ("モバイル一番", "買取一丁目", "買取商店", "イオシス", "ネットオフ"):
        assert required not in m.UNSUPPORTED_SHOPS
    # 対象外は CLAUDE.md の OPTIONAL_SHOPS に入っている店だけ
    assert {"じゃんぱら", "ゲオモバイル", "TSUTAYA"} <= m.UNSUPPORTED_SHOPS


def test_failed_run_keeps_last_success_in_report(tmp_path, monkeypatch):
    """店ごとの記録: 失敗した回は last_attempt_at だけ更新し、last_success_at は前回の値のまま。"""
    import json
    m = _load_script("update_buyback_prices")
    monkeypatch.setattr(m, "REPORT_DIR", tmp_path)
    t1 = datetime(2026, 10, 1, 12, 0, tzinfo=JST)
    ok_row = _row("iphone17pro256", "kaitori_itchome", 172000)
    ok_row["observed_at"] = t1.isoformat()
    m._generate_collector_report(new_rows=[ok_row], results_summary=[("iphone17pro256", "kaitori_itchome", "OK", 172000)],
                                 now_jst=t1, existing_rows=[], failure_reasons={}, suspicious_prices=[])
    t2 = datetime(2026, 10, 2, 12, 0, tzinfo=JST)
    fail_row = {**ok_row, "buyback_price": "0", "data_source": "fetch_failed", "observed_at": t2.isoformat()}
    m._generate_collector_report(new_rows=[fail_row], results_summary=[("iphone17pro256", "kaitori_itchome", "FAILED", 0)],
                                 now_jst=t2, existing_rows=[ok_row], failure_reasons={("iphone17pro256", "kaitori_itchome"): "http_403"},
                                 suspicious_prices=[])
    d = {x["shop_id"]: x for x in json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["shop_detail"]}
    shop = d["kaitori_itchome"]
    assert shop["last_attempt_at"].startswith("2026-10-02T12:00")
    assert shop["last_success_at"].startswith("2026-10-01T12:00")   # 失敗した回で更新しない
    assert shop["last_observed_at"].startswith("2026-10-01T12:00")


# ── 再レビュー（HIGH / MEDIUM）の回帰テスト ─────────────────────────────

@pytest.mark.parametrize("alias, text, ok", [
    ("q3", "ライカ Q3 19081 Leica 買取金額 新品同様 ￥586,000", True),
    ("q3", "ライカ Q3 メタルグレーペイント 19211 Leica 買取金額 新品同様 ￥841,000", False),
    ("q3", "ライカ Q3 モノクローム 19201 Leica 買取金額 新品同様 ￥812,000", False),
    ("q3", "Q3モノクローム用 ワイヤレスチャージャー対応ハンドグリップ HG-DC1 19697 Leica 買取金額", False),
    ("q3", "Leica Q3 43 EU/US/CN バージョン Leica 買取金額 新品同様 ￥768,000", False),
    ("m11", "ライカ M11 グロッシーブラック 20231 Leica 買取金額 新品同様 ￥986,000", False),
    ("m11", "ライカ M11モノクローム 20209 Leica 買取金額 新品同様 ￥940,000", False),
    # M11 は商品コードが公式資料で未確認（UNVERIFIED）→ どのコードでも結びつけない
    ("m11", "ライカ M11 ブラック 20200 Leica 買取金額 新品同様 ￥900,000", False),
    ("m11", "ライカ M11 ブラック 20202 Leica 買取金額 新品同様 ￥900,000", False),
    # Q3: 公式の日本向け通常版（19081）だけ。海外向け 19080 / 19082・未知のコードは結びつけない
    ("q3", "ライカ Q3 19080 Leica 買取金額 新品同様 ￥586,000", False),
    ("q3", "ライカ Q3 19082 Leica 買取金額 新品同様 ￥586,000", False),
    ("q3", "ライカ Q3 19099 Leica 買取金額 新品同様 ￥586,000", False),
    ("q3", "ライカ Q3 190811 Leica 買取金額 新品同様 ￥586,000", False),
    # 別の Leica SKU（M11 の通常版コードを書いた Q3 以外の行）は Q3 にならない
    ("q3", "ライカ M11 19081 Leica 買取金額 新品同様 ￥900,000", False),
    ("r5ii", "EOS R5 Mark II ボディー 海外モデル Canon 買取金額 新品同様 ￥350,000", False),
])
def test_leica_and_overseas_variants(alias, text, ok):
    ucb = _load_script("update_camera_buyback")
    assert ucb._strict_model_match(text, alias) is ok


def test_ricoh_gr3_not_bound_to_gr3x_card():
    page = "<html><body>" + _ricoh_block("RICOH GR IIIx", "S0001520", 149800) + "</body></html>"
    assert _ricoh_parse(page, ["GR III", "GR3"])["price"] is None          # 部分一致しない
    assert _ricoh_parse(page, ["GR IIIx", "GR3x"])["price"] == 149800


def test_ricoh_japanese_limited_set_not_bound():
    page = "<html><body>" + _ricoh_block("RICOH GR IV 限定セット", "S9", 230000) + "</body></html>"
    assert _ricoh_parse(page, ["GR IV"])["price"] is None


KS_CATEGORY = """<html><body><table><tr><th>品目</th><th>新品買取</th><th>中古買取</th></tr>
<tr><td><a href="/products/detail/24674">iPhone 17 Pro 256GB シルバー MG854J/A SIMフリー</a><span>強化</span></td>
<td class="num">¥174,000</td><td class="num">¥145,000</td></tr>
<tr><td><a href="/products/detail/24675">iPhone 17 Pro 512GB コズミックオレンジ MG8A4J/A SIMフリー</a></td>
<td class="num">¥200,000</td><td class="num">¥170,000</td></tr>
</table></body></html>"""


def test_kaitori_category_page_reads_new_column():
    c = _ks()
    assert c._parse_price(KS_CATEGORY, "iphone17pro512", "") == 200000    # 中古の ¥170,000 ではない
    assert c._parse_price(KS_CATEGORY, "iphone17pro256", "") == 174000


def test_legacy_buyback_refresh_disabled():
    from src.jobs.buyback_premium_job import BuybackPremiumJob
    job = BuybackPremiumJob.__new__(BuybackPremiumJob)
    job.repo = SimpleNamespace(list_products=lambda: pytest.fail("旧 collector が動いた"))
    assert job._refresh_buyback_prices() == 0


def test_freshness_guard_source_rewrite_and_unrelated_column():
    from src.market.freshness_guard import timestamp_only_updates
    h = "product_alias,buyback_shop,buyback_price,condition,url,observed_at,data_source,link_verified,confidence\n"
    old = h + "gr4,fujiya,151000,new,u,2026-07-22T10:00:00+09:00,manual_today,true,high\n"
    # data_source を auto_scraped に書き換えても見逃さない
    new1 = h + "gr4,fujiya,151000,new,u,2026-08-22T10:00:00+09:00,auto_scraped,true,high\n"
    assert len(timestamp_only_updates(old, new1)) == 1
    # 価格と関係ない列（confidence）を変えても見逃さない
    new2 = h + "gr4,fujiya,151000,new,u,2026-08-22T10:00:00+09:00,manual_today,true,mid\n"
    assert len(timestamp_only_updates(old, new2)) == 1
    # タイムゾーンが違っても、実際に新しければ検出する
    new3 = h + "gr4,fujiya,151000,new,u,2026-08-22T01:00:00Z,manual_today,true,high\n"
    assert len(timestamp_only_updates(old, new3)) == 1


def test_header_time_uses_last_success_not_generation():
    from src.content.daily_lp_generator import DailyLPGenerator
    report = {"generated_at": "2026-10-02T12:30:00+09:00",
              "source_health": [{"last_success": "2026-10-02T11:05:00+09:00"},
                                {"last_success": None}, {"last_success": "2026-10-01T22:00:00+09:00"}]}
    assert DailyLPGenerator._nu_data_checked_text(report) == "10/02 11:05"
    # 全部失敗したら時刻を出さない（収集を実行した時刻で「確認」に見せない）
    assert DailyLPGenerator._nu_data_checked_text({"generated_at": "2026-10-02T12:30:00+09:00",
                                                    "source_health": [{"last_success": None}]}) == ""


def test_warn_bar_rejected_only_is_not_price_problem():
    """隔離した価格（rejected）だけのときは「価格の精度に問題」にしない（公開していないので）。
    （旧UIの取得の警告バーの後継は運営者向けの取得の警告 admin.collector_warn。分類・順序は同じ）"""
    from src.content.ui import admin
    w = admin.collector_warn({"summary": {}, "shop_detail": [], "suspicious_prices": [
        {"product_alias": "a", "shop": "s", "price": 1, "reason": "above_genre_max", "action": "rejected"}]}, set(), 5)
    assert w["level"] == "rejected" and w["status"] == admin.INFO and w["suspicious"] == 0
    assert "公開していない" in admin._sources({"overview": {"warn": w}, "shops": [], "tcg": [], "lot_sources": [],
                                           "lot_coverage": {}, "resale": [], "flea": [], "resale_collected": None,
                                           "collector_generated": None})


# ── deploy-check #820〜#825 そのもの（否定対照つき） ─────────────────────────

def _dc_with(tmp_path, monkeypatch, *, csv_rows, suspicious, npo=None, cam=None):
    import json
    dc = _load_script("deploy_check")
    root = tmp_path
    for sub in ("exports/collector_report", "exports/normalized_price_observations", "data", "config"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "exports/collector_report/latest.json").write_text(json.dumps({"suspicious_prices": suspicious}), encoding="utf-8")
    h = "product_alias,buyback_shop,buyback_price,condition,url,observed_at,data_source,link_verified,confidence\n"
    (root / "data/manual_buyback_prices.csv").write_text(h + "".join(csv_rows), encoding="utf-8")
    if npo is not None:
        (root / "exports/normalized_price_observations/latest.json").write_text(json.dumps(npo), encoding="utf-8")
    if cam is not None:
        (root / "exports/camera_buyback_status.json").write_text(json.dumps(cam), encoding="utf-8")
    (root / "config/product_source_configs.yaml").write_text(
        (ROOT / "config/product_source_configs.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    # scripts と src は本物を使う
    (root / "scripts").symlink_to(ROOT / "scripts")
    monkeypatch.setattr(dc, "PROJECT_ROOT", root)
    return {r["check"]: r["level"] for r in dc._check_data_correctness()}


def test_deploy_check_820_detects_leaked_rejected_price(tmp_path, monkeypatch):
    bad = [{"product_alias": "iphone17pro256", "shop": "kaitori_shouten", "price": 435000, "reason": "above_genre_max"}]
    leaked = _dc_with(tmp_path, monkeypatch, suspicious=bad,
                      csv_rows=["iphone17pro256,kaitori_shouten,435000,new,u,2026-10-02T12:00:00+09:00,auto_scraped,true,high\n"])
    assert leaked["no_rejected_price_published"] == "error"


def test_deploy_check_820_ok_when_quarantined(tmp_path, monkeypatch):
    bad = [{"product_alias": "iphone17pro256", "shop": "kaitori_shouten", "price": 435000, "reason": "above_genre_max"}]
    r = _dc_with(tmp_path, monkeypatch, suspicious=bad,
                 csv_rows=["iphone17pro256,kaitori_shouten,0,new,u,2026-10-02T12:00:00+09:00,suspicious_rejected,false,low\n"])
    assert r["no_rejected_price_published"] == "ok"


def test_deploy_check_821_detects_generation_timestamp(tmp_path, monkeypatch):
    """否定対照: 修正前の形（公式価格が全部「生成時刻」を持つ。生成時刻は「… JST」形式）→ error。"""
    ts = "2026-10-02T11:37:28.159872+09:00"
    npo = {"generated_at": "2026-10-02 11:37 JST", "observations": [
        {"price_role": "official", "product_id": f"p{i}", "observed_at": ts, "price": 1000 + i,
         "extraction_method": "official"} for i in range(5)]}
    r = _dc_with(tmp_path, monkeypatch, suspicious=[], csv_rows=[], npo=npo)
    assert r["official_price_not_generation_time"] == "error"
    npo["observations"] = [{"price_role": "official", "product_id": f"p{i}", "observed_at": "2026-08-23",
                            "price": 1000 + i, "extraction_method": "official"} for i in range(5)]
    (tmp_path / "exports/normalized_price_observations/latest.json").write_text(__import__("json").dumps(npo), encoding="utf-8")
    dc = _load_script("deploy_check")
    monkeypatch.setattr(dc, "PROJECT_ROOT", tmp_path)
    assert {x["check"]: x["level"] for x in dc._check_data_correctness()}["official_price_not_generation_time"] == "ok"


def test_deploy_check_824_detects_trade_in_and_kit(tmp_path, monkeypatch):
    cam = {"generated_at": datetime.now(JST).isoformat(), "detail": [
        {"status": "OK", "shop_id": "src_fujiya", "product_alias": "gfx100rf", "price": 521400, "matched_item": FUJIYA_ITEM},
        {"status": "OK", "shop_id": "src_fujiya", "product_alias": "gr4", "price": 171000,
         "matched_item": "GR IV 30th Anniversary Edition Kit RICOH 買取金額 新品同様 ￥171,000"}]}
    r = _dc_with(tmp_path, monkeypatch, suspicious=[], csv_rows=[], cam=cam)
    assert r["camera_cash_buyback_only"] == "error"


def test_deploy_check_825_detects_shared_ricoh_msrp(tmp_path, monkeypatch):
    npo = {"generated_at": "2026-10-02 11:37 JST", "observations": [
        {"price_role": "official", "product_id": p, "observed_at": f"2026-10-02T1{i}:00:00", "price": 259800,
         "extraction_method": "official"} for i, p in enumerate(("prod_gr4", "prod_gr4_hdf", "prod_gr4_mono"))]}
    r = _dc_with(tmp_path, monkeypatch, suspicious=[], csv_rows=[], npo=npo)
    assert r["official_price_not_shared_across_products"] == "error"


def test_freshness_guard_normalizes_price_format_and_url_query():
    from src.market.freshness_guard import timestamp_only_updates
    old = HDR + "gr4,ebay,overseas,1850,USD,new,true,https://e.com/s?q=1,2026-07-22T10:00:00+09:00,manual_today,true,海外sold\n"
    new = HDR + "gr4,ebay,overseas,\"1,850\",USD,new,true,https://e.com/s?q=2,2026-08-22T10:00:00+09:00,manual_today,true,海外sold\n"
    assert len(timestamp_only_updates(old, new)) == 1


def test_last_success_is_observation_time_not_run_start(tmp_path, monkeypatch):
    import json
    m = _load_script("update_buyback_prices")
    monkeypatch.setattr(m, "REPORT_DIR", tmp_path)
    run_start = datetime(2026, 10, 2, 15, 48, 5, tzinfo=JST)
    row = _row("iphone17pro256", "kaitori_shouten", 174000)
    row["observed_at"] = "2026-10-02T15:49:42+09:00"
    m._generate_collector_report(new_rows=[row], results_summary=[("iphone17pro256", "kaitori_shouten", "OK", 174000)],
                                 now_jst=run_start, existing_rows=[], failure_reasons={}, suspicious_prices=[])
    d = {x["shop_id"]: x for x in json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["shop_detail"]}
    assert d["kaitori_shouten"]["last_success_at"] == "2026-10-02T15:49:42+09:00"


def test_warn_bar_price_move_only_is_soft():
    from src.content.ui import admin
    w = admin.collector_warn({"summary": {}, "shop_detail": [], "suspicious_prices": [
        {"product_alias": "ps5_pro", "shop": "kaitori_shouten", "price": 191700,
         "reason": "price_change_over_20pct"}]}, set(), 5)
    assert w["level"] == "moves" and w["status"] == admin.WARN
    # 対照: 誤りの可能性が高い理由（隔離されていない）なら強い警告
    w2 = admin.collector_warn({"summary": {}, "shop_detail": [], "suspicious_prices": [
        {"product_alias": "switch2", "shop": "x", "price": 900000, "reason": "above_genre_max"}]}, set(), 5)
    assert w2["level"] == "strong" and w2["status"] == admin.FAIL


def test_ricoh_english_bundle_not_bound():
    page = "<html><body>" + _ricoh_block("RICOH GR IV Street Package", "S0001599", 245000) + "</body></html>"
    assert _ricoh_parse(page, ["GR IV", "GR4", "GRIV"])["price"] is None


def test_deploy_check_824_stale_status_is_warning(tmp_path, monkeypatch):
    """カメラの取得が失敗して古い状態ファイルが残った場合は、公開を止めずに warning にする。"""
    cam = {"generated_at": "2026-09-01T10:00:00+09:00", "detail": [
        {"status": "OK", "shop_id": "src_fujiya", "product_alias": "gfx100rf", "price": 521400, "matched_item": FUJIYA_ITEM}]}
    r = _dc_with(tmp_path, monkeypatch, suspicious=[], csv_rows=[], cam=cam)
    assert r["camera_cash_buyback_only"] == "warning"


def test_ricoh_description_words_do_not_exclude_normal_card():
    page = ('<html><body><div class="product__item--detail"><a href="/Form/Product/ProductDetail.aspx?pid=S0001551">'
            'RICOH GR IV【1年保証】</a> セットアップが簡単。パッケージ同梱の説明 '
            '<span class="product__price--numeric">¥211,800</span></div></body></html>')
    assert _ricoh_parse(page, ["GR IV"])["price"] == 211800


def test_hard_reject_reasons_single_source():
    m = _load_script("update_buyback_prices")
    from src.market.price_quality import HARD_REJECT_REASONS
    assert m.HARD_REJECT_REASONS is HARD_REJECT_REASONS
