"""日程の解析と状態判定の回帰（年と曜日が両側にある期間・曜日の矛盾・年またぎ・日付だけの締切・購入期間・中止）。"""
from datetime import datetime

import pytest

from src.tcg.lottery.parse import detect_cancellation, extract_schedule
from src.tcg.lottery.schema import (
    L_ENDED, L_ENDING_SOON, L_OPEN, L_RESULT_PENDING, L_UNKNOWN, L_UPCOMING, L_WINNER_PURCHASE_PERIOD,
    compute_lottery_status,
)
from src.tcg.models import JST

PUB = "2026-11-20T00:00:00+09:00"


def at(*a):
    return datetime(*a, tzinfo=JST)


@pytest.mark.parametrize("text", [
    "応募期間：2026年11月21日（土）10:00～2026年11月23日（月）23:59",       # 2026-11-21 は土曜・11-23 は月曜（暦と一致）
    "応募期間：2026年11月21日(土)10:00～2026年11月23日(月・祝)23:59",
    "応募期間：2026/11/21(土) 10:00～2026/11/23(月) 23:59",
])
def test_period_with_year_and_weekday_on_both_sides(text):
    assert extract_schedule(text, PUB) == {"application_start": "2026-11-21T10:00:00+09:00",
                                           "application_end": "2026-11-23T23:59:00+09:00"}


def test_weekday_that_contradicts_the_calendar_gives_no_date():
    # 2026-11-21 は金曜ではない。どちらの年か・どちらの曜日が正しいかを推測しない
    assert extract_schedule("応募期間：2026年11月21日（金）10:00～2026年11月23日（日）23:59", PUB) == {}


def test_year_crossing_period_with_and_without_years():
    pub = "2026-12-20T00:00:00+09:00"
    full = extract_schedule("応募期間：2026年12月26日（土）10:00～2027年1月5日（火）23:59", pub)
    short = extract_schedule("応募期間：12月26日（土）10:00～1月5日（火）23:59", pub)
    assert full == short == {"application_start": "2026-12-26T10:00:00+09:00", "application_end": "2027-01-05T23:59:00+09:00"}
    assert compute_lottery_status(full, at(2027, 1, 2, 12)) == L_OPEN


def test_date_only_deadline_is_never_assumed_to_end_at_a_time():
    s = extract_schedule("応募期間：11月21日～11月28日", PUB)
    assert s == {"application_start_date": "2026-11-21", "application_end_date": "2026-11-28"}
    assert compute_lottery_status(s, at(2026, 11, 21, 12)) == L_UPCOMING     # 開始日当日は時刻が不明なので受付中と言わない
    assert compute_lottery_status(s, at(2026, 11, 22, 12)) == L_OPEN
    assert compute_lottery_status(s, at(2026, 11, 28, 23, 0)) == L_ENDING_SOON     # 締切日当日（時刻は推測しない）
    assert compute_lottery_status(s, at(2026, 11, 29, 0, 1)) not in (L_OPEN, L_ENDING_SOON)


def test_purchase_period_is_not_an_open_application():
    ev = {"application_start": "2026-11-21T10:00:00+09:00", "application_end": "2026-11-23T23:59:00+09:00",
          "winner_announcement_date": "2026-11-25", "purchase_start_date": "2026-11-26", "purchase_end_date": "2026-11-30"}
    assert compute_lottery_status(ev, at(2026, 11, 24, 12)) == L_RESULT_PENDING
    assert compute_lottery_status(ev, at(2026, 11, 27, 12)) == L_WINNER_PURCHASE_PERIOD
    assert compute_lottery_status(ev, at(2026, 12, 1, 12)) == L_ENDED
    # 購入期間しか分からない行は、受付中にも開始前にもしない
    assert compute_lottery_status({"purchase_start_date": "2026-11-26", "purchase_end_date": "2026-11-30"},
                                  at(2026, 11, 27)) == L_UNKNOWN


def test_unknown_schedule_never_becomes_open():
    assert compute_lottery_status({}, at(2026, 11, 26)) == L_UNKNOWN
    assert compute_lottery_status({"application_start": "2026-11-25T10:00:00+09:00"}, at(2026, 11, 26)) == L_UNKNOWN


def test_cancelled_or_early_ended_is_not_open_even_before_the_deadline():
    ev = {"application_start": "2026-11-21T10:00:00+09:00", "application_end": "2026-11-30T23:59:00+09:00"}
    assert compute_lottery_status(ev, at(2026, 11, 22)) == L_OPEN
    assert compute_lottery_status({**ev, "cancelled": True}, at(2026, 11, 22)) == L_ENDED
    assert compute_lottery_status({**ev, "cancelled": None}, at(2026, 11, 20)) == L_UPCOMING


