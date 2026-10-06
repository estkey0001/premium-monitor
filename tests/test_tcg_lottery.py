# -*- coding: utf-8 -*-
"""TCG LOTTERY INTELLIGENCE PHASE のテスト。

テスト用の文面は、実際に確認したゲオ / ポケモンセンターオンラインの告知の
構造に合わせたテストデータ（本番表示には使わない）。
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.rate_limiter import RateLimiter                       # noqa: E402
from src.collectors.robots_checker import RobotsChecker                   # noqa: E402
from src.collectors.tcg.lottery.base import LotteryAdapter                # noqa: E402
from src.collectors.tcg.lottery.geo import GeoLotteryAdapter              # noqa: E402
from src.collectors.tcg.lottery.others import SourceProbe                 # noqa: E402
from src.collectors.tcg.lottery.pokemon_official import PcoLotteryAdapter  # noqa: E402
from src.tcg.lottery import history as lhistory                            # noqa: E402
from src.tcg.lottery.manual import CSV_COLUMNS, load_manual_lotteries      # noqa: E402
from src.tcg.lottery.merge import merge_lotteries                          # noqa: E402
from src.tcg.lottery.parse import (                                        # noqa: E402
    extract_eligibility, extract_schedule, product_name_from_title,
)
from src.tcg.lottery.products import resolve_product                       # noqa: E402
from src.tcg.lottery.registry import (                                     # noqa: E402
    ST_NO_ACTIVE_LOTTERY, ST_SOURCE_BLOCKED, ST_SOURCE_NOT_MONITORED,
    ST_SOURCE_UNREACHABLE, coverage_summary, source_state,
)
from src.tcg.lottery.schema import (                                       # noqa: E402
    LotteryEvent, compute_lottery_status, countdown, sort_key,
)
from src.tcg.models import now_jst                                         # noqa: E402
from src.tcg.shrink import detect_shrink_status                            # noqa: E402


# ── 擬似ネットワーク ──────────────────────────────────────────────────────
class _Resp:
    def __init__(self, url, text="", status=200):
        self.url, self.text, self.status_code = url, text, status
        self.apparent_encoding = self.encoding = "utf-8"


@pytest.fixture
def fake_net(monkeypatch):
    routes: dict[str, tuple[int, str]] = {}

    def fake_get(url, *a, **k):
        for prefix, (status, body) in sorted(routes.items(), key=lambda kv: -len(kv[0])):
            if url.startswith(prefix):
                return _Resp(url, body, status)
        return _Resp(url, "not found", 404)

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(RateLimiter, "wait_if_needed", lambda self, url, min_interval_sec=60: None)
    monkeypatch.setattr(RobotsChecker, "robots_status", lambda self, url: "allowed")
    monkeypatch.setattr(RobotsChecker, "get_crawl_delay", lambda self, url: None)
    LotteryAdapter.clear_cache()
    yield routes
    LotteryAdapter.clear_cache()


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


def _md(dt):
    """「10/1(木) 17:59」形式（曜日つき・年なし）。"""
    w = "月火水木金土日"[dt.weekday()]
    return f"{dt.month}/{dt.day}({w}) {dt.hour:02d}:{dt.minute:02d}"


def _geo_news(items):
    body = "".join(f'<li><a href="/news/{n}">{d} {t}</a></li>' for n, d, t in items)
    return f"<html><body><ul>{body}</ul></body></html>"


def _geo_article(title, start, end, extra=""):
    return (f"<html><body><h1>{title}</h1><p>2026.09.18</p><p>{title}</p>"
            "<p>以下の商品につきましては抽選販売のみとさせていただきます。</p>"
            "<p>【対象商品】</p><p>・ポケモンカードゲーム MEGA 拡張パック「テスト」</p>"
            "<p>・ONE PIECEカードゲーム ブースターパック テスト戦士</p>"
            "<p>①Pontaカードをお持ちでゲオアプリと連携済のお客様</p>"
            "<p>②当選後ご購入時に、本人確認書類を提示していただけるお客様</p>"
            "<p>を応募条件としております。</p>"
            f"<p>{extra}</p>"
            f"<p>応募期間は「{_md(start)} ～ {_md(end)}」までとなります。</p>"
            '<p><a href="https://draw.geo-online.co.jp/lottery/">ゲオ抽選販売専用サイトはこちら</a></p>'
            "</body></html>")


# ══════════════════════════════════════════════════════════════════════════
# 採用 / 棄却（Task18 / Task19）
# ══════════════════════════════════════════════════════════════════════════
def test_valid_lottery_accepted(fake_net):
    now = now_jst()
    start, end = now - timedelta(days=1), now + timedelta(days=2)
    fake_net["https://geo-online.co.jp/news/"] = (200, _geo_news([
        (901, "2026/09/18", "「ポケモンカードゲーム」「ONE PIECEカードゲーム」抽選販売受付のお知らせ")]))
    fake_net["https://geo-online.co.jp/news/901"] = (200, _geo_article(
        "「ポケモンカードゲーム」「ONE PIECEカードゲーム」抽選販売受付のお知らせ", start, end))
    a = GeoLotteryAdapter()
    evs = a.collect()
    assert len(evs) == 2
    tcgs = sorted(e["tcg"] for e in evs)
    assert tcgs == ["ONE_PIECE", "POKEMON"]
    for e in evs:
        assert e["application_end"].startswith(_iso(end)[:16])
        assert e["entry_url"] == "https://draw.geo-online.co.jp/lottery/"
        assert e["source_type"] == "RETAILER_OFFICIAL" and e["confidence"] == "high"
    assert a.health["status"] == "HEALTHY"


def test_tournament_lottery_rejected():
    a = GeoLotteryAdapter()
    out = a.build_from_article(
        title="「チャンピオンズリーグ2027」事前抽選のエントリー受付",
        body="ポケモンカードゲームの大会の事前抽選です。応募期間 10/2(金) 12:00 ～ 10/5(月) 16:59",
        url="https://geo-online.co.jp/news/1", published_at="2026-09-18T00:00:00+09:00")
    assert out == []
    assert a.funnel.rejection_reasons.get("tournament_or_event") == 1


def test_giveaway_lottery_rejected():
    a = GeoLotteryAdapter()
    out = a.build_from_article(
        title="ポケモンカード購入者プレゼント",
        body="ポケモンカードゲームを購入すると、抽選でプロモカードが当たります。"
             "応募期間 10/2(金) 12:00 ～ 10/5(月) 16:59",
        url="https://geo-online.co.jp/news/2", published_at="2026-09-18T00:00:00+09:00")
    assert out == []
    assert set(a.funnel.rejection_reasons) & {"giveaway_lottery", "non_sale_announcement",
                                               "no_lottery_sale_context"}


def test_word_lottery_alone_is_not_enough():
    assert LotteryAdapter.is_lottery_sale("抽選を行います") is False


def test_purchase_right_lottery_accepted():
    a = GeoLotteryAdapter()
    out = a.build_from_article(
        title="ポケモンカードゲーム 拡張パック「テスト」BOX 購入権抽選のお知らせ",
        body="ポケモンカードゲーム 拡張パック「テスト」BOX の購入権抽選を行います。"
             "抽選で当選された方のみご購入いただけます。応募期間 10/2(金) 12:00 ～ 10/5(月) 16:59",
        url="https://geo-online.co.jp/news/3", published_at="2026-09-18T00:00:00+09:00")
    assert len(out) == 1
    assert out[0]["event_type"] == "PURCHASE_RIGHT"


def test_campaign_text_does_not_reject_valid_sale():
    a = GeoLotteryAdapter()
    out = a.build_from_article(
        title="ポケモンカードゲーム 拡張パック「テスト」抽選販売のお知らせ",
        body="ポケモンカードゲーム 拡張パック「テスト」の抽選販売を行います。"
             "同時に発売記念キャンペーンも実施中です（プレゼントあり）。"
             "応募期間 10/2(金) 12:00 ～ 10/5(月) 16:59",
        url="https://geo-online.co.jp/news/4", published_at="2026-09-18T00:00:00+09:00")
    assert len(out) == 1


# ══════════════════════════════════════════════════════════════════════════
# 状態（Task4 / Task5）
# ══════════════════════════════════════════════════════════════════════════
def _ev(**k):
    return {key: (_iso(v) if hasattr(v, "isoformat") else v) for key, v in k.items()}


def test_upcoming_lottery():
    n = now_jst()
    assert compute_lottery_status(_ev(application_start=n + timedelta(hours=17),
                                      application_end=n + timedelta(days=4))) == "UPCOMING"


def test_open_lottery():
    n = now_jst()
    assert compute_lottery_status(_ev(application_start=n - timedelta(days=1),
                                      application_end=n + timedelta(days=3))) == "OPEN"


def test_ending_soon_lottery():
    n = now_jst()
    assert compute_lottery_status(_ev(application_start=n - timedelta(days=1),
                                      application_end=n + timedelta(hours=5))) == "ENDING_SOON"


def test_closed_lottery():
    n = now_jst()
    assert compute_lottery_status(_ev(application_start=n - timedelta(days=3),
                                      application_end=n - timedelta(hours=1))) == "CLOSED"


def test_result_pending_and_winner_purchase_period():
    n = now_jst()
    base = dict(application_start=n - timedelta(days=10), application_end=n - timedelta(days=5),
                winner_announcement_at=n + timedelta(days=1),
                purchase_start=n + timedelta(days=1), purchase_end=n + timedelta(days=5))
    assert compute_lottery_status(_ev(**base)) == "RESULT_PENDING"
    base.update(winner_announcement_at=n - timedelta(days=1), purchase_start=n - timedelta(days=1))
    assert compute_lottery_status(_ev(**base)) == "WINNER_PURCHASE_PERIOD"
    base.update(purchase_end=n - timedelta(hours=1))
    assert compute_lottery_status(_ev(**base)) == "ENDED"


def test_unknown_when_no_dates_and_no_guessed_deadline():
    n = now_jst()
    assert compute_lottery_status({}) == "UNKNOWN"
    # 開始だけ分かっている抽選を、締切を推測して OPEN と言わない
    assert compute_lottery_status(_ev(application_start=n - timedelta(hours=2))) == "UNKNOWN"


def test_stale_open_lottery_never_shown_as_open():
    n = now_jst()
    st = compute_lottery_status(_ev(application_start=n - timedelta(days=60),
                                    application_end=n - timedelta(days=50)))
    assert st == "ENDED"


def test_countdown_labels():
    n = now_jst()
    assert countdown(_iso(n + timedelta(days=2, hours=5, minutes=1)), n)["label"] == "2日5時間"
    assert countdown(_iso(n + timedelta(hours=18, minutes=1)), n)["label"].startswith("18時間")
    assert countdown(_iso(n + timedelta(hours=2, seconds=30)), n)["label"] == "2時間"
    assert countdown(_iso(n - timedelta(minutes=1)), n) is None


def test_default_sorting():
    n = now_jst()
    a = _ev(status="OPEN", application_end=n + timedelta(days=3))
    b = _ev(status="OPEN", application_end=n + timedelta(days=1))
    c = _ev(status="UPCOMING", application_start=n + timedelta(days=2))
    d = _ev(status="UPCOMING", application_start=n + timedelta(hours=5))
    e = _ev(status="WINNER_PURCHASE_PERIOD", purchase_end=n + timedelta(days=1))
    out = sorted([a, c, e, b, d], key=sort_key)
    assert out[:2] == [b, a]          # 受付中は締切が近い順
    assert out[2:4] == [d, c]         # 開始前は開始が近い順
    assert out[4] == e


# ══════════════════════════════════════════════════════════════════════════
# 日程の抽出（年の補完・曜日検証・商品別の日程）
# ══════════════════════════════════════════════════════════════════════════
def test_yearless_dates_are_validated_by_weekday():
    got = extract_schedule("応募期間は「9/28(月) 11:00 ～ 10/1(木) 17:59」まで",
                           "2026-09-18T00:00:00+09:00")
    assert got["application_start"] == "2026-09-28T11:00:00+09:00"
    assert got["application_end"] == "2026-10-01T17:59:00+09:00"
    assert extract_schedule("応募期間 9/28(火) 11:00 ～ 10/1(木) 17:59",
                            "2026-09-18T00:00:00+09:00") == {}


def test_product_specific_schedule_lines():
    text = ("・抽選応募受付期間\n8月28日（金）12時00分～8月31日（月）16時59分\n・抽選結果発表日\n"
            "拡張パック「A」BOX：9月4日（金）13時00分以降\n「A プレミアムデッキセット」：9月4日（金）17時00分以降\n"
            "・注文および、支払い期間\n拡張パック「A」BOX：9月4日（金）13時00分～9月8日（火）16時59分\n"
            "「A プレミアムデッキセット」：9月4日（金）17時00分～9月8日（火）16時59分\n")
    box = extract_schedule(text, "2026-08-21T00:00:00+09:00", product_name="拡張パック「A」BOX")
    deck = extract_schedule(text, "2026-08-21T00:00:00+09:00",
                            product_name="ポケモンカードゲーム「A プレミアムデッキセット」")
    assert box["winner_announcement_at"] == "2026-09-04T13:00:00+09:00"
    assert deck["winner_announcement_at"] == "2026-09-04T17:00:00+09:00"
    assert deck["purchase_end"] == "2026-09-08T16:59:00+09:00"


def test_product_name_from_title():
    assert product_name_from_title(
        "10月16日(金)発売『ポケモンカードゲーム MEGA「X カードセット」（9種セット）』抽選販売受付のお知らせ"
    ) == "ポケモンカードゲーム MEGA「X カードセット」（9種セット）"


# ══════════════════════════════════════════════════════════════════════════
# 応募条件（Task9）
# ══════════════════════════════════════════════════════════════════════════
def test_eligibility_preserved_with_original_text():
    text = ("①Pontaカードをお持ちでゲオアプリと連携済のお客様\n"
            "②当選後ご購入時に、本人確認書類を提示していただけるお客様\nを応募条件としております。")
    got = extract_eligibility(text)
    assert got["membership_required"] is True
    assert got["app_required"] is True
    assert got["identity_verification_required"] is True
    assert "本人確認書類" in got["eligibility_text"]


def test_tiered_eligibility_is_not_simplified():
    text = ("■本人認証済み枠\nプレイヤーズクラブでの本人認証が「お済みの方」に当選資格があります。\n"
            "■本人未認証枠\nプレイヤーズクラブでの本人認証が「未対応の方」に当選資格があります。")
    got = extract_eligibility(text)
    # 未認証でも応募できる枠があるので「本人認証が必須」とは言わない
    assert got["identity_verification_required"] is None
    assert "応募枠が分かれています" in got["eligibility_text"]


def test_unstated_conditions_stay_unknown():
    got = extract_eligibility("拡張パックの抽選販売を行います。")
    assert all(got[k] is None for k in ("membership_required", "app_required",
                                        "identity_verification_required",
                                        "purchase_history_required"))


# ══════════════════════════════════════════════════════════════════════════
# 店舗別 / 全国（Task10 / Task11）・重複（Task22）・優先（Task23）・矛盾（Task24）
# ══════════════════════════════════════════════════════════════════════════
def _lot(**k):
    base = dict(tcg="POKEMON", product_name="拡張パック「X」BOX", retailer="TOYSRUS",
                source_type="RETAILER_OFFICIAL", source_url="https://www.toysrus.co.jp/a",
                application_start="2026-10-02T12:00:00+09:00",
                application_end="2026-10-05T16:59:00+09:00")
    base.update(k)
    return LotteryEvent(**base).to_dict()


def test_store_specific_lottery_separated():
    online = _lot(store_specific=False)
    osaka = _lot(store_specific=True, store_name="大阪店", prefecture="大阪府")
    out = merge_lotteries([online, osaka])
    assert len(out) == 2
    assert {e["store_specific"] for e in out} == {True, False}


def test_duplicate_lottery_merged_with_all_sources():
    a = _lot(source_url="https://www.toysrus.co.jp/news/1")
    b = _lot(source_url="https://www.toysrus.co.jp/item/2")
    out = merge_lotteries([a, b])
    assert len(out) == 1
    assert set(out[0]["source_urls"]) == {"https://www.toysrus.co.jp/news/1",
                                          "https://www.toysrus.co.jp/item/2"}


def test_source_conflict_detected():
    a = _lot(source_type="MANUFACTURER_OFFICIAL", source_url="https://www.pokemon-card.com/x")
    b = _lot(application_end="2026-10-06T16:59:00+09:00")
    out = merge_lotteries([a, b])
    assert len(out) == 1
    assert out[0]["conflict"] is True
    assert "application_end" in out[0]["conflict_fields"]
    assert out[0]["application_end"] is None          # どちらかを勝手に採用しない


def test_official_source_beats_community():
    official = _lot(source_type="RETAILER_OFFICIAL", winner_announcement_at=None)
    community = _lot(source_type="COMMUNITY", source_url="https://x.com/a",
                     application_end="2026-10-09T00:00:00+09:00",
                     winner_announcement_at="2026-10-10T00:00:00+09:00")
    out = merge_lotteries([community, official])
    assert len(out) == 1
    assert out[0]["source_type"] == "RETAILER_OFFICIAL"
    assert out[0]["application_end"] == "2026-10-05T16:59:00+09:00"   # 上書きされない
    assert out[0]["conflict"] is False      # コミュニティとの食い違いは公式の矛盾ではない


# ══════════════════════════════════════════════════════════════════════════
# 商品の紐付け（Task20 / Task21）
# ══════════════════════════════════════════════════════════════════════════
_REGISTRY = [
    {"product_id": "pokemon-a", "name": "拡張パック「30th CELEBRATION」"},
    {"product_id": "pokemon-b", "name": "「30th CELEBRATION カードセット ニャオハ」"},
    {"product_id": "pokemon-c", "name": "「30th CELEBRATION カードセット ヒバニー」"},
    {"product_id": "pokemon-d", "name": "拡張パック「ストームエメラルダ」"},
]


def test_product_resolution_exact():
    r = resolve_product("ポケモンカードゲーム MEGA 拡張パック「ストームエメラルダ」BOX", _REGISTRY)
    assert r["product_id"] == "pokemon-d" and r["product_match"] == "exact"


def test_ambiguous_product_is_not_linked():
    r = resolve_product("ポケモンカードゲーム MEGA「30th CELEBRATION カードセット」（9種セット）",
                        _REGISTRY)
    assert r["product_id"] is None and r["product_match"] == "ambiguous"


def test_unknown_product_does_not_cross_match():
    r = resolve_product("ポケモンカードゲーム MEGA 拡張パック「インフェルノX」BOX", _REGISTRY)
    assert r["product_id"] is None
    assert r["provisional_product"] is True


# ══════════════════════════════════════════════════════════════════════════
# 手動確認済み（Task13 / Task14）
# ══════════════════════════════════════════════════════════════════════════
def _write_manual(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            base = {c: "" for c in CSV_COLUMNS}
            base.update(r)
            w.writerow(base)


def test_manual_verified_expiry(tmp_path):
    n = now_jst()
    path = tmp_path / "m.csv"
    _write_manual(path, [{
        "tcg": "POKEMON", "product": "拡張パック「X」BOX", "retailer": "POKEMON_CENTER_ONLINE",
        "application_start": _iso(n - timedelta(days=10)),
        "application_end": _iso(n - timedelta(days=7)),
        "source_url": "https://www.pokemoncenter-online.com/news/?id=1",
        "verified_at": _iso(n - timedelta(days=12)), "verified_by": "tester",
        "eligibility": "会員", "notes": ""}])
    evs, errs = load_manual_lotteries(path)
    assert errs == [] and len(evs) == 1
    ev = evs[0]
    # 読み込んだ時刻で fresh 化しない（観測時刻は確認日時のまま）
    assert ev["observed_at"] == _iso(n - timedelta(days=12))
    assert compute_lottery_status(ev) not in ("OPEN", "ENDING_SOON", "UPCOMING")


def test_manual_non_official_source_is_not_official_verified(tmp_path):
    path = tmp_path / "m.csv"
    _write_manual(path, [{
        "tcg": "POKEMON", "product": "拡張パック「X」BOX", "retailer": "TOYSRUS",
        "application_start": "2026-10-02T12:00:00+09:00",
        "application_end": "2026-10-05T16:59:00+09:00",
        "source_url": "https://x.com/someone/status/1", "entry_url": "https://bit.ly/abc",
        "verified_at": "2026-10-01T10:00:00+09:00", "verified_by": "tester",
        "eligibility": "", "notes": ""}])
    ev = load_manual_lotteries(path)[0][0]
    assert ev["source_type"] == "MANUAL_VERIFIED"
    assert ev["verified"] is False
    assert ev["entry_url"] is None          # 公式以外の URL を応募ボタンにしない


def test_manual_rejects_inverted_period(tmp_path):
    path = tmp_path / "m.csv"
    _write_manual(path, [{
        "tcg": "POKEMON", "product": "X", "retailer": "GEO",
        "application_start": "2026-10-05T12:00:00+09:00",
        "application_end": "2026-10-02T12:00:00+09:00",
        "source_url": "https://geo-online.co.jp/news/1",
        "verified_at": "2026-10-01T10:00:00+09:00", "verified_by": "t",
        "eligibility": "", "notes": ""}])
    evs, errs = load_manual_lotteries(path)
    assert evs == [] and errs


def test_repository_manual_file_is_valid():
    """リポジトリに含める手動確認データ自体が検証を通ること。"""
    evs, errs = load_manual_lotteries()
    assert errs == []
    for ev in evs:
        assert ev["source_url"].startswith("https://")
        assert ev["verified_by"]


# ══════════════════════════════════════════════════════════════════════════
# PCO BLOCKED（Task12 / Task34）
# ══════════════════════════════════════════════════════════════════════════
def test_blocked_pco_does_not_fake_healthy(fake_net):
    fake_net["https://www.pokemon-card.com/info/"] = (200, (
        '<html><a class="List_item_inner" href="https://www.pokemoncenter-online.com/news/?id=1">'
        "その他 ポケモンセンターオンラインでの商品の抽選受け付けについて (外部リンク) 2026.9.29</a></html>"))
    fake_net["https://www.pokemoncenter-online.com/"] = (403, "Forbidden")
    a = PcoLotteryAdapter()
    evs = a.collect()
    assert evs == []
    # 公式ニュースで告知を確認した事実は残すが、日程は作らない
    assert a.announcements and a.announcements[0]["source_url"].startswith(
        "https://www.pokemoncenter-online.com/news/")
    assert a.health["blocked"] is True
    from src.tcg.lottery.registry import SOURCE_BY_ID
    state = source_state(SOURCE_BY_ID["POKEMON_CENTER_ONLINE"], a.health, active_lotteries=0)
    assert state == ST_SOURCE_BLOCKED


def test_no_events_vs_not_monitored_vs_blocked():
    src_impl = {"source_id": "A", "adapter": "geo_lottery"}
    src_none = {"source_id": "B", "adapter": None}
    assert source_state(src_impl, {"status": "OK_NO_EVENTS"}, 0) == ST_NO_ACTIVE_LOTTERY
    assert source_state(src_none, {}, 0) == ST_SOURCE_NOT_MONITORED
    assert source_state(src_none, {"blocked": True}, 0) == ST_SOURCE_BLOCKED
    assert source_state(src_impl, {"unreachable": True}, 0) == ST_SOURCE_UNREACHABLE
    cov = coverage_summary([
        {"adapter": "x", "state": ST_NO_ACTIVE_LOTTERY, "reachable": True},
        {"adapter": None, "state": ST_SOURCE_NOT_MONITORED, "reachable": True},
        {"adapter": None, "state": ST_SOURCE_BLOCKED, "reachable": False},
    ])
    assert cov["configured_sources"] == 3 and cov["implemented_collectors"] == 1
    assert cov["healthy_sources"] == 1 and cov["blocked_sources"] == 1
    assert cov["not_implemented_sources"] == 2


def test_probe_records_bot_challenge_as_blocked(fake_net):
    fake_net["https://www.amazon.co.jp/"] = (202, "")
    p = SourceProbe({"source_id": "AMAZON", "retailer": "Amazon",
                     "official_url": "https://www.amazon.co.jp/"})
    p.collect()
    assert p.health["blocked"] is True


# ══════════════════════════════════════════════════════════════════════════
# シュリンク（受け渡し状態と否定文）
# ══════════════════════════════════════════════════════════════════════════
def test_negated_shrink_is_not_sealed():
    text = ("レジにてシュリンク（外装ビニール）の開封、または封入テープのカットを行います。"
            "外箱（BOX）は店舗にて回収し、1BOX分のパックのみでのお渡しとなります。"
            "※そのままの状態（シュリンク付き・BOX入り）での販売は行いません。")
    assert detect_shrink_status(text) == "PACK_ONLY"
    assert detect_shrink_status("シュリンク付きでの販売は行いません") == "UNKNOWN"
    assert detect_shrink_status("シュリンク付き未開封") == "SEALED_SHRINK"


# ══════════════════════════════════════════════════════════════════════════
# 通知（Task8）・履歴（Task30 / Task31）
# ══════════════════════════════════════════════════════════════════════════
def test_notification_milestones_not_duplicated(tmp_path):
    n = now_jst()
    ev = _lot(application_start=_iso(n - timedelta(minutes=30)),
              application_end=_iso(n + timedelta(days=3)))
    ledger = tmp_path / "ledger.json"
    out1, led = lhistory.notification_candidates([ev], n, ledger_path=ledger)
    assert [o["milestone"] for o in out1] == ["lottery_open"]
    ledger.write_text(json.dumps(led), encoding="utf-8")
    out2, _ = lhistory.notification_candidates([ev], n, ledger_path=ledger)
    assert out2 == []                       # 同じ通知は二度出さない


def test_notifications_only_for_official(tmp_path):
    n = now_jst()
    ev = _lot(source_type="COMMUNITY", source_url="https://x.com/a",
              application_start=_iso(n - timedelta(minutes=10)),
              application_end=_iso(n + timedelta(days=3)))
    out, _ = lhistory.notification_candidates([ev], n, ledger_path=tmp_path / "l.json")
    assert out == []


def test_history_keeps_ended_lotteries(tmp_path):
    n = now_jst()
    path = tmp_path / "h.json"
    old = _lot(application_start=_iso(n - timedelta(days=40)),
               application_end=_iso(n - timedelta(days=37)))
    path.write_text(json.dumps({"items": [dict(old, first_seen_at=_iso(n - timedelta(days=41)))]}),
                    encoding="utf-8")
    hist = lhistory.update_history([], n, path=path)     # 今回は観測なし
    assert len(hist) == 1 and hist[0]["status"] == "ENDED"
    freq = lhistory.frequency_by_retailer(hist, n)
    assert freq["TOYSRUS"]["events_total"] == 1
    assert freq["TOYSRUS"]["average_application_window_hours"] is not None


def test_failed_pipeline_does_not_wipe_history(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cte_lot", PROJECT_ROOT / "scripts" / "collect_tcg_events.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
    (tmp_path / "lottery_history.json").write_text('{"items": [{"lottery_id": "keep"}]}',
                                                   encoding="utf-8")
    mod.build_exports([], [], [], [], mod.empty_lottery_payload("boom"))
    kept = json.loads((tmp_path / "lottery_history.json").read_text(encoding="utf-8"))
    assert kept["items"] == [{"lottery_id": "keep"}]


# ══════════════════════════════════════════════════════════════════════════
# LP（Task25-27）
# ══════════════════════════════════════════════════════════════════════════
# UI Phase 10 で旧UIの TCG セクション（_section_tcg）を削除した。LP の表示の検査は、新UIの抽選・予約のページと、
# 閲覧時の状態の判定（runtime.derive_runtime_state。ボタンを決める正本）で同じ意図を確かめる。

def _render(report, now=None):
    """新UIの抽選・予約のページ（HTML）。"""
    from src.content.ui import shell
    ctx = shell.ShellContext(tcg_report=report, opportunities={}, profit_routes={}, legacy_lotteries=[],
                             now=now or now_jst())
    root = shell.render_root(ctx)
    return root[root.index('data-nu-page="lottery"'):root.index('data-nu-page="restock"')]


def _state(ev, now=None):
    """抽選1件の閲覧時の状態（新UIのボタン・日時の文言）。"""
    from src.content.ui import runtime as rt
    return rt.derive_runtime_state(rt.tcg_vm(ev, 0), now or now_jst())


def test_lp_shows_lottery_first_and_only_official_entry_links():
    """応募ボタンは公式の応募ページだけ（コミュニティ発の情報・確かさの低い情報には出さない）。締切までの残りを出す。
    監視元のアクセス拒否（0件の理由）は運営者向けのページに出す。"""
    from src.content.ui import admin
    n = now_jst()
    lot = _lot(application_start=_iso(n - timedelta(days=1)), application_end=_iso(n + timedelta(days=2)),
               entry_url="https://draw.geo-online.co.jp/lottery/", confidence="high")
    lot["status"] = "OPEN"
    bad = _lot(product_name="拡張パック「Y」BOX", source_type="COMMUNITY", source_url="https://x.com/a",
               entry_url=None, application_start=_iso(n - timedelta(days=1)), application_end=_iso(n + timedelta(days=2)))
    bad["status"] = "OPEN"
    html = _render({"events": [], "lotteries": [lot, bad], "source_health": [], "lottery_sources": [],
                    "lottery_coverage": {"configured_sources": 17}}, n)
    assert html.count('data-nu-cta="apply"') == 1 and 'href="https://draw.geo-online.co.jp/lottery/"' in html
    ok, ng = _state(lot, n), _state(bad, n)
    assert ok["cta"]["kind"] == "apply" and ok["cd_text"].startswith("締切まで")
    assert ng["cta"] is None or ng["cta"]["kind"] != "apply"
    src = admin.build_lottery_sources({"lottery_sources": [{"retailer": "ポケモンセンターオンライン", "priority": "P0",
                                                           "state": "SOURCE_BLOCKED", "adapter": "pco"}]})
    assert "アクセス拒否" in src[0]["text"]


def test_lp_empty_lottery_state_is_explicit():
    """抽選が0件の日は、空の状態を言葉で出す（0件と黙らない）。監視できていない取得元の数は運営者向けに出す。"""
    from src.content.ui import admin
    html = _render({"events": [], "lotteries": [], "source_health": [], "lottery_sources": [],
                    "lottery_coverage": {"configured_sources": 17, "blocked_sources": 4}})
    assert "現在、このジャンルで受付中・予定中の抽選や予約はありません" in html
    v = {"lot_coverage": {"configured_sources": 17, "blocked_sources": 4}, "lot_sources": [], "shops": [], "tcg": [],
         "resale": [], "flea": [], "resale_collected": None, "collector_generated": None,
         "overview": {"warn": admin.collector_warn({}, set(), 5)}}
    assert "登録 17・" in admin._sources(v) and "アクセス拒否 4" in admin._sources(v)


def test_no_deadline_notification_after_deadline(tmp_path):
    n = now_jst()
    ev = _lot(application_start=_iso(n - timedelta(days=3)),
              application_end=_iso(n - timedelta(hours=1)))
    out, _ = lhistory.notification_candidates([ev], n, ledger_path=tmp_path / "l.json")
    assert out == []      # 締切後に「締切1時間前」等を出さない


def test_only_latest_deadline_notification_is_sent(tmp_path):
    n = now_jst()
    ev = _lot(application_start=_iso(n - timedelta(days=3)),
              application_end=_iso(n + timedelta(minutes=30)))
    out, led = lhistory.notification_candidates([ev], n, ledger_path=tmp_path / "l.json")
    assert [o["milestone"] for o in out] == ["deadline_1h"]
    assert sum(1 for k in led["sent"] if k.endswith(("deadline_24h", "deadline_6h"))) == 2


def test_product_resolution_ignores_brand_prefix_and_code():
    op = [{"product_id": "op-eb05",
           "name": "エクストラブースター ONE PIECE Heroines Edition vol.2【EB-05】"}]
    r = resolve_product("ONE PIECEカードゲーム エクストラブースター ONE PIECE Heroines Edition vol.2", op)
    assert r["product_id"] == "op-eb05"


def test_entry_button_only_while_applicable():
    """締切後は応募ボタンを出さず、公式の結果確認ページがあればそれを出す。"""
    n = now_jst()
    closed = _lot(application_start=_iso(n - timedelta(days=3)),
                  application_end=_iso(n - timedelta(hours=1)),
                  entry_url="https://draw.geo-online.co.jp/lottery/",
                  result_url="https://draw.geo-online.co.jp/lottery/")
    closed["status"] = "CLOSED"
    closed["confidence"] = "high"
    html = _render({"events": [], "lotteries": [closed], "source_health": [],
                    "lottery_sources": [], "lottery_coverage": {}}, n)
    assert 'data-nu-cta="apply"' not in html
    st_ = _state(closed, n)
    assert st_["cta"] is None or st_["cta"]["kind"] != "apply"
    # 当選発表を待つ間（結果の確認ページがあるとき）は「結果を確認」
    waiting = dict(closed, winner_announcement_at=_iso(n + timedelta(days=1)))
    got = _state(waiting, n)
    assert got["status"] == "RESULT_PENDING" and got["cta"]["kind"] == "result"
    assert got["cta"]["url"] == "https://draw.geo-online.co.jp/lottery/"


# ══════════════════════════════════════════════════════════════════════════
# レビュー指摘の回帰固定
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("title", [
    "ポケモンカードゲーム 対象商品購入で抽選でプロモカードプレゼントキャンペーン",
    "ジムバトル参加者募集 抽選",
    "購入特典 抽選でオリジナルグッズが当たる",
])
def test_pco_announcement_does_not_surface_campaign_or_tournament(fake_net, title):
    fake_net["https://www.pokemon-card.com/info/"] = (200, (
        '<html><a href="https://www.pokemoncenter-online.com/news/?id=9">'
        f"その他 {title} (外部リンク) 2026.9.29</a></html>"))
    fake_net["https://www.pokemoncenter-online.com/"] = (403, "Forbidden")
    a = PcoLotteryAdapter()
    a.collect()
    assert a.announcements == []           # 「抽選告知あり」として残さない


def test_pipeline_placeholder_screens_titles():
    from src.tcg.lottery.pipeline import _announcement_events
    n = now_jst()
    anns = [{"title": "抽選でプロモカードプレゼントキャンペーン", "tcg": "POKEMON",
             "source_url": "https://www.pokemoncenter-online.com/news/?id=1",
             "published_at": _iso(n - timedelta(days=1))},
            {"title": "ポケモンセンターオンラインでの商品の抽選受け付けについて", "tcg": "POKEMON",
             "source_url": "https://www.pokemoncenter-online.com/news/?id=2",
             "published_at": _iso(n - timedelta(days=1))}]
    out = _announcement_events(anns, set(), n)
    assert [o["source_url"] for o in out] == ["https://www.pokemoncenter-online.com/news/?id=2"]


def test_placeholder_url_matching_is_normalized():
    from src.tcg.lottery.pipeline import _announcement_events
    n = now_jst()
    anns = [{"title": "ポケモンセンターオンラインでの商品の抽選受け付けについて", "tcg": "POKEMON",
             "source_url": "https://WWW.pokemoncenter-online.com/news/?id=2#top",
             "published_at": _iso(n - timedelta(days=1))}]
    covered = {"https://www.pokemoncenter-online.com/news/?id=2"}
    assert _announcement_events(anns, covered, n) == []


def test_timeless_deadline_is_not_turned_into_midnight():
    got = extract_schedule("抽選応募受付期間\n10月1日（木）～10月5日（月）\n抽選結果発表日 10月8日",
                           "2026-09-20T00:00:00+09:00")
    assert "application_end" not in got and "winner_announcement_at" not in got
    assert got["application_end_date"] == "2026-10-05"
    assert got["winner_announcement_date"] == "2026-10-08"


def test_date_only_deadline_status_is_conservative():
    n = now_jst()
    start = (n - timedelta(days=3)).date().isoformat()
    assert compute_lottery_status({"application_start_date": start,
                                   "application_end_date": n.date().isoformat()}, n) == "ENDING_SOON"
    assert compute_lottery_status({"application_start_date": start,
                                   "application_end_date": (n - timedelta(days=1)).date().isoformat()},
                                  n) == "CLOSED"
    # 開始日当日（時刻未公表）は受付中と言わない
    assert compute_lottery_status({"application_start_date": n.date().isoformat(),
                                   "application_end_date": (n + timedelta(days=3)).date().isoformat()},
                                  n) == "UPCOMING"


def test_lp_shows_time_not_announced():
    n = now_jst()
    ev = _lot(application_start=None, application_end=None,
              application_start_date=(n - timedelta(days=1)).date().isoformat(),
              application_end_date=(n + timedelta(days=2)).date().isoformat())
    ev["status"] = "OPEN"
    st_ = _state(ev, n)
    # 日付だけの締切に時刻を作らない（00:00 と出さない）
    assert st_["status"] == "OPEN" and "時刻未公表" in st_["when"] and "00:00" not in st_["when"]
    html = _render({"events": [], "lotteries": [ev], "source_health": [], "lottery_sources": [],
                    "lottery_coverage": {}}, n)
    card = html[html.index("拡張パック「X」BOX"):]
    assert "00:00" not in card[:3000]


def test_eligibility_reads_lines_after_heading_not_before():
    got = extract_eligibility("店舗でのお渡しは別途ご案内します。\nゲオアプリでも告知します。\n"
                              "【応募条件】\n・ゲオ会員登録が完了していること\n"
                              "・過去に当店で購入実績があること\n【注意事項】\n・店頭受取のみ")
    assert got["membership_required"] is True
    assert got["purchase_history_required"] is True
    assert got["app_required"] is None and got["store_pickup_required"] is None
    assert "購入実績" in got["eligibility_text"] and "ゲオアプリでも" not in got["eligibility_text"]


def test_separate_rounds_are_not_merged_as_conflict():
    first = _lot(retailer="GEO", source_url="https://geo-online.co.jp/news/1",
                 application_start="2026-09-01T11:00:00+09:00",
                 application_end="2026-09-05T17:59:00+09:00")
    second = _lot(retailer="GEO", source_url="https://geo-online.co.jp/news/2",
                  application_start="2026-10-01T11:00:00+09:00",
                  application_end="2026-10-08T17:59:00+09:00")
    out = merge_lotteries([first, second])
    assert len(out) == 2
    assert not any(e["conflict"] for e in out)
    assert all(e["application_end"] for e in out)      # 日程が消えない


def test_status_check_uses_evaluation_time():
    """#760 は抽選を判定した時刻で整合を確認する（生成時刻とのずれで誤検知しない）。"""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import deploy_check
    n = now_jst()
    ev = _lot(application_start=_iso(n + timedelta(minutes=1)),
              application_end=_iso(n + timedelta(days=3)))
    ev["status"] = compute_lottery_status(ev, n)          # UPCOMING
    report = {"lotteries": [ev], "lottery_evaluated_at": _iso(n),
              "generated_at": _iso(n + timedelta(minutes=5)), "lottery_sources": []}
    r760 = [r for r in deploy_check._check_tcg_lottery(report)
            if r["check"] == "tcg_lottery_status_consistent"][0]
    assert r760["level"] == "ok"


