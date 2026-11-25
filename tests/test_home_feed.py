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
         "buy": {"source": "店A", "price": 222000, "freshness": "FRESH", "checked_at": "2026-11-18", "stock": "AVAILABLE"},
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
    assert _keys(feed) == ["profit_watch"]                          # 既定の SKU は判定が WAIT の黒字 → 「利益商品」ではなく様子見の枠
    assert "利益商品" not in feed and "黒字だが買いの条件に届いていない" in feed
    assert "0件" not in feed and "0 件" not in feed
    for title in ("今日やるべきこと", "締切間近", "現在受付中", "新着抽選", "最新発売", "買取価格上昇", "様子見 → 購入候補", "購入候補 → 様子見"):
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
    assert _keys(feed) == ["hero", "open"]                           # 締切間近の抽選は「今日やるべきこと」へ出す（下の節からは外す）
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
    assert _keys(feed) == ["hero"] and "RICOH GR IV HDF" in feed and "+¥16,200（7.3%）" in feed   # 購入候補は「今日やるべきこと」へ
    d = _feed(_ctx(home_feed_data={"camera": _camera([_route("D")])}))
    assert _keys(d) == ["hero"]


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


@pytest.mark.parametrize("cause", ["SELL_BASIS_CHANGED", "EVIDENCE_EXPIRED"])
def test_camera_event_with_cause_is_not_a_price_move_card(cause):
    """売値の根拠の切替・確認の失効（cause 付き）は市場の値動きではない。「買取上昇」カードにしない。"""
    evs = [{"type": "BUYBACK_SURGE", "product": "RICOH GR IV HDF", "market_type": "buyback", "source": "kt",
            "from": 181000, "to": 211000, "cause": cause}]
    assert "data-nu-feed" not in _home(_ctx(home_feed_data={"camera": _camera([], True, evs)}))
    ok = [dict(evs[0])]
    ok[0].pop("cause")
    assert _keys(_feed(_ctx(home_feed_data={"camera": _camera([], True, ok)}))) == ["surge"]    # cause が無ければ従来どおり出る


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
    # 締切間近（lot1）は購入候補が無いのでヒーローへ。順: 今日やるべきこと → … → 新着 → 受付中 → 様子見 → 最新発売 → 買取変動
    assert _keys(feed) == ["hero", "new", "open", "profit_watch", "release", "surge", "w2b", "b2w"]
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
    buy = _buy_sku("iPhone Duo 2TB")
    feed = _feed(_ctx(home_feed_data={"iphone": _iphone([buy, _sku()])}))
    assert _keys(feed) == ["hero", "profit_watch"]                                    # 購入候補 1 件はヒーローへ
    top = feed[feed.index('data-nu-feed-sec="hero"'):feed.index('data-nu-feed-sec="profit_watch"')]
    assert "iPhone Duo 2TB" in top and "iPhone Duo 1TB" not in top                    # 様子見は上の節に出ない
    assert "週次の Web 調査" in feed                                                    # 7 日以内でも週次の価格であることを示す


def test_new_lottery_is_not_repeated_in_open_or_ending():
    report = {"lotteries": [_lot(1, published_at=_iso(-timedelta(hours=5)))], "events": []}        # 受付中かつ新着
    feed = _feed(_ctx(tcg_report=report))
    assert _keys(feed) == ["open"]


# ── 今日のアクション（サマリー）・ヒーロー・表示語・色 ───────────────────────────

def _today(ctx) -> str:
    h = _home(ctx)
    s = h.index("data-nu-today")
    return h[s:h.index("</nav>", h.index("nu-hjump"))]


def _buy_sku(name, **kw):
    s = _sku(name, **kw)
    s["opportunity_status"] = "BUY"
    # 購入候補の期限は Apple の購入可否の確認から 2 日（HOME は生成時点で期限切れなら緑にしない）。NOW の前日に確認した固定値
    s.setdefault("apple_availability", {"status": "BUYABLE"})
    s["apple_availability"] = {**s["apple_availability"], "checked_at": "2026-11-19T18:00:00+09:00"}
    return s


