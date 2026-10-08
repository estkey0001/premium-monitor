"""Phase 15（商品の同一性と公式の確認）のテスト。

型番・JAN は公式ページの証拠と一致するものだけを確認済みにし、商品名・価格の一致だけで版を決めない。
希望小売価格（msrp）と公式ストアの販売価格（official_direct）・オープン価格を分ける。公式の再確認は、失敗で
確認日を進めず、価格が変われば確定から外す。各テストには、誤りを入れると失敗する否定対照も付ける。
"""

from __future__ import annotations

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
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=JST)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


AUDIT = _load("p15_audit", ROOT / "scripts" / "audit_official_sources.py")
RECHECK = _load("p15_recheck", ROOT / "scripts" / "recheck_official.py")
PRODUCTS = {p["id"]: p for p in yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))["products"]}


# ── 同一性の状態 ─────────────────────────────────────────────────────────

def test_identity_confirmed_needs_official_evidence():
    from src.market import official_registry as reg
    for pid in ("prod_ps5_pro", "prod_switch2", "prod_airpods_pro3"):
        assert reg.identity_state(PRODUCTS[pid])[0] == "IDENTITY_CONFIRMED", pid
    # JAN だけでも確認済み（Switch 2）・型番だけでも確認済み（AirPods Pro 3）
    assert PRODUCTS["prod_switch2"]["jan_code"] == reg.IDENTITY_EVIDENCE["prod_switch2"]["jan_code"]
    assert PRODUCTS["prod_airpods_pro3"]["model_number"] == reg.IDENTITY_EVIDENCE["prod_airpods_pro3"]["model_number"]


@pytest.mark.parametrize("change,state", [
    ({"model_number": "CFI-7000B01"}, "PARTIAL_IDENTITY"),               # 型番が証拠と違う（mutation）
    ({"jan_code": "4948872416320"}, "PARTIAL_IDENTITY"),                 # JAN が証拠と違う（7000B01 の JAN）
    ({"model_number": "", "jan_code": ""}, "AMBIGUOUS"),                 # 型番も JAN も無い
])
def test_wrong_model_or_jan_is_not_confirmed(change, state):
    from src.market import official_registry as reg
    p = dict(PRODUCTS["prod_ps5_pro"], **change)
    assert reg.identity_state(p)[0] == state


def test_name_only_product_is_ambiguous_not_confirmed():
    from src.market import official_registry as reg
    # 商品名に容量などがあっても、型番・JAN の証拠が無ければ確認済みにしない
    assert reg.identity_state({"id": "prod_x", "name": "iPhone 17 256GB SIMフリー"})[0] == "AMBIGUOUS"
    # Phase 16 で GR IV に公式の商品コード（S0001551）の証拠を登録した。型番が無ければ商品名だけでは確認済みにしない
    assert reg.identity_state(dict(PRODUCTS["prod_gr4"], model_number=""))[0] == "AMBIGUOUS"


def test_target_products_need_user_decision():
    """PS5 Digital Edition・Xbox Series X・Switch 2 マリオカートセットは、公式の情報でも版を決められない。"""
    from src.market import official_registry as reg
    for pid in ("prod_ps5_de", "prod_xbox_sx", "prod_switch2_mk"):
        st, why = reg.identity_state(PRODUCTS[pid])
        assert st == "NEEDS_USER_DECISION" and why
        assert len(reg.USER_DECISIONS[pid]["candidates"]) >= 2
        # 型番・JAN を推測で登録していない
        assert not PRODUCTS[pid].get("model_number") and not PRODUCTS[pid].get("jan_code")


def test_sale_ended_stays_ended():
    from src.market import official_registry as reg
    for pid in ("prod_gr3", "prod_iphone17pro_256", "prod_mac_mini_m4"):
        assert reg.identity_state(PRODUCTS[pid])[0] == "DISCONTINUED"
        assert pid not in reg.VERIFIED_URLS                              # 確認済みの定価に戻さない
    recs = {r["product_id"]: r for r in reg.records()}
    assert recs["prod_gr3"]["sale_status"] == "OFFICIAL_NOT_SOLD" and recs["prod_gr3"]["verified_price"] is None


def test_identity_audit_scales_to_all_products():
    from src.content.ui import admin
    from src.market import official_registry as reg
    a = reg.identity_audit(list(PRODUCTS.values()))
    assert sum(a["counts"][s] for s in reg.IDENTITY_STATES) == len(PRODUCTS) == 45
    many = [{"id": f"p{i}", "name": f"商品{i}"} for i in range(60)]   # 曖昧な商品が多くても崩れない
    html = admin._identity_html(reg.identity_audit(many))
    assert html.count("商品詳細") == 60 and "NaN" not in html


