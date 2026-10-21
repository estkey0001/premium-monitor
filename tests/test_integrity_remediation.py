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


# ── M-2: 利益の式は1つ（順位レポート・スキャナー・候補の優先順位） ────────────────────

APPLE_DUO = "https://www.apple.com/jp/shop/buy-iphone/iphone-duo"


def test_profit_formula_is_the_single_cost_definition():
    from src.market import profit_formula as pf
    from src.models.beginner_deal import DEFAULT_COSTS
    assert pf.fixed_costs() == 1800 == (DEFAULT_COSTS["shipping_jpy"] + DEFAULT_COSTS["transfer_fee_jpy"]
                                        + DEFAULT_COSTS["transport_jpy"] + DEFAULT_COSTS["insurance_jpy"])
    assert pf.beginner_costs("prod_iphoneduo_256", APPLE_DUO, 364800) == 1800        # Apple は購入送料が無料（確認済み）
    assert pf.net_profit(364800, 395000, 1800) == 28400                              # Duo
    assert pf.net_profit(189800, 133000, 1800) == -58600                             # Air（no_profit）
    # 送料が分からない購入元は費用を出さない（0 円にしない）。スキャナー用の指定だけ 0 を足す
    assert pf.beginner_costs("prod_unknown", "https://shop.example.jp/x", 100000) is None
    assert pf.beginner_costs("prod_unknown", "https://shop.example.jp/x", 100000, shipping_unknown_as_zero=True) == 1800


def test_scanner_and_priority_use_the_same_cost_formula():
    from src.discovery import priority
    from src.market import profit_formula as pf
    from src.market.beginner_deal_scanner import BeginnerDealScanner
    sc = BeginnerDealScanner.__new__(BeginnerDealScanner)
    sc._get_official_url = lambda product: APPLE_DUO
    product = SimpleNamespace(id="prod_iphoneduo_256", brand="Apple")
    assert sc._estimate_costs(product, 364800) == pf.beginner_costs("prod_iphoneduo_256", APPLE_DUO, 364800) == 1800
    assert priority.known_costs(APPLE_DUO, 364800) == 1800
    # 送料が不明: スキャナーは 0 を足して確定の判定で外す・優先順位は差を出さない（None）
    sc._get_official_url = lambda product: "https://shop.example.jp/x"
    assert sc._estimate_costs(SimpleNamespace(id="prod_x", brand="X"), 100000) == 1800
    assert priority.known_costs("https://shop.example.jp/x", 100000) is None


def _obs(pid, role, price, **kw):
    base = {"product_id": pid, "product_name": pid, "price_role": role, "price": price, "is_usable_for_beginner": True,
            "extraction_method": "official" if role == "official" else "auto_scraped", "source_name": "買取商店",
            "item_url": "https://www.kaitorishouten-co.jp/products/detail/1", "source_url": "", "is_fresh": True,
            "freshness_basis": "observed" if role == "official" else "observed", "is_exact_product_match": True,
            "link_type": "item", "accessory_flag": False, "wrong_model_flag": False, "rejection_reason": "",
            "condition": "new_unopened", "canonical_price_type": "BUYBACK_CASH" if role == "sell" else "RETAIL",
            "price_type": "buyback_price" if role == "sell" else "official_price"}
    base.update(kw)
    return base