def test_today_summary_always_shown_and_zero_is_a_dash_not_zero_ken():
    h = _home(_ctx())                                                # 入力が空でもサマリーは出る（フィードは出ない）
    assert "data-nu-today" in h and "data-nu-feed" not in h.replace("data-nu-today", "")
    assert "現在、購入候補の条件を満たす商品はありません" not in h   # タイルの「該当なし」で足りる（文は出さない）
    assert "抽選・予約の受付状況は下のジャンルから確認できます" in h
    t = _today(_ctx())
    assert "0件" not in t and "0 件" not in t and t.count("該当なし") == 4
    for label in ("購入候補", "締切間近", "受付中", "様子見"):
        assert label in t
    assert "nu-card" not in t                                        # feed の外に nu-card を置かない
    assert "今日の状況" in t and "今日のアクション" not in h           # サマリー見出しとヒーロー見出し「今日やるべきこと」を分ける
    assert re.findall(r'class="nu-today__tile nu-today__tile--\w+ nu-today__tile--zero"', t).__len__() == 4


def test_h1_is_action_oriented_and_genre_shortcuts_follow_the_summary():
    h = _home(_ctx())
    title = h[h.index('id="nu-home-title"'):h.index("</h1>")]
    assert "今日の判断" in title and "ジャンルから探す" not in title
    nav = h[h.index("nu-hjump"):h.index("</nav>", h.index("nu-hjump"))]
    assert h.index("data-nu-today") < h.index("nu-hjump") < h.index('id="nu-genres"')   # ジャンルより上に近道がある
    assert 'href="./#nu-genres"' in nav and 'href="./#nu-purposes-h"' in nav and 'id="nu-purposes-h"' in h
    # 抽選・予約への近道は置かない（同じ行き先を 1 画面に何度も並べない。目的から探す・ナビが担う）
    assert "page=lottery" not in nav
    # 近道は 44px 以上の操作部品（CSS）
    css = shell.styles.css() if hasattr(shell, "styles") else __import__("src.content.ui.styles", fromlist=["x"]).css()
    assert re.search(r"\.nu-hjump__a\{[^}]*min-height:var\(--tap-min\)", css)


def test_notices_are_merged_into_one_block_under_the_tiles_in_priority_order():
    h = _home(_ctx(source_issue=True))
    assert h.count("nu-today__notes") == 1 and "nu-notice" not in h   # 別立ての注意バナーは出さない
    block = h[h.index("nu-today__notes"):h.index("nu-hjump")]
    order = [block.index(x) for x in ("一部の情報源を取得できていません", "件数はページ生成時点")]
    assert order == sorted(order)                                    # 重要度の高い順
    assert block.count("<p ") <= 2                                   # 注意は最大 2 行
    assert h.index("nu-today__tiles") < h.index("nu-today__notes")
    # 情報源の問題が無ければその行は出ない
    assert "一部の情報源" not in _home(_ctx())


def test_actionable_line_is_hidden_when_zero_but_kept_by_default():
    from types import SimpleNamespace
    from src.content.ui import pages
    empty = SimpleNamespace(opportunity_set=None)
    assert pages._actionable_line(empty, hide_zero=True) == ""        # 0 件の行は出さない（「0件」を増やさない）
    assert "0件" in pages._actionable_line(empty) and "data-nu-act-untils=" in pages._actionable_line(empty)
    assert "nu-home-act" not in _home(_ctx())