# ── 買取の行の照合（版・セット・容量） ──────────────────────────────────────

@pytest.mark.parametrize("alias,row,ok", [
    ("switch2", "Nintendo Switch 2 日本語・国内専用", True),
    ("switch2", "Nintendo Switch 2 マリオカート ワールドセット 日本語・国内専用", False),   # セット（bundle）
    ("switch2", "Nintendo Switch 2（多言語対応）", False),                                   # 版（edition）
    ("ps5_pro", "プレイステーション5 Pro [CFI-7100B01] 2025版", True),
    ("ps5_pro", "プレイステーション5 デジタル・エディション 日本語専用 CFI-2200B01", False),
    ("iphone17pro256", "iPhone 17 Pro 256GB コズミックオレンジ MG864J/A SIMフリー", True),
    ("iphone17pro256", "iPhone 17 Pro 512GB コズミックオレンジ MG8A4J/A SIMフリー", False),   # 容量
    ("airpods_pro3", "AirPods Pro 3 MFHP4J/A", True),
    ("airpods_pro3", "AirPods Pro 第2世代 MTJV3J/A", False),
])
def test_buyback_rows_match_exact_identity_only(alias, row, ok):
    from src.collectors.buyback_kaitori_shouten import match_rows
    got = match_rows([(row, 50000, "https://www.kaitorishouten-co.jp/products/detail/1")], alias)
    assert bool(got) is ok


def test_no_buyback_unlock_without_decision():
    """判断待ちの商品は、買取商店の同じページに行があっても確定の買取の照合に加えない。"""
    from src.collectors.buyback_kaitori_shouten import ROW_RULES
    for alias in ("switch2_mk", "ps5_de", "xbox_sx"):
        assert alias not in ROW_RULES


# ── 価格の意味（希望小売価格・公式ストアの販売価格・オープン価格） ─────────────────

def test_price_kinds():
    from src.market import official_registry as reg
    kinds = {pid: v.get("price_kind") for pid, v in reg.VERIFIED_URLS.items()}
    assert kinds["prod_ps5_pro"] == "msrp" and kinds["prod_switch2"] == "msrp"
    assert kinds["prod_iphone17_256"] == "official_direct" and kinds["prod_airpods_pro3"] == "official_direct"
    # Phase 16: カメラの希望小売価格はオープン価格のまま（架空の希望小売価格なし）。価格はメーカー直販の販売価格
    # （official_direct）で、official_direct_gate を通ったときだけ確定の仕入れ値に使う（tests/test_phase16_official_direct.py）
    for pid in ("prod_z8", "prod_x100vi", "prod_r5ii"):
        assert reg.MSRP_OF[pid] == "open_price" and kinds[pid] == "official_direct"
        assert pid in reg.OFFICIAL_DIRECT_OFFERS
    for sid, a in reg.CAMERA_DIRECT_SALE_AUDIT.items():
        assert a["url"].startswith("https://") and a["checked_on"]


def test_official_price_must_be_on_official_domain():
    """公式の価格は公式ドメインのページだけ（第三者の価格を公式にしない。mutation: 公式 → 第三者）。"""
    from src.market import official_registry as reg
    from src.market.official_price_validator import is_official_domain
    for pid, v in reg.VERIFIED_URLS.items():
        if v["source"] != "src_nintendo_store":
            assert is_official_domain(v["source"], v["url"]), pid
    assert not is_official_domain("src_sony_store", "https://www.amazon.co.jp/dp/B0DGY63Z2H")
    assert not is_official_domain("src_apple_jp", "https://kakaku.com/item/K0001")


# ── 公式 URL（テーブル名の不具合）と送料 ──────────────────────────────────────

def _scanner_conn(rows):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE product_source_config (product_id TEXT, source_id TEXT, target_url TEXT, extra_config TEXT)")
    c.executemany("INSERT INTO product_source_config VALUES (?,?,?,?)", rows)
    return SimpleNamespace(repo=SimpleNamespace(db=SimpleNamespace(connection=c)))


