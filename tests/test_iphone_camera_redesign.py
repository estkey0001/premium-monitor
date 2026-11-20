"""iPhone 商品ハブ・カメラ判断ページの再設計（表示層だけ）の固定。ヒーロー/カード/バッジ/スパークライン/旧語の残し方。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.content import camera_market_page as C
from src.content import iphone_buyback_page as P
from src.content import iphone_hub_model as H
from tests.test_iphone_hub import NOW, _comp, _row, _simple, _sku

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))


def test_hero_comes_first_and_old_words_stay_in_details():
    html = P.render(_simple(), now=NOW)
    card = html[html.index('<section class="sku"><h3>iPhone Duo 1TB'):]
    card = card[:card.index("</section>")]
    assert card.index('class="hero"') < card.index('<details class="spec">')
    hero = card[card.index('class="hero"'):card.index('<details class="spec">')]
    for w in ("Apple 価格", "最高買取", "純利益", "ROI", "判定（週次）", "様子見"):
        assert w in hero
    assert "WAIT（待ち）" not in hero and "PROFITABLE" not in hero                  # 旧語は詳細側
    assert "WAIT（待ち）" in card and "PROFITABLE" in card
    assert 'class="pos"' not in hero and "sbadge--profit" not in hero               # 様子見の黒字は緑にしない（中立色。HOME と同じ）
    assert "sbadge--wait" in hero and "sbadge--buy" not in hero


def test_reference_hero_is_never_green_even_when_buy():
    comp = _simple()
    ref = comp["skus"][2]
    ref["opportunity_status"] = "BUY"
    html = P.render(_comp([ref]), now=NOW).split("</style>")[-1]
    assert 'class="pos"' not in html and "sbadge--buy" not in html


def test_buy_status_uses_new_word_for_registered():
    c = _comp([_sku("iPhone Duo 1TB", hx={"shop": "店A", "price": 483000}, net=40000, roi=9.0, opp="BUY",
                    rows=[_row("iPhone Duo 1TB", "a", "店A", 483000)])])
    html = P.render(c, now=NOW).split("</style>")[-1]
    assert "購入候補" in html and "sbadge--buy" in html and ">BUY<" not in html


def test_stale_rows_are_weak_and_diff_is_display_only():
    html = P.render(_simple(), now=NOW)
    assert 'class="ng is-stale"' in html and "古い店" in html
    s = _simple()["skus"][0]
    rows = [_row("iPhone Duo 1TB", "a", "店A", 483000), _row("iPhone Duo 1TB", "b", "店B", 475000)]
    s["rows"] = rows
    h = P._sku_html(s)
    assert "−¥8,000" in h and "基準（1 位）" in h and "差額（1位比）" in h
    assert h.index("<th>順位</th>") < h.index("<th>買取店</th>") < h.index(">買取価格</th>") < h.index(">差額（1位比）</th>")
    assert 'data-label="買取価格"' in h and "nu-table--stack" in h
    assert "1 位" in h and "2 位" in h and "3 位" not in h


def test_row_html_escapes_new_attributes():
    h = P._row_html({"shop": '"><b>x</b>', "shop_status": "ACTIVE", "condition": "UNOPENED", "freshness": "STALE", "basis": "uniform",
                     "listed_price": 1, "executable_price": 1, "eligible": False, "updated_on": '"><i>'}, None, None)
    assert "<b>x</b>" not in h and "<i>" not in h


def test_spark_layout_cuts_lines_when_shop_count_changes_and_skips_single_point():
    t = [{"date": "d1", "best_price": 100, "shops": 3}, {"date": "d2", "best_price": 110, "shops": 3},
         {"date": "d3", "best_price": 90, "shops": 2}]
    lay = H.spark_layout(t)
    assert lay["status"] == "OK" and len(lay["dots"]) == 3 and len(lay["segments"]) == 1 and len(lay["segments"][0]) == 2
    assert H.spark_layout(t[:1])["status"] == "ONE" and H.spark_layout([])["status"] == "NONE"
    assert H.spark_layout([{"date": "x", "best_price": None, "shops": 0}])["status"] == "NONE"
    assert P._sparkline(H.spark_layout(t[:1])) == ""


def test_page_draws_sparkline_only_with_two_points():
    s = _simple()
    hist = {"snapshots": [{"date": "2026-11-10", "rows": [
        {"sku": "iPhone Duo 1TB", "key": "a", "shop": "店A", "price": 480000, "net": 1, "identity": "REGISTERED"},
        {"sku": "iPhone Duo 1TB", "key": "b", "shop": "店B", "price": 470000, "net": None, "identity": "REGISTERED"}]}]}
    html = P.render(s, now=NOW, history=hist)
    assert '<svg class="spark"' in html and "最高買取の推移" in html and "履歴の表" in html
    svg = html[html.index('<svg class="spark"'):html.index("</svg>", html.index('<svg class="spark"'))]
    assert "11/10 ¥480,000" in svg and "11/17 ¥483,000" in svg and "48.3万" in svg and "<polyline" in svg   # 端点に日付と金額、軸ラベル
    one = P.render(s, now=NOW, history={"snapshots": []})
    assert '<svg class="spark"' not in one


def test_pages_use_shared_nav_and_css():
    assert 'class="site-nav"' in P.render(_simple(), now=NOW) and 'aria-current="page"' in P.render(_simple(), now=NOW)
    assert ":root{" in P.render(_simple(), now=NOW).split("</style>")[0]


def _market():
    p = ROOT / "exports" / "camera_research" / "camera_market.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_camera_cards_route_words_and_minus_sign():
    m = _market()
    if m is None:
        return
    html = C.render(m, now=datetime(2026, 11, 20, 12, 0, tzinfo=JST))
    assert html.index("判断カード") < html.index("判断一覧") < html.index("価格の種類ごとの確認状況")
    assert 'class="dcard' in html and "Route" in html and "正規店→買取" in html
    assert "<th>費用</th>" in html and 'aria-current="page"' in html
    assert ">A</td>" not in html and "ROI</span><b>-" not in html and "-20.27%" not in html


def test_camera_route_short_and_roi_sign():
    assert C.ROUTE_SHORT == {"A": "正規店→買取", "B": "正規店→二次流通", "C": "二次流通→買取", "D": "二次流通→二次流通"}
    assert C._roi(-4.06) == "−4.06%" and C._roi(7.3) == "7.3%" and C._roi(None) == "—"


def test_camera_decision_badge_is_separate_from_profit_badge():
    loss = {"decision": "SKIP", "net_profit": -100, "profit_status": "NO_PROFIT"}
    assert "見送り" in C._decision_badge(loss, False) and "赤字" in C._profit_badge(loss) and "赤字" not in C._decision_badge(loss, False)
    wait_profit = {"decision": "WAIT", "net_profit": 16200, "profit_status": "PROFITABLE"}
    assert "sbadge--wait" in C._decision_badge(wait_profit, False) and "sbadge--profit" not in C._profit_badge(wait_profit)   # 様子見の黒字は中立色
    assert "黒字" in C._profit_badge(wait_profit)
    buy = {"decision": "BUY", "net_profit": 5, "profit_status": "PROFITABLE"}
    assert "購入候補" in C._decision_badge(buy, False) and "sbadge--buy" in C._decision_badge(buy, False)
    assert "sbadge--profit" in C._profit_badge(buy) and "sbadge--profit" not in C._profit_badge(buy, True, True)   # 緑は購入候補（登録済み・調査が新しい）だけ
    assert "調査が古い" in C._decision_badge(buy, True) and "sbadge--buy" not in C._decision_badge(buy, True)
    assert "sbadge--buy" not in C._decision_badge(buy, False, registered=False)


def _visible(html: str) -> str:
    """本文として見える文字（details・svg・style は除く）。"""
    import re
    b = html.split("</style>")[-1]
    b = re.sub(r"<details.*?</details>", "", b, flags=re.S)
    b = re.sub(r"<svg.*?</svg>", "", b, flags=re.S)
    return re.sub(r"<[^>]+>", " ", b)


def test_top_summary_follows_h1_and_is_honest_about_wait():
    html = P.render(_simple(), now=NOW)
    after = html[html.index("</h1>"):]
    assert after[5:].lstrip().startswith('<section class="today"')
    today = after[:after.index("</section>")]
    assert "今日のおすすめ" in today and "iPhone Duo 1TB" in today and "様子見" in today and "¥483,000" in today
    assert "を買い" not in today and 'class="hero"' in today
    none = P.render(_comp([_sku("iPhone Duo 256GB", opp="PASS")]), now=NOW)
    assert "確認待ち" in none[none.index('<section class="today"'):none.index("</section>")]


def test_internal_identifiers_are_not_bare_in_body_text():
    import re
    ids = r"\b(FRESH|STALE|OUTLIER_REVIEW|SINGLE_SOURCE|DISCOVERED|INFERENCE|UNKNOWN_FRESHNESS|REGISTERED|PROFITABLE)\b"
    assert not re.search(ids, _visible(P.render(_simple(), now=NOW)))
    comp = ROOT / "exports" / "iphone_buyback" / "iphone_buyback_comparison.json"
    if comp.exists():
        t = _visible(P.render(json.loads(comp.read_text(encoding="utf-8")), now=NOW))
        assert not re.search(ids, t)
    html = P.render(_simple(), now=NOW)
    assert "PROFITABLE" in html and "掲載の最高値" in html and "まだ監視対象に登録していない機種" in html          # 識別子は詳細側・title に残す


def test_history_single_point_shows_big_prev_compare_without_orphan_dot():
    h = {"snapshots": [{"date": "2026-11-10", "rows": [{"sku": "iPhone Duo 1TB", "key": "a", "shop": "店A", "price": 480000,
                                                       "net": 1, "identity": "REGISTERED"}]}]}
    html = P.render(_simple(), now=NOW, history=h)        # 前回は 1 店・今回は 2 店 → 線は結べない
    assert '<svg class="spark"' not in html and 'class="prevbig"' in html
    only = P.render(_simple(), now=NOW, history={"snapshots": []})
    assert '<svg class="spark"' not in only and "前回の記録なし" in only


def test_css_has_no_text_under_12px_and_tap_targets():
    import re
    css = P.CSS + P.HUB_CSS
    for v in re.findall(r"font-size:\.(\d+)rem", css):
        assert float("0." + v) >= 0.75, v
    for v in re.findall(r"font-size:(\d+)px", css):
        assert int(v) >= 12
    assert "min-height:44px" in css and "summary{padding:10px 0}" in css


def test_unregistered_never_green_in_camera_card_and_verdict():
    reg_off = {"decision": "BUY", "net_profit": 5000, "profit_status": "PROFITABLE"}
    assert "sbadge--profit" not in C._profit_badge(reg_off, registered=False)
    v = C._verdict([({"product": "X", "registered": False},
                     {"decision": "BUY", "net_profit": 5000, "buy": {"stock": "AVAILABLE"}}, False)])
    assert "今日買えるもの" not in v and "sbadge--buy" not in v


def test_camera_verdict_bar_card_order_and_no_english_identifiers():
    import re
    m = _market()
    if m is None:
        return
    html = C.render(m, now=datetime(2026, 11, 20, 12, 0, tzinfo=JST))
    assert html.index('class="verdict"') < html.index("判断カード")
    assert "黒字" in html[html.index('class="verdict"'):html.index("判断カード")]
    body = html.split('class="dcard')
    first_profit = next((i for i, b in enumerate(body) if "sbadge--profit" in b.split("</header>")[0]), None)
    first_loss = next((i for i, b in enumerate(body) if "sbadge--loss" in b.split("</header>")[0]), None)
    if first_profit and first_loss:
        assert first_profit < first_loss                            # 黒字が赤字より先
    t = _visible(html)
    assert not re.search(r"\b(SKIP|WAIT|NOT_CALCULATED|conditional_price|checked_at|confidence|Primary Market|Secondary Listings)\b", t)
    assert "Route A" not in t and "<th>費用</th>" in html
    assert 'class="nu-table--stack' in html and html.count("<table>") == 0       # 表は全部カード化できる形


# ---- 独立審査の指摘への対応（表示だけ） ----
import re as _re

_ID_RE = _re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b|\bRoute [A-D]\b|ルート [A-D]\b|\b(?:FRESH|STALE|WATCH|SKIP|PASS|LISTING|SOLD|DISCOVERED|REGISTERED|PROFITABLE)\b")


def _body_text(html: str) -> str:
    """details・svg・style と属性（title など）を除いた、画面に直接見える文字。"""
    return _visible(html)


def _iphone_real():
    p = ROOT / "exports" / "iphone_buyback" / "iphone_buyback_comparison.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_camera_never_shows_route_symbols_outside_details():
    m = _market()
    if m is None:
        return
    html = C.render(m, now=datetime(2026, 11, 20, 12, 0, tzinfo=JST))
    t = _body_text(html)
    assert not _re.search(r"Route|ルート [A-D]|ルート\s*[A-D]\b|[A-D]=", t)
    assert "正規店→買取" in t or "二次流通→" in t or "正規店→二次流通" in t
    assert "A=正規店→買取" in html and "<details" in html[:html.index("A=正規店→買取")]       # 凡例は details 内の内部参照だけ
    assert 'title="Route' not in html.split('class="dcard')[1].split("<details")[0]               # カードの主要部に Route の title も出さない


def test_camera_detail_list_uses_words_not_symbols():
    r = {"route_type": "C", "route_label": "二次流通の最安 → 買取店", "costs": {}, "sell": {"price": 1, "price_type": "BUYBACK_PRICE", "condition": "NEW", "source": "x", "evidence": {}},
         "buy": {"price": 1}, "net_profit": 0, "fee_status": None}
    h = C._detail({"product": "X"}, r)
    assert "二次流通→買取" in h and "ルート C" not in h and "Route" not in h


def test_camera_not_configured_is_plain_outside_details():
    m = _market()
    if m is None:
        return
    html = C.render(m, now=datetime(2026, 11, 20, 12, 0, tzinfo=JST))
    assert "NOT_CONFIGURED" not in _body_text(html)
    assert C.MKT_STATUS["NOT_CONFIGURED"] == "未設定（未取得）" and "NOT_CONFIGURED" not in C.MKT_REASON["official_api_not_configured"]
    fake = {"research_date": "2026-11-18", "products": [], "secondary_markets": [
        {"label": "市場X", "status": "NOT_CONFIGURED", "reason": "official_api_not_configured", "credentials": "NOT_CONFIGURED"}]}
    h = C.render(fake, now=datetime(2026, 11, 20, 12, 0, tzinfo=JST))
    assert "未設定" in h and "NOT_CONFIGURED" not in _body_text(h)       # 市場表は折りたたみ内（本文外）に移した and 'title="NOT_CONFIGURED"' in h       # 原文は title に残す


def test_no_internal_identifiers_in_generated_pages_outside_details():
    now = datetime(2026, 11, 20, 12, 0, tzinfo=JST)
    pages = [P.render(_simple(), now=NOW)]
    comp = _iphone_real()
    if comp is not None:
        pages.append(P.render(comp, now=now))
    m = _market()
    if m is not None:
        pages.append(C.render(m, now=now))
    for h in pages:
        assert not _ID_RE.search(_body_text(h)), _ID_RE.search(_body_text(h)).group(0)


def test_camera_first_screen_is_compact_and_summary_moves_below_cards():
    m = _market()
    if m is None:
        return
    html = C.render(m, now=datetime(2026, 11, 20, 12, 0, tzinfo=JST))
    head = html[html.index("</h1>"):html.index('class="dcard')]
    assert "<details" not in head and 'class="grid"' not in head and len(_re.sub(r"<[^>]+>", "", head)) < 700
    assert html.index('class="dcard') < html.index("この調査について") < html.index('class="grid"')


def test_camera_verdict_plus_count_excludes_unregistered_and_stale():
    reg = ({"product": "R", "registered": True}, {"decision": "WAIT", "net_profit": 5000, "buy": {"stock": "AVAILABLE"}}, False)
    unreg = ({"product": "U", "registered": False}, {"decision": "BUY", "net_profit": 7000, "buy": {"stock": "AVAILABLE"}}, False)
    old = ({"product": "O", "registered": True}, {"decision": "BUY", "net_profit": 9000, "buy": {"stock": "AVAILABLE"}}, True)
    v = C._verdict([reg, unreg, old])
    assert "黒字 1 件" in v and "U（" not in v and "O（" not in v and "参考" in v
    assert "sbadge--profit" not in v and "sbadge--buy" not in v          # 購入候補が無い（様子見だけ）ので緑は出さない
    go = ({"product": "G", "registered": True}, {"decision": "BUY", "net_profit": 3000, "buy": {"stock": "AVAILABLE"}}, False)
    v2 = C._verdict([go])
    assert "sbadge--profit" in v2 and "sbadge--buy" in v2
    assert "黒字 0 件" in C._verdict([unreg, old]) and "sbadge--profit" not in C._verdict([unreg, old])


def test_camera_card_wait_profit_is_neutral():
    p = {"product": "X", "registered": True}
    buy = {"price": 100, "source": "店", "url": "https://e.com/", "price_type": "RETAIL_PRICE", "condition": "NEW", "stock": "AVAILABLE", "checked_at": None}
    sell = {"price": 200, "source": "買取", "url": None, "price_type": "BUYBACK_PRICE"}
    r = {"decision": "WAIT", "net_profit": 5000, "profit_status": "PROFITABLE", "roi_pct": 5.0, "route_type": "A", "buy": buy, "sell": sell,
         "reasons": [], "confidence": "high"}
    h = C._card(p, r, False)
    assert 'class="pos"' not in h and "sbadge--profit" not in h and "sbadge--wait" in h
    assert "確認日 不明" in h and "ルート A" in h.split("<details")[1]                                  # checked_at 無しは「不明」。A は details 内だけ
    r["decision"] = "BUY"
    hb = C._card(p, r, False)
    assert 'class="pos"' in hb and "sbadge--profit" in hb


def test_md_adds_year_for_old_dates_and_unknown_for_empty():
    now = datetime(2026, 11, 20, tzinfo=JST)
    assert ">11/18<" in P._md("2026-11-18", now) and ">2025/11/19<" not in P._md("2026-11-18", now)
    assert ">2025/11/20<" in P._md("2025-11-20", now) and ">11/21<" in P._md("2025-11-21", now)
    assert P._md(None) == "不明" and P._md("") == "不明"


def test_plain_dedupes_repeated_word_and_unifies_watch():
    assert P._plain("更新が古い（STALE）") == "更新が古い" and "更新が古い（更新が古い）" not in P._plain("STALE（更新が古い）")
    assert "様子見（要確認）" in P._plain("WATCH")
    assert P.OPP_LABEL["WATCH"] == C.DECISION["WATCH"]


def _mk(sku, net, opp, hx=True, roi=5.0):
    return _sku(sku, hx={"shop": "店A", "price": 400000 + net} if hx else None, net=net if hx else None, roi=roi if hx else None, opp=opp,
                rows=[_row(sku, "a", "店A", 400000 + net)] if hx else [])


def test_today_prefers_buy_candidate_over_larger_wait_profit():
    big_wait = _mk("iPhone Duo 1TB", 30000, "WAIT")
    small_buy = _mk("iPhone Duo 512GB", 9000, "BUY")
    c = _comp([big_wait, small_buy])
    html = P.render(c, now=NOW)
    today = html[html.index('<section class="today"'):html.index("</section>")]
    assert "iPhone Duo 512GB" in today and "購入候補です" in today and "買ってよいものは" not in today
    assert H.model_conclusion(c["skus"])["status"] == "PROFIT" and H.model_conclusion(c["skus"])["answer"]["capacity"] == "512GB"
    only_wait = P.render(_comp([big_wait]), now=NOW)
    t2 = only_wait[only_wait.index('<section class="today"'):only_wait.index("</section>")]
    assert "様子見" in t2 and "購入候補です" not in t2


def test_today_shows_freshness_warning_before_buy_candidate_when_research_is_old():
    c = _comp([_mk("iPhone Duo 1TB", 9000, "BUY")])
    late = datetime(2026, 12, 5, 10, 0, tzinfo=JST)                    # 調査日 11/17 から 18 日
    html = P.render(c, now=late)
    today = html[html.index('<section class="today"'):html.index("</section>")]
    assert "調査が古い" in today and "購入候補です" not in today and "sbadge--buy" not in today and 'class="pos"' not in today
    assert today.index("調査が古い") < today.index("購入候補")


def test_conclusion_rows_put_informative_rows_first_and_dedupe_same_reason():
    skus = [_mk("iPhone 18 Pro 256GB", 0, "PASS", hx=False), _mk("iPhone 18 Pro 512GB", 0, "PASS", hx=False),
            _mk("iPhone 18 Pro 1TB", 5000, "WAIT")]
    for s in skus:
        s["identity"] = "REGISTERED"
    html = P.render(_comp(skus), now=NOW)
    tbl = html[html.index('class="mini concl'):]
    tbl = tbl[:tbl.index("</table>")]
    assert ">1TB<" in tbl and ">256GB<" not in tbl and ">512GB<" not in tbl                  # 判断材料のある行だけ表に残す
    assert "確認待ち 2 容量</span>（データ無し）: 256GB、512GB" in html                              # 確認待ち・データ無しの容量は 1 行にまとめる
    assert "Apple ¥400,000" in tbl
    reason = "データ無し（実行可能な買取価格が無いため計算しない）"
    assert html.count(reason) == 1 and "複数の行に共通の理由" in html                            # 同文の理由は 1 回にまとめる
    assert 'concl-note' in html


def test_css_tap_targets_for_links_and_tokenized_top_row():
    css = P.CSS
    assert "rgba(6,118,71" not in css and "tr.top td,tr.top th{background:var(--tone-success-bg)}" in css
    assert ".tw a,.v a" in css.split("@media (max-width:639px)")[0] and "min-height:44px" in css.split("@media (max-width:639px)")[0]
    assert "table.mini.concl" in P.HUB_CSS and "min-width:640px" in P.HUB_CSS


def test_camera_research_page_has_no_bare_status_ids():
    from src.content import camera_research_page as R
    h = R.render({"research_date": "2026-11-17", "products": [{"product": "X", "status": "LOTTERY_DEPENDENT", "buy": {}, "sell_candidates": []}]},
                 now=NOW)
    t = _visible(h)
    assert "LOTTERY_DEPENDENT" not in t and 'title="LOTTERY_DEPENDENT"' in h and "即時の BUY ではない" in t


def test_stale_page_is_neutral_in_today_conclusion_and_sku_hero():
    """調査が 7 日超のとき、①上部おすすめ ②今の結論 ③SKU ヒーローのすべてが緑・断定なし。"""
    c = _comp([_mk("iPhone Duo 1TB", 9000, "BUY")])
    late = datetime(2026, 12, 5, 10, 0, tzinfo=JST)                    # 調査日 11/17 から 18 日
    html = P.render(c, now=late)
    body = html.split("</style>")[-1]
    today = body[body.index('<section class="today"'):body.index("</section>")]
    concl = body[body.index("<h2>今の結論</h2>"):body.index("<h2>モデル別・容量別の詳細</h2>")]
    card = body[body.index('<section class="sku">'):]
    card = card[:card.index("</section>")]
    hero = card[card.index('class="hero"'):card.index("<details")]
    for part in (today, concl, hero):
        assert 'class="pos"' not in part and "sbadge--buy" not in part and "sbadge--profit" not in part
    assert "調査が古い" in today and "購入候補です" not in today
    assert "調査が古い" in concl and "いまの価格とは限りません" in concl
    assert "→ <b>店A</b>（" not in concl.split("調査が古い")[0]          # 断定の文より前に注意が来る


def test_sku_card_folds_long_text_and_camera_legend_has_no_symbols_in_summary():
    html = P.render(_simple(), now=NOW)
    card = html[html.index('<section class="sku">'):]
    card = card[:card.index("</section>")]
    assert card.count("<details") >= 3 and "履歴・参考・補足" in card
    m = _market()
    if m is not None:
        t = _visible(C.render(m, now=datetime(2026, 11, 20, 12, 0, tzinfo=JST)))
        assert "A〜D" not in t and "内部参照" not in t


# ---- 重複排除・データ無しの集約・幅の統一 ----
def test_card_details_do_not_repeat_main_numbers_and_nodata_is_one_details():
    html = P.render(_simple(), now=NOW)
    card = html[html.index('<section class="sku"><h3>iPhone Duo 1TB'):]
    card = card[:card.index("</section>")]
    spec = card[card.index('<details class="spec">'):card.index("</details>")]
    assert "Apple 定価" not in spec and "最高の実行可能買取" not in spec and "純利益" not in spec.replace("純利益・ROI は上の数値", "")
    assert html.count("価格未取得の商品（") == 1 and 'class="nodata-skus"' in html
    assert "古い店" in html                                                  # 買取行のあるデータ無し容量は details の中に残す


def test_candidates_are_compact_and_unpriced_go_in_one_details():
    c = {"candidates": {"a": {"brand": "Apple", "genre": "iphone", "product_name": "iPhone Duo 1TB", "status": "REGISTERED", "official_price": 1},
                        "b": {"brand": "Apple", "genre": "iphone", "product_name": "iPhone Duo 2TB", "status": "PENDING_REVIEW", "official_price": None}}}
    h = P._candidates_html(c)
    assert h.count("発売日・予約日") == 1 and "価格未取得の商品（1件）" in h and "nu-table--stack" not in h


def test_body_width_is_1240_and_camera_route_does_not_wrap():
    assert "main{max-width:1240px" in P.CSS and "980px" not in P.CSS
    assert "main{max-width:1240px" in C._CAMERA_CSS and "white-space:nowrap" in C._CAMERA_CSS and "m--route" in C._CAMERA_CSS
    import re
    assert all(int(v) >= 12 for v in re.findall(r"font-size:(\d+)px", C._CAMERA_CSS))