@pytest.mark.parametrize("title,body,expect", [
    ("【重要】拡張パック抽選販売中止のお知らせ", "", ("CANCELLED", "中止")),
    ("抽選販売のお知らせ", "予定数に達したため、抽選受付を終了いたしました。", ("CLOSED_EARLY", "終了いたしました")),
    ("抽選販売のお知らせ", "予定数に達したため、受付は終了しました。", ("CLOSED_EARLY", "終了しました")),
    ("抽選販売のお知らせ", "天候により抽選販売を中止する場合があります。", None),          # 可能性の注意書きは中止ではない
    ("抽選販売のお知らせ", "予定数に達し次第受付を終了いたします", None),
    ("抽選販売のお知らせ", "結果発表は12月1日です", None),
    ("抽選販売のお知らせ", "悪天候時は店頭販売を中止いたします。", None),                  # 条件つき・一部の経路
    ("抽選販売のお知らせ", "※前回の抽選販売は中止となりました。", None),                  # 過去の抽選への言及
    ("抽選販売のお知らせ", "お電話での受付は中止いたします", None),
])
def test_cancellation_is_detected_only_when_stated(title, body, expect):
    assert detect_cancellation(title, body) == expect


def test_cancellation_of_another_product_is_not_applied():
    body = "拡張パック「テストB」の抽選販売は中止となりました。「テストA」は予定通り実施します。"
    names = ["拡張パック「テストA」", "拡張パック「テストB」"]
    assert detect_cancellation("抽選販売のお知らせ", body, product_name=names[0], other_products=names) is None
    assert detect_cancellation("抽選販売のお知らせ", body, product_name=names[1],
                               other_products=names) == ("CANCELLED", "中止となりました")


def test_early_close_keeps_result_and_purchase_states():
    ev = {"application_start": "2026-11-20T10:00:00+09:00", "application_end": "2026-11-30T23:59:00+09:00",
          "winner_announcement_date": "2026-12-03", "purchase_start_date": "2026-12-07", "purchase_end_date": "2026-12-13",
          "application_closed": True}
    assert compute_lottery_status(ev, at(2026, 11, 26, 12)) == L_RESULT_PENDING          # 終了にしない・受付中にもしない
    assert compute_lottery_status(ev, at(2026, 12, 8, 12)) == L_WINNER_PURCHASE_PERIOD
    assert compute_lottery_status({**ev, "cancelled": True}, at(2026, 11, 26, 12)) == L_ENDED   # 中止だけが終了


# ── 重複の判定（店舗・支店 × 商品の識別子 × 応募回） ─────────────────────
def _ev(**kw):
    from src.tcg.lottery.schema import LotteryEvent
    base = dict(tcg="POKEMON", product_name="拡張パック「テスト」", product_id="pkm-test", retailer="CARD_LABO",
                source_type="STORE_OFFICIAL", source_url="https://www.c-labo.jp/shop/a/blog/1/")
    base.update(kw)
    return LotteryEvent(**base).to_dict()


def test_dedupe_merges_url_variants_and_corrections_of_the_same_round():
    from src.tcg.lottery.merge import merge_lotteries
    a = _ev(application_start="2026-11-21T10:00:00+09:00", application_end="2026-11-23T23:59:00+09:00")
    b = _ev(application_start="2026-11-21T10:00:00+09:00", application_end="2026-11-23T23:59:00+09:00",
            source_url="https://www.c-labo.jp/shop/a/blog/1/?utm_source=x")
    assert a["lottery_id"] == b["lottery_id"]
    assert len(merge_lotteries([a, b])) == 1
    fixed = _ev(application_start="2026-11-21T10:00:00+09:00", application_end="2026-11-24T23:59:00+09:00",
                source_type="RETAILER_OFFICIAL")                       # 締切の訂正（同じ応募回）
    [m] = merge_lotteries([a, fixed])
    assert m["merged_count"] == 2 and m["conflict"] is True            # どちらかを勝手に採らず、食い違いとして残す