def test_partial_name_match_is_not_exact():
    reg = [{"product_id": "p1", "name": "拡張パック「メガドリームex」"}]
    for name in ("「ex」", "拡張パック「メガドリーム」BOX"):
        r = resolve_product(name, reg)
        assert r["product_id"] is None and r["product_match"] == "partial"
    assert resolve_product("拡張パック「メガドリームex」BOX", reg)["product_match"] == "exact"


def test_ai_transcribed_manual_data_is_not_high_confidence(tmp_path):
    n = now_jst()
    path = tmp_path / "m.csv"
    _write_manual(path, [{
        "tcg": "POKEMON", "product": "拡張パック「X」BOX", "retailer": "POKEMON_CENTER_ONLINE",
        "application_start": _iso(n - timedelta(minutes=30)),
        "application_end": _iso(n + timedelta(days=3)),
        "source_url": "https://www.pokemoncenter-online.com/news/?id=1",
        "verified_at": _iso(n - timedelta(hours=1)), "verified_by": "claude-code（画像を転記）",
        "human_confirmed": "false", "eligibility": "", "notes": ""}])
    ev = load_manual_lotteries(path)[0][0]
    assert ev["confidence"] == "medium" and ev["verified"] is False
    out, _ = lhistory.notification_candidates([ev], n, ledger_path=tmp_path / "l.json")
    assert out == []                       # 人による確認待ちのデータは通知しない
    _write_manual(path, [{**{c: "" for c in CSV_COLUMNS},
                          "tcg": "POKEMON", "product": "拡張パック「X」BOX",
                          "retailer": "POKEMON_CENTER_ONLINE",
                          "application_start": _iso(n - timedelta(minutes=30)),
                          "application_end": _iso(n + timedelta(days=3)),
                          "source_url": "https://www.pokemoncenter-online.com/news/?id=1",
                          "verified_at": _iso(n - timedelta(hours=1)), "verified_by": "運用者",
                          "human_confirmed": "true"}])
    ev2 = load_manual_lotteries(path)[0][0]
    assert ev2["confidence"] == "high" and ev2["verified"] is True


