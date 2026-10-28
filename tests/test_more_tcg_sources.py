"""キッズリパブリック・福福トレカの抽選告知の取得器（Coverage Wave 3）。合成 HTML（tests/fixtures）で確かめる。通信はしない。"""
from __future__ import annotations

from pathlib import Path

import pytest
import requests

from src.collectors.rate_limiter import RateLimiter
from src.collectors.robots_checker import RobotsChecker
from src.collectors.tcg.lottery import fukufuku, kidsrepublic
from src.collectors.tcg.lottery.base import LotteryAdapter

FX = Path(__file__).parent / "fixtures"
KR_LIST = (FX / "kidsrepublic" / "list.html").read_text(encoding="utf-8")
KR_A = (FX / "kidsrepublic" / "detail_a.html").read_text(encoding="utf-8")
KR_B = (FX / "kidsrepublic" / "detail_b.html").read_text(encoding="utf-8")
FF_LIST = (FX / "fukufuku" / "list.html").read_text(encoding="utf-8")
FF_91 = (FX / "fukufuku" / "detail_91.html").read_text(encoding="utf-8")
FF_90 = (FX / "fukufuku" / "detail_90.html").read_text(encoding="utf-8")
KR = "https://www.kidsrepublic.jp"
FF = "https://pokemon.fukufukutoreka.com"


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
    routes, calls = {}, []

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


# ── キッズリパブリック ─────────────────────────────────────────────────────────────────

def test_kr_parse_listing_reads_cards_and_requires_date_and_title():
    cards = kidsrepublic.parse_listing(KR_LIST)
    assert [c["url"].rsplit("/", 1)[1] for c in cards] == ["20261031_testcard", "20261031onepiece", "20261031_other", "202609_event"]
    assert cards[0]["published_at"].startswith("2026-10-09") and "ポケモンカード" in cards[0]["title"]
    assert kidsrepublic.parse_listing("<html>構造が変わった</html>") == []


def test_kr_detail_reads_main_only():
    d = kidsrepublic.parse_detail(KR_A)
    assert "■応募受付期間 10月9日" in d["body"] and "12月1日" not in d["body"] and "1月1日" not in d["body"]    # script・header の日程を読まない
    assert kidsrepublic.parse_detail("<html><body>本文なし</body></html>")["body"] == ""


def test_kr_collect_builds_app_lottery_events_with_year_from_publish_date_and_no_entry_url(net):
    routes, calls = net
    routes[KR + "/campaign"] = (200, KR_LIST)
    routes[KR + "/campaign/campaign_detail/20261031_testcard"] = (200, KR_A)
    routes[KR + "/campaign/campaign_detail/20261031onepiece"] = (200, KR_B)
    a = kidsrepublic.KidsRepublicLotteryAdapter()
    evs = a.collect()
    assert a.health["last_success"] and len(evs) == 2
    e = next(x for x in evs if x["tcg"] == "POKEMON")
    assert e["application_start"].startswith("2026-10-09T11:00") and e["application_end"].startswith("2026-10-15T19:59")   # 年は公開日の年
    assert e["purchase_start_date"] == "2026-10-31" and e["purchase_end_date"] == "2026-11-04"
    assert e["entry_url"] is None and e["store_specific"] is False and e["source_type"] == "RETAILER_OFFICIAL" and e["retail_price"] is None
    assert not [u for u in calls if "20261031_other" in u or "202609_event" in u]                # ポケカ・ONE PIECE 以外の告知の詳細は取らない
    assert a.health["detail_candidates"] == 2 and a.health["detail_fetched"] == 2 and a.health["skipped_due_to_limit"] == 0


def test_kr_blocked_listing_and_blocked_detail_stop_fetching(net):
    routes, calls = net
    routes[KR + "/campaign"] = (403, "forbidden")
    a = kidsrepublic.KidsRepublicLotteryAdapter()
    assert a.collect() == [] and a.health["blocked"] is True and not [u for u in calls if "campaign_detail" in u]
    routes[KR + "/campaign"] = (200, KR_LIST)
    routes[KR + "/campaign/campaign_detail/"] = (429, "slow down")
    LotteryAdapter.clear_cache()
    calls.clear()
    b = kidsrepublic.KidsRepublicLotteryAdapter()
    b.collect()
    assert b.health["blocked"] is True and len([u for u in calls if "campaign_detail" in u]) == 1   # 最初の詳細が 429 → 残りは取らない


