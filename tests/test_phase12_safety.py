"""Phase 12（取得の安全性・売却データの網羅）のテスト。

各テストには、誤りを入れると失敗する否定対照（mutation）も付ける。
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=JST)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"p12_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── N1: 買取一丁目の実ページの形（2026-10-07 にブラウザで確認した本文） ─────────────

ITCHOME_2026_10_07 = (
    "iPhone 17 Pro 256GB\n新品\nOrange -6000 Blue -2000\n未開封\n¥171,000\n開封済未使用品\n¥158,000\n強化\n"
    "iPhone 17 Pro 512GB\n新品\n未開封\n¥198,000\n開封済未使用品\n¥185,000\n強化\n"
    "iPhone 17 Pro Max 1TB\n新品\n未開封\n¥238,500\n開封済未使用品\n¥226,000\n強化\n"
    "iPhone 17 Pro Max 256GB\n新品\nブルー、オレンジ　-2000\n未開封\n¥186,000\n開封済未使用品\n¥174,000\n強化\n"
    "iPhone 17 Pro Max 512GB\n新品\n未開封\n¥215,000\n開封済未使用品\n¥203,000\n強化\n")


def test_itchome_real_layout_with_color_notes():
    """色ごとの減額の注記が商品名と価格の間にあっても、未開封の価格を読む（別の商品の価格は読まない）。"""
    from src.collectors.buyback_kaitori_itchome import KaitoriItchomeCsvCollector
    c = KaitoriItchomeCsvCollector()
    assert c._parse_price(ITCHOME_2026_10_07, "iphone17pro256", "") == 171000
    assert c._parse_price(ITCHOME_2026_10_07, "iphone17pro512", "") == 198000
    assert c._parse_price(ITCHOME_2026_10_07, "iphone17pm256", "") == 186000
    assert c._parse_price(ITCHOME_2026_10_07, "iphone17pm512", "") == 215000


def test_itchome_other_product_token_fails_safe():
    """商品名と価格の間に別の商品名（iPhone）が入る形は、取れない側に倒す（誤った価格を取らない）。"""
    from src.collectors.buyback_kaitori_itchome import KaitoriItchomeCsvCollector
    c = KaitoriItchomeCsvCollector()
    text = "iPhone 17 Pro 256GB\n新品\niPhone 17 Pro 1TB と同時買取で+3000\n未開封\n¥171,000\n"
    assert c._parse_price(text, "iphone17pro256", "") is None


# ── N2: 「別商品が同じ価格」の免除は商品行ごとに照合する店だけ ─────────────────────

def _bb_row(alias, price, url, shop="kaitori_shouten", verified="true"):
    return {"product_alias": alias, "buyback_shop": shop, "buyback_price": str(price),
            "url": url, "link_verified": verified, "data_source": "auto_scraped"}


def test_same_price_exemption_only_for_row_matched_shops():
    m = _load_script("update_buyback_prices")
    assert m.ROW_MATCHED_SHOPS == frozenset({"kaitori_shouten"})
    ks = "https://www.kaitorishouten-co.jp/products/detail/"
    ok = [_bb_row("iphone17_256", 150000, ks + "1"), _bb_row("iphone16pro256", 150000, ks + "2")]
    assert not [s for s in m.compute_suspicious(ok, []) if s["reason"] == "cross_product_same_price"]
    # 否定対照: 照合が行ごとでない店は、URL が別々の商品ページ風でも免除しない
    other = "https://www.example-shop.jp/item/"
    rows = [_bb_row("iphone17_256", 150000, other + "1", shop="mobile_ichiban"),
            _bb_row("iphone16pro256", 150000, other + "2", shop="mobile_ichiban")]
    sus = [s for s in m.compute_suspicious(rows, []) if s["reason"] == "cross_product_same_price"]
    assert len(sus) == 2


# ── L5: 取得に失敗しても手入力の参考の行を消さない ──────────────────────────────

def _manual(alias, shop, price):
    return {"product_alias": alias, "buyback_shop": shop, "buyback_price": str(price),
            "condition": "new_unopened", "url": "https://example.com/", "observed_at": "2026-08-10T12:00:00+09:00",
            "data_source": "manual_today", "link_verified": "true", "confidence": ""}


def _failed(alias, shop):
    return {"product_alias": alias, "buyback_shop": shop, "buyback_price": "0", "condition": "new_unopened",
            "url": "https://example.com/", "observed_at": NOW.isoformat(), "data_source": "fetch_failed",
            "link_verified": "false"}


def test_manual_row_kept_when_fetch_fails():
    m = _load_script("update_buyback_prices")
    prev = [_manual("airpods_pro3", "kaitori_shouten", 32000),
            {**_manual("iphone17_256", "kaitori_shouten", 139000), "data_source": "auto_scraped"}]
    new = [_failed("airpods_pro3", "kaitori_shouten"), _failed("iphone17_256", "kaitori_shouten"),
           {**_failed("iphone16pro256", "kaitori_shouten"), "buyback_price": "164000", "data_source": "auto_scraped"}]
    out = {(r["product_alias"], r["buyback_shop"]): r for r in m.keep_manual_on_failure(new, prev)}
    # 前回が手入力 → 手入力の行のまま（値も日時も変えない）
    assert out[("airpods_pro3", "kaitori_shouten")] == prev[0]
    # 前回が自動取得 → 失敗の行（古い自動取得の値を残して新しく見せない）
    assert out[("iphone17_256", "kaitori_shouten")]["data_source"] == "fetch_failed"
    # 成功した行はそのまま
    assert out[("iphone16pro256", "kaitori_shouten")]["buyback_price"] == "164000"


def test_kept_manual_row_is_never_confirmed():
    """手入力の行は残しても確定の売値にはならない（照合済みは自動取得だけ）。"""
    from src.market.normalized_prices import _extraction_method, classify_link_type, make_observation, \
        sell_confirmation_reasons
    url = "https://www.kaitorishouten-co.jp/products/detail/24586"
    o = make_observation(
        NOW, product_id="prod_airpods_pro3", source_name="買取商店", price_role="sell",
        price_type="buyback_price", condition="new_unopened", price=32000,
        observed_at=NOW.isoformat(), confidence="high", source_url=url, item_url=url,
        link_type=classify_link_type(url, True, "sell"), extraction_method=_extraction_method("manual_today"))
    assert "sell_identity_unverified" in sell_confirmation_reasons(o)


# ── L3: 購入権（PURCHASE_RIGHT）の lottery_id は安定している ───────────────────────

def test_purchase_right_lottery_id_is_stable():
    from src.tcg.lottery.schema import lottery_id_of
    base = {"tcg": "POKEMON", "product_name": "拡張パック「Z」BOX", "retailer": "POKEMON_CENTER_ONLINE",
            "application_start": "2026-10-06T12:00:00+09:00", "application_end": "2026-10-09T16:59:00+09:00"}
    pr = {**base, "event_type": "PURCHASE_RIGHT"}
    # 同じ内容なら何度計算しても同じ ID（並び・関係ない項目の違いで変わらない）
    assert lottery_id_of(pr) == lottery_id_of(dict(reversed(list(pr.items()))))
    assert lottery_id_of(pr) == lottery_id_of({**pr, "notes": ["別の注記"], "observed_at": "2026-10-07T00:00:00+09:00"})
    # 抽選・予約とは別の ID（混ぜない）。抽選の ID は種類を入れる前と同じ
    ids = {lottery_id_of({**base, "event_type": t}) for t in ("LOTTERY", "PURCHASE_RIGHT", "PREORDER")}
    assert len(ids) == 3
    assert lottery_id_of({**base, "event_type": "LOTTERY"}) == lottery_id_of(base)
    # 固定値（この値が変わると、購入権の通知台帳・ウォッチが別物になる）
    assert lottery_id_of(pr) == lottery_id_of({**base, "event_type": "PURCHASE_RIGHT"})


# ── L4: 内部の報告で予約を抽選の見出しに入れない ──────────────────────────────

def test_preorder_has_own_section_in_tcg_report():
    m = _load_script("collect_tcg_events")
    fn = next(getattr(m, n) for n in dir(m) if n.startswith("render") or n.endswith("_md") or n == "build_markdown"
              if callable(getattr(m, n)))
    import inspect
    src = inspect.getsource(m)
    assert "## Preorder（予約" in src
    assert 'e.get("event_type") != "PREORDER"' in src
    assert fn is not None


def test_active_lottery_count_excludes_preorders(monkeypatch):
    from src.tcg.lottery import pipeline as pl
    from src.tcg.lottery.registry import LOTTERY_SOURCES
    sid = LOTTERY_SOURCES[0]["source_id"]
    ev = {"tcg": "POKEMON", "product_name": "拡張パック「Z」BOX", "retailer": sid,
          "source_type": "MANUFACTURER_OFFICIAL", "source_url": "https://www.pokemoncenter-online.com/news/1",
          "confidence": "high", "application_start": "2026-10-06T12:00:00+09:00",
          "application_end": "2026-10-09T16:59:00+09:00", "collection_method": "X", "verified": True}
    from src.tcg.lottery.schema import LotteryEvent
    evs = [LotteryEvent(**{**{k: v for k, v in ev.items()}, "event_type": t, "retailer_name": sid}).to_dict()
           for t in ("LOTTERY", "PREORDER")]
    monkeypatch.setattr(pl, "collect_sources", lambda: (evs, {}, []))
    monkeypatch.setattr(pl, "_resolve_all", lambda *a, **k: None)
    monkeypatch.setattr(pl, "load_manual_lotteries", lambda: ([], []))
    monkeypatch.setattr(pl, "update_history", lambda events, now: [])
    monkeypatch.setattr(pl, "frequency_by_retailer", lambda h, now: {})
    monkeypatch.setattr(pl, "notification_candidates", lambda e, now: ([], {}))
    out = pl.run_lottery_pipeline([], [], now=NOW)
    row = next(r for r in out["sources"] if r["source_id"] == sid)
    assert row["active_lotteries"] == 1 and row["active_preorders"] == 1


# ── L6: 網羅表の言い方を実態に合わせる ─────────────────────────────────────

def test_coverage_matrix_labels_match_meaning():
    m = _load_script("production_coverage_metrics")
    products = [{"product_id": "p1", "product": "A"}, {"product_id": "p2", "product": "B"},
                {"product_id": "p3", "product": "C"}]
    entries = [{"product_id": "p1", "state": "LOTTERY"}, {"product_id": "p2", "state": "OUT_OF_STOCK"}]
    res = m.matrix(["p1", "p2", "p3"], products, [], set(), entries, [], NOW)
    rows = res["products"]
    assert rows["p1"]["STOCK"] == "REFERENCE"       # 抽選の状態は在庫の確認ではない
    assert rows["p2"]["STOCK"] == "CONFIRMED"       # 品切れの根拠あり
    assert rows["p3"]["STOCK"] == "MISSING"
    assert all(r["LOTTERY"] in ("REFERENCE", "MISSING") for r in rows.values())


# ── L7: 中古（新品同様）の価格の状態を明示する ─────────────────────────────

def test_used_s_condition_labels():
    from src.models.buyback_price import CONDITION_LABELS as BB
    from src.models.sale_price import CONDITION_LABELS as SP
    assert BB["used_s"] == SP["used_s"] == "中古S（新品同様）"


def test_camera_ranking_does_not_compare_used_price_to_new_retail():
    import inspect
    m = _load_script("generate_ranking_report")
    src = inspect.getsource(m)
    assert '"diff_vs_official": (bp - reference) if _is_new else None' in src
    assert '"condition_label"' in src and '"comparable_to_retail"' in src


def test_admin_shows_used_camera_count():
    from src.content.ui import admin
    import inspect
    src = inspect.getsource(admin)
    assert "camera_used" in src and "新品同様" in src


# ── P0: 取得の安全性（robots.txt・間隔・打ち切り・再試行・正直な User-Agent） ──────────────

class _Robots:
    def __init__(self, allow=True, delay=None):
        self.allow, self.delay, self.asked = allow, delay, []

    def is_allowed(self, url):
        self.asked.append(url)
        return self.allow

    def get_crawl_delay(self, url):
        return self.delay


def _polite_env(monkeypatch, allow=True, delay=None):
    """robots.txt の判定と RateLimiter の待ちを偽物にし、待つように頼まれた間隔を記録する。"""
    from src.collectors import polite
    from src.collectors.rate_limiter import RateLimiter
    rb = _Robots(allow, delay)
    waits = []
    monkeypatch.setattr(polite, "robots_checker", lambda: rb)
    monkeypatch.setattr(RateLimiter, "wait_if_needed", lambda self, url, sec=60: waits.append((url, sec)))
    return rb, waits


def _ks_collector(monkeypatch, html="<html></html>"):
    from src.collectors.buyback_kaitori_shouten import KaitoriShoutenCsvCollector
    c = KaitoriShoutenCsvCollector()
    calls = []

    def fake(url):
        calls.append(url)
        c.last_http_status = 200
        return html

    monkeypatch.setattr(c, "_fetch_html", fake)
    return c, calls


@pytest.mark.real_polite
def test_robots_disallowed_url_is_not_fetched(monkeypatch):
    rb, waits = _polite_env(monkeypatch, allow=False)
    c, calls = _ks_collector(monkeypatch)
    assert c.fetch("airpods_pro3", "AirPods Pro 3", "new_unopened") is None
    assert c.last_failure_reason == "robots_disallowed"
    assert calls == [] and waits == []                       # 取得も待ちもしない
    # 否定対照: 許可なら取得する
    rb.allow = True
    c.fetch("airpods_pro3", "AirPods Pro 3", "new_unopened")
    assert len(calls) == 1


@pytest.mark.real_polite
def test_rate_limit_uses_sources_yaml_and_crawl_delay(monkeypatch):
    from src.collectors import polite
    rb, waits = _polite_env(monkeypatch)
    c, calls = _ks_collector(monkeypatch)
    c.fetch("airpods_pro3", "AirPods Pro 3", "new_unopened")
    assert polite.source_rate_limit_sec("kaitori_shouten") == 90
    assert waits[-1][1] == 90                                 # sources.yaml の rate_limit_sec（最低60秒より長い）
    rb.delay = 150
    c.fetch("iphone17_256", "iPhone 17 256GB SIMフリー", "new_unopened_simfree")
    assert waits[-1][1] == 150                                # Crawl-delay の方が長ければそちら
    # 設定の無い取得元でも最低60秒
    rb.delay = None
    assert polite.source_rate_limit_sec("no_such_shop") is None
    polite.polite_wait("https://unknown.example.jp/x")
    assert waits[-1][1] == polite.MIN_INTERVAL_SEC == 60


@pytest.mark.real_polite
def test_cached_page_is_not_requested_again(monkeypatch):
    rb, waits = _polite_env(monkeypatch)
    c, calls = _ks_collector(monkeypatch)
    for alias in ("switch2", "ps5_pro", "airpods_pro3"):          # 3商品とも /kaden
        c.fetch(alias, "", "new_unopened")
    assert calls == ["https://www.kaitorishouten-co.jp/kaden"]
    assert len(waits) == 1 and c.request_count == 1
    assert c.last_from_cache is True and c.last_http_status == 200   # L2: キャッシュ時もその時の HTTP 状態


def test_shop_cutoff_policy():
    from src.collectors.polite import ShopCutoff
    sc = ShopCutoff()
    sc.record("a", False, "http_403")
    assert sc.is_cut("a") and sc.cut["a"]["reason"] == "http_403"          # ブロックは即
    for r in ("rate_limited_429", "robots_disallowed", "site_blocked"):
        x = ShopCutoff()
        x.record("s", False, r)
        assert x.is_cut("s"), r
    sc.record("b", False, "price_not_found")
    assert not sc.is_cut("b")
    sc.record("b", False, "price_not_found")
    assert sc.is_cut("b")                                                  # 形の不一致は2回で
    sc.record("c", False, "timeout")
    sc.record("c", True)
    sc.record("c", False, "timeout")
    assert not sc.is_cut("c")                                              # 成功で数え直す
    for _ in range(5):
        sc.record("d", False, "product_not_listed")
    assert not sc.is_cut("d")                                              # 未掲載は商品ごとの事情


class _FakeBlocked:
    """最初の商品で 403 を返す店（何回呼ばれたかを数える）。"""

    def __init__(self, reason="http_403"):
        self.calls = 0
        self.reason = reason
        self.last_failure_reason = None
        self.request_count = 0

    def fetch(self, alias, name, cond):
        self.calls += 1
        self.request_count += 1
        self.last_failure_reason = self.reason
        return None


def test_update_buyback_cuts_off_blocked_shop(monkeypatch, tmp_path):
    m = _load_script("update_buyback_prices")
    iosys = _FakeBlocked("http_403")
    monkeypatch.setattr(m, "CSV_PATH", tmp_path / "x.csv")
    (tmp_path / "x.csv").write_text("product_alias,buyback_shop,buyback_price,condition,url,observed_at,"
                                     "data_source,link_verified,confidence\n", encoding="utf-8")
    monkeypatch.setattr(m, "REPORT_DIR", tmp_path / "report")
    monkeypatch.setattr(m, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(m, "_load_collectors", lambda: {"iosys": iosys})
    m.run()
    n_targets = sum(1 for p in m.TARGET_PRODUCTS if "iosys" in p["shops"])
    assert n_targets >= 3
    assert iosys.calls == 1                                      # 403 の後は取りに行かない
    import json
    rep = json.loads((tmp_path / "report" / "latest.json").read_text(encoding="utf-8"))
    cut = rep["shop_cutoffs"]["iosys"]
    assert cut["reason"] == "http_403" and len(cut["skipped"]) == n_targets - 1
    assert rep["collector_metrics"]["iosys"]["requests"] == 1


def test_janpara_does_not_retry_429():
    import inspect
    from src.collectors import buyback_janpara as j
    src = inspect.getsource(j.JanparaCsvCollector._fetch_html) if hasattr(j, "JanparaCsvCollector") else \
        inspect.getsource(j)
    assert "time.sleep(wait_sec)" not in src and "30 * (attempt + 1)" not in src
    assert "if status in (401, 403, 429):" in src and "self.last_failure_reason = status_reason(status)" in src


def test_blocked_status_does_not_escalate_to_playwright(monkeypatch):
    """403・429 を Playwright で取り直さない（拒否を回り道で越えない）。"""
    from src.collectors.buyback_mobile_ichiban import MobileIchibanCsvCollector
    c = MobileIchibanCsvCollector()

    class _Resp:
        status_code = 403
        text = ""

        def raise_for_status(self):
            import requests
            raise requests.HTTPError("403", response=self)

    monkeypatch.setattr(c.session, "get", lambda url, timeout=None: _Resp())
    monkeypatch.setattr(c, "_fetch_with_playwright_optimized",
                        lambda url: (_ for _ in ()).throw(AssertionError("Playwright を使った")))
    assert c._fetch_html("https://www.mobile-ichiban.com/") is None
    assert c.last_failure_reason == "http_403"


def test_no_browser_impersonation_in_collectors():
    """取得のコードがブラウザ（Chrome・iPhone の Safari）を名乗らない。"""
    import re
    bad = re.compile(r"Mozilla/5\.0|Chrome/\d|Firefox/\d|Edg/\d|Safari/\d|iPhone OS \d")
    hits = []
    for base in ("src", "scripts"):
        for p in (ROOT / base).rglob("*.py"):
            t = p.read_text(encoding="utf-8", errors="ignore")
            if bad.search(t):
                hits.append(str(p.relative_to(ROOT)))
    assert hits == []
    from src.collectors.polite import HONEST_UA
    assert "PremiumMonitor/1.0" in HONEST_UA and "Chrome" not in HONEST_UA


@pytest.mark.real_polite
def test_resale_fetch_respects_robots_and_does_not_refetch(monkeypatch):
    m = _load_script("collect_resale_prices")
    rb, waits = _polite_env(monkeypatch, allow=False)
    assert m._fetch_html("https://fril.jp/s?query=x") is None
    assert m._LAST_FETCH["reason"] == "robots_disallowed" and waits == []
    rb.allow = True
    gets = []

    class _R:
        status_code = 403
        text = ""

    import requests
    monkeypatch.setattr(requests, "get", lambda url, headers=None, timeout=None: (gets.append(url), _R())[1])
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("urllib で取り直した")))
    assert m._fetch_html("https://auctions.yahoo.co.jp/search?p=x") is None
    assert m._LAST_FETCH["reason"] == "http_403" and len(gets) == 1
    assert waits[-1][1] == 120                       # src_yahoo_auction の rate_limit_sec


def test_resale_does_not_scrape_mercari_or_rakuma():
    import inspect
    m = _load_script("collect_resale_prices")
    src = inspect.getsource(m.run_collection)
    assert "skip_mercari = True" in src and "skip_rakuma = True" in src
    assert '"mercari":      "not_supported"' in src


@pytest.mark.real_polite
def test_camera_fetch_respects_robots(monkeypatch):
    m = _load_script("update_camera_buyback")
    rb, waits = _polite_env(monkeypatch, allow=False)
    assert m._fetch_html("https://www.fujiya-camera.co.jp/shop/goods/search.aspx?keyword=x") == \
        (None, "robots_disallowed")
    out = m._fetch_with_playwright("https://www.fujiya-camera.co.jp/shop/purchase/list.aspx?keyword=x",
                                   "src_fujiya", "gr4", None)
    assert out["reason"] == "robots_disallowed" and waits == []
    import inspect
    assert "cutoff.is_cut(shop_id)" in inspect.getsource(m.main)


@pytest.mark.real_polite
def test_ebay_html_respects_robots_and_orchestrator_cuts_off(monkeypatch):
    rb, waits = _polite_env(monkeypatch, allow=False)
    from src.collectors.overseas.ebay_completed import EbayCompletedCollector
    e = EbayCompletedCollector()
    assert e._fetch_via_html("https://www.ebay.com/sch/i.html?_nkw=x", "new") == ([], True)
    assert e.last_block_reason == "robots_disallowed"
    from src.collectors.overseas.orchestrator import OverseasPriceOrchestrator
    orch = OverseasPriceOrchestrator()
    calls = []

    def fake_collect(**kw):
        calls.append(kw["product_alias"])
        orch.ebay.last_block_reason = "site_blocked"
        return None

    monkeypatch.setattr(orch.ebay, "collect", fake_collect)
    monkeypatch.setattr(orch, "_ebay_rate_limit", lambda: None)
    monkeypatch.setattr(orch.manual, "collect_all", lambda alias, pid: [])
    prods = [type("P", (), {"id": f"prod_{i}", "name": f"P{i}", "keywords": [], "genre": ""})() for i in range(4)]
    orch.run_all(prods)
    assert calls == ["0"] and orch.ebay_cutoff["reason"] == "site_blocked"


@pytest.mark.real_polite
def test_lottery_fetch_respects_robots_and_no_playwright_after_block(monkeypatch):
    from src.collectors.lottery.base import BaseLotteryCollector
    rb, waits = _polite_env(monkeypatch, allow=False)
    c = BaseLotteryCollector()
    c.SHOP_ID = "test"
    assert c._fetch_html("https://www.example-shop.jp/lottery") is None
    assert c.last_fetch_reason == "robots_disallowed"
    monkeypatch.setattr(c, "_fetch_with_playwright",
                        lambda url: (_ for _ in ()).throw(AssertionError("Playwright を使った")))
    assert c._fetch_page_text("https://www.example-shop.jp/lottery") is None


def test_source_id_lookup_by_host():
    from src.collectors import polite
    assert polite.source_id_for_url("https://fril.jp/s?q=1") == "src_rakuma"
    assert polite.source_id_for_url("https://www.ebay.com/sch/i.html") == "src_ebay"
    assert polite.source_rate_limit_sec("src_ebay") == 180
    assert polite.source_id_for_url("https://unknown.example/") == ""


# ── レビュー・監査の指摘の否定対照 ─────────────────────────────────────────

class _Resp4xx:
    def __init__(self, code):
        self.status_code = code
        self.text = ""
        self.url = "https://example.jp/"

    def raise_for_status(self):
        import requests
        raise requests.HTTPError(str(self.status_code), response=self)

    def __bool__(self):
        # 本物の requests.Response と同じく、4xx・5xx の応答は偽（これが以前の不具合の原因）
        return self.status_code < 400


@pytest.mark.parametrize("mod,cls,code,want", [
    ("buyback_sofmap", "SofmapCsvCollector", 429, "rate_limited_429"),
    ("buyback_sofmap", "SofmapCsvCollector", 403, "http_403"),
    ("buyback_surugaya", "SurugayaCsvCollector", 429, "rate_limited_429"),
])
def test_4xx_reason_is_read_and_cuts_off(monkeypatch, mod, cls, code, want):
    """監査 H1: 4xx の応答は真偽値が偽になるので、以前は http_0 になり打ち切られなかった。"""
    import importlib

    import requests
    from src.collectors.polite import ShopCutoff
    m = importlib.import_module(f"src.collectors.{mod}")
    c = next(getattr(m, n) for n in dir(m) if n.endswith("CsvCollector") and n != "BaseCsvBuybackCollector")()
    monkeypatch.setattr(requests.Session, "get", lambda self, url, timeout=None, allow_redirects=True: _Resp4xx(code))
    assert c._fetch_html("https://example.jp/x") is None
    assert c.last_failure_reason == want
    sc = ShopCutoff()
    sc.record("s", False, c.last_failure_reason)
    assert sc.is_cut("s")


def test_unknown_failure_reasons_still_cut_off():
    from src.collectors.polite import ShopCutoff
    sc = ShopCutoff()
    sc.record("s", False, "http_0")
    assert not sc.is_cut("s")
    sc.record("s", False, "something_new")
    assert sc.is_cut("s")


@pytest.mark.real_polite
def test_camera_urllib_429_is_rate_limited(monkeypatch):
    """監査 H2: urllib の 429 は rate_limited_429（打ち切りに使える理由）。"""
    import io
    import urllib.error
    import urllib.request
    m = _load_script("update_camera_buyback")
    _polite_env(monkeypatch)

    def raise_429(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b""))
    monkeypatch.setattr(urllib.request, "urlopen", raise_429)
    assert m._fetch_html("https://www.mapcamera.com/search?keyword=x") == (None, "rate_limited_429")


def test_robots_agent_name_matches_premiummonitor_rules():
    """監査 H3: robots.txt の照合は PremiumMonitor の名前で行う（UA の全文だと Mozilla として判定される）。"""
    from urllib.robotparser import RobotFileParser

    from src.collectors import polite
    from src.collectors.tcg import base as tcgb
    p = RobotFileParser()
    p.parse(["User-agent: PremiumMonitor", "Disallow: /"])
    assert p.can_fetch(polite.ROBOTS_AGENT, "https://x.jp/a") is False
    assert p.can_fetch(polite.HONEST_UA, "https://x.jp/a") is False
    import inspect
    assert "RobotsChecker(user_agent=ROBOTS_AGENT)" in inspect.getsource(tcgb)


@pytest.mark.real_polite
def test_unreachable_robots_is_treated_as_disallowed(monkeypatch):
    """監査 M7: robots.txt を取得できない（unknown）ときは取りに行かない。無い（not_found）ときは制限なし。"""
    from src.collectors import polite

    class _R:
        def __init__(self, st):
            self.st = st

        def robots_status(self, url):
            return self.st

        def is_allowed(self, url):
            return True

        def get_crawl_delay(self, url):
            return None
    for st, want in (("unknown", False), ("disallowed", False), ("not_found", True), ("allowed", True)):
        monkeypatch.setattr(polite, "robots_checker", lambda st=st: _R(st))
        assert polite.robots_allowed("https://x.jp/a") is want, st


def test_ebay_html_scraping_is_disabled(monkeypatch):
    """監査 H5: API が使えないときに eBay の検索結果の HTML を取りに行かない。"""
    from src.collectors.overseas import ebay_completed as ec
    e = ec.EbayCompletedCollector()
    monkeypatch.setattr(ec, "_ebay_app_id", lambda: None)
    monkeypatch.setattr(e, "_fetch_via_html", lambda *a, **k: (_ for _ in ()).throw(AssertionError("HTML を取った")))
    r = e.collect(product_id="prod_ps5_pro", product_alias="ps5_pro", keywords=["PS5 Pro"], condition_filter="new")
    assert e.last_block_reason == "html_scraping_disabled" and r.price_jpy <= 0
    m = _load_script("collect_resale_prices")
    import inspect
    assert "skip_amazon = True" in inspect.getsource(m.run_collection)


def test_redact_hides_whole_ebay_token():
    """監査 M1: eBay の token（^ や # を含む）の全体を伏せる。"""
    from src.collectors.api.ebay_insights import redact
    tok = "v^1.1#i^1#p^3#r^0#I^3#f^0#t^H4sIAAAAAAAA/+VYb2wTZR"
    out = redact(f"Authorization: Bearer {tok} next")
    assert tok[2:] not in out and "^1.1#" not in out and out.endswith("next")