def test_today_summary_counts_and_jump_targets():
    report = {"lotteries": [_lot(1, application_end=_iso(timedelta(hours=3))), _lot(2), _lot(3)], "events": []}
    ctx = _ctx(tcg_report=report, home_feed_data={"iphone": _iphone([_buy_sku("iPhone Duo 2TB"), _sku()])})
    t = _today(ctx)
    tiles = re.findall(r'nu-today__tile nu-today__tile--(\w+)[^"]*" href="([^"]+)"[^>]*>.*?nu-today__n"[^>]*>(\d+)', t)
    got = {k: (href, n) for k, href, n in tiles}
    assert got["buy"] == ("./#nu-sec-hero", "1")                     # ヒーローへ移した購入候補も数える
    assert got["end"] == ("./#nu-sec-hero", "1")                     # 締切間近の抽選もヒーロー（購入候補 1 + 締切間近 1）
    assert got["open"] == ("./#nu-sec-open", "2")
    assert got["wait"] == ("./#nu-sec-profit_watch", "1")
    assert 'id="nu-sec-hero"' in _home(ctx) and 'id="nu-sec-profit_watch"' in _home(ctx)
    assert "現在、購入候補の条件を満たす商品はありません" not in t


def test_open_tile_says_it_excludes_ending_soon_and_targets_match_counts():
    report = {"lotteries": [_lot(1, application_end=_iso(timedelta(hours=3))),
                            _lot(2, application_end=_iso(timedelta(hours=4))),
                            _lot(3, application_end=_iso(timedelta(hours=5))), _lot(4)], "events": []}
    ctx = _ctx(tcg_report=report)
    t = _today(ctx)
    open_tile = t[t.index("nu-today__tile--open"):t.index("</li>", t.index("nu-today__tile--open"))]
    assert "締切間近を除く" in open_tile and ">1<" in open_tile        # 受付中は 1 件（締切間近の 3 件は含めない）
    end_tile = t[t.index("nu-today__tile--end"):t.index("</li>", t.index("nu-today__tile--end"))]
    assert ">3<" in end_tile and 'href="./#nu-sec-hero"' in end_tile   # ヒーローへ移した 2 件も数え、そこへ飛ぶ（残り 1 件は下の節）
    assert 'id="nu-sec-hero"' in _home(ctx) and 'id="nu-sec-ending"' in _home(ctx)
    zero = _today(_ctx())
    assert "締切間近を除く" not in zero                                  # 0 件のタイルには付けない


def test_hero_has_only_buy_and_ending_and_at_most_two_and_moves_them_down():
    report = {"lotteries": [_lot(1, application_end=_iso(timedelta(hours=3))),
                            _lot(2, application_end=_iso(timedelta(hours=4)))], "events": []}
    buys = [_buy_sku(f"iPhone Duo {i}TB", net_profit=1000 + i * 1000) for i in (1, 2, 3)]
    feed = _feed(_ctx(tcg_report=report, home_feed_data={"iphone": _iphone(buys + [_sku("iPhone Duo 9TB")])}))
    assert _keys(feed)[:3] == ["hero", "profit", "ending"]
    hero = feed[feed.index('data-nu-feed-sec="hero"'):feed.index('data-nu-feed-sec="profit"')]
    assert hero.count("<li ") == hf.HERO_MAX == 2
    assert "iPhone Duo 3TB" in hero and "ポケカ抽選1" in hero          # 利益の最大の購入候補 + 最も締切の近い抽選
    assert "iPhone Duo 9TB" not in hero                              # 様子見は上げない
    rest = feed[feed.index('data-nu-feed-sec="profit"'):]
    assert "iPhone Duo 3TB" not in rest.split('data-nu-feed-sec="profit_watch"')[0]   # 重複しない
    assert "ポケカ抽選2" in feed[feed.index('data-nu-feed-sec="ending"'):]


def test_unconfirmed_and_stale_are_never_actionable_buys():
    """要確認・古い調査は購入候補として数えない（サマリー件数とヒーローの対象外）。"""
    unconfirmed = hf.FeedCard(product="X", category="カメラ", action="要確認", profit=5000, roi=0.1)
    old = hf.FeedCard(product="Y", category="iPhone", action="買い", profit=5000, roi=0.1, note="調査から10日")
    fresh = hf.FeedCard(product="Z", category="iPhone", action="購入可", profit=5000, roi=0.1)
    assert hf.card_tone(unconfirmed) == "neutral" and not hf.is_buy(unconfirmed)
    assert hf.is_buy(old) and not hf.is_actionable_buy(old)
    assert hf.is_actionable_buy(fresh)
    ctx = _ctx(home_feed_data={"camera": _camera()})
    assert 'data-nu-feed-sec="hero"' in _feed(ctx)                   # 購入候補（買い）は上がる