def test_official_url_reads_verified_product_source_config():
    from src.market.beginner_deal_scanner import BeginnerDealScanner as S
    fake = _scanner_conn([
        ("prod_switch2", "src_nintendo_store", "https://store-jp.nintendo.com/item/hardware-accessory/VM_BEE_S_KB6CA",
         json.dumps({"verified": True, "link_type": "item"})),
        ("prod_z8", "src_nikon_direct", "https://nij.nikon.com/products/lineup/mirrorless/z8/",
         json.dumps({"verified": True, "link_type": "category"})),
        ("prod_ended", "src_sony_store", "https://pur.store.sony.jp/x/",
         json.dumps({"verified": False, "link_type": "item", "recheck_status": "sale_ended"})),
        ("prod_mac_mini_m4", "src_apple_jp", "", json.dumps({"verified": False, "official_not_sold": True})),
        ("prod_q", "src_apple_jp", "https://www.apple.com/jp/shop/x", json.dumps({"verified": False})),
    ])
    get = lambda pid, brand="": S._get_official_url(fake, SimpleNamespace(id=pid, brand=brand))  # noqa: E731
    assert get("prod_switch2", "Nintendo").startswith("https://store-jp.nintendo.com/item/")
    assert get("prod_mac_mini_m4", "Apple") == "https://www.apple.com/jp/shop/"     # URL の無い行は使わない（既定）
    assert get("prod_q", "Apple") == "https://www.apple.com/jp/shop/"               # 確認済みでない行は使わない
    assert get("prod_none", "Sony") == ""
    assert get("prod_z8", "Nikon") == ""                                    # 製品ページ（category）は「買う」にしない
    assert get("prod_ended", "Sony") == ""                                  # 再確認で販売終了になった行は使わない
    # 以前の不具合（存在しないテーブル名）に戻すと、確認済みの URL を引けない（mutation の検出）。
    # Phase 16 で判定を verified_official_item_url（quality_checker と共通）へ移した
    import inspect

    from src.market.beginner_deal_scanner import verified_official_item_url
    src = inspect.getsource(verified_official_item_url)
    assert "FROM product_source_config\n" in src or "FROM product_source_config " in src
    assert "verified_official_item_url" in inspect.getsource(S._get_official_url)


def test_official_url_fix_does_not_change_shipping():
    """確認済みの公式 URL を使っても、以前の既定の URL と購入送料が同じ（送料の後退0・利益の判定の変化0）。"""
    from src.market import official_registry as reg
    from src.market.official_shipping import purchase_shipping
    for pid, v in reg.VERIFIED_URLS.items():
        old = "https://www.apple.com/jp/shop/" if v["source"] == "src_apple_jp" else ""
        assert purchase_shipping(pid, v["url"], v.get("price")) == purchase_shipping(pid, old, v.get("price")), pid


# ── 公式の再確認 ────────────────────────────────────────────────────────

SONY_HTML = ('<div>PlayStation®5 Pro 選択済み CFI-7100B01 入荷待ち 137,980円(税込)</div>'
             '<button>カートに入れる</button>')
APPLE_HTML = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",'
              '"offers":[{"@type":"Offer","price":42800,"sku":"MFHP4J/A"}]}</script>')


def test_recheck_parsers_read_model_price_and_stock():
    assert RECHECK.parse_sony_store(SONY_HTML, "CFI-7100B01") == {"model_found": True, "price": 137980,
                                                                   "stock": "入荷待ち", "ended": False}
    assert RECHECK.parse_apple_jsonld(APPLE_HTML, "MFHP4J/A")["price"] == 42800
    # 型番が違えば読み取らない（別の商品の価格を拾わない）
    assert RECHECK.parse_sony_store(SONY_HTML, "CFI-7000B01")["price"] is None
    assert RECHECK.parse_apple_jsonld(APPLE_HTML, "MTJV3J/A")["model_found"] is False


@pytest.mark.parametrize("html,status", [
    (SONY_HTML, "unchanged"),
    (SONY_HTML.replace("137,980", "139,980"), "changed"),
    ("<div>CFI-7100B01 販売終了 137,980円(税込)</div>", "sale_ended"),
    # ページの別の場所の「販売終了」（旧型の行）では販売終了にしない（監査 M-1）
    ("<li>CFI-7000B01 販売終了 119,980円(税込)</li>" + SONY_HTML, "unchanged"),
    # 型番の後に別の商品（付属品）の価格が並んでも拾わない（監査 M-2）
    ("<div>CFI-7100B01 ディスクドライブ 12,980円(税込)</div>", "failed"),
    # 並びが2つあって、どれがこの商品か決められない（監査 N-1）
    ("<div>CFI-7100B01 在庫あり 3,980円(税込)</div>" + SONY_HTML, "failed"),
    ("<div>メンテナンス中</div>", "failed"),
])
def test_recheck_statuses(html, status):
    out = RECHECK.recheck(NOW, fetch=lambda url: (html, "") if "sony" in url else (APPLE_HTML, ""))
    r = {x["product_id"]: x for x in out}["prod_ps5_pro"]
    assert r["status"] == status and r["observed_at"] == NOW.isoformat(timespec="seconds")