def test_legacy_lottery_events_are_not_duplicated_in_stock_section():
    n = now_jst()
    legacy = {"tcg": "POKEMON", "product_name": "旧方式の抽選", "event_type": "LOTTERY",
              "status": "OPEN", "store": "X", "source_type": "OFFICIAL",
              "shrink_status": "UNKNOWN", "verification": "Confirmed"}
    preorder = {"tcg": "POKEMON", "product_name": "予約締切間近の商品", "event_type": "PREORDER",
                "status": "ENDING_SOON", "store": "X", "source_type": "OFFICIAL",
                "shrink_status": "UNKNOWN", "verification": "Confirmed",
                "sale_end": _iso(n + timedelta(hours=3))}
    from src.content.ui import runtime as rt
    report = {"events": [legacy, preorder], "lotteries": [], "source_health": [], "lottery_sources": [],
              "lottery_coverage": {}}
    # 抽選は lotteries からだけ作る（販売・入荷の events にある古い形の抽選を、抽選・予約に重ねて出さない）
    assert "旧方式の抽選" not in [v["t"] for v in rt.build_vms(report, [])]
    assert "旧方式の抽選" not in _render(report, n)


def test_negated_tape_cut_is_not_tape_cut():
    assert detect_shrink_status("テープのカットは行いません") == "UNKNOWN"


