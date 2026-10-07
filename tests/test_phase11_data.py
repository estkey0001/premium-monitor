"""Phase 11（本番データの拡充・取得元の網羅）のテスト。

- 買取商店: 照合できる商品の追加（iPhone 17 256GB・iPhone 16 Pro 256GB・AirPods Pro 3）と商品ページの URL
- 買取一丁目: ページ全体の最高値などの緩いフォールバックを使わない
- フジヤカメラ: 「新品同様」（中古の等級）を新品未開封として保存しない
- ネットオフ: 条件付き（特典適用後）の価格を取らない
- 公式で販売していない商品（OFFICIAL_NOT_SOLD）と確認済みの定価（VERIFIED_URLS）が矛盾しない
- TCG の予約（PREORDER）: 抽選と混ぜない・在庫に入れない・日程が無ければ受付中と言わない
- 網羅の集計（production_coverage_metrics）の段階の数え方・規模
各テストには、誤りを入れると失敗する否定対照（mutation）も付ける。
"""

from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=JST)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"p11_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 買取商店 ─────────────────────────────────────────────────────────

# カテゴリページ（表）の形式。2026-10-07 の実ページの行の書き方に合わせた
KS_TABLE = """<html><body>
<table><tr><th>品目</th><th>新品買取</th><th>中古買取</th></tr>
<tr><td><a href="/products/detail/24693">iPhone 17 256GB ラベンダー MG6A4J/A SIMフリー</a></td><td class="num">¥139,000</td><td>—</td></tr>
<tr><td><a href="/products/detail/24697">iPhone 17 256GB ブラック MG674J/A SIMフリー</a></td><td class="num">¥138,000</td><td>—</td></tr>
<tr><td><a href="/products/detail/24698">iPhone 17 512GB ラベンダー MG6G4J/A SIMフリー</a></td><td class="num">¥158,000</td><td>—</td></tr>
<tr><td><a href="/products/detail/90001">iPhone 17 Pro 256GB シルバー MG854J/A SIMフリー</a></td><td class="num">¥172,000</td><td>—</td></tr>
<tr><td><a href="/products/detail/90002">iPhone 17 256GB ブラック docomo</a></td><td class="num">¥150,000</td><td>—</td></tr>
<tr><td><a href="/products/detail/90003">iPhone 17e 256GB ホワイト SIMフリー</a></td><td class="num">¥99,000</td><td>—</td></tr>
<tr><td><a href="/products/detail/20818">iPhone 16 Pro 256GB デザートチタニウム MYN23J/A SIMフリー</a></td><td class="num">¥164,000</td><td>—</td></tr>
<tr><td><a href="/products/detail/20802">iPhone 16 Pro Max 256GB デザートチタニウム MYWJ3J/A SIMフリー</a></td><td class="num">¥180,000</td><td>—</td></tr>
</table>
<ul>
<li><a href="/products/detail/24586">AirPods Pro 第3世代 MFHP4J/A</a> <span class="num">¥32,500</span></li>
<li><a href="/products/detail/11111">AirPods Pro 第2世代 MTJV3J/A</a> <span class="num">¥22,000</span></li>
<li><a href="/products/detail/11112">AirPods Pro 第3世代 MFHP4J/A 充電ケース</a> <span class="num">¥9,000</span></li>
</ul></body></html>"""


def _ks():
    from src.collectors.buyback_kaitori_shouten import KaitoriShoutenCsvCollector
    return KaitoriShoutenCsvCollector()


def test_kaitori_shouten_new_products_match_exactly():
    c = _ks()
    # 無印 iPhone 17 256GB SIMフリーの行だけ（Pro・17e・512GB・キャリア版は使わない）。色違いは最高値
    assert c._parse_price(KS_TABLE, "iphone17_256", "") == 139000
    assert {n for n, _p, _h in c.last_matched_rows} == {
        "iPhone 17 256GB ラベンダー MG6A4J/A SIMフリー", "iPhone 17 256GB ブラック MG674J/A SIMフリー"}
    # iPhone 16 Pro 256GB は Pro Max を拾わない
    assert c._parse_price(KS_TABLE, "iphone16pro256", "") == 164000
    # AirPods Pro 3 は型番まで一致する本体だけ（第2世代・ケースは使わない）
    assert c._parse_price(KS_TABLE, "airpods_pro3", "") == 32500


def test_kaitori_shouten_missing_product_is_not_listed():
    c = _ks()
    page = KS_TABLE.replace("AirPods Pro 第3世代 MFHP4J/A</a>", "AirPods 第5世代 MKFW4J/A</a>")
    assert c._parse_price(page, "airpods_pro3", "") is None
    assert c.last_failure_reason == "product_not_listed"


