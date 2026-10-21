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


# ── M-3: カテゴリ共通の上限は目安（商品ページの行・別の店の裏付け・公式の 2 倍以内がそろうときだけ採用） ──────────

ITEM_A = "https://www.kaitorishouten-co.jp/products/detail/25543"
ITEM_B = "https://shop-b.test-store.jp/products/detail/77"
TOP_B = "https://www.mobile-ichiban.com/"


def _prow(shop, price, url, *, alias="ps5_pro", verified="true", conf="high", source="auto_scraped"):
    r = _row(alias, shop, price, at="2026-10-22T16:50:00+09:00", source=source)
    r.update({"url": url, "link_verified": verified, "confidence": conf})
    return r


def _quarantined(m, rows):
    sus = m.compute_suspicious(rows, [])
    return [r["data_source"] == "suspicious_rejected" for r in m.quarantine_suspicious(rows, sus)], {s["reason"] for s in sus}


def test_ceiling_is_accepted_only_with_item_level_corroboration_from_another_shop():
    from src.market.price_quality import HARD_REJECT_REASONS
    m = _ubp()
    rows = [_prow("kaitori_shouten", 200700, ITEM_A), _prow("shop_b", 200700, ITEM_B)]
    quarantined, reasons = _quarantined(m, rows)
    assert not any(quarantined) and "above_genre_max_corroborated" in reasons and not (reasons & HARD_REJECT_REASONS)
    sus = [s for s in m.compute_suspicious(rows, []) if s["reason"] == "above_genre_max_corroborated"]
    assert {s["shop"] for s in sus} == {"kaitori_shouten", "shop_b"} and "商品ページの行" in sus[0]["details"]


def test_ps5_pro_real_case_stays_review_required_until_an_item_level_shop_agrees():
    """2026-10-21: 買取商店は商品ページの行（200,700）、モバイル一番は店のトップの URL。トップの行は裏付けにならない。"""
    m = _ubp()
    rows = [_prow("kaitori_shouten", 200700, ITEM_A), _prow("mobile_ichiban", 200700, TOP_B, verified="false")]
    quarantined, reasons = _quarantined(m, rows)
    assert all(quarantined) and "above_genre_max" in reasons and "above_genre_max_corroborated" not in reasons


def test_ceiling_corroboration_conditions_each_matter():
    m = _ubp()
    base = [_prow("kaitori_shouten", 200700, ITEM_A)]
    cases = {
        "裏付けの店が1つも無い": base,
        "別の店の水準が違う": base + [_prow("shop_b", 150000, ITEM_B)],
        "裏付けの店が店のトップ": base + [_prow("shop_b", 200700, TOP_B)],
        "裏付けの店が未照合": base + [_prow("shop_b", 200700, ITEM_B, verified="false")],
        "裏付けの店が低信頼度": base + [_prow("shop_b", 200700, ITEM_B, conf="low")],
        "裏付けの店が手入力": base + [_prow("shop_b", 200700, ITEM_B, source="manual_today")],
        "この行が低信頼度": [_prow("kaitori_shouten", 200700, ITEM_A, conf="low"), _prow("shop_b", 200700, ITEM_B)],
        "この行が店のトップ": [_prow("kaitori_shouten", 200700, TOP_B, verified="false"), _prow("shop_b", 200700, ITEM_B)],
    }
    for name, rows in cases.items():
        quarantined, reasons = _quarantined(m, rows)
        assert quarantined[0] and "above_genre_max" in reasons, name
    # 裏付けの行が、別の理由（同じ店の別の商品に同額 = 取り違えの典型）で隔離される行なら、裏付けにならない
    rows = [_prow("kaitori_shouten", 200700, ITEM_A), _prow("dosupara", 200700, ITEM_B),
            _prow("dosupara", 200700, ITEM_B.replace("77", "78"), alias="switch2")]
    assert _quarantined(m, rows)[0][0] is True


def test_ceiling_corroboration_never_overrides_product_relative_limits():
    m = _ubp()
    ok = [_prow("kaitori_shouten", 205000, ITEM_A), _prow("shop_b", 205000, ITEM_B)]      # 公式 137,980 の 1.49 倍 = 1.5 倍以内
    assert not any(_quarantined(m, ok)[0])
    too_high = [_prow("kaitori_shouten", 210000, ITEM_A), _prow("shop_b", 210000, ITEM_B)]  # 1.52 倍 = 1.5 倍を超える（2 店が同額でも隔離）
    q, reasons = _quarantined(m, too_high)
    assert all(q) and "above_genre_max" in reasons and "above_genre_max_corroborated" not in reasons
    far = [_prow("kaitori_shouten", 450000, ITEM_A), _prow("shop_b", 450000, ITEM_B)]
    assert "over_3x_official" in _quarantined(m, far)[1] and all(_quarantined(m, far)[0])
    low = [_prow("kaitori_shouten", 5000, ITEM_A), _prow("shop_b", 5000, ITEM_B)]         # 下限未満（パース誤り）は裏付けがあっても隔離
    assert "below_genre_min" in _quarantined(m, low)[1] and all(_quarantined(m, low)[0])