def test_recheck_blocked_and_failed_do_not_refresh():
    out = RECHECK.recheck(NOW, fetch=lambda url: (None, "site_blocked"))
    assert {r["status"] for r in out} == {"blocked"}
    out = RECHECK.recheck(NOW, fetch=lambda url: (None, "timeout"))
    assert {r["status"] for r in out} == {"failed"} and all(r["price"] is None for r in out)


def _apply(results, now=None):
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
        AUDIT.apply_recheck(_C(), {"prod_ps5_pro": {"model_number": "CFI-7100B01"},
                                   "prod_airpods_pro3": {"model_number": "MFHP4J/A"}}, p)
    return [c for c in calls if c[0].lstrip().upper().startswith("UPDATE")]


def _res(status, price=137980, stock="入荷待ち", at="2026-10-09T12:00:00+09:00", **kw):
    r = {"product_id": "prod_ps5_pro", "status": status, "price": price, "recorded_price": 137980,
         "stock": stock, "observed_at": at, "url": AUDIT.VERIFIED_URLS["prod_ps5_pro"]["url"], "model": "CFI-7100B01"}
    r.update(kw)
    return r


@pytest.fixture(autouse=True)
def _audit_now(monkeypatch):
    """監査の「今」を再確認の翌日の正午に固定する（未来の日付を受け付けない判定のため）。"""
    monkeypatch.setattr(AUDIT, "NOW", datetime(2026, 10, 9, 12, 30, tzinfo=JST))


def test_apply_recheck_unchanged_reconfirms_with_observed_date_only():
    ups = _apply([_res("unchanged")])
    price = [p for s, p in ups if "official_price_updated_at=?" in s]
    assert price == [("2026-10-09", "prod_ps5_pro", 137980)]                  # 取得した日（今日ではない）
    stock = [p for s, p in ups if "official_stock_status" in s]
    assert stock and stock[0][:2] == ("入荷待ち", "2026-10-09T12:00:00+09:00")


def test_apply_recheck_changed_does_not_record_stock():
    """価格が食い違った読み取りの在庫は記録しない（別の商品の行かもしれない。監査 N-1）。"""
    ups = _apply([_res("changed", price=3980, stock="在庫あり")])
    assert not any("official_stock_status" in s for s, _ in ups)


def test_recheck_does_not_follow_redirects():
    """リダイレクトをたどらない（移動先へリクエストを送らない。監査 N-2）。"""
    import urllib.request as ur
    h = RECHECK._NoRedirect()
    assert h.redirect_request(ur.Request("https://www.apple.com/jp/shop/x"), None, 301, "Moved", {},
                              "https://www.apple.com/jp/") is None


def test_apply_recheck_changed_or_ended_removes_verified_price():
    for st in ("changed", "sale_ended"):
        ups = _apply([_res(st, price=139980)])
        assert any("official_price=NULL" in s for s, _ in ups), st
        assert any("product_source_config" in s and "'$.verified', json('false')" in s
                   and "'$.official_price', json('null')" in s for s, _ in ups), st
        assert not any("official_price_updated_at=?" in s for s, _ in ups)


@pytest.mark.parametrize("res", [
    _res("failed", price=None, stock=""), _res("blocked", price=None, stock=""),
    _res("unchanged", at="2026-10-01T12:00:00+09:00", stock=""),             # 記録（10-08）より古い → 戻さない
    _res("unchanged", at="2099-01-01T12:00:00+09:00", stock=""),             # 未来の日付 → 進めない（監査 L-1）
    _res("unchanged", url="https://pur.store.sony.jp/other/"),               # 別の URL への結果（L-2）
    _res("changed", price=139980, recorded_price=119980),                    # 古い記録への結果（L-2）
    _res("unchanged", model="CFI-7000B01"),                                  # 別の型番への結果（L-2）
])
def test_apply_recheck_never_refreshes_without_new_observation(res):
    assert _apply([res]) == []