def test_kr_structure_change_is_degraded_not_healthy(net):
    routes, _ = net
    routes[KR + "/campaign"] = (200, "<html><body>構造が変わった</body></html>")
    a = kidsrepublic.KidsRepublicLotteryAdapter()
    assert a.collect() == [] and a.health["status"] == "DEGRADED" and a.funnel.structure_changed_pages >= 1
    routes[KR + "/campaign"] = (200, KR_LIST)
    routes[KR + "/campaign/campaign_detail/"] = (200, "<html><body><aside>応募受付期間 12月1日 ～ 12月2日</aside></body></html>")
    LotteryAdapter.clear_cache()
    b = kidsrepublic.KidsRepublicLotteryAdapter()
    evs = b.collect()
    assert evs == [] and b.funnel.structure_changed_pages >= 1                                   # main が無いページの日程を読まない


def test_kr_truncation_metrics(net):
    routes, _ = net
    routes[KR + "/campaign"] = (200, KR_LIST)
    a = kidsrepublic.KidsRepublicLotteryAdapter()
    a.max_detail_fetch = 1
    a.collect()
    assert a.health["detail_candidates"] == 2 and a.health["detail_fetched"] == 1 and a.health["skipped_due_to_limit"] == 1 and a.health["truncated"] is True


# ── 福福トレカ ─────────────────────────────────────────────────────────────────────────

def test_ff_parse_listing_reads_cards_with_years_and_state():
    cards = fukufuku.parse_listing(FF_LIST)
    assert [(c["url"].rsplit("/", 1)[1], c["active"], c["end_ymd"]) for c in cards] == [
        ("91", True, (2026, 10, 29)), ("90", False, (2026, 10, 14)), ("89", False, (2026, 10, 1))]
    assert fukufuku.parse_listing("<html>構造が変わった</html>") == []


def test_ff_schedule_text_completes_the_year_from_the_list_and_refuses_mismatches():
    card = fukufuku.parse_listing(FF_LIST)[0]
    t = fukufuku._text(FF_91)
    assert fukufuku.schedule_text(card, t) == "応募期間：2026年10月23日 ～ 2026年10月29日 23:59 当選発表：2026年10月30日 購入期限：2026年11月1日まで"
    # 詳細の終了日が一覧の応募締切と違えば、応募期間を作らない（別の抽選・誤読）
    assert "応募期間" not in fukufuku.schedule_text(card, "応募期間 10.23 — 10.28 23:59")
    # 応募期間の欄から離れた別の購入期限（サイドバー・他の抽選）は拾わない
    assert "購入期限" not in fukufuku.schedule_text(card, "応募期間 10.23 — 10.29 23:59 " + "あ" * 300 + " 購入期限 当選発表後 12.31 23:59 迄")
    # 年またぎ（12.28 — 1.3）は開始を前の年にする
    ny = {"end_ymd": (2027, 1, 3), "draw_ymd": None}
    assert fukufuku.schedule_text(ny, "応募期間 12.28 — 1.3 23:59").startswith("応募期間：2026年12月28日 ～ 2027年1月3日")
    assert fukufuku.schedule_text(card, "日程なし") == "当選発表：2026年10月30日"                    # 読めた値だけ（作らない）


def test_ff_collect_builds_online_member_lottery_without_entry_url_and_skips_non_card_items(net):
    routes, calls = net
    routes[FF + "/lottery"] = (200, FF_LIST)
    routes[FF + "/lottery/91"] = (200, FF_91)
    routes[FF + "/lottery/90"] = (200, FF_90)
    a = fukufuku.FukufukuLotteryAdapter()
    evs = a.collect()
    assert len(evs) == 2 and not [u for u in calls if u.endswith("/lottery/89")]               # カード以外（雑貨）の詳細は取らない
    e = next(x for x in evs if x["application_end"].startswith("2026-10-29"))
    assert e["application_start_date"] == "2026-10-23" and e["winner_announcement_date"] == "2026-10-30"
    assert e["purchase_end_date"] == "2026-11-01" and not e.get("purchase_start_date") and not e.get("published_at")   # 期限は終了日・公開日を作らない
    assert e["entry_url"] is None and e["membership_required"] is True and e["purchase_history_required"] is True
    assert e["source_type"] == "RETAILER_OFFICIAL" and e["channel"] == "ONLINE" and e["retail_price"] is None


