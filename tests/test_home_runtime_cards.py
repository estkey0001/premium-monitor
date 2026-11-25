"""HOME の購入候補（Camera・iPhone）の期限と、期限後の表示（src/content/ui/home_feed.py・shell.py の HOME 用 JS）のテスト。

確かめること: Camera は在庫 AVAILABLE・在庫確認が stock_days 以内・価格が executable_days 以内・carried でないときだけ緑で、
until_ms は 00:00 JST 起点の最小値（rf.date_obs / days_to_hours と同じ定義）・iPhone の期限は設定どおり・期限つきの購入候補は
buy_untils に実期限で入る（"inf" にしない）・期限後に金額行も隠す JS がある・条件付き / 参考 / display_only は購入候補にならない。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from src.content.ui import home_feed as hf
from src.content.ui import shell
from src.tcg.models import JST

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=JST)


def _ms(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=JST).timestamp() * 1000)


def _route(buy_at="2026-11-19", sell_at="2026-11-18", stock="AVAILABLE", rt="C", **kw):
    r = {"route_type": rt, "profit_status": "PROFITABLE", "decision": "BUY", "executable": True, "confidence": "high",
         "net_profit": 16200, "roi_pct": 7.3,
         "buy": {"source": "店A", "price": 222000, "freshness": "FRESH", "checked_at": buy_at, "stock": stock},
         "sell": {"source": "買取B", "price": 240000, "freshness": "FRESH", "checked_at": sell_at}}
    r.update(kw)
    return r


def _cam(routes, date="2026-11-19"):
    return {"research_date": date, "events": [],
            "products": [{"product": "RICOH GR IV HDF", "registered": True, "observations": [], "routes": routes}]}


def _card(route, now=NOW, date="2026-11-19"):
    cam = _cam([route], date)
    return hf.card_from_camera_route(cam["products"][0], route, cam, now)


def _sku(**kw):
    s = {"sku": "iPhone Duo 1TB", "identity": "REGISTERED", "profit_status": "PROFITABLE", "opportunity_status": "BUY",
         "opportunity_reason": "黒字", "outlier_status": "NONE", "apple_price": 469800,
         "apple_availability": {"status": "BUYABLE", "checked_at": "2026-11-20T09:00:00+09:00"},
         "highest_executable": {"shop": "パステック", "price": 483000}, "net_profit": 11400, "roi_pct": 9.0,
         "rows": [{"shop": "パステック", "executable_price": 483000, "eligible": True, "freshness": "FRESH",
                   "checked_at": "2026-11-20"}]}
    s.update(kw)
    return s


def _iphone(skus, date="2026-11-20"):
    return {"research_date": date, "skus": skus, "events": [], "events_note": "前回の週次の調査との比較"}


def _ctx(**kw):
    args = dict(tcg_report={"lotteries": [], "events": []}, opportunities={}, profit_routes={},
                legacy_lotteries=[], updated_text="11/20 12:00", now=NOW, home_feed_data={})
    args.update(kw)
    return shell.ShellContext(**args)


def _home(ctx) -> str:
    root = shell.render_root(ctx)
    start = root.index('data-nu-page="home"')
    return root[start:root.index("</section>", start)]


# ── Camera: 緑にする条件 ─────────────────────────────────────

def test_camera_fresh_available_is_green_with_min_until():
    c = _card(_route(buy_at="2026-11-19", sell_at="2026-11-18"))
    assert c is not None and c.action == "買い"
    # 買値の在庫 11-19 + 2 日 → 11-22 00:00 / 売値 11-18 + 7 日 → 11-26 00:00 / 仕入れ価格 11-19 + 7 日 → 11-27 00:00
    assert c.until_ms == _ms(2026, 11, 22)


def test_camera_until_can_be_set_by_the_sell_price():
    c = _card(_route(buy_at="2026-11-20", sell_at="2026-11-14"))            # 売値が 6 日前: 11-14 + 8 日 = 11-22 00:00 ... 在庫は 11-23
    assert c.until_ms == _ms(2026, 11, 22)


def test_camera_not_green_when_stock_not_available():
    for st in ("STOCK_UNKNOWN", "OUT_OF_STOCK", "LOTTERY_DEPENDENT", None):
        assert _card(_route(stock=st)) is None, st


def test_camera_not_green_when_stock_check_is_three_days_old():
    assert _card(_route(buy_at="2026-11-17")) is None                       # 11-17 + 3 日 = 11-20 00:00 <= 生成時刻


def test_camera_not_green_when_sell_price_is_eight_days_old():
    assert _card(_route(sell_at="2026-11-12")) is None                      # 11-12 + 8 日 = 11-20 00:00 <= 生成時刻


def test_camera_not_green_when_carried_or_dates_unreadable():
    r = _route(); r["buy"]["carried"] = True
    assert _card(r) is None
    r = _route(); r["sell"]["carried"] = True
    assert _card(r) is None
    assert _card(_route(buy_at="")) is None and _card(_route(sell_at=None)) is None


def test_camera_conditional_and_display_only_routes_are_not_cards():
    cond = _route(profit_status="CONDITIONAL", decision="WATCH", conditional=[{"profit": 30000, "blockers": ["stamp"]}])
    assert _card(cond) is None
    only = _route(decision="WAIT", display_only=True)
    assert _card(only) is None
    ctx = _ctx(home_feed_data={"camera": _cam([cond, only])})
    h = _home(ctx)
    assert "nu-fc--success" not in h and 'data-nu-feed-sec="hero"' not in h and "RICOH" not in h


def test_camera_thresholds_come_from_config_not_hardcoded(monkeypatch):
    monkeypatch.setattr(hf, "_camera_days", lambda: {"executable_days": 7, "stock_days": 0})
    assert _card(_route(buy_at="2026-11-19")) is None                       # stock_days=0 なら前日の在庫確認は使えない
    monkeypatch.setattr(hf, "_camera_days", lambda: {"executable_days": 7, "stock_days": 5})
    assert _card(_route(buy_at="2026-11-17")).until_ms == _ms(2026, 11, 23)


def test_camera_config_loader_reads_yaml_freshness():
    assert hf._camera_days() == {"executable_days": 7, "stock_days": 2}


# ── iPhone: 期限は設定どおり ─────────────────────────────────

def test_iphone_until_is_min_of_page_and_apple(monkeypatch):
    monkeypatch.setattr(hf, "_iphone_days", lambda: {"page_buy_days": 7, "apple_availability_days": 2})
    comp = _iphone([_sku()])
    c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c.action == "買い"
    # 調査日 11-20 + 8 日 = 11-28 00:00 / Apple 11-20 09:00 + 48h = 11-22 09:00 → 後者
    assert c.until_ms == _ms(2026, 11, 22, 9)
    monkeypatch.setattr(hf, "_iphone_days", lambda: {"page_buy_days": 1, "apple_availability_days": 2})
    c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c.until_ms == _ms(2026, 11, 22)                                  # 調査日 11-20 + 2 日 = 11-22 00:00 が先


def test_iphone_default_days_when_keys_missing_is_fail_closed():
    # 設定不明は None（0 日ではない）。0 日は正当な設定値と区別する（旧: 0 日の既定 → 当日 24:00 まで購入候補が出ていた）
    unknown = {"page_buy_days": None, "apple_availability_days": None}
    assert hf._freshness_cfg(lambda: {"freshness": {"default": {"fresh_days": 1}}}, hf._IPHONE_DEFAULT_DAYS) == unknown
    assert hf._freshness_cfg(lambda: (_ for _ in ()).throw(OSError()), hf._IPHONE_DEFAULT_DAYS) == unknown
    assert hf._freshness_cfg(lambda: {"freshness": {"page_buy_days": 3}}, hf._IPHONE_DEFAULT_DAYS)["page_buy_days"] == 3


def test_freshness_cfg_accepts_zero_and_integer_floats_only():
    f = lambda v: hf._freshness_cfg(lambda: {"freshness": {"page_buy_days": v}}, hf._IPHONE_DEFAULT_DAYS)["page_buy_days"]  # noqa: E731
    assert f(0) == 0 and f(3) == 3 and f(7.0) == 7 and f(0.0) == 0
    for bad in (True, False, -1, 2.5, "7", None, [3]):
        assert f(bad) is None


def test_until_of_unknown_days_is_none_but_zero_days_is_end_of_same_day():
    assert hf._until_of("2026-11-25", None) is None
    u = hf._until_of("2026-11-25", 0)
    assert u == datetime(2026, 11, 26, 0, 0, tzinfo=JST)                     # 0 は有効（当日 24:00 まで）


def test_unknown_config_gives_no_camera_green_and_no_iphone_buy_or_amount(monkeypatch):
    unk_c = {"executable_days": None, "stock_days": None}
    monkeypatch.setattr(hf, "_camera_days", lambda: unk_c)
    assert _card(_route(buy_at="2026-11-20", sell_at="2026-11-20")) is None   # 同日確認でも購入候補にしない
    monkeypatch.setattr(hf, "_iphone_days", lambda: {"page_buy_days": None, "apple_availability_days": None})
    comp = _iphone([_sku()])
    c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c.action == "要確認" and c.until_ms is None and c.profit_hidden
    # 0 日は有効: 同日確認なら購入候補になる（None と区別される）
    monkeypatch.setattr(hf, "_iphone_days", lambda: {"page_buy_days": 0, "apple_availability_days": 1})
    c0 = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c0.action == "買い" and c0.until_ms and c0.profit_hidden is None


def test_iphone_watch_profit_amount_has_profit_until_and_js_replaces_it():
    comp = _iphone([_sku(opportunity_status="WAIT")], date="2026-11-18")
    c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c.profit_until_ms == _ms(2026, 11, 26)                              # 11-18 + (7+1) 日 00:00 JST
    h = _home(_ctx(home_feed_data={"iphone": comp}))
    assert f'data-nu-pd-profit-until="{_ms(2026, 11, 26)}"' in h and "+¥11,400" in h
    root = shell.render_root(_ctx(home_feed_data={"iphone": comp}))
    js = root[root.index("HOME の購入候補カード・タイル"):]
    assert "querySelectorAll('[data-nu-pd-profit-until]')" in js and "removeAttribute('data-nu-pd-profit-until')" in js
    hidden = hf.card_from_iphone_sku(_iphone([_sku(opportunity_status="WAIT")], date="2026-11-10")["skus"][0],
                                     _iphone([_sku(opportunity_status="WAIT")], date="2026-11-10"), NOW)
    assert hidden.profit_until_ms is None                                      # 既に伏せた金額には付けない


def test_iphone_expired_at_generation_is_not_a_buy_candidate():
    comp = _iphone([_sku(apple_availability={"status": "BUYABLE", "checked_at": "2026-11-17T09:00:00+09:00"})])
    c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c is not None and c.action == "要確認" and c.until_ms is None
    assert not hf.is_buy(c)


# ── HOME への出方 ────────────────────────────────────────────

def test_buy_untils_are_real_deadlines_never_inf():
    ctx = _ctx(home_feed_data={"camera": _cam([_route()]), "iphone": _iphone([_sku()])})
    h = _home(ctx)
    m = re.search(r'data-nu-buy-untils="([^"]*)"', h)
    assert m, "購入候補タイルに期限の一覧が無い"
    toks = m.group(1).split(",")
    assert len(toks) == 2 and "inf" not in toks and all(t.isdigit() for t in toks)
    assert str(_ms(2026, 11, 22)) in toks and str(_ms(2026, 11, 22, 9)) in toks


def test_card_with_until_has_attr_and_visible_deadline_note():
    h = _home(_ctx(home_feed_data={"camera": _cam([_route()])}))
    assert f'data-nu-pd-until="{_ms(2026, 11, 22)}"' in h
    assert "11/22 00:00（JST）までの確認です" in h                           # JS が無くても期限が分かる


def test_home_js_hides_profit_row_after_until():
    root = shell.render_root(_ctx(home_feed_data={"camera": _cam([_route()])}))
    js = root[root.index("HOME の購入候補カード・タイル"):]
    js = js[:js.index("data-nu-buy-untils")]
    assert "nu-fc__profit" in js and "更新待ち（取得日つきの参考）" in js


def test_reference_and_display_only_tcg_opportunities_do_not_make_buy_candidates():
    opp = {"product_name": "ポケカ BOX", "retailer": "店", "profit": 20000, "roi": 0.4, "display_only": True,
           "reference_only": True, "actionability": "REFERENCE_ONLY", "price_type": "REFERENCE"}
    ctx = _ctx(tcg_report={"lotteries": [], "events": [], "retailer_opportunities": [opp]})
    h = _home(ctx)
    assert 'data-nu-feed-sec="hero"' not in h and "nu-fc--success" not in h and "data-nu-buy-untils" not in h


def test_iphone_config_loader_reads_yaml_freshness():
    assert hf._iphone_days() == {"page_buy_days": 7, "apple_availability_days": 2}


def test_home_feed_does_not_import_src_research():
    """deploy-check #871: 顧客の画面（src/content/ui）は src.research を読まない。期間は config/ の yaml を直接読む。"""
    import inspect
    assert "src.research" not in inspect.getsource(hf)


