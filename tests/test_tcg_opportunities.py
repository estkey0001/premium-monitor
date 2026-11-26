# -*- coding: utf-8 -*-
"""TCG Market Opportunities（2026-11-24）: ルデヤの停止判定の fail-closed と、抽選に依存しない「現在の利益候補」。"""
import re
from datetime import timedelta

import pytest

from src.content import tcg_hub_page as page_mod
from src.tcg import buyback as bb
from src.tcg.hub import product_view as pv
from tests.test_tcg_buyback import ACTIVE_ACTION, CFG, NOW, art, page


def _rows(action):
    return bb.parse_rudeya(page(art("デッキセット", 8000, "4500000000111", action=action)), "https://r.example/c", NOW)["rows"]


def _executable(rows) -> bool:
    ann = bb.annotate([{**r, "page_asof": NOW.isoformat()} for r in rows], CFG, NOW)
    return ann[0]["executable"]


# ── 停止判定（fail-closed） ──
@pytest.mark.parametrize("action,why", [
    ('<span class="product-card-stopped">お申込一時停止中</span>', "stopped class"),
    ('<span>お申込一時停止中</span>', "stopped text only"),
    ('<div class="product-card-action"><button type="button" class="product-card-btn" disabled>買取リクエスト</button></div>', "button disabled"),
    ('<div class="product-card-action"><button type="button" aria-disabled="true">買取リクエスト</button></div>', "aria-disabled"),
    ('<span class="renamed-x9">お申込一時停止中</span>', "class renamed + stopped text"),
    ('<div class="product-card-action"><button class="renamed-btn">買取リクエスト</button><span class="renamed">受付停止中</span></div>', "active button + stop text"),
    ('<div class="product-card-action"><!-- 価格なし --></div>', "status ambiguous: no signal"),
    ("", "status ambiguous: no action block"),
    ('<div class="product-card-action"><a href="/x">詳細</a></div>', "status ambiguous: no button"),
])
def test_stopped_or_ambiguous_is_never_executable(action, why):
    rows = _rows(action)
    assert rows[0]["accept_state"] in (bb.A_STOPPED, bb.A_UNKNOWN), why
    assert rows[0].get("suspended") is True, why
    assert _executable(rows) is False, why


def test_explicit_active_state_is_an_executable_candidate():
    rows = _rows(ACTIVE_ACTION)
    assert rows[0]["accept_state"] == bb.A_ACTIVE and "suspended" not in rows[0]
    assert _executable(rows) is True


def test_active_button_works_even_if_the_button_class_is_renamed():
    rows = _rows('<div class="product-card-action"><button type="button" class="totally-new">買取リクエスト</button></div>')
    assert rows[0]["accept_state"] == bb.A_ACTIVE and _executable(rows) is True


def test_unrecognised_action_container_is_unknown_not_active():
    """申込欄の入れ物が変わって特定できないときは、受付中にしない（判定不能 = 実行不可）。"""
    rows = _rows('<div class="x"><button type="button" class="totally-new">買取リクエスト</button></div>')
    assert rows[0]["accept_state"] == bb.A_UNKNOWN and _executable(rows) is False


def test_condition_note_with_unbuyable_wording_does_not_stop_an_active_row():
    # 条件の注意書きにある「買取不可」（シュリンク切れ）は、受付停止の信号ではない
    html = page(art("デッキセット", 8000, "4500000000111", memo="新品未開封のみ買取可<br>シュリンクが切れているものは買取不可"))
    rows = bb.parse_rudeya(html, "u", NOW)["rows"]
    assert rows[0]["accept_state"] == bb.A_ACTIVE


def test_old_rows_without_accept_state_fail_closed_for_rudeya():
    old = {"shop": "rudeya", "raw_product_name": "デッキセット", "jan": "4500000000111", "price": 8000, "condition": bb.C_UNOPENED,
           "source_url": "u", "observed_at": NOW.isoformat(), "page_asof": NOW.isoformat(), "source_updated_at": None}
    ann = bb.annotate([old], CFG, NOW)
    assert ann[0]["executable"] is False and ann[0]["suspended"] is True