def test_ff_blocked_and_degraded_and_truncation(net):
    routes, calls = net
    routes[FF + "/lottery"] = (403, "forbidden")
    a = fukufuku.FukufukuLotteryAdapter()
    assert a.collect() == [] and a.health["blocked"] is True and not [u for u in calls if "/lottery/" in u]
    routes[FF + "/lottery"] = (200, "<html><body>構造が変わった</body></html>")
    LotteryAdapter.clear_cache()
    b = fukufuku.FukufukuLotteryAdapter()
    b.collect()
    assert b.health["status"] == "DEGRADED" and b.funnel.structure_changed_pages >= 1 and b.health["errors"] >= 1
    routes[FF + "/lottery"] = (200, FF_LIST)
    routes[FF + "/lottery/91"] = (200, FF_91)
    LotteryAdapter.clear_cache()
    c = fukufuku.FukufukuLotteryAdapter()
    c.max_detail_fetch = 0
    c.collect()
    assert c.health["skipped_due_to_limit"] == 1 and c.health["truncated"] is True and c.health["detail_fetched"] == 0


def test_new_sources_are_registered_with_adapters_and_no_secrets_or_fakes():
    from src.tcg.lottery.pipeline import _adapters
    from src.tcg.lottery.registry import LOTTERY_SOURCES
    for sid, ad in (("KIDS_REPUBLIC", "kids_republic_lottery"), ("FUKUFUKU_TOREKA", "fukufuku_lottery")):
        s = next(x for x in LOTTERY_SOURCES if x["source_id"] == sid)
        assert s["adapter"] == ad and ad in _adapters() and "robots.txt" in s["note"] and s["verified"] is True


def test_fixtures_are_synthetic():
    for f in list(FX.glob("kidsrepublic/*.html")) + list(FX.glob("fukufuku/*.html")):
        t = f.read_text(encoding="utf-8")
        assert "テスト" in t and "asset.kidsrepublic" not in t and "upload/save_image" not in t, f.name


def test_ff_blocked_detail_stops_remaining_details(net):
    routes, calls = net
    routes[FF + "/lottery"] = (200, FF_LIST)
    routes[FF + "/lottery/"] = (429, "slow down")
    a = fukufuku.FukufukuLotteryAdapter()
    a.collect()
    assert a.health["blocked"] is True and len([u for u in calls if "/lottery/" in u]) == 1       # 最初の詳細が 429 → 残りは取らない


def test_ff_card_frame_present_but_unreadable_is_degraded(net):
    routes, _ = net
    routes[FF + "/lottery"] = (200, FF_LIST.replace("<dt>応募締切</dt>", "<dt>締切</dt>"))
    a = fukufuku.FukufukuLotteryAdapter()
    assert a.collect() == [] and a.health["status"] == "DEGRADED" and a.funnel.structure_changed_pages >= 1


def test_ff_titles_of_other_card_games_or_non_card_items_are_not_candidates(net):
    routes, calls = net
    html = FF_LIST.replace("テスト雑貨 セール", "遊戯王 テスト1BOX 抽選販売")
    routes[FF + "/lottery"] = (200, html)
    routes[FF + "/lottery/91"] = (200, FF_91)
    routes[FF + "/lottery/90"] = (200, FF_90)
    a = fukufuku.FukufukuLotteryAdapter()
    a.collect()
    assert not [u for u in calls if u.endswith("/lottery/89")]                                    # 他のカードゲーム・雑貨はポケカとして取らない


# ── ONE PIECE 麦わらストア（Coverage Wave 4） ─────────────────────────────────────────────

from src.collectors.tcg.lottery import mugiwara  # noqa: E402

MG = "https://www.mugiwara-store.com"
MG_LIST = (FX / "mugiwara" / "list.html").read_text(encoding="utf-8")
MG_A = (FX / "mugiwara" / "detail_9003.html").read_text(encoding="utf-8")
MG_B = (FX / "mugiwara" / "detail_9001.html").read_text(encoding="utf-8")


def test_mg_parse_listing_picks_the_title_not_the_category():
    cards = mugiwara.parse_listing(MG_LIST)
    assert [c["post_id"] for c in cards] == ["9003", "9002", "9001", "9000"]
    assert cards[1]["title"] == "テストグッズ新発売" and "抽選" in cards[0]["title"]                # カテゴリ（グッズ）を件名にしない
    assert mugiwara.parse_listing("<html>構造が変わった</html>") == []