@pytest.mark.parametrize("alias,bad_row", [
    ("iphone17_256", '<tr><td><a href="/x">iPhone 17 Pro 256GB X SIMフリー</a></td><td class="num">¥999,000</td></tr>'),
    ("iphone17_256", '<tr><td><a href="/x">iPhone 17 256GB X au</a></td><td class="num">¥999,000</td></tr>'),
    ("iphone16pro256", '<tr><td><a href="/x">iPhone 16 Pro Max 256GB X SIMフリー</a></td><td class="num">¥999,000</td></tr>'),
    # SIM フリーと書かれていない行（海外版など）は使わない
    ("iphone17_256", '<tr><td><a href="/x">iPhone 17 256GB X 香港版</a></td><td class="num">¥999,000</td></tr>'),
    ("iphone16pro256", '<tr><td><a href="/x">iPhone 16 Pro 256GB X</a></td><td class="num">¥999,000</td></tr>'),
    # キャリア版の表記の大文字・小文字の違い
    ("iphone17_256", '<tr><td><a href="/x">iPhone 17 256GB X AU版 SIMフリー</a></td><td class="num">¥999,000</td></tr>'),
])
def test_kaitori_shouten_rules_reject_other_models(alias, bad_row):
    """否定対照: 別の機種・キャリア版の高い行を足しても、採用する価格は変わらない。"""
    c = _ks()
    before = c._parse_price(KS_TABLE, alias, "")
    page = KS_TABLE.replace("</table>", bad_row + "</table>")
    assert c._parse_price(page, alias, "") == before != 999000


def test_kaitori_shouten_source_url_is_product_page():
    """出典の URL は、採用した価格の行の商品ページ（一覧・カテゴリのページではない）。"""
    from src.market.normalized_prices import classify_link_type
    c = _ks()
    c._parse_price(KS_TABLE, "iphone17_256", "")
    url = c._parse_detail_url(KS_TABLE, "https://www.kaitorishouten-co.jp/category/1/708")
    assert url == "https://www.kaitorishouten-co.jp/products/detail/24693"
    assert classify_link_type(url, True, "sell") == "item"
    # 一致する行が無いときは一覧の URL のまま（別の商品のページを出典にしない）
    c._parse_price(KS_TABLE.replace("AirPods Pro 第3世代 MFHP4J/A</a>", "X</a>"), "airpods_pro3", "")
    assert c._parse_detail_url(KS_TABLE, "https://www.kaitorishouten-co.jp/kaden") == \
        "https://www.kaitorishouten-co.jp/kaden"


def test_kaitori_shouten_fetches_each_page_once(monkeypatch):
    """同じ一覧ページは1回の実行で1回だけ取る（アクセスを増やさない）。取得失敗は使い回さない。"""
    from src.collectors.buyback_base_csv import BaseCsvBuybackCollector
    calls = []

    def fake(self, url):
        calls.append(url)
        return None if "fail" in url else KS_TABLE

    monkeypatch.setattr(BaseCsvBuybackCollector, "_fetch_html", fake)
    c = _ks()
    for _ in range(3):
        assert c._fetch_html("https://www.kaitorishouten-co.jp/kaden") == KS_TABLE
        assert c._fetch_html("https://www.kaitorishouten-co.jp/fail") is None
    assert calls.count("https://www.kaitorishouten-co.jp/kaden") == 1
    assert calls.count("https://www.kaitorishouten-co.jp/fail") == 3


def test_kaitori_shouten_fetch_returns_detail_url_and_fresh_time(monkeypatch):
    c = _ks()
    monkeypatch.setattr(c, "_fetch_html", lambda url: KS_TABLE)
    r = c.fetch("airpods_pro3", "AirPods Pro 3", "new_unopened")
    assert r["buyback_price"] == 32500 and r["data_source"] == "auto_scraped"
    assert r["url"] == "https://www.kaitorishouten-co.jp/products/detail/24586"
    assert r["condition"] == "new_unopened"


# ── 確定の売値の判定（新しく取る行が確定を通り、条件が欠けると通らない） ──

def _sell_obs(url: str, condition: str = "new_unopened", data_source: str = "auto_scraped",
              age_days: float = 0.1):
    """build_observations と同じ組み立てで、買取価格1件の観測を作る。"""
    from src.market.normalized_prices import _extraction_method, classify_link_type, make_observation
    return make_observation(
        NOW, product_id="prod_airpods_pro3", product_name="AirPods Pro 3",
        source_id="src_kaitori_shouten", source_name="買取商店", market_type="domestic_buyback",
        price_role="sell", price_type="buyback_price", condition=condition, price=32500,
        observed_at=(NOW - timedelta(days=age_days)).isoformat(), confidence="high",
        source_url=url, item_url=url, link_type=classify_link_type(url, True, "sell"),
        extraction_method=_extraction_method(data_source), price_context="AirPods Pro 第3世代 MFHP4J/A")