def test_display_words_and_colors():
    buy = hf.FeedCard(product="A", action="購入可", profit=1000, roi=0.1)
    old = hf.FeedCard(product="A", action="買い", profit=1000, roi=0.1, note="調査から10日")
    wait = hf.FeedCard(product="A", action="様子見", profit=1000, roi=0.05)
    chk = hf.FeedCard(product="A", action="要確認")
    assert hf.card_tone(buy) == "success" and hf.card_tone(wait) == "warning"
    assert hf.card_tone(old) == "neutral" and hf.card_tone(chk) == "neutral"        # 古い調査は灰
    h = hf._card_html(buy, hf._PROFIT_FIELDS, "std")
    assert "購入候補" in h and "購入可" not in h and "nu-tone-success" in h and "黒字" in h
    assert "nu-fc--stale" in hf._card_html(old, hf._PROFIT_FIELDS, "std")
    assert "nu-tone-warning" in hf._card_html(wait, hf._PROFIT_FIELDS, "std") and "様子見" in hf._card_html(wait, hf._PROFIT_FIELDS, "std")
    assert "BUY" not in h and "WAIT" not in h and "PROFITABLE" not in h


def test_card_kinds_and_best_route_row():
    c = hf.FeedCard(product="A", category="iPhone", action="購入可", buy_source="Apple 公式", sell_source="店B",
                    profit=11400, roi=0.0243, checked_at="2026-11-17")
    for kind in ("hero", "std", "compact"):
        assert f"nu-fc--{kind}" in hf._card_html(c, hf._PROFIT_FIELDS, kind)
    std = hf._card_html(c, hf._PROFIT_FIELDS, "std")
    assert "最適ルート</dt><dd>Apple 公式 → 店B" in std and "確認日</dt><dd>2026-11-17" in std
    assert std.count("+¥11,400") == 1                                # 利益は大きな 1 行だけ（dl と重ねない）
    compact = hf._card_html(c, hf._EVENT_FIELDS, "compact")
    assert "nu-fc__profit" not in compact and "利益の見込み" in compact


def test_green_is_only_for_buy_candidates_in_amounts_and_chips():
    """様子見・要確認・古い調査の金額と「黒字」チップは緑にしない（CSS は tone ごとに色を決める）。"""
    from src.content.ui import styles
    css = styles.css()
    base = re.search(r"\.nu-fc__profit\{([^}]*)\}", css).group(1)
    assert "color:var(--color-text)" in base and "tone-success" not in base
    assert re.search(r"\.nu-fc--success \.nu-fc__profit\{color:var\(--tone-success-fg\)\}", css)
    tag = re.search(r"\.nu-fc__tag\{([^}]*)\}", css).group(1)
    assert "tone-success" not in tag
    assert re.search(r"\.nu-fc--warning \.nu-fc__tag\{[^}]*tone-warning-fg", css)
    wait = hf._card_html(hf.FeedCard(product="A", action="様子見", profit=1000, roi=0.05), hf._PROFIT_FIELDS, "std")
    old = hf._card_html(hf.FeedCard(product="A", action="買い", profit=1000, roi=0.1, note="調査から10日"), hf._PROFIT_FIELDS, "std")
    buy = hf._card_html(hf.FeedCard(product="A", action="購入可", profit=1000, roi=0.1), hf._PROFIT_FIELDS, "std")
    assert "nu-fc--warning" in wait and "nu-fc--success" not in wait
    assert "nu-fc--neutral" in old and "nu-fc--success" not in old
    assert "nu-fc--success" in buy