def test_mg_detail_reads_article_only_and_product_of_prefers_the_product_name():
    d = mugiwara.parse_detail(MG_A)
    assert "抽選受付期間 2026年10月23日" in d["body"] and "2027年1月1日" not in d["body"] and "2028年1月1日" not in d["body"]
    assert d["published_at"].startswith("2026-10-22")
    assert mugiwara.parse_detail("<html><body>本文なし</body></html>")["body"] == ""
    assert mugiwara.product_of("【抽選】ONE PIECE カードゲーム エクストラブースター「テスト商品 vol.1」 抽選販売のご案内") == "テスト商品 vol.1"
    assert mugiwara.product_of("件名に鍵括弧なし") == ""


def test_mg_collect_builds_events_with_year_dates_and_no_entry_url(net):
    routes, calls = net
    routes[MG + "/news/"] = (200, MG_LIST)
    routes[MG + "/news/9003/"] = (200, MG_A)
    routes[MG + "/news/9001/"] = (200, MG_B)
    a = mugiwara.MugiwaraStoreLotteryAdapter()
    evs = a.collect()
    assert len(evs) == 2 and a.health["last_success"]
    e = next(x for x in evs if "テスト商品" in (x.get("product_name") or ""))
    assert e["application_start"].startswith("2026-10-23T00:00") and e["application_end"].startswith("2026-10-25T23:59")
    assert e["purchase_start_date"] == "2026-10-31" and e["purchase_end_date"] == "2026-11-07"
    assert e["tcg"] == "ONE_PIECE" and e["entry_url"] is None and e["store_specific"] is False and e["retail_price"] is None
    assert e["source_type"] == "RETAILER_OFFICIAL"
    assert not [u for u in calls if "/9002/" in u or "/9000/" in u]                              # 抽選でない告知（グッズ・休業）の詳細は取らない


def test_mg_blocked_degraded_and_truncation(net):
    routes, calls = net
    routes[MG + "/news/"] = (403, "forbidden")
    a = mugiwara.MugiwaraStoreLotteryAdapter()
    assert a.collect() == [] and a.health["blocked"] is True and not [u for u in calls if "/news/9" in u]
    routes[MG + "/news/"] = (200, "<html><body>構造が変わった</body></html>")
    LotteryAdapter.clear_cache()
    b = mugiwara.MugiwaraStoreLotteryAdapter()
    b.collect()
    assert b.health["status"] == "DEGRADED" and b.funnel.structure_changed_pages >= 1
    routes[MG + "/news/"] = (200, MG_LIST)
    routes[MG + "/news/"] = (200, MG_LIST)
    routes[MG + "/news/9003/"] = (429, "slow")
    LotteryAdapter.clear_cache()
    calls.clear()
    c = mugiwara.MugiwaraStoreLotteryAdapter()
    c.collect()
    assert c.health["blocked"] is True and len([u for u in calls if "/news/90" in u]) == 1       # 最初の詳細が 429 → 残りは取らない
    routes[MG + "/news/9003/"] = (200, MG_A)
    routes[MG + "/news/9001/"] = (200, MG_B)
    LotteryAdapter.clear_cache()
    d = mugiwara.MugiwaraStoreLotteryAdapter()
    d.max_detail_fetch = 1
    d.collect()
    assert d.health["skipped_due_to_limit"] == 1 and d.health["truncated"] is True


def test_mg_article_missing_does_not_read_page_wide_dates(net):
    routes, _ = net
    routes[MG + "/news/"] = (200, MG_LIST)
    routes[MG + "/news/9003/"] = (200, "<html><body><aside>抽選受付期間 2026年12月1日～2026年12月2日</aside></body></html>")
    routes[MG + "/news/9001/"] = (404, "")
    a = mugiwara.MugiwaraStoreLotteryAdapter()
    evs = a.collect()
    assert not [e for e in evs if str(e.get("application_start") or "").startswith("2026-12")] and a.funnel.structure_changed_pages >= 1


def test_mg_registered_in_registry_and_pipeline():
    from src.tcg.lottery.pipeline import _adapters
    from src.tcg.lottery.registry import LOTTERY_SOURCES
    s = next(x for x in LOTTERY_SOURCES if x["source_id"] == "MUGIWARA_STORE")
    assert s["adapter"] == "mugiwara_store_lottery" and "mugiwara_store_lottery" in _adapters() and "robots.txt" in s["note"]