DETAIL = "https://www.kaitorishouten-co.jp/products/detail/24586"


def test_new_buyback_row_is_confirmed_only_when_all_conditions_hold():
    from src.market.normalized_prices import sell_confirmation_reasons
    assert sell_confirmation_reasons(_sell_obs(DETAIL)) == []
    # 否定対照: 古い・手入力・店のトップ・検索結果・中古（新品同様）はどれも確定にしない
    assert "stale_sell_price" in sell_confirmation_reasons(_sell_obs(DETAIL, age_days=20))
    assert "sell_identity_unverified" in sell_confirmation_reasons(_sell_obs(DETAIL, data_source="manual_today"))
    assert "sell_identity_unverified" in sell_confirmation_reasons(_sell_obs("https://www.1-chome.com/"))
    assert "sell_url_not_item_level" in sell_confirmation_reasons(
        _sell_obs("https://www.fujiya-camera.co.jp/shop/purchase/list.aspx?keyword=GR"))
    assert "condition_mismatch" in sell_confirmation_reasons(_sell_obs(DETAIL, condition="used_s"))


# ── 自動取得の対象（update_buyback_prices） ─────────────────────────────

def test_new_targets_use_only_kaitori_shouten_and_have_known_ids():
    m = _load_script("update_buyback_prices")
    from src.market.buyback_csv_importer import ALIAS_MAP
    by = {p["product_alias"]: p for p in m.TARGET_PRODUCTS}
    for alias, pid in (("iphone17_256", "prod_iphone17_256"), ("iphone16pro256", "prod_iphone16pro_256"),
                       ("airpods_pro3", "prod_airpods_pro3")):
        assert by[alias]["shops"] == ["kaitori_shouten"]         # 取れない店へのアクセスを増やさない
        assert ALIAS_MAP[alias] == pid
        assert alias in m.OFFICIAL_PRICES and alias in m.PRODUCT_GENRES   # 異常値の判定が効く
    # 版・型番が特定できない商品は自動取得に入れない
    assert not {"iphone16pm_256", "iphone16pm_512", "switch2_mk", "ps5_de", "xbox_sx", "airpods_max"} & set(by)


class _FakeShouten:
    last_failure_reason = None

    def fetch(self, alias, name, cond):
        prices = {"iphone17_256": 139000, "iphone16pro256": 164000, "airpods_pro3": 32500}
        if alias not in prices:
            self.last_failure_reason = "product_not_listed"
            return None
        return {"buyback_price": prices[alias], "condition": cond, "data_source": "auto_scraped",
                "url": f"https://www.kaitorishouten-co.jp/products/detail/{prices[alias]}",
                "link_verified": "true", "confidence": "high",
                "observed_at": NOW.isoformat(timespec="seconds")}