def test_unknown_state_is_excluded_from_history_and_events():
    r = bb.annotate([{**_rows("")[0], "page_asof": NOW.isoformat()}], CFG, NOW)
    assert bb.update_history([], r, "2026-11-21") == []
    assert bb.price_events([{"product_id": "deck", "shop": "rudeya", "unit": "SET", "condition": bb.C_UNOPENED, "price": 1000, "date": "2026-11-20"}],
                           r, "2026-11-21", CFG) == []


def test_unknown_state_is_not_called_stopped_in_the_label():
    assert page_mod._susp_label({"suspended_text": "受付状態を確認できません"}) == "受付状態不明"       # 停止と断定しない
    assert page_mod._susp_label({"suspended_text": "お申込一時停止中"}) == "受付停止"


# ── 利益候補 ──
MSRP = [{"product_id": "deck", "tcg": "POKEMON", "name": "デッキセット", "product_type": "CONSTRUCTED_DECK", "retail_price": 6000,
         "price_text": "6,000円", "basis": "product_unit", "checked_at": NOW.isoformat(), "official_url": "https://www.pokemon-card.com/x"}]
REG = {"products": [{"product_id": "deck", "tcg": "POKEMON", "name": "デッキセット", "product_type": "CONSTRUCTED_DECK",
                     "release_date": "2026-01-01T00:00:00+09:00", "official_url": "https://www.pokemon-card.com/x"}]}


def _hub(price, now=NOW, action=ACTIVE_ACTION, extra=()):
    rows = [{**r, "page_asof": NOW.isoformat()} for r in bb.parse_rudeya(page(art("デッキセット", price, "4500000000111", action=action), *extra), "u", NOW)["rows"]]
    bbj = {"rows": rows}
    cfg = {**CFG, "targets": CFG["targets"]}
    import src.tcg.buyback as m
    orig = m.load_config
    m.load_config = lambda *a, **k: cfg
    try:
        return pv.build_hub({"items": []}, REG, {"verified": MSRP}, now, bbj)
    finally:
        m.load_config = orig


def test_profitable_product_appears_without_any_lottery():
    hub = _hub(9000)
    assert [o["product_id"] for o in hub["opportunities"]] == ["deck"]
    o = hub["opportunities"][0]
    assert o["lottery"] is None and o["profit"]["net_profit"] == 3000 and o["state"] == pv.O_PROFIT
    html = page_mod.render(hub)
    assert "商品と利益（1）" in html and "data-lot-item" not in html and "+3,000円" in html            # 利益候補は商品カードに統合（1 商品 1 枚）


def test_small_profit_is_watch_not_a_strong_recommendation():
    o = _hub(6020)["opportunities"][0]                       # +20 円（ROI 0.3%）: 数学的には黒字だが様子見
    assert o["profit"]["net_profit"] == 20 and o["state"] == pv.O_WATCH and o["state_label"] == "様子見"
    html = page_mod.render(_hub(6020))
    assert '<b class="sb warn">様子見</b>' in html and 'class="tc-strip is-wait"' in html and 'class="sb pf"' not in html   # 少額の黒字を強い推奨（緑）にしない


def test_loss_is_watch_and_says_deficit():
    o = _hub(5800)["opportunities"][0]
    assert o["profit"]["status"] == bb.NO_PROFIT and o["state"] == pv.O_WATCH
    html = page_mod.render(_hub(5800))
    assert '<b class="sb ls">赤字</b>' in html and '<b class="amt neg">-200円</b>' in html


