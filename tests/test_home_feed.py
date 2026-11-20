"""HOME の「今日何をするか」横断セクション（src/content/ui/home_feed.py）のテスト。

確かめること: 0 件のセクションは出ない・架空の件数が無い・価格のガード（未確認・参考値・出品価格の利益を出さない）・
調査日が 7 日を超えたら注記・締切を過ぎた抽選が閲覧時に消える属性が残る・カメラ C/D が 0 件なら非表示・
壊れた JSON でも HOME が出る・FeedCard の不明は「—」・checked_at は元データのまま・/Users/ と .private が出ない。
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta

import pytest

from src.content.ui import home_feed as hf
from src.content.ui import shell
from src.tcg.models import JST

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=JST)
PCO = "https://www.pokemoncenter-online.com"
ROW_CHECKED = "2026-11-17 JST（ページ記載: 買取価格更新日 2026/11/17）"


def _iso(delta: timedelta) -> str:
    return (NOW + delta).isoformat()


def _lot(i, **kw):
    e = {"tcg": "POKEMON", "product_name": f"ポケカ抽選{i}", "retailer_name": "ポケモンセンターオンライン",
         "lottery_id": f"t{i}", "status": "OPEN", "source_url": f"{PCO}/news/{i}", "entry_url": f"{PCO}/lottery/{i}",
         "verified": True, "confidence": "high", "retail_price": 5400,
         "application_start": _iso(-timedelta(days=1)), "application_end": _iso(timedelta(days=5)),
         "last_verified_at": f"2026-11-20T09:0{i % 10}:00+09:00", "published_at": _iso(-timedelta(days=10))}
    e.update(kw)
    return e


def _sku(name="iPhone Duo 1TB", **kw):
    s = {"sku": name, "identity": "REGISTERED", "profit_status": "PROFITABLE", "opportunity_status": "WAIT",
         "opportunity_reason": "黒字だが ROI が BUY の条件（8%）未満", "outlier_status": "NONE",
         "apple_price": 469800, "apple_availability": {"status": "BUYABLE"},
         "highest_executable": {"shop": "パステック", "price": 483000}, "net_profit": 11400, "roi_pct": 2.43,
         "rows": [{"shop": "パステック", "executable_price": 483000, "eligible": True, "freshness": "FRESH",
                   "checked_at": ROW_CHECKED}]}
    s.update(kw)
    return s


def _iphone(skus=None, events=(), date="2026-11-17", note="前回の週次の調査との比較"):
    return {"research_date": date, "skus": skus if skus is not None else [_sku()], "events": list(events),
            "events_note": note}


def _route(rt="C", **kw):
    r = {"route_type": rt, "profit_status": "PROFITABLE", "decision": "BUY", "executable": True, "confidence": "high",
         "net_profit": 16200, "roi_pct": 7.3,
         "buy": {"source": "店A", "price": 222000, "freshness": "FRESH", "checked_at": "2026-11-18"},
         "sell": {"source": "買取B", "price": 240000, "freshness": "FRESH", "checked_at": "2026-11-18"}}
    r.update(kw)
    return r


def _camera(routes=None, registered=True, events=(), date="2026-11-18"):
    return {"research_date": date, "events": list(events),
            "products": [{"product": "RICOH GR IV HDF", "registered": registered, "observations": [],
                          "routes": routes if routes is not None else [_route("C")]}]}


def _ctx(**kw):
    args = dict(tcg_report={"lotteries": [], "events": []}, opportunities={}, profit_routes={},
                legacy_lotteries=[], updated_text="11/20 12:00", now=NOW, home_feed_data={})
    args.update(kw)
    return shell.ShellContext(**args)


def _home(ctx) -> str:
    root = shell.render_root(ctx)
    start = root.index('data-nu-page="home"')
    return root[start:root.index("</section>", start)]


def _feed(ctx) -> str:
    h = _home(ctx)
    if "data-nu-feed " not in h and "data-nu-feed>" not in h:
        return ""
    s = h.index("data-nu-feed")
    return h[s:h.index('id="nu-genres"')]


def _keys(feed: str) -> list[str]:
    return re.findall(r'data-nu-feed-sec="(\w+)"', feed)


# ── 0 件のセクションは出ない・架空の件数が無い ──────────────────────────

def test_empty_data_shows_no_feed_at_all():
    h = _home(_ctx())
    assert "data-nu-feed" not in h and "nu-feed__sec" not in h
    assert hf.render_sections([]) == ""
    assert "ジャンルから探す" in h                                   # 既存の HOME は残る


def test_only_sections_with_cards_appear_and_none_says_zero():
    feed = _feed(_ctx(home_feed_data={"iphone": _iphone()}))
    assert _keys(feed) == ["profit_watch"]                          # 既定の SKU は判定が WAIT の黒字 → 「今日の利益商品」ではなく様子見の枠
    assert "今日の利益商品" not in feed and "黒字だが様子見" in feed
    assert "0件" not in feed and "0 件" not in feed
    for title in ("締切間近", "現在受付中", "新着抽選", "最新発売", "買取価格上昇", "WAIT → BUY", "BUY → WAIT"):
        assert title not in feed


def test_rest_count_is_real_and_top_is_limited():
    skus = [_sku(f"iPhone Duo {i}TB", net_profit=1000 + i * 100,
                 highest_executable={"shop": "パステック", "price": 480000 + i},
                 rows=[{"shop": "パステック", "executable_price": 480000 + i, "eligible": True,
                        "freshness": "FRESH", "checked_at": ROW_CHECKED}]) for i in range(1, 8)]
    feed = _feed(_ctx(home_feed_data={"iphone": _iphone(skus)}))
    assert feed.count("data-nu-feedcard") == hf.MAX_PER_SECTION
    assert "ほか2件" in feed                                         # 7 件中 5 件を出した残りだけ
    one = _feed(_ctx(home_feed_data={"iphone": _iphone()}))
    assert "ほか" not in one                                         # 残りが無ければ件数を書かない
    # 利益が大きい順
    assert feed.index("iPhone Duo 7TB") < feed.index("iPhone Duo 3TB")


# ── 価格のガード ──────────────────────────────────────────────

@pytest.mark.parametrize("patch", [
    {"identity": "DISCOVERED"},                                      # 正本に未登録（参考）
    {"profit_status": "REFERENCE_PROFIT"},                           # 参考値
    {"profit_status": "NO_DATA"},
    {"outlier_status": "OUTLIER_REVIEW"},                            # 外れ値の確認待ち
    {"outlier_status": "SINGLE_SOURCE"},
    {"net_profit": 0}, {"net_profit": None}, {"net_profit": -5},
    {"roi_pct": 900.0}, {"roi_pct": 0}, {"roi_pct": None},           # 極端な利益率・不正
    {"apple_availability": {"status": "UNKNOWN"}},                   # 購入できると確認できていない
    {"apple_availability": None},
    {"highest_executable": None},
    {"apple_price": 0},
    {"rows": [{"shop": "パステック", "executable_price": 483000, "eligible": True, "freshness": "STALE",
               "checked_at": ROW_CHECKED}]},                         # 鮮度なし
    {"rows": [{"shop": "パステック", "executable_price": 483000, "eligible": False, "freshness": "FRESH",
               "checked_at": ROW_CHECKED}]},                         # 実行可能でない行
])
def test_iphone_profit_guards(patch):
    comp = _iphone([_sku(**patch)])
    assert hf.card_from_iphone_sku(comp["skus"][0], comp, NOW) is None
    assert "data-nu-feed" not in _home(_ctx(home_feed_data={"iphone": comp}))


def test_iphone_profit_older_than_14_days_is_dropped():
    comp = _iphone(date="2026-11-05")                                # 15 日前
    assert hf.card_from_iphone_sku(comp["skus"][0], comp, NOW) is None


def test_listing_price_profit_from_catalog_is_not_shown():
    """出品価格（確定でない売値）・売値の同一性が未確認の案件は、利益商品の判定で外れ、HOME にも出ない。"""
    deal = {"product_id": "prod_gr4", "title": "RICOH GR IV", "genre": "camera", "official_price": 211800,
            "official_checked_at": "2026-09-01T10:00:00+09:00", "msrp_evidence": "VERIFIED_DATED",
            "stock_status": "在庫あり", "sale_method": "normal", "sell_shop": "フジヤカメラ",
            "sell_identity_verified": False, "sell_price": 240000, "sell_checked_at": "2026-11-19T12:00:00+09:00",
            "net_profit": 26400, "user_level": "beginner_easy", "resale_sell": False, "href": "./?from=new#x",
            "purchase_shipping": 0, "purchase_shipping_status": "FREE_VERIFIED"}
    ctx = _ctx(profit_deals=[deal], product_genres={"prod_gr4": "camera"})
    assert "data-nu-feed" not in _home(ctx)
    ok = dict(deal, sell_identity_verified=True)
    feed = _feed(_ctx(profit_deals=[ok], product_genres={"prod_gr4": "camera"}))
    assert _keys(feed) == ["profit"] and "RICOH GR IV" in feed       # 確認済みなら同じ案件が出る（判定は既存のまま）


# ── 調査日が古いときの注記 ────────────────────────────────────

def test_stale_research_is_annotated_after_7_days():
    old = _feed(_ctx(home_feed_data={"iphone": _iphone(date="2026-11-10")}))     # 10 日前
    assert "調査から10日" in old
    edge = _feed(_ctx(home_feed_data={"iphone": _iphone(date="2026-11-13")}))    # 7 日前ちょうどは注記なし
    assert "調査から" not in edge
    fresh = _feed(_ctx(home_feed_data={"iphone": _iphone(date="2026-11-17")}))   # 3 日前
    assert "調査から" not in fresh
    assert hf.stale_note("2026-11-12", NOW) == "調査から8日"


def test_stale_note_on_events_too():
    ev = [{"type": "BUYBACK_SURGE", "sku": "iPhone Duo 1TB", "shop": "パステック", "from": 480000, "to": 486000}]
    feed = _feed(_ctx(home_feed_data={"iphone": _iphone([_sku(profit_status="NO_DATA")], ev, date="2026-11-09")}))
    assert _keys(feed) == ["surge"] and "調査から11日" in feed


# ── 抽選: 閲覧時に消える属性・新着 ─────────────────────────────

def test_lottery_cards_keep_runtime_attributes():
    soon = _lot(1, application_end=_iso(timedelta(hours=3)))
    feed = _feed(_ctx(tcg_report={"lotteries": [soon, _lot(2)], "events": []}))
    assert _keys(feed) == ["ending", "open"]
    assert feed.count("data-nu-lot=") == 2
    assert 'data-nu-bucket="0"' in feed and 'data-nu-bucket="1"' in feed
    assert 'data-nu-status="ENDING_SOON"' in feed and 'data-nu-sort="' in feed
    assert "nu-cd" in feed and "nu-when" in feed                    # runtime が書き換える場所
    # 閲覧時に bucket が 99 になったカード・セクションを消す CSS がある
    from src.content.ui import styles
    css = styles.css()
    assert '.nu-feed [data-nu-bucket="99"]' in css and ".nu-feed__sec[data-nu-lotsec]:not(:has(" in css


def test_ended_lottery_at_generation_is_not_listed():
    gone = _lot(1, application_start=_iso(-timedelta(days=9)), application_end=_iso(-timedelta(days=8)), status="ENDED")
    assert "data-nu-feed" not in _home(_ctx(tcg_report={"lotteries": [gone], "events": []}))


def test_open_excludes_ending_soon_and_unconfirmed():
    soon = _lot(1, application_end=_iso(timedelta(hours=3)))
    unv = _lot(2, verified=False, confidence="low")                 # 参考情報（応募ボタンも出ない）
    feed = _feed(_ctx(tcg_report={"lotteries": [soon, unv, _lot(3)], "events": []}))
    sec_open = feed[feed.index('data-nu-feed-sec="open"'):]
    assert "ポケカ抽選3" in sec_open and "ポケカ抽選1" not in sec_open and "ポケカ抽選2" not in feed


def test_new_lottery_uses_official_published_at_within_48h_only():
    start = _iso(timedelta(days=2))                                  # 応募開始前（受付中・締切間近は別の節に出るので、新着の節には重ねない）
    end = _iso(timedelta(days=5))
    new = _lot(1, published_at=_iso(-timedelta(hours=20)), application_start=start, application_end=end)
    old = _lot(2, published_at=_iso(-timedelta(hours=60)), application_start=start, application_end=end)
    none = _lot(3, published_at=None, application_start=start, application_end=end)
    feed = _feed(_ctx(tcg_report={"lotteries": [new, old, none], "events": []}))
    sec = feed[feed.index('data-nu-feed-sec="new"'):]
    sec = sec[:sec.index("</div></div>") if "</div></div>" in sec else len(sec)]
    assert "ポケカ抽選1" in sec and "ポケカ抽選2" not in sec and "ポケカ抽選3" not in sec
    assert "data-nu-feed-sec=\"new\"" not in _feed(_ctx(tcg_report={"lotteries": [old, none], "events": []}))


# ── カメラ ────────────────────────────────────────────────

def test_camera_profit_shown_only_for_confirmed_cd_routes():
    feed = _feed(_ctx(home_feed_data={"camera": _camera()}))
    assert _keys(feed) == ["profit"] and "RICOH GR IV HDF" in feed and "+¥16,200（7.3%）" in feed
    d = _feed(_ctx(home_feed_data={"camera": _camera([_route("D")])}))
    assert _keys(d) == ["profit"]


@pytest.mark.parametrize("routes, registered", [
    ([_route("A")], True), ([_route("B")], True),                    # ルート A/B は対象外
    ([_route("C", profit_status="NO_PROFIT")], True),
    ([_route("C", profit_status="NOT_CALCULATED", net_profit=None, roi_pct=None)], True),
    ([_route("C", decision="WAIT")], True), ([_route("C", executable=False)], True),   # 確定でない
    ([_route("C", confidence="low")], True),
    ([_route("C", sell={"source": "買取B", "price": 240000, "freshness": "STALE", "checked_at": "2026-11-01"})], True),
    ([_route("C", roi_pct=900)], True),
    ([_route("C")], False),                                          # registered=False の発見
    ([], True),
])
def test_camera_profit_not_shown(routes, registered):
    assert "data-nu-feed" not in _home(_ctx(home_feed_data={"camera": _camera(routes, registered)}))


def test_camera_events_only_registered_and_cd_routes():
    evs = [{"type": "BUYBACK_SURGE", "product": "RICOH GR IV HDF", "market_type": "buyback", "source": "kt",
            "from": 240000, "to": 250000},
           {"type": "WAIT_TO_BUY", "product": "RICOH GR IV HDF", "route": "A", "from": "WAIT", "to": "BUY"},
           {"type": "BUY_TO_WAIT", "product": "RICOH GR IV HDF", "route": "D", "from": "BUY", "to": "WAIT"}]
    feed = _feed(_ctx(home_feed_data={"camera": _camera([], True, evs)}))
    assert _keys(feed) == ["surge", "b2w"]                           # ルート A の WAIT→BUY は出ない
    assert "data-nu-feed" not in _home(_ctx(home_feed_data={"camera": _camera([], False, evs)}))


# ── iPhone のイベント・TCG のイベントは出ない ───────────────────

def test_iphone_events_sections_and_first_run_and_unregistered():
    evs = [{"type": "BUYBACK_SURGE", "sku": "iPhone Duo 1TB", "shop": "パステック", "from": 480000, "to": 486000},
           {"type": "WAIT_TO_BUY", "sku": "iPhone Duo 1TB", "from": "WAIT", "to": "BUY", "net": 30000},
           {"type": "BUY_TO_WAIT", "sku": "iPhone Duo 1TB", "from": "BUY", "to": "WAIT", "net": 1000},
           {"type": "BUYBACK_SURGE", "sku": "iPhone X", "shop": "A", "from": 1000, "to": 9000},
           {"type": "PRICE_DROP", "sku": "iPhone Duo 1TB", "shop": "パステック", "from": 490000, "to": 480000}]
    skus = [_sku(profit_status="NO_DATA"), _sku("iPhone X", identity="DISCOVERED", profit_status="NO_DATA")]
    feed = _feed(_ctx(home_feed_data={"iphone": _iphone(skus, evs)}))
    assert _keys(feed) == ["surge", "w2b", "b2w"]
    assert "iPhone X" not in feed and "PRICE_DROP" not in feed
    assert "¥480,000 → ¥486,000（+¥6,000）" in feed
    first = _feed(_ctx(home_feed_data={"iphone": _iphone(skus, evs, note="初回の調査のため比較なし")}))
    assert first == ""                                               # 前回が無ければ出さない


def test_section_order_matches_spec():
    evs = [{"type": "BUYBACK_SURGE", "sku": "iPhone Duo 1TB", "shop": "パステック", "from": 480000, "to": 486000},
           {"type": "WAIT_TO_BUY", "sku": "iPhone Duo 1TB", "from": "WAIT", "to": "BUY", "net": 30000},
           {"type": "BUY_TO_WAIT", "sku": "iPhone Duo 1TB", "from": "BUY", "to": "WAIT", "net": 1000}]
    release = {"status": "COMING_SOON", "product_name": "新弾BOX", "canonical_url": f"{PCO}/product/9",
               "release_date": "2026年12月1日（火）", "store": "POKEMON_CENTER_ONLINE"}
    report = {"lotteries": [_lot(1, application_end=_iso(timedelta(hours=3))),
                            _lot(2),
                            _lot(3, published_at=_iso(-timedelta(hours=5)), application_start=_iso(timedelta(days=2)), application_end=_iso(timedelta(days=5)))],
              "events": [release]}
    feed = _feed(_ctx(tcg_report=report, home_feed_data={"iphone": _iphone(events=evs)}))
    assert _keys(feed) == ["profit_watch", "ending", "open", "new", "release", "surge", "w2b", "b2w"]
    h = _home(_ctx(tcg_report=report, home_feed_data={"iphone": _iphone(events=evs)}))
    assert h.index("data-nu-feed") < h.index('id="nu-genres"')        # 先頭に追加。既存の構成は残る


# ── 壊れた JSON でも HOME は出る ──────────────────────────────

@pytest.mark.parametrize("data", [
    {"iphone": "broken", "camera": [1, 2]},
    {"iphone": {"skus": "x", "events": 3, "research_date": None}, "camera": {"products": [None, 5, {"routes": "r"}]}},
    {"iphone": {"skus": [None, 1, {"identity": "REGISTERED"}], "events": [None, {"type": "BUYBACK_SURGE"}]},
     "camera": {"products": [{"product": "x", "registered": True, "routes": [None, {"route_type": "C"}]}],
                "events": [None, {"type": "WAIT_TO_BUY", "product": "x", "route": "C"}]}},
    None, "x", {},
])
def test_broken_sources_never_break_home(data):
    h = _home(_ctx(home_feed_data=data))
    assert "ジャンルから探す" in h and "nu-feed__sec" not in h


def test_one_broken_card_does_not_hide_the_others():
    comp = _iphone([{"sku": "壊れ", "identity": "REGISTERED", "profit_status": "PROFITABLE", "net_profit": "x",
                     "roi_pct": object()}, _sku()])
    feed = _feed(_ctx(home_feed_data={"iphone": comp}))
    assert _keys(feed) == ["profit_watch"] and "iPhone Duo 1TB" in feed and "壊れ" not in feed


def test_feed_failure_inside_render_returns_empty(monkeypatch):
    monkeypatch.setattr(hf, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert "ジャンルから探す" in _home(_ctx(home_feed_data={"iphone": _iphone()}))


# ── FeedCard ────────────────────────────────────────────────

def test_feedcard_unknown_fields_render_as_dash():
    html = hf._card_html(hf.FeedCard(product="X"), hf._PROFIT_FIELDS)
    assert html.count("<dd>—</dd>") == len(hf._PROFIT_FIELDS)
    assert "None" not in html and "nan" not in html
    assert "—" in hf._card_html(hf.FeedCard(), hf._EVENT_FIELDS)
    c = hf.FeedCard()
    assert (c.product, c.category, c.action, c.buy_source, c.sell_source, c.profit, c.roi, c.status, c.deadline,
            c.checked_at) == (None,) * 10


def test_checked_at_is_the_source_value_not_generation_time():
    comp = _iphone()
    card = hf.card_from_iphone_sku(comp["skus"][0], comp, NOW)
    assert card.checked_at == ROW_CHECKED and card.category == "iPhone"
    feed = _feed(_ctx(home_feed_data={"iphone": comp}))
    assert "2026-11-17" in feed and "2026-11-20" not in feed        # 生成日（NOW）では置き換えない
    lot = _lot(1)
    f = _feed(_ctx(tcg_report={"lotteries": [lot], "events": []}))
    assert f  # 抽選は lottery_card で描く。FeedCard 側の写しは元の値のまま
    from src.content.ui import runtime as rt
    vm = rt.tcg_vm(lot, 0)
    lc = hf.card_from_lottery(vm, rt.derive_runtime_state(vm, NOW), lot, "TCG", 0)
    assert lc.checked_at == lot["last_verified_at"] and lc.category == "TCG"
    cam = _camera()
    cc = hf.card_from_camera_route(cam["products"][0], cam["products"][0]["routes"][0], cam, NOW)
    assert cc.checked_at == "2026-11-18" and cc.category == "カメラ"


# ── 公開物の安全 ────────────────────────────────────────────

def test_no_local_paths_private_or_unsafe_links():
    report = {"lotteries": [_lot(1, application_end=_iso(timedelta(hours=3))), _lot(2)], "events": []}
    ev = [{"type": "BUYBACK_SURGE", "sku": "iPhone Duo 1TB", "shop": "パステック", "from": 480000, "to": 486000}]
    ctx = _ctx(tcg_report=report, home_feed_data={"iphone": _iphone(events=ev), "camera": _camera()})
    root = shell.render_root(ctx)
    assert "/Users/" not in root and ".private" not in root
    feed = _feed(ctx)
    hrefs = re.findall(r'href="([^"]*)"', feed)
    assert hrefs and all(h.startswith(("./", "?", "https://")) for h in hrefs), hrefs
    assert "javascript:" not in feed.lower()
    assert "./iphone-buyback.html" in feed and "./camera-research.html" in feed


def test_html_is_escaped():
    comp = _iphone([_sku('<script>alert(1)</script>')])
    feed = _feed(_ctx(home_feed_data={"iphone": comp}))
    assert "<script>alert(1)" not in feed and "&lt;script&gt;" in feed


def test_load_sources_reads_only_the_two_documents():
    calls = []

    def loader(*parts):
        calls.append(parts)
        return {"x": 1}
    out = hf.load_sources(loader)
    assert set(out) == {"iphone", "camera"}
    assert calls == [("iphone_buyback", "iphone_buyback_comparison.json"),
                     ("camera_research", "camera_market.json")]
    assert copy.deepcopy(out) == out


# ── 監査の指摘の回帰: BUY でない黒字は「今日の利益商品」に出さない・新着は他の節と重ねない ──
def test_only_buy_decisions_appear_in_todays_profit_and_watch_is_separate():
    buy = _sku("iPhone Duo 2TB")
    buy["opportunity_status"] = "BUY"
    feed = _feed(_ctx(home_feed_data={"iphone": _iphone([buy, _sku()])}))
    assert _keys(feed) == ["profit", "profit_watch"]
    top = feed[feed.index('data-nu-feed-sec="profit"'):feed.index('data-nu-feed-sec="profit_watch"')]
    assert "iPhone Duo 2TB" in top and "iPhone Duo 1TB" not in top                    # 様子見は上の節に出ない
    assert "週次の Web 調査" in feed                                                    # 7 日以内でも週次の価格であることを示す


def test_new_lottery_is_not_repeated_in_open_or_ending():
    report = {"lotteries": [_lot(1, published_at=_iso(-timedelta(hours=5)))], "events": []}        # 受付中かつ新着
    feed = _feed(_ctx(tcg_report=report))
    assert _keys(feed) == ["open"]