def test_year_with_weekday_is_range_checked():
    # 公開日 2026-12-20 の記事で「6/10(水)」→ 2026-06-10(水) は半年以上前なので採用しない
    got = extract_schedule("応募期間 6/10(水) 11:00 ～ 6/12(金) 17:59", "2026-12-20T00:00:00+09:00")
    assert "application_start" not in got or not got["application_start"].startswith("2026-06")


# ══════════════════════════════════════════════════════════════════════════
# 2回目のレビュー指摘の回帰固定
# ══════════════════════════════════════════════════════════════════════════
def test_date_only_start_with_same_day_deadline_is_not_upcoming_after_close():
    from datetime import datetime
    from src.tcg.models import JST
    after = datetime(2026, 10, 2, 19, 0, tzinfo=JST)
    ev = {"application_start_date": "2026-10-02", "application_end": "2026-10-02T18:00:00+09:00"}
    assert compute_lottery_status(ev, after) == "CLOSED"
    got = extract_schedule("応募期間：10月2日（金）～10月2日（金）18:00", "2026-09-20T00:00:00+09:00")
    assert compute_lottery_status(got, after) == "CLOSED"


def test_date_only_rounds_get_distinct_ids_and_history():
    a = _lot(application_start=None, application_end=None,
             application_start_date="2026-09-01", application_end_date="2026-09-05")
    b = _lot(application_start=None, application_end=None,
             application_start_date="2026-10-01", application_end_date="2026-10-08",
             source_url="https://www.toysrus.co.jp/b")
    out = merge_lotteries([a, b])
    assert len({e["lottery_id"] for e in out}) == 2
    import tempfile
    hist = lhistory.update_history(out, path=Path(tempfile.mkdtemp()) / "h.json")
    assert len(hist) == 2
    assert all(h.get("application_start_date") for h in hist)