def test_roi_threshold_is_the_existing_buy_now_threshold():
    from src.tcg.scoring import BUY_NOW_MIN_PREMIUM_PERCENT as T
    assert T == 30.0
    assert pv.opportunity_state({"net_profit": 1800, "roi_pct": 30.0}) == pv.O_PROFIT
    assert pv.opportunity_state({"net_profit": 1799, "roi_pct": 29.9}) == pv.O_WATCH
    assert pv.opportunity_state({"net_profit": None, "roi_pct": None}) is None


def test_stopped_or_unknown_or_stale_or_outlier_are_not_candidates():
    assert _hub(9000, action='<span class="product-card-stopped">お申込一時停止中</span>')["opportunities"] == []
    assert _hub(9000, action="")["opportunities"] == []
    assert _hub(9000, now=NOW + timedelta(days=3))["opportunities"] == []            # 古い価格
    assert _hub(30000)["opportunities"] == []                                         # 1 店だけで定価の 3 倍超 = OUTLIER_REVIEW


def test_no_msrp_means_no_candidate():
    rows = [{**r, "page_asof": NOW.isoformat()} for r in bb.parse_rudeya(page(art("デッキセット", 9000, "4500000000111")), "u", NOW)["rows"]]
    import src.tcg.buyback as m
    orig = m.load_config
    m.load_config = lambda *a, **k: CFG
    try:
        assert pv.build_hub({"items": []}, REG, {"verified": []}, NOW, {"rows": rows})["opportunities"] == []
    finally:
        m.load_config = orig


def test_ordering_is_state_then_profit_then_roi():
    mk = lambda pid, net, roi, state: {"name": pid, "state": state, "profit": {"net_profit": net, "roi_pct": roi}}
    items = [mk("w", 500, 5.0, pv.O_WATCH), mk("p-small", 1000, 40.0, pv.O_PROFIT), mk("p-big", 9000, 35.0, pv.O_PROFIT)]
    items.sort(key=lambda o: (pv._OPP_ORDER[o["state"]], -o["profit"]["net_profit"], -o["profit"]["roi_pct"], o["name"]))
    assert [o["name"] for o in items] == ["p-big", "p-small", "w"]


def test_card_has_runtime_freshness_and_required_fields():
    html = page_mod.render(_hub(9000))
    sec = html[html.index('id="opportunities"'):html.index('id="page-foot"')]
    for w in ("ポケカ", "公式定価", "最高買取", "純利益", "ROI", "1店のみ", "買取ルデヤ", "再確認待ち", "data-stale-note"):
        assert w in sec
    assert 'data-fb-live' in sec and 'data-fb-stale' in sec
    assert len(re.findall(r'data-fb-live[^>]*\bhidden', sec)) >= 3          # 金額は JS が鮮度を確認するまで出さない


def test_lottery_status_is_shown_when_bound():
    ev = {"lottery_id": "L1", "tcg": "POKEMON", "retailer": "POKEMON_CENTER", "retailer_name": "ポケモンセンター", "product_name": "デッキセット",
          "product_id": "deck", "product_match": "exact", "source_url": "https://www.pokemon-center-online.com/x", "source_type": "OFFICIAL",
          "verified": True, "application_start": (NOW - timedelta(days=1)).isoformat(), "application_end": (NOW + timedelta(days=3)).isoformat()}
    rows = [{**r, "page_asof": NOW.isoformat()} for r in bb.parse_rudeya(page(art("デッキセット", 9000, "4500000000111")), "u", NOW)["rows"]]
    import src.tcg.buyback as m
    orig = m.load_config
    m.load_config = lambda *a, **k: CFG
    try:
        o = pv.build_hub({"items": [ev]}, REG, {"verified": MSRP}, NOW, {"rows": rows})["opportunities"][0]
    finally:
        m.load_config = orig
    assert o["lottery"] and o["lottery"]["label"] in ("受付中", "締切間近")


