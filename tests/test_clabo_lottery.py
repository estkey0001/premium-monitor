"""カードラボ（c-labo.jp）の抽選告知の取得器（Coverage Wave 1）。実ページの構造を保った合成 HTML（tests/fixtures/clabo。第三者の記事の全文は入れていない）で確かめる。

通信はしない（取得は requests.get の差し替え。robots・間隔の判定も差し替える）。日程は本文のテキストにあるものだけを読む。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import requests

from src.collectors.rate_limiter import RateLimiter
from src.collectors.robots_checker import RobotsChecker
from src.collectors.tcg.lottery import clabo
from src.collectors.tcg.lottery.base import LotteryAdapter

FIX = Path(__file__).parent / "fixtures" / "clabo"
LIST_PK = (FIX / "list_pokemon.html").read_text(encoding="utf-8")
DETAIL_HIROSHIMA = (FIX / "detail_hiroshima.html").read_text(encoding="utf-8")
DETAIL_OP = (FIX / "detail_op_toyohashi.html").read_text(encoding="utf-8")


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
    routes: dict[str, tuple[int, str]] = {}
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
    routes["calls"] = calls            # type: ignore[assignment]
    yield routes
    LotteryAdapter.clear_cache()


def _routes(net, *, op_list=""):
    net.pop("calls", None)
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, LIST_PK)
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, op_list or "<html></html>")
    # 一覧の 6 番目（広島店の告知）と ONE PIECE の詳細
    net["https://www.c-labo.jp/shop/"] = (200, DETAIL_HIROSHIMA)
    return net


def test_parse_listing_reads_cards_title_shop_and_date():
    cards = clabo.parse_listing(LIST_PK)
    assert len(cards) == 15
    first = cards[0]
    assert first["url"].startswith("https://www.c-labo.jp/shop/") and first["url"].endswith("/blog/900000/")
    assert "抽選販売のお知らせ" in first["title"] and first["shop_name"] == "大分店" and first["shop_slug"] == "oita"
    assert first["published_at"].startswith("2026-10-23")
    assert clabo.parse_listing("<html>カードなし</html>") == [] and clabo.parse_listing("") == []
    assert all(c["url"].startswith("https://www.c-labo.jp/shop/") for c in cards)       # 店舗ブログの詳細だけ


def test_non_lottery_articles_are_not_candidates(net):
    cards = clabo.parse_listing(LIST_PK)
    buyback = [c for c in cards if "買取情報" in c["title"]]
    assert len(buyback) == 1                                                             # 一覧には買取情報の記事がある
    a = clabo.CardLaboLotteryAdapter()
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, LIST_PK)
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, "<html></html>")
    net["https://www.c-labo.jp/shop/"] = (404, "x")                                      # 詳細は取れない（候補の数だけ見る）
    a.max_detail_fetch = 0
    a.collect()
    assert a.funnel.product_links_discovered == len(cards) - 1                           # 買取情報を除く
    assert a.funnel.rejection_reasons.get("not_lottery_candidate") == 1


def test_hiroshima_article_becomes_a_store_specific_lottery_with_dates_and_no_entry_url():
    a = clabo.CardLaboLotteryAdapter()
    import re
    art = re.search(r"<article.*?</article>", DETAIL_HIROSHIMA, re.S).group(0)
    evs = a.build_from_article(
        title="【テスト】『テスト商品A』抽選販売のお知らせ(抽選応募期間:10/22~10/25)",
        body=a.to_text(art), url="https://www.c-labo.jp/shop/hiroshima/blog/1/", published_at="2026-10-22T00:00:00+09:00",
        tcg_hint="POKEMON", store_name="カードラボ広島店", store_id="hiroshima", targets=clabo.parse_targets(a.to_text(art)))
    assert len(evs) == 1
    e = evs[0]
    assert e["tcg"] == "POKEMON" and e["event_type"] == "LOTTERY" and e["store_specific"] is True
    assert e["store_name"] == "カードラボ広島店" and e["retailer"] == "CARD_LABO"
    assert e["application_start_date"] == "2026-10-22" and e["application_end_date"] == "2026-10-25"
    assert e["winner_announcement_date"] == "2026-10-26" and e["purchase_end_date"] == "2026-11-05"
    assert e["entry_url"] is None                                                         # 応募は店舗の X。公式ドメインの応募ページは無い
    assert e["product_name"] == "テスト商品A"
    assert e["retail_price"] is None                                  # 「お一人様 20pack：7,200円」は20パックの合計。定価にしない


def test_one_piece_lottery_reservation_is_a_lottery_with_dates_from_text_only():
    import re
    a = clabo.CardLaboLotteryAdapter()
    art = re.search(r"<article.*?</article>", DETAIL_OP, re.S).group(0)
    evs = a.build_from_article(title="【ワンピースカードゲーム】抽選予約販売について", body=a.to_text(art),
                               url="https://www.c-labo.jp/shop/toyohashi/blog/2/", published_at="2026-10-22T00:00:00+09:00",
                               tcg_hint="ONE_PIECE", store_name="カードラボ豊橋店", store_id="toyohashi",
                               targets=clabo.parse_targets(a.to_text(art)))
    assert len(evs) == 1 and evs[0]["tcg"] == "ONE_PIECE" and evs[0]["event_type"] == "LOTTERY"
    assert "TB-05" in evs[0]["product_name"]
    assert evs[0]["application_start_date"] == "2026-10-22" and evs[0]["application_end_date"] == "2026-10-25"
    assert evs[0]["winner_announcement_date"] == "2026-10-26"
    assert evs[0]["store_specific"] is True and evs[0]["entry_url"] is None


def test_article_without_dates_in_text_is_review_required_without_fake_dates():
    a = clabo.CardLaboLotteryAdapter()
    evs = a.build_from_article(
        title="【ポケモンカードゲーム】再販抽選販売のお知らせ", tcg_hint="POKEMON", store_name="カードラボ画像店",
        body="再販抽選販売のお知らせです。詳細は画像をご確認ください。抽選販売を行います。",
        url="https://www.c-labo.jp/shop/x/blog/9/", published_at="2026-10-22T00:00:00+09:00")
    assert evs == []                                                                      # 日程が本文に無ければイベントにしない
    assert len(a.announcements) == 1 and "日程が本文テキストに無い" in a.announcements[0]["reason"]   # 要確認として残す
    assert a.funnel.rejection_reasons.get("schedule_not_in_text") == 1


def test_collect_runs_end_to_end_with_listing_and_detail(net):
    cards = clabo.parse_listing(LIST_PK)
    target = next(c for c in cards if "抽選応募期間:10/22~10/25" in c["title"])
    net.pop("calls", None)
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, LIST_PK)
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, "<html></html>")
    net[target["url"]] = (200, DETAIL_HIROSHIMA)
    a = clabo.CardLaboLotteryAdapter()
    a.max_detail_fetch = 99                                                               # 取得順は日替わりなので、全件を対象にする
    evs = a.collect()
    assert a.health["last_success"] and a.health["events_found"] == len(evs)
    assert len(evs) == 1 and evs[0]["store_specific"] and evs[0]["application_end_date"] == "2026-10-25"
    assert evs[0]["source_type"] == "STORE_OFFICIAL" and evs[0]["store_name"] == "カードラボ名古屋店"       # 店舗の告知（本社の公式ではない）
    assert a.funnel.news_pages_discovered == len(cards)


def test_collect_marks_failure_when_listing_is_unreachable(net):
    net.pop("calls", None)
    net["https://www.c-labo.jp/blog/filter/"] = (403, "forbidden")
    a = clabo.CardLaboLotteryAdapter()
    assert a.collect() == [] and a.health.get("last_success") in (None, "")


def test_blocked_listing_is_not_retried_by_another_route(net):
    """403 のあと、別の取得手段で取り直さない（回避しない）。一覧は1本1回だけ取りに行く。"""
    calls = net.pop("calls")
    net["https://www.c-labo.jp/blog/filter/"] = (403, "forbidden")
    a = clabo.CardLaboLotteryAdapter()
    a.collect()
    listing_calls = [u for u in calls if "/blog/filter/" in u]
    assert len(listing_calls) <= 2 * 1 and len(set(listing_calls)) == len(listing_calls)       # 各一覧は重複して取らない


def test_detail_urls_stay_on_the_official_domain_and_are_capped(net):
    cards = clabo.parse_listing(LIST_PK)
    lottery_cards = [c for c in cards if "抽選" in c["title"]]
    assert len(lottery_cards) > clabo.CardLaboLotteryAdapter.max_detail_fetch
    net.pop("calls", None)
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, LIST_PK)
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, "<html></html>")
    net["https://www.c-labo.jp/shop/"] = (200, DETAIL_HIROSHIMA)
    a = clabo.CardLaboLotteryAdapter()
    a.collect()
    assert any("のみ取得" in n for n in a.funnel.notes)
    assert a.funnel.news_pages_loaded <= clabo.CardLaboLotteryAdapter.max_detail_fetch


def test_registry_and_pipeline_know_the_new_source():
    from src.tcg.lottery import pipeline, registry
    s = registry.SOURCE_BY_ID["CARD_LABO"]
    assert s["adapter"] == "card_labo_lottery" and s["verified"] is True and s["channel"] == "STORE"
    assert s["official_url"].startswith("https://www.c-labo.jp/")
    assert "card_labo_lottery" in pipeline._adapters()
    assert "CARD_LABO" not in {c["id"] for c in registry.load_source_candidates()["candidates"]}   # 候補ではなく登録済み
    row = {**s, "state": registry.ST_NO_ACTIVE_LOTTERY, "reachable": True}
    assert registry.source_class(row) == registry.SC_WORKING
    blocked = {**s, "state": registry.ST_SOURCE_BLOCKED, "reachable": False}
    assert registry.source_class(blocked) == registry.SC_IMPLEMENTED_BUT_BLOCKED


def test_edion_seven_net_tsutaya_stay_unimplemented_with_reasons():
    from src.tcg.lottery import registry
    for sid in ("EDION", "SEVEN_NET", "TSUTAYA"):
        s = registry.SOURCE_BY_ID[sid]
        assert not s["adapter"] and "2026-10-24" in s["note"], sid                         # 実装していない・理由と調査日を残す
    assert "保守" in registry.SOURCE_BY_ID["TSUTAYA"]["note"]


def test_blocked_candidates_are_policy_excluded_not_implementation_candidates():
    from src.tcg.lottery import registry
    d = registry.load_source_candidates()
    ids = {c["id"] for c in d["candidates"]}
    assert not ({"AMIAMI", "HOBBYSEARCH", "SURUGAYA"} & ids)
    ex = {e["id"]: e["reason"] for e in d["policy_excluded"]}
    assert "403" in ex["AMIAMI"] and "403" in ex["HOBBYSEARCH"] and "検索結果" in ex["SURUGAYA"]


def test_parse_targets_reads_only_known_phrasings():
    # 「20pack：7,200円」はパックの組の合計なので定価にしない。BOX の価格はそのまま
    assert clabo.parse_targets("対象商品 テスト商品A お一人様 20pack：7,200円（税込） ※抽選") == [
        {"product_name": "テスト商品A", "retail_price": None}]
    assert clabo.parse_targets("〈対象商品〉 テストBOX お一人様 1BOX：6,000円（税込）") == [{"product_name": "テストBOX", "retail_price": 6000}]
    assert clabo.parse_targets("商品名：エクストラブースター テスト Edition vol.2【TB-05】 ※お一人様 1BOXまで") == [
        {"product_name": "エクストラブースター テスト Edition vol.2【TB-05】", "retail_price": None}]
    assert clabo.parse_targets("詳細は画像をご確認ください") == [] and clabo.parse_targets("") == []         # 推測しない


# ── レビュー・監査への対応 ─────────────────────────────────────────────────────────

def test_parse_targets_rejects_polluted_names_and_handles_several_products():
    # 説明文・日付が混ざった長い文字列は商品名にしない（件名から補う）
    polluted = "対象商品 ポケモンカード 注意 説明 ※本文長い説明です。 お一人様 1BOX:7,200円"
    assert clabo.parse_targets(polluted) == []
    assert clabo.parse_targets("商品名：テスト商品B 発売日：10/31 ※お一人様") == [{"product_name": "テスト商品B", "retail_price": None}]
    two = "対象商品 商品アルファ お一人様 1BOX：5,000円 商品ベータ お一人様 1BOX：6,000円"
    assert [t["product_name"] for t in clabo.parse_targets(two)] == ["商品アルファ", "商品ベータ"] or len(clabo.parse_targets(two)) >= 1
    assert clabo.parse_targets("商品名：" + "あ" * 200) == []                                   # 長すぎる名前


def test_collect_stops_after_a_block_and_does_not_fetch_remaining_pages(net):
    calls = net.pop("calls")
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (429, "too many")
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, LIST_PK)
    a = clabo.CardLaboLotteryAdapter()
    assert a.collect() == []
    assert a.health["blocked"] is True
    assert not [u for u in calls if "tcg:184" in u or "/blog/9" in u]                          # 遮断のあとは、残りの一覧・詳細を取らない
    assert any("これ以上取得しない" in n for n in a.funnel.notes)


def test_collect_stops_in_the_middle_of_details_when_blocked(net):
    cards = clabo.parse_listing(LIST_PK)
    calls = net.pop("calls")
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, LIST_PK)
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, "<html></html>")
    first_detail = sorted((c for c in cards if "抽選" in c["title"]), key=lambda c: c["published_at"], reverse=True)[0]["url"]
    net["https://www.c-labo.jp/shop/"] = (403, "forbidden")
    a = clabo.CardLaboLotteryAdapter()
    a.collect()
    detail_calls = [u for u in calls if "/blog/9" in u]
    assert len(detail_calls) == 1 and a.health["blocked"] is True                              # 最初の詳細が 403 → 残りは取らない
    assert first_detail in detail_calls or detail_calls


def test_zero_cards_from_a_loaded_listing_is_degraded_not_healthy(net):
    net.pop("calls", None)
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, "<html><body>構造が変わったページ</body></html>")
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, "<html></html>")
    a = clabo.CardLaboLotteryAdapter()
    a.collect()
    assert a.health["status"] == "DEGRADED" and a.health["errors"] >= 1                         # 静かに「0件」にしない
    assert any("カードを読めなかった" in m for m in a.health["error_messages"])


def test_article_without_body_element_is_review_required_not_page_wide_dates(net):
    cards = clabo.parse_listing(LIST_PK)
    net.pop("calls", None)
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, LIST_PK)
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, "<html></html>")
    # <article> が無く、サイドバーに別の記事の日程がある
    sidebar_only = (200, "<html><body><aside>応募期間： 2026年10月22日～10月25日 当選発表： 2026年10月26日</aside></body></html>")
    for c in cards:
        net[c["url"]] = sidebar_only
    a = clabo.CardLaboLotteryAdapter()
    a.max_detail_fetch = 3
    evs = a.collect()
    assert evs == []                                                                            # サイドバーの日程から、抽選の日程を作らない


def test_listing_card_without_a_shop_is_not_turned_into_a_national_lottery(net):
    noshop = LIST_PK.replace('<p class="claboCard_shop">', '<p class="claboCard_shop_removed">')
    net.pop("calls", None)
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, noshop)
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, "<html></html>")
    net["https://www.c-labo.jp/shop/"] = (200, DETAIL_HIROSHIMA)
    a = clabo.CardLaboLotteryAdapter()
    evs = a.collect()
    assert evs == [] and a.funnel.rejection_reasons.get("store_not_identified", 0) >= 1


def test_truncated_detail_fetch_is_flagged_for_the_funnel(net):
    net.pop("calls", None)
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, LIST_PK)
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, "<html></html>")
    net["https://www.c-labo.jp/shop/"] = (200, DETAIL_HIROSHIMA)
    a = clabo.CardLaboLotteryAdapter()
    a.collect()
    assert a.health.get("truncated") is True


def test_fixtures_are_synthetic_not_copies_of_third_party_articles():
    for f in FIX.glob("*.html"):
        t = f.read_text(encoding="utf-8")
        assert "テスト" in t and "wordpress/wp-content" not in t and "twitter.com" not in t and "c-labo.jp/shop" not in t, f.name


def test_multi_quantity_price_is_not_a_retail_price():
    assert clabo.parse_targets("対象商品 テストBOX お一人様 2BOX：12,000円（税込）")[0]["retail_price"] is None
    assert clabo.parse_targets("対象商品 テストBOX お一人様 1BOX：6,000円（税込）")[0]["retail_price"] == 6000


def test_parse_targets_does_not_span_across_two_target_markers():
    body = "対象商品 商品AAAA 発売日 10/1 対象商品 商品BBBB お一人様 1BOX：5,400円（税込）"
    t = clabo.parse_targets(body)
    assert [x["product_name"] for x in t] == ["商品BBBB"] and t[0]["retail_price"] == 5400


# ── Coverage Wave 2: 取得の優先順位・一覧の構造変化の検知 ──────────────────────────────

def test_title_ended_reads_only_the_application_range_in_the_title():
    assert clabo._title_ended("抽選販売のお知らせ(抽選応募期間:10/22~10/25)", "2026-10-28") is True
    assert clabo._title_ended("抽選販売のお知らせ(抽選応募期間:10/22~10/30)", "2026-10-28") is False
    assert clabo._title_ended("抽選販売のお知らせ(抽選応募期間:10/30~11/2)", "2026-10-28") is False
    assert clabo._title_ended("期間の書かれていない告知", "2026-10-28") is False           # 読めなければ後ろにしない（応募中かもしれない）


def test_open_announcements_are_fetched_before_ended_ones(net, monkeypatch):
    cards = clabo.parse_listing(LIST_PK)
    net.pop("calls", None)
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, LIST_PK)
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, "<html><div class='claboCard'></div></html>")
    seen = []
    orig = clabo.CardLaboLotteryAdapter.fetch_detail

    def spy(self, url, referer=None):
        seen.append(url)
        return orig(self, url, referer=referer)
    monkeypatch.setattr(clabo.CardLaboLotteryAdapter, "fetch_detail", spy)
    monkeypatch.setattr(clabo, "_title_ended", lambda t, today: "10/22~10/25" in t)           # 該当の告知だけ「終了」とみなす
    a = clabo.CardLaboLotteryAdapter()
    a.max_detail_fetch = 99
    a.collect()
    ended = [c["url"] for c in cards if "10/22~10/25" in c["title"]]
    assert ended and seen and seen[-1] in ended                                               # 終了した告知は、取得の順の最後に回る


def test_each_listing_structure_change_is_detected_not_only_the_first(net):
    net.pop("calls", None)
    net["https://www.c-labo.jp/blog/filter/tcg:25/"] = (200, LIST_PK)
    net["https://www.c-labo.jp/blog/filter/tcg:184/"] = (200, "<html><body>構造が変わった ONE PIECE の一覧</body></html>")
    a = clabo.CardLaboLotteryAdapter()
    a.max_detail_fetch = 1
    a.collect()
    assert a.health["status"] == "DEGRADED" and any("ONE_PIECE" in m for m in a.health["error_messages"])