def _ranking():
    import importlib.util
    sp = importlib.util.spec_from_file_location("grr_integrity", ROOT / "scripts" / "generate_ranking_report.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _deals(obs, url=APPLE_DUO):
    return _ranking().build_beginner_deals(obs, {"prod_iphoneduo_256": "iphone"}, lambda pid: url)


def test_ranking_uses_canonical_formula_and_matches_opportunity():
    pid = "prod_iphoneduo_256"
    deals, ineligible = _deals([_obs(pid, "official", 364800), _obs(pid, "sell", 395000)])
    assert [(d.product_id, d.net_profit_jpy) for d in deals] == [(pid, 28400)] and ineligible == []   # 1,300 円の式なら +28,900
    assert round(deals[0].net_profit_rate, 4) == round(28400 / 364800, 4)                                # ROI 7.8%


def test_ranking_never_ranks_configured_reference_official_price():
    pid = "prod_iphoneduo_256"
    ref = _obs(pid, "official", 364800, extraction_method="retail_concept", freshness_basis="config_unknown_date")
    deals, ineligible = _deals([ref, _obs(pid, "sell", 395000)])
    assert deals == [] and ineligible == [{"product_id": pid, "reason": "official_configured_reference"}]
    stale = _obs(pid, "official", 364800, freshness_basis="verified_stale")
    assert _deals([stale, _obs(pid, "sell", 395000)])[0] == []                                          # 古い公式の価格も載せない


@pytest.mark.parametrize("sell", [
    {"link_type": "shop_home"}, {"link_type": "search"},            # 店のトップ・検索結果の行
    {"is_fresh": False}, {"is_exact_product_match": False},         # 古い・同一性が未確認
    {"rejection_reason": "suspicious_rejected"}, {"accessory_flag": True},
])
def test_ranking_ignores_unconfirmed_sell_rows(sell):
    pid = "prod_iphoneduo_256"
    assert _deals([_obs(pid, "official", 364800), _obs(pid, "sell", 395000, **sell)])[0] == []


def test_ranking_skips_products_with_unknown_purchase_shipping():
    pid = "prod_iphoneduo_256"
    deals, ineligible = _deals([_obs(pid, "official", 364800), _obs(pid, "sell", 395000)],
                               url="https://shop.example.jp/x")
    assert deals == [] and ineligible == [{"product_id": pid, "reason": "purchase_shipping_unknown"}]


def test_ranking_script_has_no_private_cost_constant():
    src = (ROOT / "scripts" / "generate_ranking_report.py").read_text(encoding="utf-8")
    assert "BEGINNER_COST" not in src and "1300" not in src and "profit_formula" in src


# ── M-3: 買取の比較の基準（直近の正常な自動取得の値） ──────────────────────────────

BNOW = datetime(2026, 10, 22, 17, 0, tzinfo=JST)


def _row(alias, shop, price, *, at="2026-10-21T17:22:00+09:00", source="auto_scraped", cond="new_unopened"):
    return {"product_alias": alias, "buyback_shop": shop, "buyback_price": str(price), "condition": cond,
            "url": "https://www.kaitorishouten-co.jp/kaden", "observed_at": at, "data_source": source,
            "link_verified": "true", "confidence": "high"}


def test_baseline_load_uses_only_recent_auto_scraped_values(tmp_path):
    from src.collectors import price_baseline as pb
    path = tmp_path / "price_baseline.json"
    pb.save(path, [
        {**_row("ps5_pro", "kaitori_shouten", 134500, at="2026-08-22T20:39:41+09:00")},        # 2か月前（古い）
        {**_row("x100vi", "kaitori_shouten", 428000, source="manual_today")},                 # 手入力
        {**_row("switch2", "kaitori_shouten", 0)},                                            # 価格なし
        {**_row("airpods_pro3", "kaitori_shouten", 32500, at="2026-11-30T00:00:00+09:00")},   # 未来
        {**_row("iphoneduo_256", "kaitori_shouten", 395000)},                                 # 正常
    ], BNOW)
    assert [(e["product_alias"], int(e["buyback_price"])) for e in pb.load(path, BNOW)] == [("iphoneduo_256", 395000)]
    assert pb.load(tmp_path / "missing.json", BNOW) == [] and pb.read_entries(tmp_path / "missing.json") == []
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert pb.load(tmp_path / "broken.json", BNOW) == []


def test_baseline_build_keeps_last_good_value_and_never_stores_bad_rows():
    from src.collectors import price_baseline as pb
    prev = [_row("iphoneduo_256", "kaitori_shouten", 395000, at="2026-10-20T17:00:00+09:00"),
            _row("x100vi", "kaitori_shouten", 260000, at="2026-10-01T17:00:00+09:00")]              # 21日前 = 古い
    new = [_row("ps5_pro", "kaitori_shouten", 0, source="suspicious_rejected"),                      # 隔離
           _row("ps5_pro", "mobile_ichiban", 0, source="fetch_failed"),                              # 取得失敗
           _row("switch2", "kaitori_shouten", 51800, source="manual_today"),                          # 手入力
           _row("airpods_pro3", "kaitori_shouten", 32500, at="2026-10-22T16:50:00+09:00")]          # 正常
    out = {(e["product_alias"], e["buyback_shop"]): e for e in pb.build(prev, new, BNOW)}
    assert set(out) == {("iphoneduo_256", "kaitori_shouten"), ("airpods_pro3", "kaitori_shouten")}
    assert out[("iphoneduo_256", "kaitori_shouten")]["observed_at"] == "2026-10-20T17:00:00+09:00"   # 失敗した日に時刻を新しくしない
    assert out[("airpods_pro3", "kaitori_shouten")]["observed_at"] == "2026-10-22T16:50:00+09:00"
    # 今回取れた値は基準を置き換える（取得できた時刻に）
    out2 = {(e["product_alias"], e["buyback_shop"]): e for e in pb.build(
        prev, [_row("iphoneduo_256", "kaitori_shouten", 400000, at="2026-10-22T16:55:00+09:00")], BNOW)}
    assert out2[("iphoneduo_256", "kaitori_shouten")]["buyback_price"] == 400000


def test_baseline_stats_report_new_observations_and_dropped_stale(tmp_path):
    from src.collectors import price_baseline as pb
    allp = [_row("x100vi", "kaitori_shouten", 428000, at="2026-08-22T12:00:00+09:00"),
            _row("iphoneduo_256", "kaitori_shouten", 395000, at="2026-10-21T17:00:00+09:00")]
    fresh = [e for e in allp if pb.is_fresh(e, BNOW)]
    st = pb.stats(allp, fresh, [_row("x100vi", "kaitori_shouten", 260000), _row("iphoneduo_256", "kaitori_shouten", 395000)])
    assert st["baseline_entries"] == 1 and st["stale_baseline_dropped"] == 1
    assert st["new_observations"] == [{"product_alias": "x100vi", "shop": "kaitori_shouten"}]       # 初めての観測は比較しない


def test_save_is_atomic_and_roundtrips(tmp_path):
    from src.collectors import price_baseline as pb
    path = tmp_path / "sub" / "price_baseline.json"
    rows = pb.build([], [_row("iphoneduo_256", "kaitori_shouten", 395000, at="2026-10-22T16:55:00+09:00")], BNOW)
    pb.save(path, rows, BNOW)
    assert not path.with_suffix(".json.tmp").exists() and pb.read_entries(path) == rows


def test_price_change_flag_needs_a_recent_baseline_and_is_never_a_hard_reject():
    from src.market.price_quality import HARD_REJECT_REASONS
    m = _ubp()
    new = [_row("x100vi", "kaitori_shouten", 260000, at="2026-10-22T16:50:00+09:00")]
    # 基準なし（初めての観測・古い手入力は基準にしない）→ 前回比の警告を出さない
    assert [s for s in m.compute_suspicious(new, []) if s["reason"] == "price_change_over_20pct"] == []
    # 直近の基準があり ±20% を超えれば警告（理由は記録）。ただし隔離の理由ではない
    base = [_row("x100vi", "kaitori_shouten", 428000, at="2026-10-21T17:00:00+09:00")]
    flags = [s for s in m.compute_suspicious(new, base) if s["reason"] == "price_change_over_20pct"]
    assert len(flags) == 1 and "428,000" in flags[0]["details"] and "260,000" in flags[0]["details"]
    assert "price_change_over_20pct" not in HARD_REJECT_REASONS
    assert m.quarantine_suspicious(new, m.compute_suspicious(new, base))[0]["data_source"] == "auto_scraped"


def test_run_compares_against_the_baseline_not_the_stale_manual_csv():
    src = (ROOT / "scripts" / "update_buyback_prices.py").read_text(encoding="utf-8")
    run_body = src[src.index("def run("):src.index("def keep_manual_on_failure(")]
    assert "compute_suspicious(new_rows, baseline_rows)" in run_body and "compute_suspicious(new_rows, existing_rows)" not in run_body
    assert "existing_rows=baseline_rows" in run_body and "price_baseline.save(" in run_body and "price_baseline.load(" in run_body


# ── M-3: カテゴリ共通の上限は絶対の上限にしない（別の店が裏付ければ採用） ────────────────

def _ps5(price_a, price_b=None, shop_b="mobile_ichiban"):
    rows = [_row("ps5_pro", "kaitori_shouten", price_a, at="2026-10-22T16:50:00+09:00")]
    if price_b:
        rows.append(_row("ps5_pro", shop_b, price_b, at="2026-10-22T16:51:00+09:00"))
    return rows


def test_ps5_pro_200700_is_accepted_when_another_shop_agrees():
    from src.market.price_quality import HARD_REJECT_REASONS
    m = _ubp()
    new = _ps5(200700, 200700)                                    # 買取商店の価格表の型番行と、モバイル一番が同額
    flags = {s["reason"] for s in m.compute_suspicious(new, [])}
    assert "above_genre_max_corroborated" in flags and not (flags & HARD_REJECT_REASONS)
    out = m.quarantine_suspicious(new, m.compute_suspicious(new, []))
    assert all(r["data_source"] == "auto_scraped" and r["buyback_price"] == "200700" for r in out)   # 隔離しない


def test_price_over_the_band_without_corroboration_is_still_quarantined():
    m = _ubp()
    for new in (_ps5(200700), _ps5(200700, 150000)):              # 1店だけ・別の店は水準が違う
        sus = m.compute_suspicious(new, [])
        assert any(s["reason"] == "above_genre_max" and "裏付けなし" in s["details"] for s in sus)
        assert m.quarantine_suspicious(new, sus)[0]["data_source"] == "suspicious_rejected"


def test_corroboration_never_overrides_product_relative_limits():
    m = _ubp()
    # 公式 137,980 の 2.5 倍（344,950）を超える・3 倍以上は、2店が同額でも隔離のまま
    new = _ps5(360000, 360000)
    reasons = {s["reason"] for s in m.compute_suspicious(new, [])}
    assert "above_genre_max" in reasons and "above_genre_max_corroborated" not in reasons
    assert m.quarantine_suspicious(new, m.compute_suspicious(new, []))[0]["data_source"] == "suspicious_rejected"
    far = _ps5(450000, 450000)
    assert "over_3x_official" in {s["reason"] for s in m.compute_suspicious(far, [])}
    # 下限未満（パース誤り）は裏付けがあっても隔離のまま
    low = [_row("ps5_pro", "kaitori_shouten", 5000), _row("ps5_pro", "mobile_ichiban", 5000)]
    assert any(s["reason"] == "below_genre_min" for s in m.compute_suspicious(low, []))