def test_home_is_not_changed_by_opportunities():
    # HOME の利益根拠は profit_map（抽選に結ばれた商品の利益欄）のまま。利益候補の追加で関数の形は変わらない
    import inspect
    assert "opportunities" not in inspect.getsource(pv.profit_map)


def test_wrapper_disabled_or_hidden_does_not_make_a_row_active():
    for h in ('<fieldset disabled><button class="b">買取リクエスト</button></fieldset>', '<div hidden><button class="b">買取リクエスト</button></div>',
              '<button class="b" style="pointer-events:none">買取リクエスト</button>', '<button data-disabled="1">買取リクエスト</button>'):
        assert bb.rudeya_accept_state(h)[0] != bb.A_ACTIVE, h
    assert bb.rudeya_accept_state('<div class="product-card-action"><button class="b">買取リクエスト</button></div>')[0] == bb.A_ACTIVE


def test_shop_state_warns_when_no_row_is_active():
    r = {**bb.parse_rudeya(page(art("デッキセット", 8000, "4500000000111", action="")), "u", NOW)["rows"][0], "page_asof": NOW.isoformat()}
    exp, _h = bb.build_export([r], [], {"rudeya": {"state": "OK", "pages_ok": 1, "pages_failed": 0, "rows": 1, "reason": None}}, CFG, NOW, [])
    assert exp["shops"]["rudeya"]["state"] == "WARN" and exp["shops"]["rudeya"]["active_rows"] == 0
    ok = {**bb.parse_rudeya(page(art("デッキセット", 8000, "4500000000111")), "u", NOW)["rows"][0], "page_asof": NOW.isoformat()}
    exp2, _ = bb.build_export([ok], [], {"rudeya": {"state": "OK", "pages_ok": 1, "pages_failed": 0, "rows": 1, "reason": None}}, CFG, NOW, [])
    assert exp2["shops"]["rudeya"]["state"] == "OK"


def test_outlier_price_is_not_saved_as_the_next_days_baseline():
    hist = bb.update_history([], [{"identity_status": "CONFIRMED", "product_id": "x", "shop": "s", "unit": "BOX", "condition": "UNOPENED",
                                   "price": 9, "observed_at": NOW.isoformat()}], "2026-11-24", skip_products={"x"})
    assert hist == []


def test_single_source_is_visible_in_the_state_badge():
    html = page_mod.render(_hub(9000))
    best = re.search(r"<li data-strip-best>.*?</li>", html, re.S).group(0)
    assert "1店のみ" in best and best.index("data-fb-live") < best.index("1店のみ")          # 買取が 1 店だけであることを、最高買取の欄（鮮度の判定の中）に出す


# ── 最終監査での指摘の回帰（2026-11-24） ──
@pytest.mark.parametrize("word", ["買取中止", "受付中止", "買取終了", "受付は終了しました", "一時的に停止しています", "入荷待ち", "現在買取できません"])
def test_unregistered_stop_wording_with_active_button_is_stopped(word):
    """有効な申込ボタンが残っていても、停止の文言があれば受付中にしない。"""
    action = f'<span>{word}</span><button class="b">買取リクエスト</button>'
    rows = _rows(action)
    assert rows[0]["accept_state"] in (bb.A_STOPPED, bb.A_UNKNOWN)      # 語が登録済みなら STOPPED、未登録でも申込欄の形が既知でなければ UNKNOWN
    assert _executable(rows) is False


def test_history_only_keeps_fresh_rows():
    base = {"identity_status": bb.ID_CONFIRMED, "product_id": "p", "shop": "rudeya", "unit": "BOX", "condition": "UNOPENED",
            "price": 1000, "observed_at": NOW.isoformat()}
    rows = [{**base, "freshness": bb.FRESH}, {**base, "product_id": "q", "freshness": "STALE"}, {**base, "product_id": "r"}]
    h = bb.update_history([], rows, "2026-11-24")
    assert [x["product_id"] for x in h] == ["p"]


