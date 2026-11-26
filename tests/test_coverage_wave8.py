"""Coverage Wave 8: CARD BOX・ONE PIECE 公式ショップ・PLANT・トレカプラザ55 の抽選告知の取得器。

合成 HTML（tests/fixtures。実ページの構造を縮めたテスト用）で確かめる。通信はしない（requests.get・robots・間隔の待ちを差し替える）。
日程は本文にある値だけ。年の無い日付は掲載日・取得日から補い、曜日・前後関係が合わなければ日程にしない（推測で作らない）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from src.collectors.rate_limiter import RateLimiter
from src.collectors.robots_checker import RobotsChecker
from src.collectors.tcg.lottery import bnam_onepiece as bn
from src.collectors.tcg.lottery import cardbox, plant
from src.collectors.tcg.lottery import torecaplaza55 as tp
from src.collectors.tcg.lottery.base import LotteryAdapter
from src.tcg.lottery.schema import compute_lottery_status, lottery_id_of

JST = timezone(timedelta(hours=9))
FX = Path(__file__).parent / "fixtures"
CB_P1 = (FX / "cardbox" / "list_p1.html").read_text(encoding="utf-8")
CB_P2 = (FX / "cardbox" / "list_p2.html").read_text(encoding="utf-8")
CB_1794 = (FX / "cardbox" / "detail_1794.html").read_text(encoding="utf-8")
CB_1864 = (FX / "cardbox" / "detail_1864.html").read_text(encoding="utf-8")
CB_1700 = (FX / "cardbox" / "detail_1700.html").read_text(encoding="utf-8")
BN_TOP = (FX / "bnam_onepiece" / "top.html").read_text(encoding="utf-8")
BN_OP18 = (FX / "bnam_onepiece" / "detail_20261110.html").read_text(encoding="utf-8")
BN_EB99 = (FX / "bnam_onepiece" / "detail_20260920.html").read_text(encoding="utf-8")
PL_LIST = (FX / "plant" / "list.html").read_text(encoding="utf-8")
PL_1634 = (FX / "plant" / "detail_1634.html").read_text(encoding="utf-8")
PL_9001 = (FX / "plant" / "detail_9001.html").read_text(encoding="utf-8")
TP_BYTES = (FX / "torecaplaza55" / "top.html").read_bytes()
TP_TOP = TP_BYTES.decode("euc-jp")                   # requests が apparent_encoding（EUC-JP）で復号した後の文字列にあたる

CB = "https://cardbox.online"
BN = "https://bandainamco-am.co.jp/official_shop/onepiece-cardgame/"
PL = "https://www.plant-co.jp"
TP = "https://torecaplaza55.com/"


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
        if url in routes:                                         # 完全一致を優先（query の違う一覧のページを取り違えない）
            status, body = routes[url]
            return _Resp(url, body, status)
        for prefix, (status, body) in sorted(routes.items(), key=lambda kv: -len(kv[0])):
            if prefix.endswith("*") and url.startswith(prefix[:-1]):
                return _Resp(url, body, status)
        return _Resp(url, "not found", 404)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(RateLimiter, "wait_if_needed", lambda self, url, min_interval_sec=60: None)
    monkeypatch.setattr(RobotsChecker, "robots_status", lambda self, url: "allowed")
    monkeypatch.setattr(RobotsChecker, "get_crawl_delay", lambda self, url: None)
    LotteryAdapter.clear_cache()
    yield routes, calls
    LotteryAdapter.clear_cache()


# ── CARD BOX ─────────────────────────────────────────────────────────────────────────

def test_cb_parse_listing_reads_items_and_next_page():
    items = cardbox.parse_listing(CB_P1)
    assert [c["id"] for c in items] == [1867, 1864, 933, 1745, 1844, 1855, 1870, 1794]
    c = next(x for x in items if x["id"] == 1794)
    assert c["url"] == CB + "/news/detail/?id=1794" and c["taxonomy"] == "ポケモンカードゲーム" and c["shop"] == "北国書林辰口店"
    assert c["published_at"].startswith("2026-10-13")
    assert next(x for x in items if x["id"] == 1855)["taxonomy"] == ""            # ゲーム名の無い項目
    assert cardbox.next_page_url(CB_P1) == CB + "/news/shop_list/?&page=2"
    assert cardbox.parse_listing("<html>構造が変わった</html>") == [] and cardbox.next_page_url("<html></html>") is None


def test_cb_detail_reads_content_only_and_posted_time_and_shop():
    d = cardbox.parse_detail(CB_1794)
    assert d["published_at"] == "2026-10-13T19:39:00+09:00" and d["shop"] == "北国書林辰口店" and d["shop_id"] == "4277"
    assert "抽選受付期間 10月15日" in d["body"] and "1月1日" not in d["body"] and "2月1日" not in d["body"]   # script・フッターの日程を読まない
    assert "<" not in d["body"] and "example.invalid" not in d["body"]
    assert cardbox.parse_detail("<html><body>本文なし</body></html>")["body"] == ""
    assert "当選発表は" in cardbox.normalize_body(d["body"]) and "当選番号" not in cardbox.normalize_body(d["body"])


def test_cb_product_of_title():
    assert cardbox.product_of("再販商品のポケモンカードゲーム 「ポケモンMEGA 30th CELEBRATIONカードセット」の抽選購入につきまして") == "ポケモンMEGA 30th CELEBRATIONカードセット"
    assert cardbox.product_of("ポケモンカードゲーム再販商品各種の購入権抽選につきまして") == "ポケモンカードゲーム再販商品各種"
    assert cardbox.product_of("抽選につきまして") == ""


def _cb_routes(routes):
    routes[CB + "/news/shop_list/"] = (200, CB_P1)
    routes[CB + "/news/shop_list/?&page=2"] = (200, CB_P2)
    routes[CB + "/news/shop_list/?&page=3"] = (200, "<html>3ページ目は取らない</html>")
    routes[CB + "/news/detail/?id=1794"] = (200, CB_1794)
    routes[CB + "/news/detail/?id=1864"] = (200, CB_1864)
    routes[CB + "/news/detail/?id=1700"] = (200, CB_1700)


def test_cb_collect_builds_store_lotteries_with_year_from_posted_date(net):
    routes, calls = net
    _cb_routes(routes)
    a = cardbox.CardBoxLotteryAdapter()
    evs = a.collect()
    assert not any("page=3" in u for u in calls) and a.health["listing_pages"] == 2         # 一覧は 2 ページまで
    assert not any("id=1867" in u or "id=1844" in u or "id=933" in u or "id=1870" in u for u in calls)   # 当選者発表・買取・他のゲームは詳細を取らない
    assert a.funnel.rejection_reasons["result_announcement_only"] == 2
    assert len(evs) == 2
    e = next(x for x in evs if x["source_url"].endswith("id=1794"))
    assert e["retailer"] == "CARDBOX" and e["tcg"] == "POKEMON" and e["event_type"] == "PURCHASE_RIGHT"
    assert e["store_specific"] is True and e["store_name"] == "北国書林辰口店" and e["store_id"] == "4277" and e["channel"] == "STORE"
    assert e["application_start"] == "2026-10-15T00:00:00+09:00" and e["application_end"] == "2026-10-22T00:00:00+09:00"
    assert e["winner_announcement_at"] == "2026-10-24T10:00:00+09:00"                    # 「当選番号の発表は」
    assert e["entry_url"] is None and e["retail_price"] is None and e["source_type"] == "STORE_OFFICIAL"
    f = next(x for x in evs if x["source_url"].endswith("id=1864"))
    assert f["product_name"] == "ポケモンMEGA 30th CELEBRATIONカードセット" and f["event_type"] == "LOTTERY"
    assert f["application_start"] == "2026-11-23T10:00:00+09:00" and f["application_end"] == "2026-11-29T23:59:00+09:00"
    assert f["winner_announcement_at"] == "2026-12-01T12:00:00+09:00"
    # 曜日が日付と合わない告知（1700）は日程を作らず、要確認の告知として残す
    assert any(an["source_url"].endswith("id=1700") for an in a.announcements)
    assert a.health["detail_candidates"] == 3 and a.health["detail_fetched"] == 3 and not a.health.get("truncated")


def test_cb_detail_limit_and_block_stop(net):
    routes, calls = net
    _cb_routes(routes)
    a = cardbox.CardBoxLotteryAdapter()
    a.max_detail_fetch = 1
    a.collect()
    assert a.health["skipped_due_to_limit"] == 2 and a.health["truncated"] is True and a.health["detail_fetched"] == 1
    LotteryAdapter.clear_cache()
    calls.clear()
    routes[CB + "/news/shop_list/?&page=2"] = (429, "slow down")
    b = cardbox.CardBoxLotteryAdapter()
    b.collect()
    assert b.health["blocked"] is True and not any("/news/detail/" in u for u in calls)    # 遮断の後は取らない（回避しない）


def test_cb_structure_change_is_reported(net):
    routes, _ = net
    routes[CB + "/news/shop_list/"] = (200, "<html>構造が変わった</html>")
    a = cardbox.CardBoxLotteryAdapter()
    assert a.collect() == [] and a.funnel.structure_changed_pages == 1 and a.health["errors"] == 1


# ── ONE PIECE 公式ショップ ───────────────────────────────────────────────────────────

def test_bn_parse_listing_and_detail_table():
    items = bn.parse_listing(BN_TOP)
    assert len(items) == 6 and items[0]["url"] == BN + "news/important/20261110.html"
    assert items[0]["published_at"].startswith("2026-11-11") and items[0]["stores"] == ["全店"]
    assert items[-1]["url"].endswith("news/information/20230414.html")
    d = bn.parse_detail(BN_OP18)
    assert d["title"] == "『ブースターパック 神の支配【OP-18】』事前抽選について"
    assert d["rows"]["申込受付期間"] == "2026年11月11日(水) 10:00 ～ 15日(日) 23:59"
    assert "2026年1月1日" not in d["body"]                                                  # ヘッダーの日程を読まない
    assert bn.parse_detail("<html>本文なし</html>") == {"title": "", "body": "", "rows": {}}


def test_bn_read_period_fills_month_and_year_from_start_and_checks_weekday():
    p = bn.read_period("2026年11月11日(水) 10:00 ～ 15日(日) 23:59")
    assert p == {"start": (2026, 11, 11, 10, 0), "end": (2026, 11, 15, 23, 59)}
    assert bn.read_period("2026年9月28日(月) 10:00 ～ 2日(金) 23:59")["end"] == (2026, 10, 2, 23, 59)         # 日が小さい = 翌月
    assert bn.read_period("2026年12月30日(水) ～ 1月3日(日)")["end"] == (2027, 1, 3, None, None)             # 年をまたぐ
    assert bn.read_period("2026年11月11日(木) 10:00 ～ 15日(日) 23:59") is None                            # 曜日が合わない
    assert bn.read_period("2026年11月11日(水) 10:00 ～ 15日(月) 23:59") is None
    assert bn.read_period("2026年11月21日(土)～11月27日(金)")["end"] == (2026, 11, 27, None, None)
    assert bn.read_period("申込は店頭で") is None


def test_bn_collect_builds_official_shop_lottery_without_entry_url(net):
    routes, calls = net
    routes[BN] = (200, BN_TOP)
    routes[BN + "news/important/20261110.html"] = (200, BN_OP18)
    routes[BN + "news/important/20260920.html"] = (200, BN_EB99)
    a = bn.BnamOnePieceShopLotteryAdapter()
    evs = a.collect()
    assert not any("parks2" in u for u in calls)                                            # 応募先は取得しない
    assert not any("20260123" in u or "20261121" in u or "20260915" in u or "information" in u for u in calls)
    assert a.funnel.rejection_reasons["result_announcement_only"] == 1
    assert len(evs) == 2
    e = next(x for x in evs if x["source_url"].endswith("20261110.html"))
    assert e["retailer"] == "ONEPIECE_CARD_OFFICIAL_SHOP" and e["tcg"] == "ONE_PIECE" and e["event_type"] == "LOTTERY"
    assert e["product_name"] == "ブースターパック 神の支配【OP-18】" and e["product_code"] == "OP-18"
    assert e["application_start"] == "2026-11-11T10:00:00+09:00" and e["application_end"] == "2026-11-15T23:59:00+09:00"
    assert e["purchase_start_date"] == "2026-11-21" and e["purchase_end_date"] == "2026-11-27"   # 抽選販売日（時刻は作らない）
    assert e["entry_url"] is None and e["store_specific"] is False and e["source_type"] == "RETAILER_OFFICIAL"
    f = next(x for x in evs if x["source_url"].endswith("20260920.html"))
    assert f["store_specific"] is True and f["store_name"] == "ONE PIECEカードゲーム公式ショップ 東京新宿店"
    assert f["application_end"] == "2026-10-02T23:59:00+09:00"
    assert all(x.get("eligibility_text", "") == "" for x in evs)                          # サイトポリシー: 応募条件の原文は公開の出力に残さない


def test_bn_matches_expected_guards_against_other_labels():
    assert bn.matches_expected({"application_start": "a", "application_end": "b"}, {"application_start": "a", "application_end": "b"})
    assert not bn.matches_expected({"application_start": "x", "application_end": "b"}, {"application_start": "a", "application_end": "b"})
    assert not bn.matches_expected({"application_start": "2026-11-21", "application_end": "2026-11-27"}, {})   # 表から読めない日は採用しない


# ── PLANT ────────────────────────────────────────────────────────────────────────────

def test_pl_parse_listing_and_detail():
    items = plant.parse_listing(PL_LIST)
    assert [c["no"] for c in items] == [1616, 1634, 1630, 9001]
    assert items[1]["url"] == PL + "/campaign/detail/1634.html?campaignNo=1634&shopCode=0" and items[1]["published_at"].startswith("2026-11-12")
    d = plant.parse_detail(PL_1634)
    assert d["published_at"].startswith("2026-11-12") and d["products"] == ["ポケモンカードゲーム MEGA 拡張パック ハドウシーカー"]
    assert "古い文言" not in d["body"] and "1月5日" not in d["body"] and "2月1日" not in d["body"]   # コメント・ヘッダー・フッターを読まない
    assert plant.parse_detail("<html>本文なし</html>")["body"] == ""


def test_pl_deadline_rules():
    base = datetime(2026, 11, 12, tzinfo=JST)
    assert plant.deadline_of("応募締切： 11月19日（木）23：59まで", base) == ((2026, 11, 19, 23, 59), "ok")
    assert plant.deadline_of("【応募期間】 11月19日（木）まで", base) == ((2026, 11, 19, None, None), "ok")
    assert plant.deadline_of("【応募期間】 12月3日（木）まで 応募締切： 12月4日（金）23：59まで", base) == (None, "conflict")
    assert plant.deadline_of("応募締切： 11月19日（金）23：59まで", base) == (None, "unreadable")             # 曜日が合わない
    assert plant.deadline_of("応募締切： 11月1日（日）23：59まで", base) == (None, "unreadable")              # 公開日より前
    assert plant.deadline_of("【応募期間】 11月13日（金）～ 11月19日（木）", base)[1] == "range"
    assert plant.deadline_of("日程の記載なし", base) == (None, "missing")
    assert plant.resolve_deadline((None, "1", "8", "金", None, None), datetime(2026, 12, 20, tzinfo=JST)) == (2027, 1, 8, None, None)


def test_pl_as_deadline_only_moves_single_date_to_end_and_rejects_other_values():
    ev = {"tcg": "POKEMON", "product_name": "x", "retailer": "PLANT", "application_start": "2026-11-19T23:59:00+09:00"}
    out = plant.as_deadline_only(ev, "application_end", "2026-11-19T23:59:00+09:00")
    assert out["application_start"] is None and out["application_end"] == "2026-11-19T23:59:00+09:00"
    assert out["lottery_id"] == lottery_id_of(out)
    assert plant.as_deadline_only(ev, "application_end", "2026-11-20T23:59:00+09:00") is None
    assert plant.as_deadline_only({**ev, "application_end": "2026-11-30T00:00:00+09:00"}, "application_end", "2026-11-19T23:59:00+09:00") is None


def test_pl_collect_builds_deadline_only_lottery(net):
    routes, calls = net
    routes[PL + "/campaign.html"] = (200, PL_LIST)
    routes[PL + "/campaign/detail/1634.html?campaignNo=1634&shopCode=0"] = (200, PL_1634)
    routes[PL + "/campaign/detail/9001.html?campaignNo=9001&shopCode=0"] = (200, PL_9001)
    a = plant.PlantLotteryAdapter()
    evs = a.collect()
    assert not any("1616" in u or "1630" in u for u in calls)                                # 灯油・プレゼントのキャンペーンは取らない
    assert len(evs) == 1
    e = evs[0]
    assert e["retailer"] == "PLANT" and e["tcg"] == "POKEMON" and e["product_name"] == "ポケモンカードゲーム MEGA 拡張パック ハドウシーカー"
    assert e["application_start"] is None and e["application_start_date"] is None              # 開始日は作らない
    assert e["application_end"] == "2026-11-19T23:59:00+09:00"
    assert e["purchase_start"] == "2026-11-27T09:00:00+09:00" and e["purchase_end_date"] == "2026-11-30"
    assert e["retail_price"] is None and e["entry_url"] is None and e["store_specific"] is False
    assert e["lottery_id"] == lottery_id_of(e)
    assert compute_lottery_status(e, datetime(2026, 11, 15, 12, 0, tzinfo=JST)) == "OPEN"
    # 締切が2か所で食い違う告知（9001）は日程を作らず、要確認の告知として残す（ONE PIECE として）
    an = next(x for x in a.announcements if "9001" in x["source_url"])
    assert an["tcg"] == "ONE_PIECE"
    assert any("conflict" in n for n in a.funnel.notes)


# ── トレカプラザ55 ──────────────────────────────────────────────────────────────────

NOW = datetime(2026, 11, 26, 17, 0, tzinfo=JST)


def test_tp_parse_listing_reads_only_lottery_block():
    items = tp.parse_listing(TP_TOP)
    assert len(items) == 6 and all("シングル" not in i["title"] for i in items)          # シングルの取扱予定は読まない
    assert items[0] == {"day": "11.22", "deadline_label": "終日締切", "game": "ポケモンカードゲーム",
                        "title": "拡張パック「ハドウシーカー」抽選販売", "published": datetime(2026, 11, 18, 20, 0, tzinfo=JST)}
    assert tp.parse_listing("<html>枠が無い</html>") is None
    assert tp.parse_listing(TP_BYTES.decode("latin-1")) is None                              # 文字化け（復号の誤り）は構造の変更として扱う


def test_tp_resolve_deadline_year_rules():
    pub = datetime(2026, 11, 18, 20, tzinfo=JST)
    assert tp.resolve_deadline("11.22", "終日締切", NOW, pub) == (2026, 11, 22, None, None)
    assert tp.resolve_deadline("12.2", "18:00締切", NOW, pub) == (2026, 12, 2, 18, 0)
    assert tp.resolve_deadline("1.5", "終日締切", datetime(2026, 12, 28, tzinfo=JST), datetime(2026, 12, 20, tzinfo=JST)) == (2027, 1, 5, None, None)
    assert tp.resolve_deadline("12.28", "終日締切", datetime(2027, 1, 3, tzinfo=JST), datetime(2026, 12, 20, tzinfo=JST)) == (2026, 12, 28, None, None)
    assert tp.resolve_deadline("11.10", "終日締切", NOW, datetime(2026, 11, 20, tzinfo=JST)) is None   # 公開より前の締切 = 矛盾
    assert tp.resolve_deadline("5.10", "終日締切", NOW, None) is None                            # 取得日から半年を超える
    assert tp.resolve_deadline("11.22", "抽選中", NOW, pub) is None                              # 「締切」の語が無い
    assert tp.resolve_deadline("2.30", "終日締切", NOW, None) is None


def test_tp_collect_builds_deadline_only_events_and_excludes_other_games(net):
    routes, calls = net
    routes[TP] = (200, TP_TOP)
    a = tp.TorecaPlaza55LotteryAdapter()
    evs = a.collect(now=NOW)
    assert calls == [TP]                                                                    # トップ1ページだけ（応募先のフォームは取らない）
    assert a.funnel.rejection_reasons["not_lottery_candidate"] == 1                         # ユニオンアリーナ
    assert a.funnel.rejection_reasons["not_yet_public"] == 1                                # data-ts が取得より先
    assert len(evs) == 3
    by = {e["product_name"]: e for e in evs}
    h = by["拡張パック「ハドウシーカー」"]
    assert h["tcg"] == "POKEMON" and h["retailer"] == "TORECAPLAZA55" and h["application_end_date"] == "2026-11-22"
    assert h["application_start"] is None and h["application_start_date"] is None and h["application_end"] is None
    assert h["published_at"] == "2026-11-18T20:00:00+09:00" and h["entry_url"] is None and h["source_url"] == TP
    o = by["テスト商品【OP-96】"]
    assert o["tcg"] == "ONE_PIECE" and o["application_end"] == "2026-12-02T18:00:00+09:00" and o["product_code"] == "OP-96"
    assert by["セット商品 再入荷分/キャンセル分"]["application_end_date"] == "2026-11-30"
    assert len({e["lottery_id"] for e in evs}) == 3
    # 公開より前の締切は日程にしない（要確認の告知）
    assert any("公開より前" in an["title"] for an in a.announcements)
    assert compute_lottery_status(h, NOW) in ("CLOSED", "ENDED")


def test_tp_blocked_and_structure_change(net):
    routes, _ = net
    routes[TP] = (403, "forbidden")
    a = tp.TorecaPlaza55LotteryAdapter()
    assert a.collect(now=NOW) == [] and a.health["blocked"] is True
    LotteryAdapter.clear_cache()
    routes[TP] = (200, "<html>枠が無い</html>")
    b = tp.TorecaPlaza55LotteryAdapter()
    assert b.collect(now=NOW) == [] and b.funnel.structure_changed_pages == 1


# ── 共通 ─────────────────────────────────────────────────────────────────────────────

def test_fixtures_are_synthetic_and_have_no_personal_data_or_real_forms():
    files = [f for d in ("cardbox", "bnam_onepiece", "plant") for f in (FX / d).glob("*.html")]
    texts = [f.read_text(encoding="utf-8") for f in files] + [TP_TOP]
    for t in texts:
        assert "テスト" in t
        assert "電話番号" not in t and "生年月日" not in t and "forms.gle" not in t and "e-starbox" not in t
        assert "select-type.com" not in t and "ECCL" not in t


def test_adapters_follow_registry_source_ids():
    for cls, sid in ((cardbox.CardBoxLotteryAdapter, "CARDBOX"), (bn.BnamOnePieceShopLotteryAdapter, "ONEPIECE_CARD_OFFICIAL_SHOP"),
                     (plant.PlantLotteryAdapter, "PLANT"), (tp.TorecaPlaza55LotteryAdapter, "TORECAPLAZA55")):
        assert cls.source_id == sid and cls.retailer == sid                                  # pipeline は retailer == source_id で数える
        assert "robots.txt" in (__import__(cls.__module__, fromlist=["x"]).__doc__ or "")