def test_partial_period_event_joins_matching_round():
    a = _lot(application_start="2026-09-01T11:00:00+09:00",
             application_end="2026-09-05T17:59:00+09:00")
    b = _lot(application_start="2026-10-01T11:00:00+09:00",
             application_end="2026-10-08T17:59:00+09:00", source_url="https://www.toysrus.co.jp/b")
    x = _lot(application_start="2026-10-01T11:00:00+09:00", application_end=None,
             source_type="MANUFACTURER_OFFICIAL", source_url="https://www.pokemon-card.com/x")
    out = sorted(merge_lotteries([x, a, b]), key=lambda e: e["application_start"])
    assert len(out) == 2
    assert out[0]["application_end"] == "2026-09-05T17:59:00+09:00"   # 古い回の日程は消えない
    assert out[1]["application_end"] == "2026-10-08T17:59:00+09:00"   # 公式の空欄は公式から補う
    assert not any(e["conflict"] for e in out)


def test_community_never_fills_official_blanks():
    off = _lot(source_type="MANUFACTURER_OFFICIAL", source_url="https://www.pokemon-card.com/x",
               application_end=None)
    com = _lot(source_type="COMMUNITY", source_url="https://x.com/a",
               winner_announcement_at="2026-10-10T00:00:00+09:00", membership_required=True)
    out = merge_lotteries([off, com])
    assert out[0]["source_type"] == "MANUFACTURER_OFFICIAL"
    assert out[0]["winner_announcement_at"] is None
    assert out[0]["membership_required"] is None