def test_history_drops_past_rows_of_a_product_now_under_outlier_review():
    old = [{"product_id": "kuma", "shop": "rudeya", "unit": "BOX", "condition": "UNOPENED", "price": 30000, "checked_at": "x", "date": "2026-11-22"},
           {"product_id": "ok", "shop": "rudeya", "unit": "BOX", "condition": "UNOPENED", "price": 5000, "checked_at": "x", "date": "2026-11-22"}]
    h = bb.update_history(old, [], "2026-11-24", skip_products=("kuma",))
    assert [x["product_id"] for x in h] == ["ok"]


@pytest.mark.parametrize("word", ["現在お取り扱いしておりません", "お取り扱いできません", "買取できない状態です", "現在買取を行っておりません",
                                   "買取をお断り", "在庫なし", "完売", "未登録の言い回しの停止"])
def test_any_extra_text_in_the_action_block_is_not_active(word):
    """停止語を列挙しなくても、申込欄にボタン以外の文字があれば受付中にしない（肯定条件）。"""
    action = f'<div class="product-card-action"><span>{word}</span><div class="product-card-qty-row"><button class="b">買取リクエスト</button></div></div>'
    rows = _rows(action)
    assert rows[0]["accept_state"] in (bb.A_STOPPED, bb.A_UNKNOWN)
    assert _executable(rows) is False


def test_real_active_markup_stays_active():
    action = ('<div class="product-card-action"><!-- カートに入れる (オプション無し) --><div class="product-card-qty-row">'
              '<input type="tel" class="product-card-qty cart_quantity" placeholder="個数">'
              '<button type="button" class="product-card-btn" onclick="cart_add_input(this, \'7373\')">買取リクエスト</button></div></div>')
    rows = _rows(action)
    assert rows[0]["accept_state"] == bb.A_ACTIVE


def test_other_button_or_image_in_the_action_block_is_not_active():
    ok = '<button class="b">買取リクエスト</button>'
    for extra in ('<button class="x">売り切れ</button>', '<img src="/s.png" alt="停止">'):
        rows = _rows(f'<div class="product-card-action"><div class="product-card-qty-row">{extra}{ok}</div></div>')
        assert rows[0]["accept_state"] == bb.A_UNKNOWN, extra
        assert _executable(rows) is False


OK_BTN = '<button type="button" class="product-card-btn" onclick="cart_add_input(this, \'1\')">買取リクエスト</button>'


@pytest.mark.parametrize("inner", [
    '<button class="b">買取リクエスト停止</button>',
    '<button class="b">買取リクエスト（現在ご利用不可）</button>',
    f'{OK_BTN}<button>完売</button>',
    '<img alt="受付停止">' + OK_BTN,
    '<span title="停止中"></span>' + OK_BTN,
    '<input type="button" value="受付停止">' + OK_BTN,
    '<div aria-label="停止" data-status="stopped">' + OK_BTN + '</div>',
    '<button class="b" tabindex="-1" onclick="return false">買取リクエスト</button>',
    '<button class="b" title="停止中">買取リクエスト</button>',
    '<input class="q" placeholder="停止中">' + OK_BTN,
    '<span>お休み中</span>' + OK_BTN,
])
def test_action_block_must_match_the_known_shape_exactly(inner):
    """申込欄が「数量入力 + 申込ボタン 1 つ」の既知の形と完全に一致しないものは、受付中にしない。"""
    rows = _rows(f'<div class="product-card-action">{inner}</div>')
    assert rows[0]["accept_state"] != bb.A_ACTIVE, inner
    assert _executable(rows) is False


def test_condition_memo_with_cannot_buy_wording_does_not_stop_a_known_active_row():
    rows = bb.parse_rudeya(page(art("デッキセット", 8000, "4500000000111", memo="シュリンク切れは買取できません")), "https://r.example/c", NOW)["rows"]
    assert rows[0]["accept_state"] == bb.A_ACTIVE