def test_iphone_card_keeps_weekly_note_and_adds_deadline():
    comp = _iphone([_sku()])
    c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c.note and c.until_ms
    html = hf._card_html(c, hf._PROFIT_FIELDS)
    assert c.note in html and "までの確認です" in html and html.count("nu-feed__stale") == 1


def test_buy_untils_marks_camera_iphone_without_deadline_as_none_and_tcg_as_inf():
    cam = hf.FeedCard(product="a", category="カメラ", action="買い", profit=1000, roi=0.1)
    tcg = hf.FeedCard(product="b", category="ポケカ", action="買い", profit=1000, roi=0.1)
    cats = hf._DEADLINE_CATEGORIES
    assert "カメラ" in cats and "iPhone" in cats and "ポケカ" not in cats
    assert hf.is_actionable_buy(cam) and hf.is_actionable_buy(tcg)


# ── M2: iPhone の期限は詳細ページと同じ観測日（最高買取の行の updated_on。無ければ調査日）と page_buy_days ──

def _sku_updated(day):
    s = _sku()
    s["rows"][0]["updated_on"] = day
    return s


def test_iphone_until_uses_highest_buyback_row_updated_on_like_the_detail_page(monkeypatch):
    monkeypatch.setattr(hf, "_iphone_days", lambda: {"page_buy_days": 7, "apple_availability_days": 20})
    comp = _iphone([_sku_updated("2026-11-14")])                              # 調査日は 11-20 だが、買取価格の確認は 11-14
    c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c.action == "買い" and c.until_ms == _ms(2026, 11, 22)             # 11-14 + 8 日 = 11-22 00:00（調査日基準なら 11-28）
    comp = _iphone([_sku_updated("2026-11-12")])                              # 11-12 + 8 日 = 11-20 00:00 <= 生成時刻 → 詳細ページでも期限切れ
    c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c.action == "要確認" and c.until_ms is None