def test_identity_and_registration_never_use_run_time(monkeypatch):
    """同一性の登録・公式の確認の登録は、実行の時刻（NOW）を価格・在庫の時刻にしない（mutation: 時刻を今に）。"""
    calls = []

    class _C:
        def execute(self, sql, params=()):
            calls.append((sql, params))
            return SimpleNamespace(fetchone=lambda: None)

        def commit(self):
            pass
    future = datetime(2026, 10, 9, 0, 0, tzinfo=JST)                        # 確認の翌日の CI
    monkeypatch.setattr(AUDIT, "NOW", future)
    AUDIT.register_verified(_C(), {pid: {"name": PRODUCTS[pid]["name"], "model_number": PRODUCTS[pid].get(
        "model_number", "")} for pid in ("prod_ps5_pro", "prod_switch2", "prod_airpods_pro3")})
    # 商品の価格・在庫の時刻（products の更新）に、実行の時刻を入れない（設定の行の updated_at は記録の更新時刻なので別）
    flat = json.dumps([p for s, p in calls if s.lstrip().upper().startswith("UPDATE PRODUCTS")],
                      ensure_ascii=False, default=str)
    assert "2026-10-09" not in flat and "2026-10-08" in flat


# ── 検索（型番・JAN） ────────────────────────────────────────────────────

def test_search_by_model_and_jan():
    import re

    from src.content.ui import pages
    from src.content.ui import product_detail as pd
    views = pd.build(products=[{"product_id": "prod_ps5_pro", "name": "PlayStation 5 Pro", "genre": "game_console",
                                "model": "CFI-7100B01", "jan": "4948872417075", "keywords": ["PS5 Pro"]}],
                     catalog=None, observations=[], price_history={}, stock_history={}, now=NOW)
    s = re.findall(r'data-search="([^"]*)"', pages.render_search(views))[0]
    assert "cfi-7100b01" in s and "4948872417075" in s and "ps5 pro" in s
    no_jan = pd.build(products=[{"product_id": "prod_ps5_pro", "name": "PlayStation 5 Pro", "genre": "game_console"}],
                      catalog=None, observations=[], price_history={}, stock_history={}, now=NOW)
    assert "4948872417075" not in pages.render_search(no_jan)


def test_seed_reads_jan_code():
    import inspect

    from src import cli
    assert 'jan_code=p.get("jan_code") or None' in inspect.getsource(cli.seed.callback)


def test_recheck_moved_page_is_not_read(monkeypatch):
    """リダイレクト（3xx）を受け取ったら読まない（moved）。移動先へ取りに行かない（監査 L-3・N-2）。"""
    import io
    import urllib.error
    import urllib.request
    from src.collectors import polite
    monkeypatch.setattr(polite, "robots_allowed", lambda url: True)
    monkeypatch.setattr(polite, "polite_wait", lambda url, sid=None: 0)
    opened = []

    class _Opener:
        def open(self, req, timeout=None):
            opened.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 301, "Moved", {"Location": "https://www.apple.com/jp/"},
                                         io.BytesIO(b""))
    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: _Opener())
    assert RECHECK._fetch("https://www.apple.com/jp/shop/buy-airpods/airpods-pro-3") == (None, "moved")
    assert opened == ["https://www.apple.com/jp/shop/buy-airpods/airpods-pro-3"]       # 移動先は取りに行かない


@pytest.mark.parametrize("ld", [
    '{"@type":"Product","offers":{"@type":"Offer","price":42800,"sku":"MFHP4J/A"}}',
    '{"@graph":[{"@type":"Product","offers":[{"price":42800,"sku":"MFHP4J/A"}]}]}',
    '[{"@type":"Product","offers":[{"price":42800,"sku":"MFHP4J/A"}]}]',
])
def test_apple_jsonld_shapes(ld):
    h = f'<script type="application/ld+json">{ld}</script>'
    assert RECHECK.parse_apple_jsonld(h, "MFHP4J/A")["price"] == 42800


def test_recheck_waits_host_interval_before_first_request(monkeypatch):
    """直前の CI のステップが同じ取得元を取ったばかりかもしれないので、最初の取得の前に間隔の分を待つ（L-1）。"""
    waits = []
    monkeypatch.setattr(RECHECK, "_host_interval", lambda url: 120.0 if "apple" in url else 60.0)
    RECHECK.recheck(NOW, fetch=lambda url: (SONY_HTML if "sony" in url else APPLE_HTML, ""),
                    sleep=waits.append, wait_first=True)
    hosts = {t["url"].split("/")[2] for t in RECHECK._targets()}            # Phase 16 で Canon・Nikon を加えた
    assert len(waits) == len(hosts) and 55 <= waits[0] <= 60 and all(55 <= w <= 120 for w in waits)  # 取得元ごとに1回
    # テスト（偽の取得）では既定で待たない
    waits.clear()
    RECHECK.recheck(NOW, fetch=lambda url: (SONY_HTML, ""), sleep=waits.append)
    assert waits == []