def test_one_main_button_per_card_and_no_duplicate_links():
    c = hf.FeedCard(product="A", category="iPhone", action="購入可", profit=1000, roi=0.1, href="./iphone-buyback.html")
    hero = hf._card_html(c, hf._PROFIT_FIELDS, "hero")
    std = hf._card_html(c, hf._PROFIT_FIELDS, "std")
    compact = hf._card_html(c, hf._EVENT_FIELDS, "compact")
    assert all(h.count("<a ") == 1 and "詳細と情報元を見る" in h for h in (hero, std, compact))
    assert "nu-btn--primary" in hero and "nu-btn--secondary" in std and "nu-btn--link" in compact
    # 同じ行き先は 1 節に 1 つだけ（様子見の節: base_link・iPhone 買取比較・カードのボタンが同じ → カードのボタンだけ残す）
    feed = _feed(_ctx(home_feed_data={"iphone": _iphone()}))
    assert feed.count('href="./iphone-buyback.html"') == feed.count("詳細と情報元を見る") == 1
    # 抽選の節は「抽選・予約をすべて見る」だけ（TCG 抽選ハブと二重に出さない）
    lot = _feed(_ctx(tcg_report={"lotteries": [_lot(2), _lot(3)], "events": []}))
    assert "抽選・予約をすべて見る" in lot and "TCG 抽選ハブ" not in lot


# ── 独立審査の指摘（HOME と他 3 ページの一体感・CTA の重複・未確認の購入候補） ──────────────

def test_wait_to_buy_event_is_not_green_unless_a_verified_buy_exists():
    ev = [{"type": "WAIT_TO_BUY", "sku": "iPhone Duo 1TB", "from": "WAIT", "to": "BUY", "net": 30000}]
    feed = _feed(_ctx(home_feed_data={"iphone": _iphone(events=ev)}))
    sec = feed[feed.index("nu-feed__sec--w2b"):]
    assert "nu-tone-success" not in sec and "nu-fc--success" not in sec          # 実行可能・FRESH の確認が無い → 緑にしない
    assert "購入候補に変化" in sec and "購入できるかは未確認" in sec and "様子見 → 購入候補" in sec
    assert "BUY" not in sec and "WAIT" not in sec                               # 旧語は HOME に出さない
    # 同じ商品が確認済みの購入候補（利益商品）にもいるなら緑のまま
    sku = _buy_sku("iPhone Duo 1TB")
    feed = _feed(_ctx(home_feed_data={"iphone": _iphone(skus=[sku], events=ev)}))
    assert "nu-fc--success" in feed[feed.index("nu-feed__sec--w2b"):]
    assert hf.card_tone(hf.FeedCard(action="買い", unverified=True)) == "info"


def test_plain_words_replace_judgement_codes_on_home():
    assert hf.plain_reason("黒字だが ROI が BUY の条件（8%）未満") == "黒字だが ROI が購入候補の条件（8%）未満"
    assert hf.judge_word("WAIT") == "様子見" and hf.judge_word("BUY") == "購入候補" and hf.judge_word(None) == "—"
    feed = _feed(_ctx(home_feed_data={"iphone": _iphone()}))
    assert "BUY" not in feed and "WAIT" not in feed


def test_lottery_all_link_appears_once_in_the_feed_and_zero_tile_is_one_word():
    lots = [_lot(2), _lot(3), _lot(4)]
    feed = _feed(_ctx(tcg_report={"lotteries": lots, "events": []}))
    assert feed.count('href="?page=lottery"') <= 1
    t = _today(_ctx())
    assert 'nu-today__n">—<' not in t and t.count("該当なし") == 4