def test_iphone_until_falls_back_to_research_date_without_updated_on(monkeypatch):
    monkeypatch.setattr(hf, "_iphone_days", lambda: {"page_buy_days": 7, "apple_availability_days": 20})
    comp = _iphone([_sku()])
    assert hf.card_from_iphone_sku(comp["skus"][0], comp, NOW).until_ms == _ms(2026, 11, 28)


# ── M3: 未来の観測日・時刻は購入候補にしない（ページの未来日付 = UNKNOWN と同じ） ──

def test_future_dates_never_make_a_green_card_camera():
    assert _card(_route(buy_at="2026-11-21")) is None
    assert _card(_route(sell_at="2026-11-30")) is None
    assert _card(_route(), date="2026-11-21") is None
    assert _card(_route(buy_at="2026-11-20T13:00:00+09:00")) is None          # 同日でも生成時刻より未来の時刻
    assert _card(_route(buy_at="2026-11-20")) is not None                     # 同日の日付は未来ではない


def test_future_dates_never_make_a_card_iphone():
    for kw in ({"date": "2026-11-21"},):
        comp = _iphone([_sku()], **kw)
        assert hf.card_from_iphone_sku(comp["skus"][0], comp, NOW) is None
    for patch in ({"apple_availability": {"status": "BUYABLE", "checked_at": "2026-11-20T13:00:00+09:00"}},
                  {"apple_availability": {"status": "BUYABLE", "checked_at": "2026-11-25"}}):
        comp = _iphone([_sku(**patch)])
        assert hf.card_from_iphone_sku(comp["skus"][0], comp, NOW) is None, patch
    comp = _iphone([_sku_updated("2026-12-01")])
    assert hf.card_from_iphone_sku(comp["skus"][0], comp, NOW) is None
    h = _home(_ctx(home_feed_data={"iphone": _iphone([_sku(apple_availability={"status": "BUYABLE", "checked_at": "2099-01-01"})])}))
    assert "nu-fc--success" not in h and "data-nu-pd-until" not in h