@pytest.mark.parametrize("title", [
    "新商品の抽選販売（プレイヤーズクラブ本人認証）について",
    "ポケモンセンターアプリでの抽選販売について",
    "「XX」抽選販売のお知らせ（購入特典付き）",
    "「XX」抽選による販売のお知らせ",
])
def test_legit_pco_lottery_titles_are_not_over_rejected(title):
    a = LotteryAdapter()
    assert a.screen_announcement_title(title) is None
    assert a.screen_title(title) is None
    out = a.build_from_article(
        title=title, body="ポケモンカードゲーム 拡張パック「XX」BOX の抽選販売を行います。"
                          "抽選応募受付期間 10月2日（金）12時00分～10月5日（月）16時59分",
        url="https://www.pokemoncenter-online.com/news/?id=1",
        published_at="2026-09-29T00:00:00+09:00", tcg_hint="POKEMON")
    assert len(out) == 1


def test_legit_pco_title_with_app_word_reaches_detail_fetch(fake_net):
    fake_net["https://www.pokemon-card.com/info/"] = (200, (
        '<html><a href="https://www.pokemoncenter-online.com/news/?id=7">'
        "その他 ポケモンセンターアプリでの抽選販売について (外部リンク) 2026.9.29</a></html>"))
    fake_net["https://www.pokemoncenter-online.com/news/"] = (200, (
        "<html><body>トップページ\n<p>ポケモンセンターアプリでの抽選販売について</p>"
        "<p>2026年09月29日（火）</p><p>【抽選販売を実施する商品】</p>"
        "<p>・ポケモンカードゲーム 拡張パック「XX」BOX</p>"
        "<p>・抽選応募受付期間</p><p>10月2日（金）12時00分～10月5日（月）16時59分</p></body></html>"))
    a = PcoLotteryAdapter()
    evs = a.collect()
    assert len(evs) == 1 and evs[0]["application_end"] == "2026-10-05T16:59:00+09:00"