def test_home_has_dark_theme_and_header_matches_site_nav():
    from src.content.ui import design_tokens as dt, shared_css
    from src.content.ui import styles
    css = styles.css()
    legacy = shared_css.legacy_css()
    # ダーク: 他ページと同じ条件（prefers-color-scheme:dark・data-theme=light で無効）・同じトークン値
    assert dt.dark_variables() in css and dt.dark_variables() in legacy
    assert '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) #new-ui-root{' in css
    assert f"background:{dt.DARK_BASE_COLORS['bg']}" in css
    # フォントスタックは HOME・他ページで同じ値（正本は design_tokens.FONT_STACK）
    assert dt.FONT_STACK in css and dt.FONT_STACK in legacy
    # ヘッダーのリンクは site_nav と同じピル型（枠・角丸・primary の現在地）
    assert re.search(r"\.nu-topnav__link\{[^}]*border:1px solid var\(--color-border-strong\);border-radius:var\(--radius-sm\)", css)
    assert ".nu-topnav__link[aria-current=page]{background:var(--color-primary)" in css
    # 他ページ向けの共通クラス: 様子見の利益は中立色
    assert ".is-wait .pos" in legacy and ".sbadge--profit-neutral" in legacy


# ── 購入候補の閲覧時の期限（actionable は生成時の判定。期限を過ぎたら緑の購入候補を残さない） ──────────

class _Act:
    def __init__(self, ok=True, until=None):
        self.actionable, self.until_ms = ok, until


class _View:
    def __init__(self, act):
        self.product_name, self.category, self.buy_source, self.sell_source = "テスト商品", "tcg", "店A", "店B"
        self.net_profit, self.roi, self.stock_label = 3000, 0.2, "在庫あり"
        self.last_verified_at = "2026-11-25T10:00:00+09:00"
        self.action = act

    @property
    def actionable(self):
        return bool(self.action is not None and self.action.actionable)


def _now():
    return datetime(2026, 11, 25, 12, 0, tzinfo=JST)


def test_actionable_card_carries_until_and_badge_has_expiry_attributes():
    card = hf.card_from_view(_View(_Act(True, 1764000000000)), _now())
    assert card.until_ms == 1764000000000
    html = hf._card_html(card, hf._PROFIT_FIELDS, "hero")
    assert 'data-nu-pd-until="1764000000000"' in html and 'data-nu-pd-stale-text="更新待ち"' in html
    assert 'nu-tone-neutral' in html.split('data-nu-pd-stale-class="')[1].split('"')[0]


@pytest.mark.parametrize("act", [_Act(False, None), None])
def test_non_actionable_view_is_not_a_buy_and_has_no_until(act):
    card = hf.card_from_view(_View(act), _now())
    assert card.until_ms is None and not hf.is_buy(card)
    assert "data-nu-pd-until" not in hf._card_html(card, hf._PROFIT_FIELDS, "std")


def test_unverified_or_reference_buy_has_no_expiry_attribute():
    card = hf.FeedCard(product="W", category="iPhone", action="買い", profit=1000, roi=0.1, unverified=True, until_ms=1)
    assert "data-nu-pd-until" not in hf._card_html(card, hf._PROFIT_FIELDS, "std")


def test_buy_tile_recounts_in_browser_and_runtime_handles_expiry():
    html = hf.render_today([], {"buy": 2, "buy_untils": "1764000000000,inf"})
    assert 'data-nu-buy-untils="1764000000000,inf"' in html
    assert "data-nu-buy-untils" not in hf.render_today([], {"buy": 1})          # 期限が無ければ従来どおり
    js = shell.SCRIPT if hasattr(shell, "SCRIPT") else open(shell.__file__, encoding="utf-8").read()
    assert ".nu-fc [data-nu-pd-until]" in js and "data-nu-buy-untils" in js and "nu-fc--success" in js


def test_build_counts_expose_until_tokens_only_for_actionable_buys():
    class _Set:
        eligible = [_View(_Act(True, 1764000000000)), _View(_Act(False, None))]
    _Set.eligible[1].product_name = "別商品"
    cat = type("C", (), {"opportunity_set": _Set})()
    _s, counts = hf.build_with_counts(cat, None, {}, {}, _now())
    assert counts["buy"] == 1 and counts["buy_untils"] == "1764000000000"