# ── Auditor M3: 期限切れ（page_buy_days 超）の iPhone 黒字は金額・ROI を出さない（他カテゴリの 14 日は変えない） ──

def test_iphone_profit_amount_is_hidden_after_page_buy_days_but_card_stays_as_watch():
    comp = _iphone([_sku(opportunity_status="WAIT")], date="2026-11-10")      # 10 日前 > page_buy_days（7）
    c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c is not None and c.action == "様子見" and c.profit_hidden and "更新待ち" in c.profit_hidden and "調査から" in c.profit_hidden
    h = _home(_ctx(home_feed_data={"iphone": comp}))
    assert "iPhone Duo 1TB" in h and "11,400" not in h and "2.4%" not in h and "9.0%" not in h and "更新待ち（調査から" in h
    fresh = _home(_ctx(home_feed_data={"iphone": _iphone([_sku(opportunity_status="WAIT")], date="2026-11-18")}))
    assert "+¥11,400" in fresh                                                 # 期限内は従来どおり金額を出す


def test_iphone_stale_buy_candidate_also_hides_amount():
    comp = _iphone([_sku_updated("2026-11-10")])
    c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert c.action == "要確認" and c.profit_hidden


def test_camera_profit_still_uses_14_day_rule_unchanged():
    assert _card(_route(), date="2026-11-07") is not None                     # 13 日前: Camera は従来の 14 日基準のまま（金額を隠さない）
    c = _card(_route(), date="2026-11-07")
    assert c.profit_hidden is None