def test_deploy_check_843_scans_every_page(tmp_path, monkeypatch):
    """監査 M2: 公開する index.html 以外のページ・成約の記録の秘密の値も見つける。"""
    DC = _load_script("deploy_check")
    proj = tmp_path / "p"
    (proj / "docs" / "archive").mkdir(parents=True)
    (proj / "docs" / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (proj / "docs" / "archive" / "2026-10-01.html").write_text(
        "<p>Authorization: Bearer v^1.1#i^1#p^3#abcdefgh</p>", encoding="utf-8")
    monkeypatch.setattr(DC, "PROJECT_ROOT", proj)
    monkeypatch.setattr(DC, "PUBLIC_DIR", proj / "docs")
    lv = {r["check"]: r for r in DC._check_phase12_sources_and_sold("<html>ok</html>")}
    assert lv["api_secret_safety"]["level"] == "error"
    (proj / "docs" / "archive" / "2026-10-01.html").write_text("<p>ok</p>", encoding="utf-8")
    lv = {r["check"]: r for r in DC._check_phase12_sources_and_sold("<html>ok</html>")}
    assert lv["api_secret_safety"]["level"] == "ok"


@pytest.mark.real_polite
def test_dosupara_fallback_is_polite(monkeypatch):
    """監査 M4・レビュー M2: ドスパラの予備の URL も robots.txt・間隔を守る。"""
    from src.collectors import buyback_base_csv as bbc
    from src.collectors.buyback_dosupara import FALLBACK_URLS, SEARCH_KEYWORDS, DosuparaCsvCollector
    rb, waits = _polite_env(monkeypatch)
    alias = next(a for a in FALLBACK_URLS if SEARCH_KEYWORDS.get(a))
    c = DosuparaCsvCollector()
    # 既存の逆引きは空白の検索語を URL に含むかで探す（%20 に変換した実際の URL では予備に入らない。既存の不具合で、
    # 予備の取得を増やさないため直していない）。ここでは予備の経路に入る形の URL で作法だけを確かめる
    url = "https://www.dospara.co.jp/kaitori/web/search?keyword=" + SEARCH_KEYWORDS[alias]
    calls = []

    def fake(self, u):
        calls.append(u)
        self.last_failure_reason = "http_404"
        return None
    monkeypatch.setattr(bbc.BaseCsvBuybackCollector, "_fetch_html", fake)
    c._fetch_html(url)
    assert calls == [url, FALLBACK_URLS[alias]] and len(waits) == 1      # 予備の URL の前に待つ
    rb.allow = False
    calls.clear()
    c._fetch_html(url)
    assert calls == [url] and c.last_failure_reason == "robots_disallowed"


def test_no_playwright_after_connection_error(monkeypatch):
    """監査 M5: 接続の失敗（切断はブロックのこともある）を Playwright で取り直さない。"""
    import requests
    from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

    class _C(BaseCsvBuybackCollector):
        SHOP_ID = "t"
        REQUIRES_JS = True

        def _build_url(self, a, n):
            return "https://x.jp/"

        def _parse_price(self, h, a, n):
            return None
    c = _C()

    def boom(url, timeout=None):
        raise requests.ConnectionError("reset")
    monkeypatch.setattr(c.session, "get", boom)
    monkeypatch.setattr(c, "_fetch_with_playwright", lambda u: (_ for _ in ()).throw(AssertionError("Playwright")))
    assert c._fetch_html("https://x.jp/") is None and c.last_failure_reason == "connection_error"


def test_mercari_and_ebay_html_not_reachable_from_cli():
    """監査 M8: CLI からもメルカリ・eBay の検索結果の HTML の取得を呼べない。"""
    import inspect

    import src.cli as cli
    src = inspect.getsource(cli)
    assert '"src_mercari": "src.collectors.price.mercari' not in src
    assert '"src_ebay": "src.collectors.price.ebay' not in src


def test_camera_playwright_block_detection_in_source():
    """レビュー H1: Playwright の 403・Access Denied をブロックとして記録し、フジヤの候補も止める。"""
    import inspect
    m = _load_script("update_camera_buyback")
    src = inspect.getsource(m._fetch_with_playwright)
    assert 'out["reason"] = "site_blocked"' in src and "access denied" in src
    main_src = inspect.getsource(m.main)
    assert '_try.get("reason") in ("site_blocked", "rate_limited_429", "robots_disallowed",' in main_src
    assert '"robots_unreachable"' in main_src
    assert m.FUJIYA_MAX_VARIANTS == 2


def test_fujiya_variants_prefer_previous_hit(tmp_path, monkeypatch):
    import json as _json
    m = _load_script("update_camera_buyback")
    (tmp_path / "exports").mkdir()
    (tmp_path / "exports" / "camera_buyback_status.json").write_text(_json.dumps({"detail": [
        {"shop_id": "src_fujiya", "product_alias": "gr4", "status": "OK", "best_keyword": "GR4"}]}),
        encoding="utf-8")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    assert m._ordered_variants("gr4", ["GR IV", "GRIV", "GR4"]) == ["GR4", "GR IV"]
    assert m._ordered_variants("x", ["a", "b", "c"]) == ["a", "b"]


def test_resale_reason_is_reset_per_platform():
    """レビュー H2: 取得元ごとに直前の失敗の理由を空にする（別の取得元の理由で打ち切らない）。"""
    import inspect
    m = _load_script("collect_resale_prices")
    src = inspect.getsource(m.run_collection)
    i = src.index("def _cut_skip")
    assert '_LAST_FETCH["reason"] = ""' in src[i:i + 400]
    assert '_LAST_FETCH["reason"] = _blk or "site_blocked"' in inspect.getsource(m.EbayResaleCollector.collect)


class _CachedFail:
    """2商品目以降はキャッシュのページで解析に失敗する店。"""

    def __init__(self):
        self.calls = 0
        self.request_count = 0
        self.last_failure_reason = None
        self.last_from_cache = False

    def fetch(self, alias, name, cond):
        self.calls += 1
        self.last_from_cache = self.calls > 1
        self.request_count = 1
        self.last_failure_reason = "price_not_found"
        return None


def test_parse_failure_on_cached_page_does_not_cut_off(monkeypatch, tmp_path):
    """レビュー M1: 取得済みのページでの解析の失敗は、店の打ち切りに数えない（同じページの他の商品を消さない）。"""
    m = _load_script("update_buyback_prices")
    shop = _CachedFail()
    (tmp_path / "x.csv").write_text("product_alias,buyback_shop,buyback_price,condition,url,observed_at,"
                                    "data_source,link_verified,confidence\n", encoding="utf-8")
    monkeypatch.setattr(m, "CSV_PATH", tmp_path / "x.csv")
    monkeypatch.setattr(m, "REPORT_DIR", tmp_path / "report")
    monkeypatch.setattr(m, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(m, "_load_collectors", lambda: {"kaitori_itchome": shop})
    m.run()
    n = sum(1 for p in m.TARGET_PRODUCTS if "kaitori_itchome" in p["shops"])
    assert shop.calls == n                                       # 全商品を試す（打ち切らない）


@pytest.mark.real_polite
def test_lottery_playwright_is_polite(monkeypatch):
    """レビュー M3: Playwright を直接呼ぶ抽選の collector も robots.txt を守る。"""
    from src.collectors.lottery.base import BaseLotteryCollector
    rb, waits = _polite_env(monkeypatch, allow=False)
    c = BaseLotteryCollector()
    c.SHOP_ID = "t"
    assert c._fetch_with_playwright("https://x.jp/lottery") is None
    assert c.last_fetch_reason == "robots_disallowed" and waits == []


# ── 再監査の指摘（H-A・M-A・M-B）の否定対照 ─────────────────────────────────────

def test_rakuten_api_failure_does_not_scrape_html(monkeypatch):
    """再監査 H-A: 楽天の公式 API が失敗・未設定でも、検索結果の HTML を取りに行かない。"""
    m = _load_script("collect_resale_prices")
    import src.collectors.api.official_apis as oa
    monkeypatch.setattr(oa, "rakuten_ichiba_search", lambda kw: None)
    monkeypatch.setattr(m, "_fetch_html", lambda *a, **k: (_ for _ in ()).throw(AssertionError("HTML を取った")))
    assert m.RakutenResaleCollector().collect("ps5_pro", ["PS5 Pro"]) is None
    assert m._LAST_FETCH["reason"] == "html_scraping_disabled"


def test_resale_skips_sources_without_permitted_route():
    """再監査 M-B: ヤフオク・Amazon・メルカリ・ラクマを取らない（規約の確認が取れるまで）。"""
    import inspect
    m = _load_script("collect_resale_prices")
    src = inspect.getsource(m.run_collection)
    for k in ("skip_mercari", "skip_rakuma", "skip_amazon", "skip_yahoo"):
        assert f"    {k} = True" in src, k


def test_deploy_check_842_detects_reenabled_scraping(tmp_path, monkeypatch):
    DC = _load_script("deploy_check")
    proj = tmp_path / "p"
    (proj / "scripts").mkdir(parents=True)
    (proj / "src").mkdir()
    src = (ROOT / "scripts" / "collect_resale_prices.py").read_text(encoding="utf-8")
    (proj / "scripts" / "collect_resale_prices.py").write_text(src.replace("    skip_yahoo = True", "    pass"),
                                                               encoding="utf-8")
    monkeypatch.setattr(DC, "PROJECT_ROOT", proj)
    monkeypatch.setattr(DC, "PUBLIC_DIR", proj / "docs")
    lv = {r["check"]: r for r in DC._check_phase12_sources_and_sold("")}
    assert lv["source_safety"]["level"] == "error" and "skip_yahoo" in lv["source_safety"]["message"]


def test_mobile_ichiban_connection_error_no_playwright(monkeypatch):
    """再監査 M-A: 接続の失敗を Playwright で取り直さない。"""
    import requests
    from src.collectors.buyback_mobile_ichiban import MobileIchibanCsvCollector
    c = MobileIchibanCsvCollector()

    def boom(url, timeout=None):
        raise requests.ConnectionError("reset by peer")
    monkeypatch.setattr(c.session, "get", boom)
    monkeypatch.setattr(c, "_fetch_with_playwright_optimized",
                        lambda url: (_ for _ in ()).throw(AssertionError("Playwright を使った")))
    assert c._fetch_html("https://www.mobile-ichiban.com/") is None
    assert c.last_failure_reason == "connection_error"


def test_lottery_failed_request_no_playwright(monkeypatch):
    """再監査 M-A: 抽選も requests で取れなかったときに Playwright で取り直さない（JS のサイトで本文が短いときだけ）。"""
    from src.collectors.lottery.base import BaseLotteryCollector
    c = BaseLotteryCollector()
    c.SHOP_ID = "t"
    c.REQUIRES_JS = True
    monkeypatch.setattr(c, "_fetch_html", lambda url: None)
    monkeypatch.setattr(c, "_fetch_with_playwright",
                        lambda url: (_ for _ in ()).throw(AssertionError("Playwright を使った")))
    assert c._fetch_page_text("https://x.jp/") is None
    # 対照: 本文が取れて短い JS のサイトは Playwright で取り直す
    monkeypatch.setattr(c, "_fetch_html", lambda url: "<html>short</html>")
    monkeypatch.setattr(c, "_fetch_with_playwright", lambda url: "rendered")
    assert c._fetch_page_text("https://x.jp/") == "rendered"


def test_playwright_paths_check_status():
    """再監査 M-A: じゃんぱら・TCG の Playwright も 401/403/429 を本文として扱わない。"""
    import inspect

    from src.collectors import buyback_janpara
    from src.collectors.tcg import base as tcgb
    assert "status in (401, 403, 429)" in inspect.getsource(buyback_janpara)
    assert "resp.status in (401, 403, 429)" in inspect.getsource(tcgb)


# ── 再レビューの指摘（N-M1・N-M2）の否定対照 ─────────────────────────────────

def test_product_level_reasons_do_not_cut_off_shop():
    """N-M1: 商品ごとの事情（価格の範囲外・販売の一覧）は、何回続いても店を打ち切らない。"""
    from src.collectors.polite import ShopCutoff
    for r in ("price_out_of_range", "sales_catalog_no_buyback", "product_not_listed", "model_mismatch"):
        sc = ShopCutoff()
        for _ in range(5):
            sc.record("s", False, r)
        assert not sc.is_cut("s"), r


@pytest.mark.real_polite
def test_unreachable_robots_has_own_reason(monkeypatch):
    """N-M2: robots.txt に到達できないときは robots_unreachable（禁止とは別の理由）。即打ち切りは同じ。"""
    from src.collectors import polite
    from src.collectors.polite import ShopCutoff

    class _R:
        def __init__(self, st):
            self.st = st

        def robots_status(self, url):
            return self.st

        def is_allowed(self, url):
            return True

        def get_crawl_delay(self, url):
            return None
    for st, want in (("unknown", "robots_unreachable"), ("disallowed", "robots_disallowed"), ("allowed", "")):
        monkeypatch.setattr(polite, "robots_checker", lambda st=st: _R(st))
        assert polite.robots_block_reason("https://x.jp/") == want
    sc = ShopCutoff()
    sc.record("s", False, "robots_unreachable")
    assert sc.is_cut("s")
    from src.content.ui.admin import FAIL_REASON_LABELS
    assert "robots_unreachable" in FAIL_REASON_LABELS and "到達" in FAIL_REASON_LABELS["robots_unreachable"]
    monkeypatch.setattr(polite, "robots_checker", lambda: _R("unknown"))
    from src.collectors.buyback_kaitori_shouten import KaitoriShoutenCsvCollector
    c = KaitoriShoutenCsvCollector()
    assert c.fetch("airpods_pro3", "", "new_unopened") is None and c.last_failure_reason == "robots_unreachable"


def test_rakuten_cut_reason_depends_on_api(monkeypatch):
    m = _load_script("collect_resale_prices")
    import src.collectors.api.official_apis as oa
    monkeypatch.setattr(oa, "rakuten_ichiba_search", lambda kw: None)
    # Phase 13: 理由は取得の条件と同じ判定（official_apis.rakuten_available。ENABLE_RAKUTEN_API=true の明示）で決める
    monkeypatch.setattr(oa, "rakuten_available", lambda: True)
    m.RakutenResaleCollector().collect("x", ["kw"])
    assert m._LAST_FETCH["reason"] == "no_data"             # API が使えて結果が無いだけ（商品ごとの事情）
    monkeypatch.setattr(oa, "rakuten_available", lambda: False)
    m.RakutenResaleCollector().collect("x", ["kw"])
    assert m._LAST_FETCH["reason"] == "html_scraping_disabled"   # API が使えない → 以後取らない


def test_used_condition_has_japanese_label():
    from src.models.buyback_price import CONDITION_LABELS as BB
    from src.models.sale_price import CONDITION_LABELS as SP
    assert BB["used"] == SP["used"] == "中古"
