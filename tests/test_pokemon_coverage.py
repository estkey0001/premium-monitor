# -*- coding: utf-8 -*-
"""POKEMON COVERAGE EXPANSION PHASE のテスト。

ネットワークは requests.get を差し替えた擬似ルーターで再現し、
コレクターの _fetch（ページ診断の記録を含む）は実コードのまま通す。
テスト用の HTML / JSON は公式サイトで実際に確認した構造に合わせているが、
これはテストデータであり本番表示には使わない。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.rate_limiter import RateLimiter                     # noqa: E402
from src.collectors.robots_checker import RobotsChecker                 # noqa: E402
from src.collectors.tcg import base as tcg_base                         # noqa: E402
from src.collectors.tcg.lawson import (                                 # noqa: E402
    LawsonPokemonDiscoveryCollector, discover_card_links,
    extract_sale_time, extract_store_conditions,
)
from src.collectors.tcg.pokemon_news import (                           # noqa: E402
    PokemonNewsCollector, _article_region, parse_news_index,
)
from src.collectors.tcg.pokemon_products import (                       # noqa: E402
    PokemonProductRegistryCollector, build_api_url, normalize_detail_url,
    product_from_api, secondary_mapping,
)
from src.tcg import alerts, classify, freshness, premium, scoring, shrink  # noqa: E402
from src.tcg.funnel import (                                            # noqa: E402
    HEALTH_BLOCKED, HEALTH_DEGRADED, HEALTH_FAILED, HEALTH_HEALTHY,
    HEALTH_NO_EVENTS, CollectorFunnel,
)
from src.tcg.models import now_jst                                      # noqa: E402
from src.tcg.product_types import (                                     # noqa: E402
    PT_ACCESSORY, PT_BOOSTER_BOX, PT_ENHANCED_BOOSTER, PT_PREMIUM_COLLECTION,
    PT_SPECIAL_SET, PT_STARTER_DECK, PT_CONSTRUCTED_DECK, PT_OTHER,
    classify_pokemon_product_type, is_box_opportunity_eligible,
    parse_release_date, split_prices,
)


# ══════════════════════════════════════════════════════════════════════════
# 擬似ネットワーク
# ══════════════════════════════════════════════════════════════════════════
class _Resp:
    def __init__(self, url, text="", status=200):
        self.url = url
        self.text = text
        self.status_code = status
        self.apparent_encoding = "utf-8"
        self.encoding = "utf-8"


@pytest.fixture
def fake_net(monkeypatch):
    """URL の前方一致で応答を返す擬似 requests.get。未登録 URL は 404。"""
    routes: dict[str, tuple[int, str]] = {}
    calls: list[str] = []

    def fake_get(url, *a, **k):
        calls.append(url)
        for prefix, (status, body) in sorted(routes.items(), key=lambda kv: -len(kv[0])):
            if url.startswith(prefix):
                return _Resp(url, body, status)
        return _Resp(url, "not found", 404)

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    # テスト中は同一ドメイン60秒待機と robots.txt 取得を行わない
    monkeypatch.setattr(RateLimiter, "wait_if_needed", lambda self, url, min_interval_sec=60: None)
    monkeypatch.setattr(RobotsChecker, "robots_status", lambda self, url: "not_found")
    monkeypatch.setattr(RobotsChecker, "get_crawl_delay", lambda self, url: None)
    return routes, calls


def _api_payload(products, max_page=1):
    return json.dumps({"result": 1, "errMsg": "", "thisPage": 1, "maxPage": max_page,
                       "hitCnt": len(products), "products": products}, ensure_ascii=False)


def _jp(dt):
    return f"{dt.year}年{dt.month:2d}月{dt.day:2d}日（金）"


def _api_item(title, ptype, release, price, detail="", stores="", desc="・カード5枚入り"):
    return {"productTitle": title, "productType": ptype, "tumbsImg": "/products/x.jpg",
            "releaseDate": release, "priceTxt": price, "description": desc,
            "beginnerFlg": 0, "storesAvailable": stores, "link_cardList": "",
            "link_detailPage": detail, "link_pokemonCenter": ""}


# ══════════════════════════════════════════════════════════════════════════
# Task2 / Task11: 商品一覧 → 商品詳細 URL の発見
# ══════════════════════════════════════════════════════════════════════════
def test_category_listing_discovers_product_urls(fake_net):
    routes, calls = fake_net
    future = now_jst() + timedelta(days=20)
    past = now_jst() - timedelta(days=60)
    routes["https://www.pokemon-card.com/products/resultAPI.php?productType=expansion"] = (
        200, _api_payload([
            _api_item("拡張パック「テストA」", "拡張パック", _jp(future), "200円（税込）", "/ex/test-a/"),
            _api_item("拡張パック「テストB」", "拡張パック", _jp(past), "180円（税込）", "/ex/test-b/"),
        ]))
    routes["https://www.pokemon-card.com/products/resultAPI.php?productType=construction"] = (
        200, _api_payload([
            _api_item("スターターセットex テスト", "構築デッキ", _jp(future), "1,800円（税込）",
                      "/ex/me/#mee"),
        ]))
    routes["https://www.pokemon-card.com/products/resultAPI.php?productType=others"] = (
        200, _api_payload([
            _api_item("「テスト FUTURISTIC BOX」", "その他の商品", _jp(future), "27,500円（税込）",
                      "https://www.30th.pokemon-card.com/product/testbox",
                      stores="ポケモンセンターオンライン"),
        ]))
    routes["https://www.pokemon-card.com/ex/"] = (200, "<html><title>詳細</title><body>内容物</body></html>")
    routes["https://www.30th.pokemon-card.com/product/"] = (
        200, "<html><title>BOX</title><body>こちらの商品は、ポケモンセンターオンラインのみでのお取り扱いとなります。</body></html>")

    c = PokemonProductRegistryCollector()
    events = c.collect()
    f = c.funnel.to_dict()

    assert len(c.registry) == 4
    urls = {r["official_url"] for r in c.registry}
    # アンカー（#mee）は取り除き、公式ドメインの詳細 URL を記録する
    assert "https://www.pokemon-card.com/ex/me/" in urls
    assert "https://www.30th.pokemon-card.com/product/testbox" in urls
    assert f["product_pages_discovered"] == 4
    assert f["product_links_discovered"] == 4
    for r in c.registry:
        assert r["discovered_at"] and r["source_url"].startswith(
            "https://www.pokemon-card.com/products/resultAPI.php")
    # 発売済み（60日前）はイベントにしない、発売予定は COMING_SOON 用のイベントになる
    names = {e["product_name"] for e in events}
    assert "拡張パック「テストA」" in names
    assert "拡張パック「テストB」" not in names
    assert f["rejection_reasons"].get("past_release") == 1
    assert c.health["status"] in (HEALTH_HEALTHY, HEALTH_NO_EVENTS)


def test_api_url_uses_official_parameters():
    url = build_api_url("expansion", page=2)
    for p in ("productType=expansion", "dateLowerY=", "dateUpperD=", "page=2"):
        assert p in url
    assert "page=" not in build_api_url("expansion", page=1)


def test_detail_url_normalization_rejects_other_domains():
    assert normalize_detail_url("/ex/m6/") == "https://www.pokemon-card.com/ex/m6/"
    assert normalize_detail_url("/ex/me/#mee") == "https://www.pokemon-card.com/ex/me/"
    assert normalize_detail_url("https://evil.example.com/product") is None
    assert normalize_detail_url("") is None


# ══════════════════════════════════════════════════════════════════════════
# Task4: 商品詳細（存在しない値は null）
# ══════════════════════════════════════════════════════════════════════════
def test_product_detail_fields_are_null_when_absent():
    rec = product_from_api(_api_item("拡張パック「テスト」", "拡張パック",
                                     "2026年 7月31日（金）", "200円（税込）", "/ex/m6/"),
                           now_jst().isoformat(), "https://www.pokemon-card.com/products/resultAPI.php")
    assert rec["product_type"] == PT_BOOSTER_BOX
    assert rec["release_date"].startswith("2026-07-31")
    assert rec["pack_price"] == 200
    assert rec["retail_price"] is None          # BOX 価格は不明
    assert rec["packs_per_box"] is None         # 公式に明示されていない
    assert rec["series_name"] is None and rec["product_code"] is None
    assert rec["cards_per_pack"] == 5
    assert rec["verified"] is True


def test_detail_page_store_note_is_extracted_only_when_explicit():
    note = PokemonProductRegistryCollector._store_note(
        "※こちらの商品は、ポケモンセンターオンラインのみでのお取り扱いとなります。")
    assert "ポケモンセンターオンライン" in note
    assert PokemonProductRegistryCollector._store_note("発売日 2026年9月16日") is None


# ══════════════════════════════════════════════════════════════════════════
# Task5: 商品種別
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("api_type,title,expected", [
    ("拡張パック", "拡張パック「ストームエメラルダ」", PT_BOOSTER_BOX),
    ("拡張パック", "強化拡張パック「熱風のアリーナ」", PT_ENHANCED_BOOSTER),
    ("拡張パック", "ハイクラスパック 「MEGAドリームex」", PT_SPECIAL_SET),
    ("拡張パック", "拡張パックデラックス「ブラックボルト」", PT_SPECIAL_SET),
    ("構築デッキ", "スターターセットex イーブイex", PT_STARTER_DECK),
    ("構築デッキ", "「30th CELEBRATION プレミアムデッキセット」", PT_CONSTRUCTED_DECK),
    ("その他の商品", "「30th CELEBRATION FUTURISTIC BOX」", PT_PREMIUM_COLLECTION),
    ("その他の商品", "「30th CELEBRATION カードセット ニャオハ」", PT_SPECIAL_SET),
    ("その他の商品", "カードイラストフィギュアコレクション", PT_OTHER),
    ("周辺グッズ", "デッキシールド 30th CELEBRATION", PT_ACCESSORY),
])
def test_pokemon_product_types(api_type, title, expected):
    assert classify_pokemon_product_type(api_type, title) == expected


def test_accessory_is_not_box_opportunity():
    assert is_box_opportunity_eligible(PT_ACCESSORY) is False
    assert is_box_opportunity_eligible(PT_BOOSTER_BOX) is True
    rec = product_from_api(_api_item("デッキケース テスト", "周辺グッズ", "2026年 9月16日（水）",
                                     "500円（税込）"), now_jst().isoformat(), "x")
    assert rec["box_opportunity_eligible"] is False
    assert secondary_mapping(rec) is None


def test_accessory_is_never_turned_into_sale_event(fake_net):
    routes, _ = fake_net
    future = now_jst() + timedelta(days=5)
    routes["https://www.pokemon-card.com/products/resultAPI.php?productType=others"] = (
        200, _api_payload([_api_item("デッキシールド テスト", "周辺グッズ", _jp(future),
                                     "990円（税込）")]))
    c = PokemonProductRegistryCollector()
    assert c.collect() == []
    assert c.funnel.rejection_reasons.get("accessory") == 1


# ══════════════════════════════════════════════════════════════════════════
# Task18: パック価格を BOX 定価として自動断定しない
# ══════════════════════════════════════════════════════════════════════════
def test_pack_price_is_not_verified_box_retail():
    for api_type, title in (("拡張パック", "拡張パック「X」"),
                            ("拡張パック", "ハイクラスパック「X」"),
                            ("拡張パック", "拡張パックデラックス「X」")):
        pt = classify_pokemon_product_type(api_type, title)
        sp = split_prices(pt, "550円（税込）", api_type=api_type)
        assert sp["pack_price"] == 550 and sp["retail_price"] is None, title


def test_registry_retail_prices_exclude_pack_prices():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cte", PROJECT_ROOT / "scripts" / "collect_tcg_events.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    now = now_jst().isoformat()
    pack = product_from_api(_api_item("拡張パック「X」", "拡張パック", "2026年 7月31日（金）",
                                      "200円（税込）"), now, "x")
    box = product_from_api(_api_item("「X FUTURISTIC BOX」", "その他の商品", "2026年 9月16日（水）",
                                     "27,500円（税込）"), now, "x")
    deck = product_from_api(_api_item("スターターセットex X", "構築デッキ", "2026年 7月31日（金）",
                                      "1,800円（税込）"), now, "x")
    prices = mod.registry_retail_prices([pack, box, deck])
    assert pack["product_id"] not in prices           # パック価格は定価にしない
    assert prices[box["product_id"]] == 27500          # 商品単価と明示されたもの
    assert deck["product_id"] not in prices            # BOX Opportunity 対象外


def test_release_date_does_not_invent_time():
    assert parse_release_date("2026年 9月16日（水）") == "2026-09-16T00:00:00+09:00"
    assert parse_release_date("2026年秋発売予定") is None


# ══════════════════════════════════════════════════════════════════════════
# Task6 / Task7: ニュース（大会・キャンペーン参加を販売にしない）
# ══════════════════════════════════════════════════════════════════════════
def _news_index(items):
    body = []
    for href, label_cls, label, title, date in items:
        lab = (f'<div class="Calendar_Label Calendar_Label_{label_cls}">{label}</div>'
               if label_cls else "")
        body.append(f'<a class="List_item_inner" href="{href}"><div class="List_title">'
                    f'<img src="/x.jpg"></div><div class="List_body">{lab}{title}'
                    f'<span class="Date Date-small">{date}</span></div></a>')
    return "<html><title>ニュース一覧</title><body>" + "".join(body) + "</body></html>"


def _d(days):
    t = now_jst() - timedelta(days=days)
    return f"{t.year}.{t.month}.{t.day}"


def test_news_index_parses_official_categories():
    html = _news_index([
        ("/info/000001.html", "Event", "イベント", "「チャンピオンズリーグ」開催！", "2026.9.28"),
        ("/info/000002.html", "Products", "商品", "新商品が登場！", "2026.8.20"),
        ("/info/000003.html", "", "", "スペシャルBOXの追加販売のお知らせ", "2026.3.13"),
    ])
    items = parse_news_index(html)
    assert [i["category"] for i in items] == ["Event", "Products", "Other"]
    assert items[0]["published_at"].startswith("2026-09-28")
    assert items[2]["title"] == "スペシャルBOXの追加販売のお知らせ"


def test_tournament_articles_are_rejected_without_fetching(fake_net):
    routes, calls = fake_net
    routes["https://www.pokemon-card.com/info/"] = (200, _news_index([
        ("/info/000001.html", "Event", "イベント", "「チャンピオンズリーグ2027」エントリー受付中", _d(1)),
        ("/info/000002.html", "Event", "イベント", "ジムバトル 30thプロモカードパック配布", _d(2)),
    ]))
    c = PokemonNewsCollector()
    assert c.collect() == []
    assert c.funnel.rejection_reasons.get("event_category") == 2
    # イベント記事の本文は取得しない
    assert not any("/info/000001.html" in u for u in calls)


def test_campaign_entry_and_player_recruitment_rejected(fake_net):
    routes, calls = fake_net
    routes["https://www.pokemon-card.com/info/"] = (200, _news_index([
        ("/info/000010.html", "", "", "ポケカジムエントリーキャンペーン2026年後期、9月1日スタート！", _d(1)),
        ("/info/000011.html", "", "", "「シティリーグ2027 シーズン1」事前抽選のエントリー期間延長", _d(2)),
        ("/info/000012.html", "", "", "「ポケカ体験会」参加者募集！", _d(3)),
    ]))
    c = PokemonNewsCollector()
    assert c.collect() == []
    assert c.funnel.rejection_reasons.get("non_sale_announcement") == 3
    assert not any("/info/0000" in u for u in calls if u != "https://www.pokemon-card.com/info/")


def test_news_sale_article_is_parsed(fake_net):
    routes, _ = fake_net
    pub = _d(1)
    routes["https://www.pokemon-card.com/info/"] = (200, _news_index([
        ("/info/000020.html", "Products", "商品", "拡張パック「テスト」抽選販売のお知らせ", pub),
    ]))
    y = now_jst().year + 1
    routes["https://www.pokemon-card.com/info/000020.html"] = (200, (
        "<html><title>拡張パック「テスト」抽選販売のお知らせ | 公式</title><body>"
        "<p>ポケモンカードチャンネル</p>"
        "<h1>拡張パック「テスト」抽選販売のお知らせ</h1>"
        f"<p>{pub}</p>"
        "<p>拡張パック「テスト」BOXの抽選販売を行います。</p>"
        f"<p>応募期間 {y}年1月10日 10:00 〜 {y}年1月20日 23:59</p>"
        f"<p>当選発表 {y}年1月25日</p>"
        f"<p>購入期間 {y}年1月26日 〜 {y}年1月31日</p>"
        "<p>発送時期 2月上旬</p><p>価格 7,200円（税込）</p></body></html>"))
    c = PokemonNewsCollector()
    events = c.collect()
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "LOTTERY"
    assert ev["application_start"].startswith(f"{y}-01-10T10:00")
    assert ev["application_end"].startswith(f"{y}-01-20T23:59")
    assert ev["result_date"].startswith(f"{y}-01-25")
    assert ev["purchase_start"].startswith(f"{y}-01-26")
    assert ev["purchase_end"].startswith(f"{y}-01-31")
    assert ev["article_category"] == "商品"
    assert ev["published_at"] and ev["reported_at"] == ev["published_at"]
    assert ev["source_type"] == "OFFICIAL"
    assert c.funnel.news_pages_loaded == 1
    assert c.health["status"] == HEALTH_HEALTHY


def test_article_region_ignores_navigation_text():
    text = ("拡張パック「テスト」 | 公式\nポケモンカードチャンネル\nイベント検索\n"
            "拡張パック「テスト」のお知らせ\n2026.8.20\n本文です")
    region = _article_region(text, "拡張パック「テスト」のお知らせ")
    assert region.startswith("拡張パック「テスト」のお知らせ")
    assert "チャンネル" not in region
    text2 = "ナビ\nタイトル記事の件名です\n2026年 3月 13日（金）更新\n本文"
    assert _article_region(text2, "タイトル記事の件名です").startswith("タイトル記事")


def test_figure_article_is_not_a_card_sale(fake_net):
    routes, _ = fake_net
    pub = _d(1)
    routes["https://www.pokemon-card.com/info/"] = (200, _news_index([
        ("/info/000030.html", "Products", "商品", "カードイラストがフィギュアになって登場！", pub)]))
    routes["https://www.pokemon-card.com/info/000030.html"] = (200, (
        "<html><body><h1>カードイラストがフィギュアになって登場！</h1>"
        f"<p>{pub}</p><p>拡張パック「スターバース」に収録されたカードを立体化。</p>"
        "<p>商品名</p><p>カードイラストフィギュアコレクション みずべのポケモン</p>"
        "<p>希望小売価格</p><p>1,800円（税込）</p><p>発売日 2026年8月27日</p></body></html>"))
    c = PokemonNewsCollector()
    assert c.collect() == []
    assert c.funnel.rejection_reasons.get("non_card_product") == 1


# ══════════════════════════════════════════════════════════════════════════
# Task9 / Task10: 抽選の日付と当選者購入期間
# ══════════════════════════════════════════════════════════════════════════
def test_lottery_dates_are_label_associated():
    y = now_jst().year + 1
    got = tcg_base.BaseTcgCollector.extract_labeled_datetimes(
        f"当選発表 {y}年1月25日 購入期限 {y}年1月31日 23:59 "
        f"応募期間 {y}年1月10日 〜 {y}年1月20日 発送時期 {y}年2月10日")
    assert got["application_start"].startswith(f"{y}-01-10")
    assert got["application_end"].startswith(f"{y}-01-20")
    assert got["result_date"].startswith(f"{y}-01-25")
    assert got["purchase_end"].startswith(f"{y}-01-31T23:59")
    assert got["shipping_date"].startswith(f"{y}-02-10")


def test_invalid_lottery_period_is_dropped():
    got = tcg_base.BaseTcgCollector.extract_labeled_datetimes(
        "応募期間 2026年10月20日 〜 2026年10月1日")
    assert "application_start" not in got and "application_end" not in got


def test_winner_purchase_period_is_not_general_sale():
    now = now_jst()
    ev = {"event_type": "LOTTERY", "source_type": "OFFICIAL",
          "application_start": (now - timedelta(days=10)).isoformat(),
          "application_end": (now - timedelta(days=5)).isoformat(),
          "purchase_start": (now - timedelta(days=1)).isoformat(),
          "purchase_end": (now + timedelta(days=2)).isoformat()}
    st = freshness.compute_status(ev)
    assert st == "WINNER_PURCHASE_PERIOD"
    assert st != "AVAILABLE_NOW"
    ev["status"] = st
    assert scoring.buy_now_signal(ev, {"premium_percent": 90.0})["buy_now"] is False
    assert freshness.available_now(ev) is False


def test_lottery_before_application_is_not_open():
    """応募開始前の抽選を「受付中」にしない。"""
    ev = {"event_type": "LOTTERY", "source_type": "OFFICIAL",
          "application_start": (now_jst() + timedelta(days=5)).isoformat(),
          "application_end": (now_jst() + timedelta(days=10)).isoformat()}
    assert freshness.compute_status(ev) == "COMING_SOON"


# ══════════════════════════════════════════════════════════════════════════
# Task23: 発売予定は AVAILABLE_NOW ではない
# ══════════════════════════════════════════════════════════════════════════
def test_future_product_is_coming_soon_not_available():
    ev = {"event_type": "GENERAL_SALE", "source_type": "OFFICIAL",
          "sale_start": (now_jst() + timedelta(days=16)).isoformat()}
    st = freshness.compute_status(ev)
    assert st == "COMING_SOON"
    ev["status"] = st
    assert freshness.available_now(ev) is False
    assert scoring.buy_now_signal(ev, {"premium_percent": 90.0})["buy_now"] is False
    assert alerts.notification_kind(ev) is None


def test_stale_first_come_is_not_available_after_pipeline():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cte2", PROJECT_ROOT / "scripts" / "collect_tcg_events.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raw = [{"tcg": "POKEMON", "product_id": "p", "product_name": "旧BOX",
            "event_type": "FIRST_COME", "store": "YODOBASHI",
            "source_type": "RETAILER_OFFICIAL", "confidence": "high",
            "sale_start": (now_jst() - timedelta(days=30)).isoformat(),
            "observed_at": now_jst().isoformat(), "shrink_status": "UNKNOWN"}]
    events, _ = mod.enrich(raw, {})
    assert events[0]["status"] != "AVAILABLE_NOW"
    assert events[0]["notification_kind"] is None


# ══════════════════════════════════════════════════════════════════════════
# Task14 / Task15 / Task24: 信頼度・再販分類・通知候補
# ══════════════════════════════════════════════════════════════════════════
def test_community_report_is_not_confirmed_sale():
    conf = classify.confidence_for("COMMUNITY_REPORT", corroborations=1)
    assert conf == "low"
    assert classify.verification_label("COMMUNITY_REPORT", conf, 1) != "Confirmed"
    ev = {"event_type": "RESTOCK", "source_type": "COMMUNITY_REPORT",
          "reported_at": now_jst().isoformat()}
    assert freshness.compute_status(ev) != "AVAILABLE_NOW"
    assert classify.restock_class("RESTOCK", "COMMUNITY_REPORT") == "COMMUNITY_RESTOCK_REPORT"


def test_restock_classes():
    assert classify.restock_class("RESTOCK", "OFFICIAL") == "OFFICIAL_RESTOCK"
    assert classify.restock_class("ONLINE_RESTOCK", "RETAILER_OFFICIAL") == "OFFICIAL_RESTOCK"
    assert classify.restock_class("RESTOCK", "STORE_OFFICIAL") == "STORE_OFFICIAL_RESTOCK"
    assert classify.restock_class("RESTOCK", "SOCIAL_REPORT") == "COMMUNITY_RESTOCK_REPORT"
    assert classify.restock_class("LOTTERY", "OFFICIAL") is None


def test_unverified_community_report_is_never_critical_notification():
    ev = {"event_type": "RESTOCK", "source_type": "SOCIAL_REPORT", "status": "UNVERIFIED",
          "confidence": "medium", "product_name": "BOX", "store": "LAWSON"}
    assert alerts.notification_kind(ev) is None
    assert alerts.instant_sale_alerts([ev], signals=[{"chain": "LAWSON"}]) == []


def test_official_convenience_sale_is_critical_candidate():
    ev = {"event_type": "CONVENIENCE_STORE", "source_type": "RETAILER_OFFICIAL",
          "status": "AVAILABLE_NOW", "confidence": "high", "product_name": "BOX",
          "store": "LAWSON"}
    out = alerts.instant_sale_alerts([ev])
    assert out and out[0]["kind"] == "CONVENIENCE_OFFICIAL"
    assert out[0]["priority"] == "CRITICAL"


def test_notification_kinds_are_restricted():
    assert set(alerts.NOTIFICATION_KINDS) == {
        "LOTTERY_OPEN", "LOTTERY_ENDING", "FIRST_COME_START",
        "OFFICIAL_RESTOCK", "ONLINE_RESTOCK", "CONVENIENCE_OFFICIAL"}


# ══════════════════════════════════════════════════════════════════════════
# Task19 / Task21: シュリンク・プレミアのサンプル数
# ══════════════════════════════════════════════════════════════════════════
def test_box_is_not_sealed_shrink():
    assert shrink.detect_shrink_status("BOX販売あり 1会計1BOXまで") == "UNKNOWN"
    assert shrink.assume_shrink_from_box(True) == "UNKNOWN"


def test_less_than_three_market_samples_gives_null_premium():
    p = premium.build_premium(27500, sealed_prices=[40000, 42000])
    assert p["market_median"] is None
    assert p["premium_yen"] is None and p["premium_percent"] is None
    assert p["insufficient_samples"] is True


# ══════════════════════════════════════════════════════════════════════════
# Task12: ローソン（明記がある場合だけ保存）
# ══════════════════════════════════════════════════════════════════════════
def test_lawson_discovers_only_card_links_on_official_domain():
    html = ('<a href="/campaign/detail/pokemoncard/">ポケモンカードゲーム 新弾</a>'
            '<a href="/campaign/detail/goods/">ポケモングッズ</a>'
            '<a href="https://evil.example.com/pokemoncard">x</a>')
    assert discover_card_links(html, "https://www.lawson.co.jp/campaign/") == [
        "https://www.lawson.co.jp/campaign/detail/pokemoncard/"]


def test_lawson_sale_time_only_when_explicit():
    assert extract_sale_time("9月16日（水）午前7時より販売開始") == "07:00"
    assert extract_sale_time("発売日 9月16日 7:00") == "07:00"
    assert extract_sale_time("9月16日発売") is None


def test_lawson_store_conditions_only_when_explicit():
    got = extract_store_conditions("ご予約はお受けしておりません。お取り置きはできません。")
    assert got["reservation_allowed"] is False and got["hold_allowed"] is False
    assert got["box_sale"] is None
    none = extract_store_conditions("ポケモンカードを販売します")
    assert none == {"reservation_allowed": None, "hold_allowed": None, "box_sale": None}


def test_lawson_collector_follows_discovered_link(fake_net):
    routes, calls = fake_net
    y = now_jst().year + 1
    routes["https://www.lawson.co.jp/campaign/"] = (
        200, '<html><a href="/campaign/detail/pokemoncard/">ポケモンカードゲーム 新弾発売</a></html>')
    routes["https://www.lawson.co.jp/recommend/"] = (200, "<html>なし</html>")
    routes["https://www.lawson.co.jp/campaign/detail/pokemoncard/"] = (200, (
        "<html><body><p>ポケモンカードゲーム 拡張パック「テスト」</p>"
        f"<p>販売開始 {y}年3月13日 午前7時より店頭にて販売</p>"
        "<p>お一人様5パックまで</p><p>ご予約はお受けしておりません。</p></body></html>"))
    c = LawsonPokemonDiscoveryCollector()
    events = c.collect()
    assert c.funnel.product_pages_discovered == 1
    assert events, "発見したローソン告知から販売イベントを作れていない"
    ev = events[0]
    assert ev["event_type"] == "CONVENIENCE_STORE"
    assert ev["sale_start_time"] == "07:00"
    assert ev["reservation_allowed"] is False
    assert ev["purchase_limit"] == "1会計5パックまで"
    assert ev["official_confirmation"] is True
    assert ev["shrink_status"] == "UNKNOWN"


def test_lawson_without_card_links_is_ok_no_events(fake_net):
    routes, _ = fake_net
    routes["https://www.lawson.co.jp/campaign/"] = (200, "<html><a href='/a/'>おにぎり</a></html>")
    routes["https://www.lawson.co.jp/recommend/"] = (200, "<html>なし</html>")
    c = LawsonPokemonDiscoveryCollector()
    assert c.collect() == []
    assert c.health["status"] == HEALTH_NO_EVENTS
    assert any("推測 URL" in n for n in c.funnel.notes)


# ══════════════════════════════════════════════════════════════════════════
# Task3 / Task17 / Task31: ファネルと健全性
# ══════════════════════════════════════════════════════════════════════════
def test_collector_funnel_metrics_are_emitted(fake_net):
    routes, _ = fake_net
    routes["https://www.pokemon-card.com/products/resultAPI.php"] = (
        200, _api_payload([_api_item("拡張パック「X」", "拡張パック",
                                     _jp(now_jst() + timedelta(days=9)), "200円（税込）", "/ex/x/")]))
    routes["https://www.pokemon-card.com/ex/"] = (200, "<html><title>X</title></html>")
    c = PokemonProductRegistryCollector()
    c.collect()
    f = c.health["funnel"]
    for key in ("pages_discovered", "pages_requested", "pages_loaded",
                "product_pages_discovered", "news_pages_discovered",
                "candidate_events", "accepted_sales_events", "rejected_events",
                "rejection_reasons", "current_events", "pages"):
        assert key in f, key
    page = f["pages"][0]
    for key in ("http_status", "final_url", "page_title", "html_length",
                "text_length", "links_discovered", "product_links_discovered",
                "candidate_blocks", "accepted", "rejected", "robots_status"):
        assert key in page, key
    assert page["http_status"] == 200 and page["html_length"] > 0
    assert c.health["status"] == HEALTH_HEALTHY


def test_page_loaded_but_no_product_links_is_degraded(fake_net, monkeypatch):
    """Playwright でページが読めても商品リンクが無ければ DEGRADED。"""
    import types
    from src.collectors.tcg.pokemon import PokemonProductsCollector

    class _Page:
        def goto(self, *a, **k): pass
        def wait_for_timeout(self, *a, **k): pass
        def content(self):
            return ("<html><title>商品情報</title><body>拡張パック 複数のカードが"
                    "ランダムに封入されている。</body></html>")

    class _Browser:
        def new_page(self, *a, **k): return _Page()
        def close(self): pass

    class _PW:
        chromium = types.SimpleNamespace(launch=lambda *a, **k: _Browser())
        def __enter__(self): return self
        def __exit__(self, *a): return False

    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: _PW()
    pkg = types.ModuleType("playwright")
    pkg.sync_api = mod
    monkeypatch.setitem(sys.modules, "playwright", pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)

    class CategoryOnly(PokemonProductsCollector):
        requires_product_pages = True

    c = CategoryOnly()
    c.collect()
    assert c.funnel.pages_loaded == 1          # ページは読めた
    assert c.funnel.errors == 0                # エラーも無い
    assert c.health["status"] == HEALTH_DEGRADED   # それでも健全とは言わない


def test_http_403_is_blocked_not_healthy(fake_net):
    routes, _ = fake_net
    routes["https://www.pokemoncenter-online.com/"] = (403, "Forbidden")
    from src.collectors.tcg.pokemon import PokemonCenterOnlineCollector
    c = PokemonCenterOnlineCollector()
    assert c.collect() == []
    assert c.health["status"] == HEALTH_BLOCKED
    assert c.funnel.pages[0].http_status == 403


def test_no_page_loaded_is_failed():
    f = CollectorFunnel("X")
    f.pages_requested = 2
    f.errors = 2
    assert f.status() == HEALTH_FAILED


# ══════════════════════════════════════════════════════════════════════════
# Task27 / Task28: robots と RateLimiter
# ══════════════════════════════════════════════════════════════════════════
def test_robots_fetch_failure_is_reported_as_unknown(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", boom)
    rc = RobotsChecker()
    assert rc.robots_status("https://example.org/page") == "unknown"
    # 既存仕様（fail-open）は変えていないが、根拠は unknown として区別される
    assert rc.is_allowed("https://example.org/page") is True


def test_robots_404_is_reported_as_not_found(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp("x", "<html>404</html>", 404))
    rc = RobotsChecker()
    assert rc.robots_status("https://example.org/page") == "not_found"


def test_robots_disallow_is_reported(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: _Resp("x", "User-agent: *\nDisallow: /private/", 200))
    rc = RobotsChecker()
    assert rc.robots_status("https://example.org/private/a") == "disallowed"
    assert rc.robots_status("https://example.org/public") == "allowed"


def test_rate_limiter_still_enforces_60_seconds(monkeypatch):
    """アクセス頻度を上げる方向に変えていないこと（最低60秒）。"""
    import time as _time
    waits: list[float] = []
    monkeypatch.setattr(_time, "sleep", lambda s: waits.append(s))
    rl = RateLimiter()
    rl.reset()
    rl.wait_if_needed("https://rate.example.org/a", min_interval_sec=20)
    rl.wait_if_needed("https://rate.example.org/b", min_interval_sec=20)
    assert waits and waits[0] > 55
    assert tcg_base.MIN_INTERVAL_SEC >= 60
    rl.reset()


# ══════════════════════════════════════════════════════════════════════════
# Task25 / Task26: deploy-check の失敗で CI を必ず失敗させる
# ══════════════════════════════════════════════════════════════════════════
def test_deploy_check_cli_exits_nonzero_on_errors(monkeypatch):
    from click.testing import CliRunner
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import deploy_check
    monkeypatch.setattr(deploy_check, "check", lambda: [
        {"level": "error", "check": "mock_failure", "message": "意図的な失敗"}])
    from src.cli import cli
    res = CliRunner().invoke(cli, ["deploy-check-lp"])
    assert res.exit_code != 0
    assert "FAILED" in res.output


def test_deploy_check_cli_exits_zero_when_clean(monkeypatch):
    from click.testing import CliRunner
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import deploy_check
    monkeypatch.setattr(deploy_check, "check", lambda: [
        {"level": "ok", "check": "fine", "message": "ok"}])
    from src.cli import cli
    assert CliRunner().invoke(cli, ["deploy-check-lp"]).exit_code == 0


def _deploy_check_step() -> dict:
    import yaml
    wf = yaml.safe_load((PROJECT_ROOT / ".github" / "workflows" / "daily_lp.yml")
                        .read_text(encoding="utf-8"))
    steps = [s for s in wf["jobs"]["update-lp"]["steps"] if s.get("name") == "Deploy check"]
    assert len(steps) == 1
    return steps[0]


def test_workflow_deploy_check_step_is_fail_closed():
    step = _deploy_check_step()
    assert "pipefail" in step["run"]
    assert "tee exports/deploy_check_latest.txt" in step["run"]   # ログ保存は維持
    assert not step.get("continue-on-error")


def test_workflow_step_fails_when_deploy_check_fails(tmp_path):
    """ワークフローの run スクリプトを実際に bash で実行し、非ゼロになることを確認する。

    deploy-check 本体の代わりに「失敗する deploy-check」を差し込む。
    GitHub Actions の既定シェル（bash -e）と同じ条件で実行する。
    """
    step = _deploy_check_step()
    script = step["run"].replace("python -m src.cli deploy-check-lp",
                                 "(echo 'Errors: 1'; exit 1)")
    script = script.replace("exports/deploy_check_latest.txt", str(tmp_path / "log.txt"))
    res = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True)
    assert res.returncode != 0
    assert "Errors: 1" in (tmp_path / "log.txt").read_text()   # ログは残る


def test_without_pipefail_tee_would_hide_the_failure(tmp_path):
    """修正前の問題の再現: pipefail が無いと tee の終了コードで成功扱いになる。"""
    res = subprocess.run(["bash", "-e", "-c", f"(exit 1) | tee {tmp_path / 'x.txt'}"],
                         capture_output=True, text=True)
    assert res.returncode == 0


def test_funnel_discovered_is_not_less_than_requested(fake_net):
    """ファネルの整合性: 取得したページはすべて「発見」にも数える。"""
    routes, _ = fake_net
    routes["https://www.pokemon-card.com/products/resultAPI.php"] = (
        200, _api_payload([_api_item("拡張パック「X」", "拡張パック",
                                     _jp(now_jst() + timedelta(days=9)), "200円（税込）", "/ex/x/")]))
    routes["https://www.pokemon-card.com/ex/"] = (200, "<html><title>X</title></html>")
    c = PokemonProductRegistryCollector()
    c.collect()
    assert c.funnel.pages_discovered >= c.funnel.pages_requested >= c.funnel.pages_loaded


# ══════════════════════════════════════════════════════════════════════════
# レビュー指摘の回帰固定
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("title,body", [
    ("拡張パック「テスト」発売記念 購入キャンペーン開催！",
     "拡張パック「テスト」を購入すると、抽選でプロモカードが当たるキャンペーンを実施します。"
     "応募期間 2099年1月10日 〜 2099年1月20日"),
    ("ジムバトル参加者向け 購入権のお知らせ",
     "ジムバトルに参加するとBOXの購入権がもらえます。"),
    ("プロモカードプレゼント企画",
     "拡張パックBOXを購入した方に、抽選でプロモカードをプレゼント。価格 7,200円"),
])
def test_purchase_campaign_is_not_lottery_sale(fake_net, title, body):
    routes, _ = fake_net
    pub = _d(1)
    routes["https://www.pokemon-card.com/info/"] = (200, _news_index([
        ("/info/000050.html", "", "", title, pub)]))
    routes["https://www.pokemon-card.com/info/000050.html"] = (
        200, f"<html><body><h1>{title}</h1><p>{pub}</p><p>{body}</p></body></html>")
    c = PokemonNewsCollector()
    events = c.collect()
    assert events == [], f"キャンペーン記事を販売イベントにしている: {title}"
    assert not any(e.get("event_type") == "LOTTERY" for e in events)


def test_giveaway_lottery_wording_is_not_product_lottery():
    from src.tcg.sales_context import is_product_lottery
    assert is_product_lottery("購入すると抽選でプロモカードが当たる") is False
    assert is_product_lottery("抽選で100名様にプレゼント") is False
    assert is_product_lottery("拡張パックBOXの抽選販売を行います") is True


def test_lawson_negated_conditions_are_false():
    got = extract_store_conditions("BOX販売は行っておりません。予約受付は行っておりません。")
    assert got["box_sale"] is False
    assert got["reservation_allowed"] is False
    pos = extract_store_conditions("予約受付中です。BOX販売あり。")
    assert pos["reservation_allowed"] is True and pos["box_sale"] is True


def test_lawson_link_host_is_exact():
    html = '<a href="https://xlawson.co.jp/pokemoncard">ポケモンカード</a>'
    assert discover_card_links(html, "https://www.lawson.co.jp/") == []


def test_release_date_alone_never_means_available_now():
    """公式の発売日を過ぎても、在庫を確認していなければ「今買える」にしない。"""
    ev = {"event_type": "GENERAL_SALE", "source_type": "OFFICIAL",
          "sale_start": (now_jst() - timedelta(hours=3)).isoformat(),
          "availability_basis": "release_date_only"}
    assert freshness.compute_status(ev) == "UNVERIFIED"
    assert freshness.available_now(ev) is False
    ev["status"] = freshness.compute_status(ev)
    assert scoring.buy_now_signal(ev, {"premium_percent": 90.0})["buy_now"] is False


def test_article_date_alone_never_means_available_now():
    """記事公開日（00:00 起点）だけの再販情報を深夜実行時に「今買える」にしない。"""
    ev = {"event_type": "RESTOCK", "source_type": "OFFICIAL",
          "reported_at": (now_jst() - timedelta(minutes=30)).isoformat(),
          "availability_basis": "article_date_only"}
    assert freshness.compute_status(ev) != "AVAILABLE_NOW"


def test_registry_events_carry_release_date_basis(fake_net):
    routes, _ = fake_net
    routes["https://www.pokemon-card.com/products/resultAPI.php"] = (
        200, _api_payload([_api_item("拡張パック「X」", "拡張パック",
                                     _jp(now_jst() - timedelta(days=1)), "200円（税込）", "/ex/x/")]))
    routes["https://www.pokemon-card.com/ex/"] = (200, "<html><title>X</title></html>")
    events = PokemonProductRegistryCollector().collect()
    assert events and events[0]["availability_basis"] == "release_date_only"
    assert freshness.compute_status(events[0]) != "AVAILABLE_NOW"


def test_registry_keeps_same_name_with_different_release_dates(fake_net):
    routes, _ = fake_net
    a = _jp(now_jst() + timedelta(days=5))
    b = _jp(now_jst() + timedelta(days=40))
    routes["https://www.pokemon-card.com/products/resultAPI.php?productType=others"] = (
        200, _api_payload([
            _api_item("「テスト BOX」", "その他の商品", a, "5,000円（税込）"),
            _api_item("「テスト BOX」", "その他の商品", b, "5,000円（税込）"),
        ]))
    c = PokemonProductRegistryCollector()
    c.collect()
    assert len([r for r in c.registry if r["name"] == "「テスト BOX」"]) == 2


def test_registry_survives_malformed_api_response(fake_net):
    routes, _ = fake_net
    routes["https://www.pokemon-card.com/products/resultAPI.php"] = (
        200, json.dumps({"result": 1, "maxPage": "abc", "products": ["bad", None]}))
    c = PokemonProductRegistryCollector()
    assert c.collect() == []          # 例外にならない
    assert c.registry == []


def test_fixture_check_ignores_community_reports_without_url():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import deploy_check
    ok = deploy_check._check_pokemon_coverage({"events": [
        {"product_name": "店頭目撃", "source_type": "SOCIAL_REPORT", "source_url": ""}]})
    r756 = [r for r in ok if r["check"] == "tcg_no_fixture_in_production"][0]
    assert r756["level"] == "ok"
    ng = deploy_check._check_pokemon_coverage({"events": [
        {"product_name": "偽物", "source_type": "OFFICIAL", "source_url": "https://example.com/x"},
        {"product_name": "URL無し公式", "source_type": "OFFICIAL", "source_url": ""}]})
    r756 = [r for r in ng if r["check"] == "tcg_no_fixture_in_production"][0]
    assert r756["level"] == "error"


def test_empty_payload_schema_matches_normal(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cte3", PROJECT_ROOT / "scripts" / "collect_tcg_events.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
    mod._write_empty_payload("boom")
    funnel = json.loads((tmp_path / "pokemon_funnel.json").read_text(encoding="utf-8"))
    assert {"sources", "total", "rejection_reasons", "current_events"} <= set(funnel)
    reg = json.loads((tmp_path / "pokemon_registry.json").read_text(encoding="utf-8"))
    assert reg["products"] == [] and reg["secondary_mapping"] == []
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert "pokemon_funnel" in latest


def test_failure_is_still_notified_after_fail_closed():
    """deploy-check 失敗でジョブが止まっても通知ステップは実行される。"""
    import yaml
    wf = yaml.safe_load((PROJECT_ROOT / ".github" / "workflows" / "daily_lp.yml")
                        .read_text(encoding="utf-8"))
    steps = {s.get("name"): s for s in wf["jobs"]["update-lp"]["steps"]}
    assert steps["Notify workflow result"].get("if") == "always()"
    assert steps["Prelaunch check"].get("if") == "always()"
    # 公開（commit / push）は失敗時に行わない（fail-closed を維持）
    assert "if" not in steps["Commit and push"]


# ── 過剰棄却の防止（キャンペーン語が近くにあっても販売告知は通す） ─────────
@pytest.mark.parametrize("block", [
    "ブースターパック 神の支配【OP-18】 発売日 2026年11月7日 価格 220円（税込） 発売記念キャンペーン実施中",
    "ONE PIECEカードゲーム プレミアムカードコレクション 予約受付開始 購入特典としてプロモカードをプレゼント",
    "ローソンにて拡張パック「X」の販売を開始します。購入特典としてオリジナルカードを配布",
    "拡張パック「X」 BOX 販売開始 ※お一人様1点限り。参加者多数",
])
def test_sale_notice_with_campaign_words_is_kept(block):
    from src.tcg.sales_context import is_sales_block
    assert is_sales_block(block) is True


@pytest.mark.parametrize("block", [
    "拡張パック「X」BOXの抽選販売を行います。抽選で当選された方のみご購入いただけます。",
    "抽選で当選した方には購入権をお送りします。拡張パックBOX 1箱",
])
def test_lottery_sale_with_winner_wording_is_kept(block):
    from src.tcg.sales_context import is_product_lottery
    assert is_product_lottery(block) is True


def test_campaign_only_block_is_rejected():
    from src.tcg.sales_context import is_campaign_only, is_non_sale_announcement
    b = "拡張パック「テスト」を購入すると、抽選でプロモカードが当たるキャンペーンを実施します。"
    assert is_campaign_only(b) is True
    assert is_non_sale_announcement(b) is True


def test_lawson_partial_store_condition_is_not_asserted():
    got = extract_store_conditions("BOX販売は、店舗によっては行っておりません")
    assert got["box_sale"] is None
