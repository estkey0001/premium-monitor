"""Production Integrity Remediation（2026-10-21 の監査の Medium 5件）のテスト。

M-1 公式の再確認（PS5 Pro・Switch 2）／M-2 順位レポートの利益式／M-3 買取の比較の基準／M-4 運営者向けの劣化の通知／
M-5 定時の実行の遅れ／Low（404 の再試行・公式価格の二重管理・健康度・失敗の数え方）。
通信はしない（ページは本物と同じ形の小さな HTML）。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import recheck_official as RO  # noqa: E402
from src.collectors import base as collector_base  # noqa: E402

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=JST)


# ── M-1: Sony Store の商品ページ ───────────────────────────────────────────────

SONY_PRODUCT = ("<html><body><h1>PlayStation®5 Pro CFI-7100B01</h1><p>ソニーストアで購入すると 137,980 円(税込) "
                "クーポン適用額をチェック (サインイン/新規登録) 入荷待ち 提携カード決済で3％OFF</p>"
                "<p>ソニーストアで購入すると 137,980 円(税込) クーポン適用額をチェック (サインイン/新規登録) 入荷待ち</p>"
                "</body></html>")


def test_sony_product_page_is_read_by_model_price_and_stock():
    r = RO.parse_sony_product(SONY_PRODUCT, "CFI-7100B01")
    assert r == {"model_found": True, "price": 137980, "stock": "入荷待ち", "ended": False}
    assert RO.classify({"price": 137980}, r) == "unchanged"


def test_sony_product_page_price_change_needs_review_not_overwrite():
    h = SONY_PRODUCT.replace("137,980", "149,980")
    r = RO.parse_sony_product(h, "CFI-7100B01")
    assert r["price"] == 149980 and RO.classify({"price": 137980}, r) == "changed"      # 自動で書き換えない


@pytest.mark.parametrize("html", [
    SONY_PRODUCT.replace("CFI-7100B01", "CFI-7000B01"),                                # 別の型番のページ
    SONY_PRODUCT.replace("<p>ソニーストアで購入すると 137,980", "<p>ソニーストアで購入すると 99,980", 1),  # 価格が2種類
    "<html><body>CFI-7100B01 ページが見つかりません</body></html>",                     # 価格が無い
])
def test_sony_product_page_ambiguous_or_wrong_is_not_read(html):
    r = RO.parse_sony_product(html, "CFI-7100B01")
    assert r["price"] is None and RO.classify({"price": 137980}, r) == "failed"


def test_sony_product_page_falls_back_to_purchase_page_layout():
    h = "<div>PlayStation®5 Pro 選択済み CFI-7100B01 入荷待ち 137,980円(税込)</div>"
    assert RO.parse_sony_product(h, "CFI-7100B01")["price"] == 137980


# ── M-1: 任天堂の商品ラインナップ ──────────────────────────────────────────────

TITLE = "Nintendo Switch 2 本体 日本語・国内専用"
NIN_CURRENT = ("<html><body><h2>" + TITLE + "</h2><p>発売日： 2025. 6 . 5 （木） 希望小売価格： 59,980 円（税込） セット内容</p>"
               "<div>生産終了した本体</div><div>本体＋ソフト 生産終了 Nintendo Switch 2 日本語・国内専用 "
               "マリオカート ワールド セット 2025.6.5（木）発売</div>"
               "<p>Nintendo Switch 2 スプラトゥーン レイダースセット 日本語・国内専用 発売日： 2026. 7 . 23 （木） "
               "希望小売価格： 64,980 円（税込）</p></body></html>")


def test_nintendo_lineup_current_unit_is_read():
    r = RO.parse_nintendo_lineup(NIN_CURRENT, TITLE)
    assert r == {"model_found": True, "price": 59980, "stock": "", "ended": False}
    assert RO.classify({"price": 59980}, r) == "unchanged"


def test_nintendo_lineup_unit_moved_to_ended_section_is_sale_ended():
    h = ("<html><body><div>生産終了した本体</div><h2>" + TITLE + "</h2>"
         "<p>発売日： 2025. 6 . 5 （木） 希望小売価格： 59,980 円（税込）</p></body></html>")
    r = RO.parse_nintendo_lineup(h, TITLE)
    assert r["ended"] is True and RO.classify({"price": 59980}, r) == "sale_ended"


def test_nintendo_lineup_set_products_and_price_change_are_not_confused():
    # セットの商品（別の名前・別の価格）は拾わない。価格が違えば changed
    assert RO.parse_nintendo_lineup(NIN_CURRENT, "Nintendo Switch 2 スプラトゥーン レイダースセット 日本語・国内専用")["price"] == 64980
    r = RO.parse_nintendo_lineup(NIN_CURRENT.replace("59,980", "64,980", 1), TITLE)
    assert RO.classify({"price": 59980}, r) == "changed"
    assert RO.parse_nintendo_lineup("<html><body>別のページ</body></html>", TITLE)["model_found"] is False


# ── M-1: 対象・取得するページ・結果の記録 ───────────────────────────────────────

def test_ps5_pro_and_switch2_are_recheck_targets_with_separate_fetch_page():
    ts = {t["product_id"]: t for t in RO._targets()}
    ps5, sw = ts["prod_ps5_pro"], ts["prod_switch2"]
    assert ps5["fetch_url"].endswith("/CFI-7100B01_product/") and ps5["fetch_url"] != ps5["url"]
    assert ps5["parser"] == "sony_product" and ps5["match"] == "CFI-7100B01"
    # Switch 2: My Nintendo Store（待機室へ移る）は取らない。任天堂の公式のラインナップを読む
    assert sw["url"].startswith("https://store-jp.nintendo.com/") and sw["fetch_url"].startswith("https://www.nintendo.com/jp/")
    assert sw["parser"] == "nintendo_lineup" and sw["match"] == TITLE
    assert "store-jp.nintendo.com" not in {t["fetch_url"].split("/")[2] for t in RO._targets()}


def test_recheck_result_keeps_registry_url_and_records_fetched_page():
    seen = []

    def fetch(url):
        seen.append(url)
        return (SONY_PRODUCT, "") if "sony" in url else (NIN_CURRENT, "") if "nintendo.com/jp" in url else (None, "timeout")

    out = {r["product_id"]: r for r in RO.recheck(NOW, fetch=fetch)}
    ps5, sw = out["prod_ps5_pro"], out["prod_switch2"]
    assert ps5["status"] == "unchanged" and ps5["stock"] == "入荷待ち"
    assert sw["status"] == "unchanged" and sw["stock"] == ""
    # 結果の url は記録（VERIFIED_URLS）の URL のまま（記録との照合に使う）。読んだページは fetched_url
    from src.market.official_registry import VERIFIED_URLS
    assert ps5["url"] == VERIFIED_URLS["prod_ps5_pro"]["url"] and ps5["fetched_url"].endswith("_product/")
    assert sw["url"] == VERIFIED_URLS["prod_switch2"]["url"] and "store-jp.nintendo.com" not in sw["fetched_url"]
    assert not any("store-jp.nintendo.com" in u or u.endswith("_purchase/") for u in seen)
    assert "fetched_url" not in out["prod_airpods_pro3"]                                # 同じページを読む商品には付けない


def test_recheck_unreachable_page_is_failed_and_does_not_confirm():
    out = {r["product_id"]: r for r in RO.recheck(NOW, fetch=lambda url: (None, "moved"))}
    assert out["prod_ps5_pro"]["status"] == "failed" and out["prod_ps5_pro"]["price"] is None


# ── Low: 404 / 410 を取り直さない ──────────────────────────────────────────────

class _Robots:
    def robots_status(self, url):
        return "allowed"

    def is_allowed(self, url):
        return True

    def get_crawl_delay(self, url):
        return 0


class _Limiter:
    def wait_if_needed(self, url, interval):
        pass


def _collector(monkeypatch, statuses):
    """状態コードを順に返す偽のセッションを持つ取得の基盤（待たない）。"""
    class C(collector_base.BaseCollector):
        def collect(self, product, config):
            return None

    c = C(SimpleNamespace(rate_limit_sec=0), None, rate_limiter=_Limiter(), robots_checker=_Robots())
    calls = []

    def get(url, timeout=None):
        calls.append(url)
        code = statuses[min(len(calls) - 1, len(statuses) - 1)]
        r = requests.Response()
        r.status_code = code
        r._content = b"<html>ok</html>"
        r.url = url
        return r

    monkeypatch.setattr(c.session, "get", get)
    sleeps = []
    monkeypatch.setattr(collector_base.time, "sleep", sleeps.append)
    monkeypatch.setattr(collector_base, "_GONE_URLS", set())
    return c, calls, sleeps


@pytest.mark.parametrize("code", [404, 410, 403, 401])
def test_permanent_client_errors_are_not_retried(monkeypatch, code):
    c, calls, sleeps = _collector(monkeypatch, [code])
    assert c.fetch_page("https://www.example.jp/x") is None
    assert len(calls) == 1 and sleeps == []                                           # 取り直さない・待たない


@pytest.mark.parametrize("code", [429, 500, 503])
def test_transient_errors_are_still_retried(monkeypatch, code):
    c, calls, sleeps = _collector(monkeypatch, [code])
    assert c.fetch_page("https://www.example.jp/x") is None
    assert len(calls) == c.MAX_RETRIES and len(sleeps) == c.MAX_RETRIES - 1


def test_transient_error_then_success_returns_page(monkeypatch):
    c, calls, _ = _collector(monkeypatch, [503, 200])
    assert c.fetch_page("https://www.example.jp/x") == "<html>ok</html>" and len(calls) == 2


def test_gone_url_is_not_fetched_again_in_the_same_run(monkeypatch):
    c, calls, _ = _collector(monkeypatch, [404])
    assert c.fetch_page("https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro-max") is None
    assert c.fetch_page("https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro-max") is None   # 別の商品の取得
    assert len(calls) == 1
    # 403 は URL を「消えた」とは記録しない（別の商品の取得は規則どおり1回試す）
    c2, calls2, _ = _collector(monkeypatch, [403])
    c2.fetch_page("https://www.example.jp/y")
    c2.fetch_page("https://www.example.jp/y")
    assert len(calls2) == 2


# ── Low: 公式価格の二重管理（update_buyback_prices.OFFICIAL_PRICES） ───────────────

def _ubp():
    import importlib.util
    sp = importlib.util.spec_from_file_location("ubp_integrity", ROOT / "scripts" / "update_buyback_prices.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_official_prices_for_anomaly_check_come_from_the_registry():
    from src.market import official_registry as reg
    m = _ubp()
    # 改定前の値（PS5 Pro 119,980・Switch 2 49,980）が別の表に残らない
    assert m.OFFICIAL_PRICES["ps5_pro"] == reg.VERIFIED_URLS["prod_ps5_pro"]["price"] == 137980
    assert m.OFFICIAL_PRICES["switch2"] == reg.VERIFIED_URLS["prod_switch2"]["price"] == 59980
    for alias, pid in m.ALIAS_PRODUCT_ID.items():
        rec = reg.VERIFIED_URLS.get(pid) or reg.OFFICIAL_DIRECT_OFFERS.get(pid) or reg.LIST_PRICES.get(pid)
        if rec:
            assert m.OFFICIAL_PRICES[alias] == rec["price"], alias
    assert set(m.OFFICIAL_PRICES) == set(m.ALIAS_PRODUCT_ID) and set(m.OFFICIAL_PRICES) <= set(m.PRODUCT_GENRES)


def test_verified_price_of_precedence_and_no_guess():
    from src.market import official_registry as reg
    assert reg.verified_price_of("prod_ps5_pro", 119980) == 137980            # 確認済みの記録が設定値より先
    assert reg.verified_price_of("prod_gr4_hdf", 0) == 222000                  # 定価の記録
    assert reg.verified_price_of("prod_unknown", 1000) == 1000                 # 記録が無ければ参考価格
    assert reg.verified_price_of("prod_unknown", 0) is None and reg.verified_price_of("prod_unknown") is None
    assert reg.verified_price_of("prod_unknown", True) is None                  # bool を価格にしない


def test_config_price_drift_is_read_only_and_needs_review():
    import yaml

    from src.market import official_registry as reg
    path = ROOT / "config" / "products.yaml"
    before = path.read_bytes()
    rows = reg.config_price_drift(yaml.safe_load(path.read_text(encoding="utf-8"))["products"])
    assert path.read_bytes() == before                                         # 正本を書き換えない
    ids = {r["product_id"]: r for r in rows}
    assert {"prod_x100vi", "prod_gr4_hdf", "prod_iphone17_256"} <= set(ids)
    assert all(r["status"] == "REVIEW_REQUIRED" and r["diff"] == r["verified_price"] - r["config_price"] for r in rows)
    assert "prod_ps5_pro" not in ids and "prod_switch2" not in ids             # 設定値と確認値が同じ商品は出さない
    assert reg.config_price_drift([{"id": "prod_x100vi", "retail_price": 315700}]) == []