def test_ceiling_corroborator_must_pass_the_same_limits_itself():
    """隔離される行（公式の 1.5 倍超）を裏付けにして、別の行を採用しない。"""
    m = _ubp()
    rows = [_prow("kaitori_shouten", 200700, ITEM_A), _prow("shop_b", 215000, ITEM_B)]    # 215,000 は 1.56 倍・±10% の中
    q, reasons = _quarantined(m, rows)
    assert q == [True, True] and "above_genre_max_corroborated" not in reasons
    mixed = [_prow("kaitori_shouten", 270000, ITEM_A), _prow("shop_b", 285000, ITEM_B)]   # 両方 1.5 倍超
    assert _quarantined(m, mixed)[0] == [True, True]


def test_ceiling_corroboration_needs_independent_item_pages_and_explicit_fields():
    m = _ubp()
    base = _prow("kaitori_shouten", 200700, ITEM_A)
    cases = {
        "同じ URL（同じ元の複製）": [base, _prow("shop_b", 200700, ITEM_A)],
        "同じ運営元のホスト": [base, _prow("shop_b", 200700, "https://www.kaitorishouten-co.jp/products/detail/9")],
        "一覧ページの根": [base, _prow("shop_b", 200700, "https://b.test-store.jp/products/")],
        "識別の番号が無い": [base, _prow("shop_b", 200700, "https://b.test-store.jp/products/detail/")],
    }
    for name, rows in cases.items():
        assert _quarantined(m, rows)[0][0] is True, name
    for missing in ("confidence", "data_source", "link_verified"):                      # キーが欠けた行は通さない
        b = _prow("shop_b", 200700, ITEM_B)
        b.pop(missing)
        assert _quarantined(m, [base, b])[0][0] is True, missing
    ok = [base, _prow("shop_b", 200700, ITEM_B, conf="medium")]
    assert not any(_quarantined(m, ok)[0])


def test_adopted_ceiling_price_is_visible_to_the_operator():
    from src.ops import health_alert as ha
    m = _ubp()
    rows = [_prow("kaitori_shouten", 200700, ITEM_A), _prow("shop_b", 200700, ITEM_B)]
    sus = m.compute_suspicious(rows, [])
    col = _col_report({"kaitori_shouten": {"ok": 5, "failed": 0}}, suspicious=sus)
    keys = {a["key"]: a["severity"] for a in ha.evaluate(_inp(col), HNOW)}
    assert keys == {"price_adopted_over_ceiling:ps5_pro": "WARNING"}                     # 隔離ではないが、人が確認できるように出す


def test_stale_collector_report_is_not_used_and_does_not_recover_alerts():
    from src.ops import health_alert as ha
    col = _col_report({"netoff": {"ok": 0, "failed": 4}, "kaitori_shouten": {"ok": 30, "failed": 0}},
                      fetch_failed=[{"shop": "netoff", "reason": "price_not_found"}])
    state, r1 = ha.reconcile({}, ha.evaluate(_inp(col, {"netoff": _days(4)}), HNOW), HNOW)
    assert [c["key"] for c in r1["candidates"]] == ["source_failure:netoff"]
    old = dict(col, generated_at="2026-10-20T18:00:00+09:00")                             # 2 日前のレポートが残った
    inputs = _inp(old, {"netoff": _days(4)})
    now2 = HNOW + timedelta(days=1)
    assert ha.collector_state(inputs, now2) == "stale" and ha.collector_state(_inp(col), HNOW) == "ok"
    cur = ha.evaluate(inputs, now2)
    assert {a["key"] for a in cur} == {"collector_report_stale:collector_report"} and cur[0]["severity"] == "HIGH"
    state, r2 = ha.reconcile(state, cur, now2, ha.unobservable_categories(inputs, now2))
    assert r2["recovered"] == [] and "source_failure:netoff" in state["active"]
    assert ha.collector_state(_inp(dict(col, generated_at="壊れた")), HNOW) == "stale"
    assert ha.collector_state(_inp({}), HNOW) == "missing"


# ── Low: 健康度（利益の発見・設定値を新鮮と数えない） ────────────────────────────────