def test_legacy_tcg_lottery_events_are_integrated():
    from src.tcg.lottery.pipeline import from_tcg_events
    legacy = [{"tcg": "POKEMON", "product_name": "拡張パック「Z」BOX", "event_type": "LOTTERY",
               "store": "YODOBASHI", "source_type": "RETAILER_OFFICIAL",
               "source_url": "https://www.yodobashi.com/x", "confidence": "high",
               "application_start": "2026-10-02T12:00:00+09:00",
               "application_end": "2026-10-05T16:59:00+09:00", "price": 360},
              {"tcg": "POKEMON", "product_name": "通常販売", "event_type": "GENERAL_SALE"}]
    out = from_tcg_events(legacy)
    assert len(out) == 1
    ev = out[0]
    assert ev["source_type"] == "RETAILER_OFFICIAL"
    assert ev["retail_price"] is None             # ページ記載の金額を定価にしない
    assert ev["collection_method"] == "LEGACY_TCG_EVENT"


def test_bare_eligibility_heading_reads_following_lines():
    got = extract_eligibility("応募条件\nゲオ会員の方\n購入実績がある方\n【注意】\n・その他")
    assert got["membership_required"] is True and got["purchase_history_required"] is True
    assert "購入実績" in got["eligibility_text"]


def test_placeholder_rejections_are_counted():
    from src.tcg.lottery.pipeline import _announcement_events
    n = now_jst()
    rej: dict = {}
    _announcement_events([{"title": "抽選でプロモカードプレゼントキャンペーン", "tcg": "POKEMON",
                           "source_url": "https://www.pokemoncenter-online.com/news/?id=1",
                           "published_at": _iso(n)}], set(), n, rej)
    assert sum(rej.values()) == 1


def test_unconfirmed_transcription_is_not_official_source(tmp_path):
    n = now_jst()
    path = tmp_path / "m.csv"
    _write_manual(path, [{
        "tcg": "POKEMON", "product": "拡張パック「X」BOX", "retailer": "POKEMON_CENTER_ONLINE",
        "application_start": "2026-10-02T12:00:00+09:00",
        "application_end": "2026-10-05T16:59:00+09:00",
        "source_url": "https://www.pokemoncenter-online.com/news/?id=1",
        "entry_url": "https://www.pokemoncenter-online.com/lottery/",
        "verified_at": _iso(n), "verified_by": "claude-code", "human_confirmed": "false",
        "eligibility": "", "notes": ""}])
    ev = load_manual_lotteries(path)[0][0]
    assert ev["source_type"] == "MANUAL_VERIFIED"
    assert ev["confidence"] == "medium"
    # 公式の自動取得データと矛盾判定しない（公式扱いでないので日程を消さない）
    auto = _lot(retailer="POKEMON_CENTER_ONLINE", source_type="MANUFACTURER_OFFICIAL",
                source_url="https://www.pokemoncenter-online.com/news/?id=1",
                application_end="2026-10-06T16:59:00+09:00")
    out = merge_lotteries([ev, auto])
    assert len(out) == 1 and out[0]["conflict"] is False
    assert out[0]["application_end"] == "2026-10-06T16:59:00+09:00"