def test_dedupe_keeps_different_rounds_and_branches_apart():
    from src.tcg.lottery.merge import merge_lotteries
    r1 = _ev(application_end_date="2026-11-23")                       # 受付開始が不明な別々の回
    r2 = _ev(application_end_date="2026-12-10")
    assert r1["lottery_id"] != r2["lottery_id"] and len(merge_lotteries([r1, r2])) == 2
    s1 = _ev(store_specific=True, store_name="カードラボ池袋店", application_end_date="2026-11-23")
    s2 = _ev(store_specific=True, store_name="カードラボ難波店", application_end_date="2026-11-23")
    assert len(merge_lotteries([s1, s2])) == 2                         # 支店が違えば別の抽選
    assert "jan" not in s1                                             # JAN を作らない（商品マスターの ID を使う）


def test_early_close_without_deadline_ages_out_from_the_announcement_date():
    ev = {"application_start": "2026-11-20T10:00:00+09:00", "application_closed": True, "published_at": "2026-11-19T00:00:00+09:00"}
    assert compute_lottery_status(ev, at(2026, 11, 22)) not in (L_OPEN, L_ENDING_SOON, L_UPCOMING)
    assert compute_lottery_status(ev, at(2027, 1, 30)) == L_ENDED                    # 保持期間の後は終了（受付終了のまま残らない）


@pytest.mark.parametrize("body", ["以下の店舗では抽選販売を中止いたします：A店", "オンラインでの抽選販売は中止し、店頭で実施します"])
def test_partial_cancellation_is_not_a_cancellation_of_the_whole_lottery(body):
    assert detect_cancellation("拡張パック「テストX」抽選販売", body, product_name="拡張パック「テストX」") is None


def test_early_close_with_no_dates_at_all_is_unknown_and_old_ones_end():
    assert compute_lottery_status({"application_closed": True}, at(2026, 11, 26)) == L_UNKNOWN
    old = {"application_start": "2025-01-01T10:00:00+09:00", "application_closed": True}
    assert compute_lottery_status(old, at(2026, 11, 26)) == L_ENDED


@pytest.mark.parametrize("body,cancelled", [
    ("WEB抽選を中止いたします。", True),                                        # 全体（Web の抽選）の中止
    ("WEBでの抽選販売のみ中止し、店頭抽選は継続いたします。", False),           # 一部の経路だけ
    ("抽選販売を中止いたします。", True),                                       # 全体の中止
    ("抽選販売を中止する場合があります。", False),                              # 可能性の注意書き
])
def test_cancellation_reaches_the_status_and_the_page(body, cancelled):
    from src.collectors.tcg.lottery.clabo import CardLaboLotteryAdapter
    from src.content.tcg_hub_page import render_pages_from_json
    from src.tcg.lottery.schema import compute_lottery_status
    a = CardLaboLotteryAdapter()
    text = body + "\n応募期間：11月25日 10:00～11月30日 23:59\n"
    [ev] = a.build_from_article(title="【テスト店】拡張パック「テストZ」抽選販売", body=text,
                                url="https://www.c-labo.jp/shop/a/blog/9/", published_at="2026-11-24T00:00:00+09:00",
                                tcg_hint="POKEMON", targets=[{"product_name": "拡張パック「テストZ」", "retail_price": None}])
    now = at(2026, 11, 26, 12)
    ev["status"] = compute_lottery_status(ev, now)
    assert (ev["status"] == L_ENDED) is cancelled and (ev["status"] == L_OPEN) is (not cancelled)
    html = render_pages_from_json({"generated_at": now.isoformat(), "items": [ev], "coverage": {}, "announcements": []},
                                  {"products": []}, {}, now=now)["tcg-lottery.html"]
    assert ('data-lot-state="OPEN"' in html) is (not cancelled)                 # 中止は受付中の行・応募の導線に残らない


@pytest.mark.parametrize("body", [
    "店頭での抽選販売は中止となりました。WEB抽選は予定通り実施します。",     # 継続は次の文
    "抽選販売は中止いたしません。", "当選者への販売は中止しません。",         # 否定
    "応募フォームの不具合のため、応募を一時中止しております。",               # 一時的な停止
    "転売目的の方への販売を中止します。",                                     # 特定の人への販売の停止
    "Web受付は終了しました。店頭受付は継続いたします。",                       # 一部の経路の受付終了
])
def test_partial_negated_or_temporary_stops_are_not_cancellations(body):
    assert detect_cancellation("抽選販売のお知らせ", body) is None


def test_greeting_after_a_web_cancellation_is_not_a_continuation():
    assert detect_cancellation("抽選販売のお知らせ", "WEB抽選を中止いたします。今後とも引き続きよろしくお願いいたします。") == (
        "CANCELLED", "中止いたします")