def _health():
    import importlib.util
    sp = importlib.util.spec_from_file_location("ghr_integrity", ROOT / "scripts" / "generate_health_report.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_health_profit_discovery_sees_confirmed_official_to_buyback_deals():
    h = _health()
    pid = "prod_iphoneduo_256"
    obs = [_obs(pid, "official", 364800), _obs(pid, "sell", 395000)]
    deals = h._official_to_buyback(obs, url_of=lambda p: APPLE_DUO)
    pf = h._profit({"main_routes": [], "reference_routes": []}, deals)
    assert pf["official_to_buyback_count"] == 1 and pf["official_to_buyback_max_profit"] == 28400
    assert pf["main_route_count"] == 0                                                     # 売買ルートとは別に数える
    dq = h._data_quality(obs)
    score = h._score(dq, pf, h._sources(obs))
    assert score["profit_discovery"] == 15.0                                               # 以前は 0.0（売買ルートしか見ていなかった）
    none = h._profit({"main_routes": [], "reference_routes": []}, [])
    assert h._score(dq, none, h._sources(obs))["profit_discovery"] == 0.0                  # 案件が無ければ 0
    # 利益なし・設定値だけの公式の価格は数えない
    assert h._official_to_buyback([_obs(pid, "official", 364800), _obs(pid, "sell", 300000)], url_of=lambda p: APPLE_DUO) == []
    ref = _obs(pid, "official", 364800, extraction_method="retail_concept", freshness_basis="config_unknown_date")
    assert h._official_to_buyback([ref, _obs(pid, "sell", 395000)], url_of=lambda p: APPLE_DUO) == []


def test_health_does_not_count_configured_reference_as_fresh():
    h = _health()
    ref = _obs("prod_iphone17pro_256", "official", 179800, extraction_method="retail_concept",
               freshness_basis="config_unknown_date", source_name="メーカー公式/定価")
    real = _obs("prod_iphoneduo_256", "official", 364800, source_name="メーカー公式/定価")
    dq = h._data_quality([ref, real])
    assert dq["stale_count"] == 1 and dq["config_reference_count"] == 1                  # 設定値は新鮮に数えない
    src = h._sources([ref, real])["メーカー公式/定価"]
    assert src["freshness"] == 0.5 and src["stale_count"] == 1


# ── Low: 失敗の数え方（rows_failed・quality_rejected・rows_skipped・sources_failed・requests_failed） ──

def test_failure_counters_separate_rows_rejected_skipped_and_sources():
    m = _ubp()
    summary = [("a", "s1", "OK", 100), ("a", "s2", "FAILED", 0), ("b", "s2", "FAILED", 0), ("a", "s3", "SKIP", 0),
               ("c", "s1", "FAILED", 0), ("d", "s4", "FAILED", 0)]
    reasons = {("a", "s2"): "http_403", ("b", "s2"): "http_403", ("c", "s1"): "suspicious_rejected", ("d", "s4"): "price_not_found"}
    stats = {"s1": {"ok": 1, "failed": 1, "skip": 0}, "s2": {"ok": 0, "failed": 2, "skip": 0},
             "s3": {"ok": 0, "failed": 0, "skip": 1}, "s4": {"ok": 0, "failed": 1, "skip": 0}}
    c = m.failure_counters(summary, reasons, stats, fetch_failed_count=5)
    assert (c["rows_total"], c["rows_ok"], c["rows_failed"], c["quality_rejected"], c["rows_skipped"]) == (6, 1, 3, 1, 1)
    assert c["rows_not_ok"] == 5 == c["rows_not_ok_listed"]                     # fetch_failed の一覧の件数と一致する
    assert c["failure_rate_pct"] == round(4 / 6 * 100, 1)                        # (失敗 + 隔離) / 全行（品質ゲートの率）
    assert (c["sources_failed"], c["sources_ok"]) == (2, 1) and c["requests_failed"] == 2   # s3 は試していないので数えない
    assert set(c) - {"rows_not_ok_listed"} <= set(m.COUNTER_DEFINITIONS)         # 全部に定義がある


# ── M-4: 運営者向けの劣化アラート（商品の通知とは別・外部へ送らない・重ねて出さない・復旧を記録） ──────────

HNOW = datetime(2026, 10, 22, 18, 30, tzinfo=JST)


def _col_report(by_shop, fetch_failed=(), suspicious=(), low=0):
    return {"generated_at": "2026-10-22T18:00:00+09:00", "by_shop": by_shop, "fetch_failed": list(fetch_failed),
            "suspicious_prices": list(suspicious), "low_confidence_count": low}


def _inp(collector, history=None, official=(), optional=("geo", "hardoff")):
    from src.market.price_quality import HARD_REJECT_REASONS
    return {"collector": collector, "failure_history": history or {}, "optional_shops": list(optional),
            "hard_reject_reasons": sorted(HARD_REJECT_REASONS), "official_status": list(official)}


def _days(n, end="2026-10-22"):
    from datetime import date, timedelta
    d = date.fromisoformat(end)
    return [(d - timedelta(days=i)).isoformat() for i in range(n)]


def test_health_alert_normal_day_has_no_candidates():
    from src.ops import health_alert as ha
    healthy = _col_report({"kaitori_shouten": {"ok": 15, "failed": 2}, "kaitori_itchome": {"ok": 4, "failed": 0},
                          "geo": {"ok": 0, "failed": 2}, "hardoff": {"ok": 0, "failed": 2}})
    cur = ha.evaluate(_inp(healthy, {"geo": _days(30), "hardoff": _days(30)}), HNOW)
    assert cur == []                                                  # 任意の店の失敗・必須の店の少しの失敗は出さない
    state, res = ha.reconcile({}, cur, HNOW)
    assert res["candidates"] == [] and res["recovered"] == [] and state["active"] == {}


def test_health_alert_required_source_failures_are_classified_and_degraded_runs_are_not_hidden():
    from src.ops import health_alert as ha
    col = _col_report({"iosys": {"ok": 0, "failed": 6}, "netoff": {"ok": 0, "failed": 4}, "kaitori_shouten": {"ok": 1, "failed": 0}},
                     fetch_failed=[{"shop": "iosys", "reason": "http_403"}, {"shop": "netoff", "reason": "price_not_found"}])
    cur = {a["key"]: a for a in ha.evaluate(_inp(col, {"iosys": _days(4), "netoff": _days(4)}), HNOW)}
    assert cur["source_failure:iosys"]["severity"] == "WARNING"        # 既知のブロック（403）= degraded
    assert cur["source_failure:netoff"]["severity"] == "HIGH"          # 予想外の理由（価格が見つからない）
    # 今日から取れなくなった必須の店は HIGH（新しい異常）
    new = {a["key"]: a for a in ha.evaluate(_inp(col, {"iosys": _days(1), "netoff": _days(4)}), HNOW)}
    assert new["source_failure:iosys"]["severity"] == "HIGH" and new["source_failure:iosys"]["evidence"]["consecutive_days"] == 1
    # 失敗率（必須の店）: 50% 以上 WARNING・80% 以上 HIGH。任意の店は分母に入れない
    half = ha.evaluate(_inp(_col_report({"iosys": {"ok": 5, "failed": 5}, "geo": {"ok": 0, "failed": 99}}), {}), HNOW)
    assert [a["severity"] for a in half if a["category"] == "failure_rate"] == ["WARNING"]
    most = ha.evaluate(_inp(_col_report({"iosys": {"ok": 1, "failed": 9}}), {}), HNOW)
    assert [a["severity"] for a in most if a["category"] == "failure_rate"] == ["HIGH"]


def test_health_alert_quality_gate_and_official_verification():
    from src.ops import health_alert as ha
    sus = [{"product_alias": "ps5_pro", "shop": "kaitori_shouten", "reason": "above_genre_max", "details": "上限超過"},
           {"product_alias": "x100vi", "shop": "kaitori_shouten", "reason": "price_change_over_20pct", "details": "変動"},
           {"product_alias": "ps5_pro", "shop": "mobile_ichiban", "reason": "above_genre_max_corroborated", "details": "採用"}]
    off = [{"product_id": "prod_ps5_pro", "days_left": 5, "expired": False, "consecutive_failures": 9, "last_verified": "2026-10-12"},
           {"product_id": "prod_switch2", "days_left": 1, "expired": False, "consecutive_failures": 0, "last_verified": "2026-10-08"},
           {"product_id": "prod_old", "days_left": -2, "expired": True, "consecutive_failures": 3, "last_verified": "2026-10-01"},
           {"product_id": "prod_ok", "days_left": 14, "expired": False, "consecutive_failures": 0, "last_verified": "2026-10-22"}]
    cur = {a["key"]: a["severity"] for a in ha.evaluate(_inp(_col_report({}, suspicious=sus, low=2), official=off), HNOW)}
    assert cur["quality_gate_failure:ps5_pro"] == "WARNING" and "quality_gate_failure:x100vi" not in cur   # 変動だけ・採用した価格は出さない
    assert cur["quality_gate_failure:low_confidence"] == "WARNING"
    assert cur["official_recheck_failing:prod_ps5_pro"] == "HIGH"              # 9日連続
    assert cur["official_verification_expiry:prod_switch2"] == "WARNING"
    assert cur["official_verification_expiry:prod_old"] == "HIGH" and cur["official_recheck_failing:prod_old"] == "WARNING"
    assert not any(k.endswith("prod_ok") for k in cur)
    # 取得レポートが無ければ HIGH
    assert ha.evaluate(_inp({}), HNOW)[0]["key"] == "collector_report_missing:collector_report"


def test_health_alert_deduplicates_escalates_and_records_recovery():
    from datetime import timedelta as _td

    from src.ops import health_alert as ha
    a = ha._alert("source_failure", "iosys", ha.WARNING, "http_403", "t", "d")
    state, r1 = ha.reconcile({}, [a], HNOW)
    assert [c["event"] for c in r1["candidates"]] == ["NEW"] and r1["candidates"][0]["type"] == "PRODUCTION_HEALTH_ALERT"
    state, r2 = ha.reconcile(state, [a], HNOW + _td(days=1))                    # 翌日も同じ異常 → 出し直さない
    assert r2["candidates"] == [] and r2["suppressed"] == 1 and state["active"][a["key"]]["times_seen"] == 2
    assert state["active"][a["key"]]["first_seen"] == r1["candidates"][0]["first_seen"]
    high = {**a, "severity": ha.HIGH}
    state, r3 = ha.reconcile(state, [high], HNOW + _td(days=2))                  # 重くなったときだけ出し直す
    assert [c["event"] for c in r3["candidates"]] == ["ESCALATED"]
    state, r4 = ha.reconcile(state, [high], HNOW + _td(days=3))                  # 重いまま = 出さない
    assert r4["candidates"] == []
    state, r5 = ha.reconcile(state, [], HNOW + _td(days=4))                      # 解消 → 復旧を記録・状態から外す
    assert [x["type"] for x in r5["recovered"]] == ["PRODUCTION_HEALTH_RECOVERED"] and state["active"] == {}
    state, r6 = ha.reconcile(state, [a], HNOW + _td(days=5))                     # 復旧の後に再発 → 新しい異常として出す
    assert [c["event"] for c in r6["candidates"]] == ["NEW"]


def test_health_alert_record_is_operator_only_and_sends_nothing(tmp_path):
    import importlib.util
    sp = importlib.util.spec_from_file_location("oha_integrity", ROOT / "scripts" / "operator_health_alert.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    for rel, body in (("exports/collector_report/latest.json", '{"generated_at": "2026-10-22T18:00:00+09:00", "by_shop": {"iosys": {"ok": 0, "failed": 4}}, '
                                                               '"fetch_failed": [{"shop": "iosys", "reason": "price_not_found"}]}'),
                      ("exports/collector_report/failure_history.json", '{"iosys": ["2026-10-20", "2026-10-21", "2026-10-22"]}')):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body, encoding="utf-8")
    rec = m.run(root=tmp_path, now=HNOW)
    assert rec["type"] == "PRODUCTION_HEALTH_ALERT" and rec["audience"] == "operator"
    assert rec["product_notification_candidates"] == 0 and rec["customer_notification"] is False and rec["external_sends"] == 0
    assert (tmp_path / "exports" / "ops" / "health_alert.json").exists()
    assert not (tmp_path / "exports" / "notifications").exists()                  # 商品の通知の台帳に触れない
    again = m.run(root=tmp_path, now=HNOW + timedelta(hours=1))
    assert again["candidates"] == [] and again["suppressed"] >= 1                  # 同じ異常を毎回出さない
    assert any("source_failure:iosys" in line for line in m._annotations(rec))
    assert m.run(root=tmp_path, now=HNOW, dry_run=True)["type"] == "PRODUCTION_HEALTH_ALERT"


