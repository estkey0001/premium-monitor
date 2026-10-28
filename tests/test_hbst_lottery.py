"""ホビーステーション（hbst.net）の抽選告知の取得器（Coverage Wave 2）。合成 HTML（tests/fixtures/hbst）で確かめる。

通信はしない（requests.get の差し替え。robots・間隔の判定も差し替える）。日程は本文のテキストにあるものだけを読む。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import requests

from src.collectors.rate_limiter import RateLimiter
from src.collectors.robots_checker import RobotsChecker
from src.collectors.tcg.lottery import hbst
from src.collectors.tcg.lottery.base import LotteryAdapter

FIX = Path(__file__).parent / "fixtures" / "hbst"
LIST = (FIX / "list_news.html").read_text(encoding="utf-8")
DETAIL_A = (FIX / "detail_a.html").read_text(encoding="utf-8")
DETAIL_B = (FIX / "detail_b.html").read_text(encoding="utf-8")
LIST_URL = "https://www.hbst.net/result/?category=news"


class _Resp:
    def __init__(self, url, text, status=200):
        self.url, self.text, self.status_code = url, text, status
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


@pytest.fixture
def net(monkeypatch):
    routes: dict = {}
    calls: list[str] = []

    def fake_get(url, *a, **k):
        calls.append(url)
        for prefix, (status, body) in sorted(routes.items(), key=lambda kv: -len(kv[0])):
            if url.startswith(prefix):
                return _Resp(url, body, status)
        return _Resp(url, "not found", 404)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(RateLimiter, "wait_if_needed", lambda self, url, min_interval_sec=60: None)
    monkeypatch.setattr(RobotsChecker, "robots_status", lambda self, url: "allowed")
    monkeypatch.setattr(RobotsChecker, "get_crawl_delay", lambda self, url: None)
    LotteryAdapter.clear_cache()
    yield routes, calls
    LotteryAdapter.clear_cache()


def _ok(routes):
    routes[LIST_URL] = (200, LIST)
    routes["https://www.hbst.net/?p=900001"] = (200, DETAIL_A)
    routes["https://www.hbst.net/?p=900002"] = (200, DETAIL_B)


def test_parse_listing_reads_cards_with_published_dates():
    cards = hbst.parse_listing(LIST)
    assert [c["post_id"] for c in cards] == ["900001", "900002", "900003", "900004"]
    assert cards[0]["published_at"].startswith("2026-10-20") and "抽選販売" in cards[0]["title"]
    assert hbst.parse_listing("<html>構造が変わった</html>") == []


def test_parse_detail_unescapes_numeric_references_and_ignores_the_sidebar():
    d = hbst.parse_detail(DETAIL_A)
    assert "■応募期間：2026年10月20日" in d["body"] and "応募方法" in d["body"]
    assert "2026年12月1日" not in d["body"]                      # <article> 相当の外（サイドバー）の日程は読まない
    assert d["title"].startswith("【2026.10.20】") and not d["title"].endswith("ホビーステーション")
    assert hbst.parse_detail("<html><body>本文なし</body></html>")["body"] == ""


def test_product_of_accepts_only_clean_names():
    assert hbst.product_of("【2026.10.20】抽選販売「ポケモンカードゲーム テスト拡張パック A（再販）」") == "ポケモンカードゲーム テスト拡張パック A（再販）"
    assert hbst.product_of("抽選販売「応募期間：10/20 注意」") == ""
    assert hbst.product_of("件名に鍵括弧なし") == ""


def test_collect_builds_events_from_text_dates_only_and_no_entry_url(net):
    routes, calls = net
    _ok(routes)
    a = hbst.HobbyStationLotteryAdapter()
    evs = a.collect()
    assert a.health["last_success"] and a.health["events_found"] == len(evs) and len(evs) == 2
    e = next(x for x in evs if x["tcg"] == "POKEMON")
    assert e["application_start"].startswith("2026-10-20T12:00") and e["application_end"].startswith("2026-10-22T23:59")
    assert e["purchase_start_date"] == "2026-11-02" and e["purchase_end_date"] == "2026-11-08"
    assert not e.get("result_date") and "2025" not in str(e.get("result_announcement"))        # 年が不自然な当選発表（誤記）は日程にしない
    assert e["entry_url"] is None and e["store_specific"] is False and e["source_type"] == "STORE_OFFICIAL"
    assert e["retail_price"] is None                                                        # 「各7,200円」を定価にしない
    assert not [u for u in calls if "p=900003" in u or "p=900004" in u]                      # 休業・カード以外の告知の詳細は取らない


def test_blocked_listing_stops_all_fetching(net):
    routes, calls = net
    routes[LIST_URL] = (403, "forbidden")
    a = hbst.HobbyStationLotteryAdapter()
    assert a.collect() == [] and a.health["blocked"] is True
    assert not [u for u in calls if "?p=" in u]


def test_blocked_detail_stops_remaining_details(net):
    routes, calls = net
    _ok(routes)
    routes["https://www.hbst.net/?p=900001"] = (429, "too many")
    a = hbst.HobbyStationLotteryAdapter()
    a.collect()
    assert a.health["blocked"] is True
    assert len([u for u in calls if "?p=90000" in u]) == 1                                  # 最初の詳細が 429 → 残りは取らない


def test_zero_cards_from_a_loaded_listing_is_degraded_not_healthy(net):
    routes, _ = net
    routes[LIST_URL] = (200, "<html><body>構造が変わったページ</body></html>")
    a = hbst.HobbyStationLotteryAdapter()
    assert a.collect() == []
    assert a.health["status"] == "DEGRADED" and any("カードを読めなかった" in m for m in a.health["error_messages"])


def test_article_without_body_does_not_read_page_wide_dates(net):
    routes, _ = net
    _ok(routes)
    routes["https://www.hbst.net/?p=900001"] = (200, "<html><head><title>【2026.10.20】抽選販売「ポケモンカードゲーム テスト拡張パック A」 - ホビーステーション</title></head>"
                                                      "<body><aside>応募期間：2026年12月1日～12月2日</aside></body></html>")
    routes["https://www.hbst.net/?p=900002"] = (404, "")
    evs = hbst.HobbyStationLotteryAdapter().collect()
    assert not [e for e in evs if str(e.get("application_start") or "").startswith("2026-12")]   # サイドバーの日程から作らない


def test_registered_in_the_source_registry_and_pipeline():
    from src.tcg.lottery.pipeline import _adapters
    from src.tcg.lottery.registry import LOTTERY_SOURCES
    s = next(x for x in LOTTERY_SOURCES if x["source_id"] == "HOBBY_STATION")
    assert s["adapter"] == "hobby_station_lottery" and "hobby_station_lottery" in _adapters()
    assert "robots.txt" in s["note"]


def test_fixtures_are_synthetic():
    for f in FIX.glob("*.html"):
        t = f.read_text(encoding="utf-8")
        assert "テスト" in t and "livepocket" not in t.lower() and "wp-content" not in t, f.name


def test_detail_without_article_marks_the_source_degraded(net):
    routes, _ = net
    _ok(routes)
    routes["https://www.hbst.net/?p=900001"] = (200, "<html><head><title>【2026.10.20】抽選販売「ポケモンカードゲーム テスト拡張パック A」 - ホビーステーション</title></head><body></body></html>")
    a = hbst.HobbyStationLotteryAdapter()
    a.collect()
    assert a.health["status"] == "DEGRADED" and a.funnel.structure_changed_pages >= 1