def test_deploy_check_759_logic_and_767_output_are_split():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import deploy_check
    bad = _lot(product_name="ジムバトル参加者向け 拡張パック")
    res = {r["check"]: r for r in deploy_check._check_tcg_lottery(
        {"lotteries": [bad], "lottery_sources": []})}
    assert res["tcg_no_tournament_or_giveaway_lottery"]["level"] == "ok"
    assert res["tcg_lottery_output_no_tournament_or_giveaway"]["level"] == "warning"


# ══════════════════════════════════════════════════════════════════════════
# 3回目のレビュー指摘の回帰固定
# ══════════════════════════════════════════════════════════════════════════
def test_legacy_midnight_deadline_becomes_date_only():
    from datetime import datetime
    from src.tcg.lottery.pipeline import from_tcg_events
    from src.tcg.models import JST
    leg = from_tcg_events([{
        "tcg": "POKEMON", "product_name": "拡張パック「X」BOX", "event_type": "LOTTERY",
        "store": "POKEMON_CARD_OFFICIAL", "source_type": "OFFICIAL",
        "source_url": "https://www.pokemon-card.com/info/1.html",
        "application_start": "2026-10-01T00:00:00+09:00",
        "application_end": "2026-10-05T00:00:00+09:00"}])[0]
    assert leg["application_end"] is None and leg["application_end_date"] == "2026-10-05"
    # 新パーサーの「日付のみ」と合流しても 00:00 を足さない
    new = LotteryEvent(tcg="POKEMON", product_name="拡張パック「X」BOX",
                       retailer="POKEMON_CARD_OFFICIAL", source_type="MANUFACTURER_OFFICIAL",
                       source_url="https://www.pokemon-card.com/info/1.html",
                       application_start_date="2026-10-01",
                       application_end_date="2026-10-05").to_dict()
    m = merge_lotteries([new, leg])[0]
    assert m["application_end"] is None
    assert compute_lottery_status(m, datetime(2026, 10, 5, 12, tzinfo=JST)) == "ENDING_SOON"


def test_date_only_base_is_not_filled_with_exact_time():
    a = _lot(source_type="MANUFACTURER_OFFICIAL", source_url="https://www.pokemon-card.com/a",
             application_start=None, application_end=None,
             application_start_date="2026-10-01", application_end_date="2026-10-05")
    b = _lot(source_type="RETAILER_OFFICIAL", source_url="https://www.toysrus.co.jp/b",
             application_start=None, application_end="2026-10-05T00:00:00+09:00",
             application_start_date="2026-10-01")
    m = merge_lotteries([a, b])[0]
    assert m["application_end"] is None and m["application_end_date"] == "2026-10-05"


def test_start_only_new_round_is_not_absorbed_into_single_old_round():
    old = _lot(retailer="GEO", source_url="https://geo-online.co.jp/news/1",
               application_start="2026-09-01T11:00:00+09:00",
               application_end="2026-09-05T17:59:00+09:00")
    new = _lot(retailer="GEO", source_url="https://geo-online.co.jp/news/2",
               application_start="2026-10-20T11:00:00+09:00", application_end=None)
    out = merge_lotteries([old, new])
    assert len(out) == 2
    assert not any(e["conflict"] for e in out)
    starts = sorted(e["application_start"] for e in out)
    assert starts == ["2026-09-01T11:00:00+09:00", "2026-10-20T11:00:00+09:00"]


def test_bare_heading_stops_at_schedule_label():
    got = extract_eligibility("応募条件\nゲオ会員の方\n抽選応募受付期間\n10月1日～10月5日\n"
                              "お受け取りは店頭でのお渡しのみ")
    assert "抽選応募受付期間" not in got["eligibility_text"]
    assert got["membership_required"] is True


# ══════════════════════════════════════════════════════════════════════════
# 4回目のレビュー指摘の回帰固定（片側だけの日程の合流と、食い違いの検出）
# ══════════════════════════════════════════════════════════════════════════
_FULL = dict(application_start="2026-10-01T10:00:00+09:00",
             application_end="2026-10-05T16:59:00+09:00",
             source_type="MANUFACTURER_OFFICIAL", source_url="https://www.pokemon-card.com/a")


@pytest.mark.parametrize("other,expect_n,expect_conflict", [
    (dict(application_start=None, application_end=None, application_end_date="2026-10-05"), 1, False),
    (dict(application_start=None, application_end="2026-10-05T17:00:00+09:00"), 1, True),
    (dict(application_start=None, application_end=None, application_end_date="2026-10-07"), 1, True),
    (dict(application_start=None, application_end=None, application_start_date="2026-10-01"), 1, False),
    (dict(application_start="2026-10-20T11:00:00+09:00", application_end=None), 2, False),
    (dict(application_start=None, application_end="2026-10-30T17:59:00+09:00"), 2, False),
])
def test_partial_schedules_merge_by_date(other, expect_n, expect_conflict):
    full = _lot(**_FULL)
    part = _lot(source_url="https://www.toysrus.co.jp/b", **other)
    out = merge_lotteries([full, part])
    assert len(out) == expect_n                         # 同じ抽選のカードを二重に出さない
    assert any(e["conflict"] for e in out) is expect_conflict   # 食い違いは要確認にする


# ── 5回目のレビュー指摘の回帰固定 ─────────────────────────────────────────
@pytest.mark.parametrize("other,expect_n,expect_conflict", [
    # 回の締切（16:59）より後に始まる回は別の回
    (dict(application_start="2026-10-05T18:00:00+09:00", application_end=None), 2, False),
    # 時刻付きで締切が別の日なら、3日以内でも別の回（追加抽選）
    (dict(application_start=None, application_end="2026-10-08T23:59:00+09:00"), 2, False),
])
def test_next_round_right_after_deadline_is_not_merged(other, expect_n, expect_conflict):
    out = merge_lotteries([_lot(**_FULL), _lot(source_url="https://www.toysrus.co.jp/b", **other)])
    assert len(out) == expect_n
    assert any(e["conflict"] for e in out) is expect_conflict


def test_conflicted_lottery_is_shown_as_needs_review():
    full = _lot(**_FULL)
    other = _lot(source_url="https://www.toysrus.co.jp/b", application_start=None,
                 application_end="2026-10-05T17:00:00+09:00")
    merged = merge_lotteries([full, other])
    assert merged[0]["conflict"] is True
    merged[0]["status"] = compute_lottery_status(merged[0])
    html = _render({"events": [], "lotteries": merged, "source_health": [],
                    "lottery_sources": [], "lottery_coverage": {}})
    assert "日程要確認" in html                         # 矛盾した抽選も消さない
    st_ = _state(merged[0])
    assert st_["status"] == "SOURCE_CONFLICT" and st_["when"] == "日程は公式情報でご確認ください"
    assert 'data-nu-cta="apply"' not in html and (st_["cta"] is None or st_["cta"]["kind"] != "apply")


def test_payment_link_text_is_not_a_payment_requirement():
    """ナビゲーションの「お支払い方法について」を支払条件として表示しない。"""
    got = extract_eligibility("お支払い方法について\nよくあるご質問\n"
                              "当選の場合の支払方法は、クレジットカード決済のみご利用いただけます。")
    assert got["payment_method_requirement"] == \
        "当選の場合の支払方法は、クレジットカード決済のみご利用いただけます。"
    assert extract_eligibility("お支払い方法について")["payment_method_requirement"] is None