def test_health_alert_module_is_isolated_from_product_notifications():
    import re
    for rel in ("src/ops/health_alert.py", "scripts/operator_health_alert.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        imports = "\n".join(line for line in src.splitlines() if re.match(r"\s*(from|import)\s", line))
        assert not re.search(r"notifiers|outbox|telegram|discord|adapters|actionable|requests|urllib|smtplib", imports, re.I), rel
        assert not re.search(r"os\.environ\.get\(['\"](TELEGRAM|DISCORD|PRODUCT_REAL|PHASE24|NOTIFICATION)", src), rel
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    step = wf[wf.index("- name: Operator health alert"):wf.index("- name: Update lottery events")]
    assert "secrets." not in step and "TELEGRAM" not in step and "DISCORD" not in step and "vars." not in step
    assert "exports/ops/" in wf                                                   # 状態・記録を commit する


def test_admin_shows_ops_alert_separately(tmp_path):
    from src.content.ui import admin
    rec = {"type": "PRODUCTION_HEALTH_ALERT", "generated_at": "2026-10-22T18:30:00+09:00", "high": 1, "warning": 1,
           "suppressed": 3, "recovered": [{"key": "x"}],
           "active": [{"key": "required_source_failure:netoff", "severity": "HIGH", "title": "必須の店 netoff が連続", "details": "理由"},
                      {"key": "official_verification_expiry:prod_switch2", "severity": "WARNING", "title": "期限", "details": "残り1日"}]}
    v = admin.build_ops_alert(rec)
    assert v["present"] and (v["high"], v["warning"], v["recovered"], v["suppressed"]) == (1, 1, 1, 3) and len(v["rows"]) == 2
    assert admin.build_ops_alert(None)["present"] is False and admin.build_ops_alert("壊れた")["rows"] == []


# ── Low: 識別の手がかりの割合（部品番号は 2/47。coverage だけ。足す指示ではない） ───────────────

def test_identity_coverage_counts_clues_without_changing_products():
    import yaml

    from src.market import official_registry as reg
    path = ROOT / "config" / "products.yaml"
    before = path.read_bytes()
    prods = yaml.safe_load(path.read_text(encoding="utf-8"))["products"]
    ic = reg.identity_coverage(prods)
    assert path.read_bytes() == before and ic["products"] == len(prods) == 47
    assert ic["part_numbers"]["count"] == 2 and ic["part_numbers"]["pct"] == round(2 / 47 * 100, 1)
    assert ic["any_strong_key"]["count"] >= ic["part_numbers"]["count"] and ic["identity_evidence"]["count"] >= 2
    assert reg.identity_coverage([])["products"] == 0 and reg.identity_coverage(None)["part_numbers"]["pct"] == 0.0


# ── M-5: 定時の実行（毎時 0 分を避ける・1日1回・昼に始まる） ───────────────────────────

def _workflow():
    import yaml
    return yaml.safe_load((ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8"))


def test_schedule_is_daily_off_peak_and_starts_at_jst_noon():
    wf = _workflow()
    on = wf.get("on") or wf.get(True)
    crons = [x["cron"] for x in on["schedule"]]
    assert len(crons) == 1                                                   # 頻度を上げていない（1日1回）
    minute, hour, dom, month, dow = crons[0].split()
    assert (dom, month, dow) == ("*", "*", "*")
    assert int(minute) % 15 != 0                                             # 毎時 0 分（GitHub Actions が混む）を避ける
    assert 11 <= (int(hour) + 9) % 24 <= 14                                  # JST の昼（20:30 の確認より前に終わる）
    assert (int(hour), int(minute)) == (3, 17)                               # 12:17 JST
    assert "workflow_dispatch" in on and wf["concurrency"]["cancel-in-progress"] is False


def test_operator_alert_step_runs_after_quality_gate_and_never_blocks_the_run():
    steps = _workflow()["jobs"]["update-lp"]["steps"]
    names = [s.get("name") for s in steps]
    i = names.index("Operator health alert")
    assert i == names.index("Collector quality gate") + 1 and steps[i]["continue-on-error"] is True


def test_alert_key_does_not_change_as_a_failure_gets_older():
    """1〜2日目（新しい異常）→ 3日目（連続の異常）で key が変わると、「復旧」と「新規」が同時に出てしまう。"""
    from src.ops import health_alert as ha
    col = _col_report({"iosys": {"ok": 0, "failed": 6}, "kaitori_shouten": {"ok": 30, "failed": 0}},
                      fetch_failed=[{"shop": "iosys", "reason": "http_403"}])
    state = {}
    events = []
    for n in (1, 2, 3, 4):
        day = HNOW + timedelta(days=n)
        cur = ha.evaluate(_inp(dict(col, generated_at=day.isoformat()), {"iosys": _days(n)}), day)
        state, res = ha.reconcile(state, cur, day)
        events.append(([c["event"] for c in res["candidates"]], [r["key"] for r in res["recovered"]]))
    assert events[0] == (["NEW"], []) and all(rec == [] for _, rec in events)               # 一度も「復旧」にならない
    assert [e for e, _ in events[1:]] == [[], [], []]                                        # HIGH（新しい）→ WARNING（既知のブロック）でも出し直さない


def test_missing_collector_report_does_not_recover_collector_alerts_and_keeps_official_checks():
    from src.ops import health_alert as ha
    col = _col_report({"netoff": {"ok": 0, "failed": 4}, "kaitori_shouten": {"ok": 30, "failed": 0}},
                      fetch_failed=[{"shop": "netoff", "reason": "price_not_found"}])
    state, r1 = ha.reconcile({}, ha.evaluate(_inp(col, {"netoff": _days(4)}), HNOW), HNOW)
    assert [c["key"] for c in r1["candidates"]] == ["source_failure:netoff"]
    off = [{"product_id": "prod_switch2", "days_left": 1, "expired": False, "consecutive_failures": 0, "last_verified": "2026-10-08"}]
    missing_inputs = _inp({}, official=off)
    cur = ha.evaluate(missing_inputs, HNOW + timedelta(days=1))
    assert {a["key"] for a in cur} == {"collector_report_missing:collector_report", "official_verification_expiry:prod_switch2"}
    unobs = ha.unobservable_categories(missing_inputs, HNOW + timedelta(days=1))
    state, r2 = ha.reconcile(state, cur, HNOW + timedelta(days=1), unobs)
    assert r2["recovered"] == [] and "source_failure:netoff" in state["active"]             # 見えなくなっただけ（復旧にしない）
    fresh = dict(col, generated_at=(HNOW + timedelta(days=2)).isoformat())                 # 戻った日の取得レポート
    state, r3 = ha.reconcile(state, ha.evaluate(_inp(fresh, {"netoff": _days(4)}), HNOW + timedelta(days=2)),
                             HNOW + timedelta(days=2), ha.unobservable_categories(_inp(fresh), HNOW + timedelta(days=2)))
    assert [c["key"] for c in r3["candidates"]] == [] and {r["key"] for r in r3["recovered"]} == {
        "collector_report_missing:collector_report", "official_verification_expiry:prod_switch2"}
    assert ha.unobservable_categories(_inp(fresh), HNOW + timedelta(days=2)) == frozenset()


def test_alert_reescalates_after_severity_dropped_and_survives_broken_state():
    from src.ops import health_alert as ha
    a = ha._alert("source_failure", "iosys", ha.HIGH, "x", "t", "d")
    low = {**a, "severity": ha.WARNING}
    state, _ = ha.reconcile({}, [a], HNOW)
    state, r2 = ha.reconcile(state, [low], HNOW + timedelta(days=1))
    assert r2["candidates"] == [] and state["active"][a["key"]]["emitted_severity"] == ha.WARNING
    _, r3 = ha.reconcile(state, [a], HNOW + timedelta(days=2))
    assert [c["event"] for c in r3["candidates"]] == ["ESCALATED"]                           # 下がった後の再発は出し直す
    for broken in ({"active": []}, {"active": {"k": "壊れた"}}, "壊れた", None, {"active": None}):
        st, res = ha.reconcile(broken, [a], HNOW)
        assert [c["event"] for c in res["candidates"]] == ["NEW"] and set(st["active"]) == {a["key"]}


def test_annotations_escape_workflow_command_characters():
    import importlib.util
    sp = importlib.util.spec_from_file_location("oha_escape", ROOT / "scripts" / "operator_health_alert.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    rec = {"candidates": [{"severity": "HIGH", "event": "NEW", "title": "t", "key": "k",
                           "details": "理由\n::error::注入 100%"}], "recovered": []}
    line = m._annotations(rec)[0]
    assert len(line.splitlines()) == 1 and line.startswith("::error::") and "%0A" in line and "%25" in line   # 1行のまま（別のコマンドにならない）


def test_recheck_result_says_what_was_verified_and_msrp_lineup_does_not_extend_freshness():
    from datetime import date

    from src.market import official_registry as reg
    out = {r["product_id"]: r for r in RO.recheck(NOW, fetch=lambda u: (SONY_PRODUCT, "") if "sony" in u else
                                                  (NIN_CURRENT, "") if "nintendo.com/jp" in u else (None, "timeout"))}
    assert out["prod_switch2"]["verified_by"] == "msrp_lineup"                 # 希望小売価格だけ（購入ページ・在庫は未確認）
    assert out["prod_ps5_pro"]["verified_by"] == "store_product_page"
    assert "verified_by" not in out["prod_airpods_pro3"]                       # 記録の購入ページそのものを読んだ商品
    today = date(2026, 10, 22)
    rows = {r["product_id"]: r for r in reg.verification_status(list(out.values()), today=today)}
    # PS5 Pro（同じストアの商品ページ）は確認日が進む。Switch 2（希望小売価格だけ）は進まない = 期限が減り続ける
    assert rows["prod_ps5_pro"]["last_verified"] == "2026-10-22" and rows["prod_ps5_pro"]["verified_by"] == "store_product_page"
    assert rows["prod_switch2"]["last_verified"] == reg.VERIFIED_URLS["prod_switch2"]["checked_on"]
    assert rows["prod_switch2"]["days_left"] < rows["prod_ps5_pro"]["days_left"]
    assert reg.extends_verification({"verified_by": "msrp_lineup"}) is False
    assert reg.extends_verification({}) and reg.extends_verification({"verified_by": "store_product_page"})
    # 価格が変わった・販売終了は、希望小売価格だけの確認でも検知される（確認日を進める話ではない）
    moved = RO.recheck(NOW, fetch=lambda u: (NIN_CURRENT.replace("59,980", "64,980", 1), "") if "nintendo.com/jp" in u else (None, "timeout"))
    assert {r["product_id"]: r["status"] for r in moved}["prod_switch2"] == "changed"


def _audit_module():
    import importlib.util
    sp = importlib.util.spec_from_file_location("aos_integrity", ROOT / "scripts" / "audit_official_sources.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_apply_recheck_does_not_advance_dates_for_msrp_lineup_but_does_for_store_page(tmp_path):
    import json
    m = _audit_module()
    calls = []

    class C:
        def execute(self, sql, params=()):
            calls.append((sql, params))
            return SimpleNamespace(rowcount=1, fetchone=lambda: None)

        def commit(self):
            pass
    m.NOW = datetime(2026, 10, 22, 13, 0, tzinfo=JST)
    v_sw, v_ps = m.VERIFIED_URLS["prod_switch2"], m.VERIFIED_URLS["prod_ps5_pro"]
    results = [
        {"product_id": "prod_switch2", "status": "unchanged", "price": v_sw["price"], "recorded_price": v_sw["price"],
         "url": v_sw["url"], "model": "", "observed_at": "2026-10-22T12:30:00+09:00", "stock": "", "verified_by": "msrp_lineup"},
        {"product_id": "prod_ps5_pro", "status": "unchanged", "price": v_ps["price"], "recorded_price": v_ps["price"],
         "url": v_ps["url"], "model": "CFI-7100B01", "observed_at": "2026-10-22T12:31:00+09:00", "stock": "入荷待ち",
         "verified_by": "store_product_page"}]
    path = tmp_path / "latest.json"
    path.write_text(json.dumps({"results": results}), encoding="utf-8")
    applied = m.apply_recheck(C(), {"prod_switch2": {}, "prod_ps5_pro": {"model_number": "CFI-7100B01"}}, path)
    acts = {(a["product_id"], a["action"]) for a in applied}
    assert ("prod_switch2", "price_seen_not_extended") in acts and ("prod_switch2", "price_reconfirmed") not in acts
    assert ("prod_ps5_pro", "price_reconfirmed") in acts
    updated = [p for sql, p in calls if "official_price_updated_at=?" in sql]
    assert [x[1] for x in updated] == ["prod_ps5_pro"]                       # Switch 2 の確認日は書き換えない



def test_baseline_file_status_and_alert_when_unreadable(tmp_path):
    from src.collectors import price_baseline as pb
    from src.ops import health_alert as ha
    path = tmp_path / "price_baseline.json"
    assert pb.file_status(path) == "missing"
    path.write_text("{壊れた", encoding="utf-8")
    assert pb.file_status(path) == "unreadable"
    path.write_text('{"entries": "壊れた形"}', encoding="utf-8")
    assert pb.file_status(path) == "unreadable"
    pb.save(path, [], BNOW)
    assert pb.file_status(path) == "ok"
    st = pb.stats([], [], [], file="unreadable")
    assert st["baseline_file"] == "unreadable"
    col = _col_report({"kaitori_shouten": {"ok": 5, "failed": 0}})
    col["price_baseline"] = st
    keys = {a["key"]: a["severity"] for a in ha.evaluate(_inp(col), HNOW)}
    assert keys == {"baseline_unreadable:price_baseline": "WARNING"}
    col["price_baseline"] = pb.stats([], [], [], file="missing")                          # まだ無い（初回）は異常ではない
    assert ha.evaluate(_inp(col), HNOW) == []


# ── 在庫の状態を順位の各行に添える・公式 URL の取り方は3面で同じ ─────────────────────────

def test_ranking_rows_carry_availability_without_guessing_stock():
    rk = _ranking()
    off = "official_store"
    hist = {"entries": {
        "a": {"product_id": "prod_gr4_hdf", "source_type": off, "state": "LOTTERY", "last_checked_at": "2026-10-21T18:00:00+09:00"},
        "b": {"product_id": "prod_ps5_pro", "source_type": off, "state": "OUT_OF_STOCK", "last_checked_at": "2026-10-12T19:55:03+09:00"},
        "c": {"product_id": "prod_x100vi", "source_type": off, "state": "OUT_OF_STOCK", "last_checked_at": "2026-10-21T18:04:24+09:00"},
        "d": {"product_id": "prod_x100vi", "source_type": off, "state": "IN_STOCK", "last_checked_at": "2026-10-20T10:00:00+09:00"},
        "e": {"product_id": "", "source_type": off, "state": "IN_STOCK", "last_checked_at": "2026-10-21T18:00:00+09:00"},
        "f": {"product_id": "prod_z8", "source_type": off, "state": "IN_STOCK", "last_checked_at": "壊れた"},
        "g": "壊れた",
        # 公式以外の情報源（別の店・手入力）は、公式で買う案件に付けない
        "h": {"product_id": "prod_gr4_hdf", "source_type": "retail_ec", "state": "IN_STOCK", "last_checked_at": "2026-10-21T19:00:00+09:00"},
        "i": {"product_id": "prod_r5ii", "state": "IN_STOCK", "last_checked_at": "2026-10-21T19:00:00+09:00"},
        # タイムゾーン無しの時刻は JST とみなす（比較で落ちない）
        "j": {"product_id": "prod_switch2", "source_type": off, "state": "IN_STOCK", "last_checked_at": "2026-10-22T09:00:00"}}}
    av = rk.availability_by_product(hist, datetime(2026, 10, 22, 12, 0, tzinfo=JST))
    assert av == {"prod_gr4_hdf": "LOTTERY", "prod_ps5_pro": "UNKNOWN", "prod_x100vi": "OUT_OF_STOCK",
                  "prod_switch2": "IN_STOCK"}                                          # 7日超は未確認・新しい方・公式だけ
    assert rk.availability_by_product({}, NOW) == {} and rk.availability_by_product(None, NOW) == {}
    assert "在庫未確認" in rk._AVAILABILITY_LABELS["UNKNOWN"] and "入荷待ち" in rk._AVAILABILITY_LABELS["OUT_OF_STOCK"]
    src = (ROOT / "scripts" / "generate_ranking_report.py").read_text(encoding="utf-8")
    assert src.count("購入元の在庫:") >= 1                                              # 主語を付けた表示（買取店の在庫と読めない）


def test_official_url_is_the_same_for_scanner_ranking_and_health():
    import sqlite3

    from src.market import beginner_deal_scanner as bds
    assert bds.official_url_for_product(None, "prod_x", "Apple") == bds.APPLE_STORE_DEFAULT_URL
    assert bds.official_url_for_product(None, "prod_x", "RICOH") == ""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE product_source_config (product_id TEXT, source_id TEXT, target_url TEXT, extra_config TEXT)")
    con.execute("INSERT INTO product_source_config VALUES ('prod_a', 's', ?, ?)",
                (APPLE_DUO, '{"verified": true, "link_type": "item"}'))
    assert bds.official_url_for_product(con, "prod_a", "Apple") == APPLE_DUO                  # 確認済みの商品ページが先
    assert bds.official_url_for_product(con, "prod_b", "Apple") == bds.APPLE_STORE_DEFAULT_URL
    broken = sqlite3.connect(":memory:")                                                       # 表が無い DB でも落ちない
    assert bds.official_url_for_product(broken, "prod_a", "Apple") == bds.APPLE_STORE_DEFAULT_URL
    for rel in ("scripts/generate_ranking_report.py", "scripts/generate_health_report.py"):
        assert "official_url_for_product" in (ROOT / rel).read_text(encoding="utf-8"), rel


# ── git add は存在しないパスが1つでもあると全体が失敗する（運営者アラートの step が落ちても LP を commit する） ──

def test_commit_step_never_fails_because_of_a_missing_path():
    import re
    import subprocess
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    step = wf[wf.index("- name: Commit and push"):]
    start = step.index("git add docs/")
    add = step[start:step.index("|| true", start)]
    paths = [p for p in re.sub(r"\\\n|':\(exclude\)[^']*'", " ", add.replace("git add", "")).split() if p]
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    created = set(re.findall(r"mkdir -p (\S+)", step.split("git add docs/")[0]))
    missing = [p for p in paths if not any(t == p or t.startswith(p.rstrip("/") + "/") for t in tracked)
               and p.rstrip("/") not in {c.rstrip("/") for c in created}]
    assert missing == [], f"git add の対象に、リポジトリに無く・先に作られないパスがある: {missing}"
    assert "exports/ops/" in paths and "exports/ops" in created                      # 運営者アラートが落ちても失敗しない
    assert (ROOT / "exports" / "ops" / ".gitkeep").exists()


def test_admin_warning_bar_does_not_count_adopted_ceiling_price_as_a_move():
    from src.content.ui import admin
    sus = [{"product_alias": "ps5_pro", "shop": "a", "reason": "above_genre_max_corroborated", "price": 200700},
           {"product_alias": "x100vi", "shop": "a", "reason": "price_change_over_20pct", "price": 260000}]
    w = admin.collector_warn({"suspicious_prices": sus, "shop_detail": []}, set(), 5)
    assert w["moves"] == 1 and w["suspicious"] == 0                                    # 採用した価格は「大きな変動」に数えない


def test_baseline_future_observation_time_is_not_trusted():
    from src.collectors import price_baseline as pb
    now = BNOW
    ok = _row("a", "s", 1000, at="2026-10-22T17:30:00+09:00")                           # 30分先 = 時計のずれの範囲
    future = _row("a", "s", 1000, at="2026-10-22T20:00:00+09:00")                       # 3時間先
    assert pb.is_fresh(ok, now) and not pb.is_fresh(future, now)
    assert pb.build([], [future], now) == []                                              # 未来の時刻は基準に入れない


def test_official_direct_audit_ignores_msrp_lineup_for_freshness():
    from src.market import official_registry as reg
    v = reg.VERIFIED_URLS["prod_switch2"]
    base = {"product_id": "prod_switch2", "url": v["url"], "recorded_price": v["price"], "status": "unchanged",
            "price": v["price"], "observed_at": "2026-10-22T12:00:00+09:00"}
    products = [{"id": "prod_switch2", "name": "Switch 2"}]
    def last(extra):
        rows = reg.official_direct_audit(products, today="2026-10-22", recheck=[{**base, **extra}])
        return rows[0]["verified_at"] if rows else v["checked_on"]
    # official_direct_audit は公式直販価格（OFFICIAL_DIRECT_OFFERS）の商品だけを返す。Switch 2 は定価（msrp）なので
    # 関数の判定そのもの（extends_verification）で確かめる
    assert reg.extends_verification({**base, "verified_by": "store_product_page"}) is True
    assert reg.extends_verification({**base, "verified_by": "msrp_lineup"}) is False
    assert last({"verified_by": "msrp_lineup"}) == v["checked_on"]