def _run_update(monkeypatch, tmp_path, existing: list[dict]):
    m = _load_script("update_buyback_prices")
    path = tmp_path / "manual_buyback_prices.csv"
    fields = ["product_alias", "buyback_shop", "buyback_price", "condition", "url", "observed_at",
              "data_source", "link_verified", "confidence"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in existing:
            w.writerow({k: r.get(k, "") for k in fields})
    monkeypatch.setattr(m, "CSV_PATH", path)
    monkeypatch.setattr(m, "REPORT_DIR", tmp_path / "report")
    monkeypatch.setattr(m, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(m, "_load_collectors", lambda: {"kaitori_shouten": _FakeShouten()})
    m.run()
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _manual(alias, shop, price):
    return {"product_alias": alias, "buyback_shop": shop, "buyback_price": str(price),
            "condition": "new_unopened", "url": "https://example.com/", "observed_at": "2026-08-10T12:00:00+09:00",
            "data_source": "manual_today", "link_verified": "true", "confidence": ""}


def test_other_shops_manual_rows_are_kept(monkeypatch, tmp_path):
    """買取商店だけ自動取得する商品で、他店の手入力の行を消さない（日時も値も変えない）。"""
    rows = _run_update(monkeypatch, tmp_path, [
        _manual("airpods_pro3", "kaitori_shouten", 32000),
        _manual("airpods_pro3", "janpara", 30000),
        _manual("iphone17_256", "mobile_ichiban", 135000),
        _manual("gr4", "mapcamera", 185000),
    ])
    by = {(r["product_alias"], r["buyback_shop"]): r for r in rows}
    # 自動取得した組は今回の値で置き換わる
    assert by[("airpods_pro3", "kaitori_shouten")]["buyback_price"] == "32500"
    assert by[("airpods_pro3", "kaitori_shouten")]["data_source"] == "auto_scraped"
    # 他店の手入力・対象外の商品は元のまま（時刻を新しくしない）
    for key, price in ((("airpods_pro3", "janpara"), "30000"), (("iphone17_256", "mobile_ichiban"), "135000"),
                       (("gr4", "mapcamera"), "185000")):
        assert by[key]["buyback_price"] == price
        assert by[key]["observed_at"] == "2026-08-10T12:00:00+09:00"
        assert by[key]["data_source"] == "manual_today"
    # 同じ組の行が2つにならない
    assert len(rows) == len(by)


def test_pair_preservation_mutation(monkeypatch, tmp_path):
    """否定対照: 以前の「商品ごと消す」書き方に戻すと、他店の手入力の行が消える。"""
    m = _load_script("update_buyback_prices")
    existing = [_manual("airpods_pro3", "janpara", 30000)]
    old = [r for r in existing if r["product_alias"] not in m.AUTO_ALIASES]
    new = [r for r in existing if (r["product_alias"], r["buyback_shop"]) not in m.AUTO_PAIRS]
    assert old == [] and new == existing


# ── 買取一丁目（緩いフォールバックを使わない） ───────────────────────────

def _itchome():
    from src.collectors.buyback_kaitori_itchome import KaitoriItchomeCsvCollector
    return KaitoriItchomeCsvCollector()


def test_itchome_reads_only_unopened_price():
    c = _itchome()
    text = ("iPhone 17 Pro 256GB\n\n新品\n\n未開封\n¥178,000\n開封済未使用品\n¥168,000\n"
            "iPhone 17 Pro Max 512GB\n\n新品\n\n未開封\n¥226,000\n")
    assert c._parse_price(text, "iphone17pro256", "") == 178000
    assert c._parse_price(text, "iphone17pm512", "") == 226000


@pytest.mark.parametrize("text", [
    # 未開封の価格が無い（開封済未使用品だけ）→ 開封済の価格を新品として取らない
    "iPhone 17 Pro 256GB\n新品\n開封済未使用品\n¥168,000\nほかの商品\n¥435,000",
    # 商品が載っていない → ページ全体の最高値を取らない
    "iPhone 18 Pro Max 1TB\n未開封\n¥435,000\n",
    # 商品名から遠く離れた別商品の未開封の価格を取らない
    "iPhone 17 Pro 256GB\n" + "説明" * 200 + "\niPhone 18 Pro\n未開封\n¥300,000",
])
def test_itchome_no_fallback(text):
    c = _itchome()
    assert c._parse_price(text, "iphone17pro256", "") is None
    assert c.last_failure_reason == "price_not_found"


# ── フジヤカメラ（「新品同様」は中古） ─────────────────────────────────────

@pytest.mark.parametrize("matched,price,want", [
    ("FUJIFILM X100VI シルバー 買取金額 新品同様 ￥190,000 良品 ￥189,000 下取は10%UP", 190000, "used_s"),
    ("… 新品同様 ￥190,000 良品 ￥189,000", 189000, "used_b"),
    ("… 美品 ¥150,000", 150000, "used_a"),
    ("… 未開封 ¥150,000", 150000, "new_unopened"),
    ("表示なし 190,000円", 190000, "new_unopened"),             # 表示が無ければ従来どおり
    # 桁の違う価格の表示に合わせない。等級の表示はあるので新品とは決めつけない
    ("新品同様 ￥1,190,000", 190000, "unknown"),
])
def test_fujiya_condition_from_label(matched, price, want):
    m = _load_script("update_camera_buyback")
    assert m._condition_for_price(matched, price) == want


def test_fujiya_like_new_is_not_same_condition_as_new():
    """否定対照: 「新品同様」を新品として保存していた以前の扱いだと、新品の仕入れと同じ状態になる。"""
    from src.content.ui.opportunity import _cond_family
    assert _cond_family("used_s") == "used"
    assert _cond_family("new_unopened") == "new"
    from src.models.buyback_price import CONDITION_LABELS
    assert CONDITION_LABELS["used_s"] == "中古S（新品同様）"


# ── ネットオフ（条件付きの価格を取らない） ───────────────────────────────

NETOFF_2026_10 = """<div class="pricelist_item"><a class="pricelist_link" href="./smartphone/iphone/iphone17/iphone17pro.html">
<p class="pricelist_title">iPhone 17 Pro</p>
<div class="pricelist_detail"><p class="pricelist_capacity">256GB</p><p class="pricelist_text">未開封品</p>
<p class="pricelist_num">159,600</p><p class="pricelist_yentext">円買取</p></div></a></div>
<p>※ 特典 適用後の買取価格です。</p>"""


def test_netoff_conditional_campaign_price_not_taken():
    from src.collectors.buyback_netoff import NetoffCsvCollector
    c = NetoffCsvCollector()
    assert c._parse_price(NETOFF_2026_10, "iphone17pro256", "") is None


# ── 公式の定価の確認（VERIFIED_URLS / OFFICIAL_NOT_SOLD） ───────────────

def test_official_not_sold_and_verified_do_not_conflict():
    m = _load_script("audit_official_sources")
    assert not set(m.VERIFIED_URLS) & set(m.OFFICIAL_NOT_SOLD)
    assert not set(m.UNVERIFIED) & set(m.OFFICIAL_NOT_SOLD)
    for pid, v in m.OFFICIAL_NOT_SOLD.items():
        assert v.get("checked_on") and v.get("reason"), pid
        datetime.strptime(v["checked_on"], "%Y-%m-%d")
    for pid in ("prod_iphone16pro_256", "prod_iphone16pm_256", "prod_iphone16pm_512", "prod_airpods_max",
                "prod_mac_mini_m4", "prod_macbook_air_m4_13", "prod_macbook_air_m4_15", "prod_macbook_pro_m4_14"):
        assert m.OFFICIAL_NOT_SOLD[pid]["checked_on"] == "2026-10-07"


def test_official_not_sold_clears_price_in_db(tmp_path, monkeypatch):
    """販売終了の商品は、以前の確認済みの定価を外し、販売終了の印を付ける（参考価格に戻る）。"""
    import sqlite3
    m = _load_script("audit_official_sources")
    db = sqlite3.connect(tmp_path / "t.db")
    db.row_factory = sqlite3.Row
    db.executescript(
        "CREATE TABLE products (id TEXT, official_price INTEGER, official_price_source TEXT,"
        " official_price_updated_at TEXT, is_discontinued INTEGER DEFAULT 0, official_stock_status TEXT,"
        " official_stock_observed_at TEXT);"
        "CREATE TABLE product_source_config (id TEXT, product_id TEXT, source_id TEXT, target_url TEXT,"
        " extra_config TEXT, is_active INTEGER, created_at TEXT);"
        "INSERT INTO products (id, official_price, official_price_source, official_price_updated_at)"
        " VALUES ('prod_mac_mini_m4', 94800, 'src_apple_jp', '2026-08-23');")
    products = {"prod_mac_mini_m4": {"name": "Mac mini M4", "brand": "Apple", "retail_price": 94800}}
    m.register_verified(db, products)
    row = db.execute("SELECT * FROM products WHERE id='prod_mac_mini_m4'").fetchone()
    assert row["official_price"] is None and row["is_discontinued"] == 1


# ── TCG の予約（PREORDER） ────────────────────────────────────────────

PCO = "https://www.pokemoncenter-online.com"


def _legacy(event_type, **kw):
    ev = {"tcg": "POKEMON", "product_name": "拡張パック「Z」BOX", "event_type": event_type,
          "store": "POKEMON_CENTER_ONLINE", "source_type": "MANUFACTURER_OFFICIAL",
          "source_url": f"{PCO}/news/1", "confidence": "high",
          "application_start": "2026-10-06T12:00:00+09:00", "application_end": "2026-10-09T16:59:00+09:00"}
    ev.update(kw)
    return ev


def test_preorder_event_is_converted_as_preorder():
    from src.tcg.lottery.pipeline import from_tcg_events
    out = from_tcg_events([_legacy("PREORDER"), _legacy("GENERAL_SALE"), _legacy("RESTOCK")])
    assert [e["event_type"] for e in out] == ["PREORDER"]
    assert "予約" in out[0]["notes"][0]


def test_preorder_and_lottery_are_not_merged():
    from src.tcg.lottery.merge import merge_lotteries
    from src.tcg.lottery.pipeline import from_tcg_events
    evs = from_tcg_events([_legacy("LOTTERY"), _legacy("PREORDER")])
    assert evs[0]["lottery_id"] != evs[1]["lottery_id"]
    merged = merge_lotteries(evs)
    assert sorted(e["event_type"] for e in merged) == ["LOTTERY", "PREORDER"]
    assert not any(e.get("conflict") for e in merged)


def test_lottery_id_unchanged_for_lottery_events():
    """既存の抽選の lottery_id は変えない（種類は LOTTERY 以外のときだけキーに入る）。"""
    import hashlib
    from src.tcg.lottery.schema import lottery_id_of, lottery_key
    d = _legacy("LOTTERY", tcg="POKEMON", retailer="POKEMON_CENTER_ONLINE")
    old_key = lottery_key(d)
    assert len(old_key) == 6
    raw = "|".join(str(x) for x in old_key)
    assert lottery_id_of(d) == "lot-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    assert lottery_id_of({**d, "event_type": "PREORDER"}) != lottery_id_of(d)
    # 実データの抽選の ID も変わらない
    p = ROOT / "exports" / "tcg" / "latest.json"
    if p.exists():
        for lot in json.loads(p.read_text(encoding="utf-8")).get("lotteries") or []:
            if lot.get("lottery_id") and (lot.get("event_type") or "LOTTERY") == "LOTTERY":
                assert lottery_id_of(lot) == lot["lottery_id"]


def _pre_vm(**kw):
    from src.content.ui import runtime as rt
    ev = {"tcg": "POKEMON", "product_name": "拡張パック「Z」BOX", "retailer_name": "ポケモンセンターオンライン",
          "status": "OPEN", "source_url": f"{PCO}/news/1", "entry_url": f"{PCO}/preorder/1",
          "verified": True, "confidence": "high", "lottery_id": "lot-pre", "event_type": "PREORDER",
          "application_start": "2026-10-06T12:00:00+09:00", "application_end": "2026-10-09T16:59:00+09:00"}
    ev.update(kw)
    return rt.tcg_vm(ev, 0)


def test_preorder_display_states():
    from src.content.ui import runtime as rt
    vm = _pre_vm()
    assert vm["k"] == "preorder"
    s = rt.derive_runtime_state(vm, NOW)
    assert s["label"] == "予約受付中" and s["cta"]["label"] == "予約する"
    assert s["open"] is False and s["upcoming"] is False        # 抽選受付中の件数に数えない
    before = rt.derive_runtime_state(vm, datetime(2026, 10, 5, 12, 0, tzinfo=JST))
    assert before["label"] == "予約開始待ち" and before["starting_24h"] is False
    after = rt.derive_runtime_state(vm, datetime(2026, 10, 12, 12, 0, tzinfo=JST))
    assert after["status"] == "CLOSED" and after["label"] == "予約受付終了"
    assert "当選" not in after["when"]
    # 当選発表の日時が入っていても、予約には当選発表が無いので「当選発表待ち・当選発表済み」にしない
    vm_w = _pre_vm(winner_announcement_at="2026-10-10T12:00:00+09:00")
    for t in (datetime(2026, 10, 9, 18, 0, tzinfo=JST), datetime(2026, 10, 12, 12, 0, tzinfo=JST)):
        s_w = rt.derive_runtime_state(vm_w, t)
        assert s_w["status"] == "CLOSED" and s_w["label"] == "予約受付終了", t
        assert "当選" not in s_w["when"] and s_w["cta"]["kind"] not in ("result", "purchase")


def test_preorder_without_dates_is_unknown_not_open():
    from src.content.ui import runtime as rt
    vm = _pre_vm(application_start=None, application_end=None, status="UNKNOWN")
    s = rt.derive_runtime_state(vm, NOW)
    assert s["status"] == "UNKNOWN" and s["open"] is False and s["cta"]["kind"] != "apply"
    assert s["when"] == "日程は未公表です"


def test_preorder_keeps_official_release_card():
    from src.content.ui import runtime as rt
    report = {"lotteries": [{"tcg": "POKEMON", "product_name": "拡張パック「Z」BOX", "event_type": "PREORDER",
                             "status": "OPEN", "source_url": f"{PCO}/news/1", "lottery_id": "lot-pre",
                             "application_start": "2026-10-06T12:00:00+09:00",
                             "application_end": "2026-10-09T16:59:00+09:00"}],
              "events": [{"status": "COMING_SOON", "product_name": "拡張パック「Z」BOX", "release_date": "2026年10月30日",
                          "source_url": f"{PCO}/news/2", "store": "POKEMON_CENTER_ONLINE"},
                         {"status": "COMING_SOON", "product_name": "拡張パック「Y」BOX", "release_date": "2026年11月6日",
                          "source_url": f"{PCO}/news/3", "store": "POKEMON_CENTER_ONLINE"}]}
    kinds = [(v["k"], v["t"]) for v in rt.build_vms(report, [])]
    # 予約と公式の発売日は別の情報なので両方出す（予約が日程不明・受付終了でも発売日を消さない）
    assert ("preorder", "拡張パック「Z」BOX") in kinds
    assert ("release", "拡張パック「Z」BOX") in kinds
    assert ("release", "拡張パック「Y」BOX") in kinds


def test_preorder_not_in_lottery_history(monkeypatch):
    """予約は抽選の履歴・店ごとの頻度に入れない。"""
    from src.tcg.lottery import pipeline as pl
    seen = {}

    def fake_history(events, now):
        seen["types"] = [e.get("event_type") for e in events]
        return []

    monkeypatch.setattr(pl, "collect_sources", lambda: ([], {}, []))
    monkeypatch.setattr(pl, "_resolve_all", lambda *a, **k: None)
    monkeypatch.setattr(pl, "load_manual_lotteries", lambda: ([], []))
    monkeypatch.setattr(pl, "update_history", fake_history)
    monkeypatch.setattr(pl, "frequency_by_retailer", lambda h, now: {})
    try:
        pl.run_lottery_pipeline([], [], now=NOW, legacy_events=[_legacy("LOTTERY"), _legacy("PREORDER")])
    except Exception:
        pass                                  # 後段（書き出し等）の失敗はこのテストの対象外
    assert "types" in seen                   # 履歴の更新まで届いている
    assert seen["types"] == ["LOTTERY"]


_NODE = shutil.which("node")


@pytest.mark.skipif(_NODE is None, reason="node が無い")
def test_preorder_python_and_js_identical():
    from src.content.ui import runtime as rt
    vms = [_pre_vm(), _pre_vm(lottery_id="lot-pre2", application_start=None, application_end=None),
           _pre_vm(lottery_id="lot-pre3", winner_announcement_at="2026-10-10T12:00:00+09:00")]
    nows = [datetime(2026, 10, 4, tzinfo=JST) + timedelta(hours=6 * k) for k in range(40)]
    harness = (
        "const R = require(process.argv[1]);"
        "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{"
        "const x=JSON.parse(s);"
        "const out=x.nows.map(n=>x.vms.map(v=>R.deriveLotteryRuntimeState(v,n,x.cfg)));"
        "process.stdout.write(JSON.stringify(out));});"
    )
    res = subprocess.run([_NODE, "-e", harness, str(rt.JS_PATH)],
                         input=json.dumps({"vms": vms, "nows": [rt._ms(t) for t in nows], "cfg": rt.config()}),
                         capture_output=True, text=True, check=True)
    for t, row in zip(nows, json.loads(res.stdout)):
        for vm, j in zip(vms, row):
            assert rt.derive_runtime_state(vm, t) == j, (vm["id"], t.isoformat())


# ── 網羅の集計（production_coverage_metrics） ───────────────────────────

def _diag(n_cands: int, eligible: int, reasons_cycle: list[list[str]]) -> dict:
    cands = [{"product_id": f"p{i}", "reasons": reasons_cycle[i % len(reasons_cycle)]} for i in range(n_cands)]
    return {"candidates": cands, "eligible_count": eligible}


@pytest.mark.parametrize("n", [0, 1, 10, 50, 150])
def test_funnel_scales_and_is_monotonic(n):
    m = _load_script("production_coverage_metrics")
    diag = _diag(n, 1 if n else 0, [["unverified_buy_price"], ["stale_buyback"], ["no_profit"], ["missing_costs"]])
    st = m.funnel(diag)
    counts = [s["count"] for s in st]
    assert counts[0] == n + (1 if n else 0)
    assert all(a >= b for a, b in zip(counts, counts[1:]))        # 段階が進むと減るだけ
    assert sum(s["dropped"] for s in st) + counts[-1] == counts[0]
    assert counts[-1] == (1 if n else 0)                           # 確定の案件は最後まで残る


def test_funnel_counts_confirmed_case_mutation():
    """否定対照: 確定の案件（eligible_count）を数えないと、候補の総数が商品数より少なくなる。"""
    m = _load_script("production_coverage_metrics")
    st = m.funnel(_diag(44, 1, [["no_profit"]]))
    assert st[0]["count"] == 45 and st[-1]["count"] == 1


# ── 買取 CSV の取り込み（観測日時の無い価格を取り込み時刻で新しく見せない） ─────────

def test_buyback_csv_without_observed_at_is_not_imported(tmp_path):
    from src.db.database import Database
    from src.db.repository import Repository
    from src.market.buyback_csv_importer import ALIAS_MAP, BuybackCSVImporter
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    pid = ALIAS_MAP["airpods_pro3"]
    db.connection.execute("INSERT INTO products (id, name, genre, brand, retail_price, is_active, created_at, updated_at) "
                          "VALUES (?, 'AirPods Pro 3', 'audio', 'Apple', 39800, 1, 'x', 'x')", (pid,))
    db.connection.commit()
    imp = BuybackCSVImporter(Repository(db))
    head = "product_alias,buyback_shop,buyback_price,condition,url,observed_at,data_source,link_verified,confidence\n"
    imp.import_csv(head + "airpods_pro3,janpara,30000,new_unopened,u,,manual_today,true,high\n")
    assert db.connection.execute("SELECT COUNT(*) FROM buyback_prices").fetchone()[0] == 0
    # 対照: 観測日時がある行は取り込まれる（日時はそのまま）
    imp.import_csv(head + "airpods_pro3,janpara,30000,new_unopened,u,2026-08-10T12:00:00+09:00,manual_today,true,high\n")
    got = db.connection.execute("SELECT observed_at FROM buyback_prices").fetchall()
    assert len(got) == 1 and str(got[0][0]).startswith("2026-08-10")


# ── レビューの指摘（H1・M1・M2・M4）の否定対照 ──────────────────────────────

def test_preorder_not_in_lottery_notifications(monkeypatch):
    """H1: 予約から「抽選開始」「当選発表」の通知候補を作らない。"""
    from src.tcg.lottery import pipeline as pl
    seen = {}

    def fake_notify(events, now):
        seen["types"] = [e.get("event_type") for e in events]
        return [], {}

    monkeypatch.setattr(pl, "collect_sources", lambda: ([], {}, []))
    monkeypatch.setattr(pl, "_resolve_all", lambda *a, **k: None)
    monkeypatch.setattr(pl, "load_manual_lotteries", lambda: ([], []))
    monkeypatch.setattr(pl, "update_history", lambda events, now: [])
    monkeypatch.setattr(pl, "frequency_by_retailer", lambda h, now: {})
    monkeypatch.setattr(pl, "notification_candidates", fake_notify)
    try:
        pl.run_lottery_pipeline([], [], now=NOW, legacy_events=[_legacy("LOTTERY"), _legacy("PREORDER")])
    except Exception:
        pass
    assert "types" in seen
    assert seen["types"] == ["LOTTERY"]


def test_itchome_does_not_take_next_products_unopened_price():
    """M1: 未開封の価格が無い商品で、すぐ後ろの別商品（512GB）の未開封の価格を取らない。"""
    c = _itchome()
    text = ("iPhone 17 Pro 256GB\n\n新品\n\n開封済未使用品\n¥168,000\n"
            "iPhone 17 Pro 512GB\n\n新品\n\n未開封\n¥200,000")
    assert c._parse_price(text, "iphone17pro256", "") is None
    assert c._parse_price(text, "iphone17pro512", "") == 200000


def test_fujiya_cash_tier_is_used_s_even_if_label_beyond_140_chars():
    """M2: 段階表示の現金の段（新品同様）は、表示が140文字より後ろでも中古（used_s）。"""
    m = _load_script("update_camera_buyback")
    alias = "x100vi"
    head = "FUJIFILM X100VI シルバー 富士フイルム " + "説明" * 80
    item = head + " 買取のみ10%UP 新品同様 ￥190,000 良品 ￥189,000 下取は15%UP 新品同様 ￥200,000"
    assert len(head) > 140
    if not m._strict_model_match(item, alias):
        pytest.skip("機種照合のルールが変わった")
    sel = m._select_camera_buyback([{"price": 200000, "item_text": item, "near_buyback": True}], alias)
    assert sel["price"] == 190000                 # 下取の段は使わない（既存の挙動）
    assert sel["condition"] == "used_s"


@pytest.mark.parametrize("text,want", [
    ("X100VI 並品 ￥150,000", "unknown"),            # 中古の表示があるのに等級を読めない → 新品と決めつけない
    ("X100VI 中古 150,000円", "unknown"),
    ("X100VI 150,000円", "new_unopened"),            # 等級の表示が無い → 従来どおり
])
def test_fujiya_unreadable_used_label_is_unknown(text, want):
    m = _load_script("update_camera_buyback")
    assert m._condition_for_price(text, 150000) == want


def _bb_row(alias, price, url, verified="true"):
    return {"product_alias": alias, "buyback_shop": "kaitori_shouten", "buyback_price": str(price),
            "url": url, "link_verified": verified, "data_source": "auto_scraped"}


def test_same_price_from_distinct_product_pages_not_quarantined():
    """M4: 別々の商品ページから取った同じ価格は隔離しない。同じページ・一覧から取った同じ価格は隔離する。"""
    m = _load_script("update_buyback_prices")
    base = "https://www.kaitorishouten-co.jp/products/detail/"
    ok = [_bb_row("iphone17_256", 150000, base + "1"), _bb_row("iphone16pro256", 150000, base + "2")]
    assert not [s for s in m.compute_suspicious(ok, []) if s["reason"] == "cross_product_same_price"]
    # 否定対照: 同じ商品ページ・一覧ページ・確認されていないリンクなら従来どおり隔離の対象
    for rows in ([_bb_row("iphone17_256", 150000, base + "1"), _bb_row("iphone16pro256", 150000, base + "1")],
                 [_bb_row("iphone17_256", 150000, "https://www.kaitorishouten-co.jp/kaden"),
                  _bb_row("iphone16pro256", 150000, base + "2")],
                 [_bb_row("iphone17_256", 150000, base + "1", "false"),
                  _bb_row("iphone16pro256", 150000, base + "2", "false")]):
        sus = [s for s in m.compute_suspicious(rows, []) if s["reason"] == "cross_product_same_price"]
        assert len(sus) == 2