# ── L2: HOME の期限 JS は 60 秒ごと・visibilitychange・pageshow でも評価し直す ──

def test_home_js_reevaluates_periodically_and_on_visibility_and_pageshow():
    root = shell.render_root(_ctx(home_feed_data={"camera": _cam([_route()])}))
    assert root.count("function homeUntils()") == 1
    assert "setInterval(homeUntils, 60000)" in root
    assert "addEventListener('visibilitychange', homeUntils)" in root and "addEventListener('pageshow', homeUntils)" in root
    i = root.index("function homeUntils()")
    j = root.index("setInterval(homeUntils, 60000)")
    body = root[i:j]
    assert "var now = Date.now();" in body and body.count("Date.now()") == 1   # 評価のたびに今の時刻を取る（読み込み時の値を使い回さない）


# ── L1: 生成時刻は HTML に埋めた値（ファイルの更新時刻ではない） ──

def test_home_html_embeds_generation_time_with_offset():
    from scripts import deploy_check as dc
    root = shell.render_root(_ctx())
    assert 'data-nu-generated-at="2026-11-20T12:00:00+09:00"' in root
    assert dc.home_generated_ms(root) == _ms(2026, 11, 20, 12)
    assert dc.home_generated_ms("<main>") is None
    assert dc.home_generated_ms('<main data-nu-generated-at="2026-11-20T12:00:00">') is None   # オフセットなしは不合格
    assert dc.home_generated_ms('<main data-nu-generated-at="x">') is None


# ── Reviewer L2: Apple の確認時刻が無い・オフセットなし・読めないときは、iPhone ページと同じく購入候補（買い）にしない ──
def test_iphone_buy_card_requires_offset_aware_apple_checked_at():
    ok = _iphone([_sku()])
    assert hf.card_from_iphone_sku(ok["skus"][0], ok, NOW).action == "買い"          # オフセット付きなら従来どおり
    for av in ({"status": "BUYABLE"},
               {"status": "BUYABLE", "checked_at": "2026-11-20T09:00:00"},          # オフセットなし（ページの parse_aware は None）
               {"status": "BUYABLE", "checked_at": "2026-11-20"},
               {"status": "BUYABLE", "checked_at": "not-a-date"}):
        comp = _iphone([_sku(apple_availability=av)])
        c = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
        assert c is None or (c.action != "買い" and c.until_ms is None), av
