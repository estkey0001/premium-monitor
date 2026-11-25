# -*- coding: utf-8 -*-
"""TCG 商品カード（1 商品 1 枚・画像・利益ストリップ・最高額の買取店・折りたたみの他店・抽選）のテスト。

- 同じ商品が利益候補と商品カードに 2 枚出ない（キーは (tcg, product_id)）。
- 利益ストリップ: 公式定価 → 最高買取（最高額の 1 店）→ 利益（基準店を併記）。最高買取の店が基準店と違えば差額を別行で。
- 買取由来の金額は data-fb-live の中だけ（<div>/<span> の入れ子で外へ漏れない）。鮮度切れ後は JS（node）で消えて stale が出る。
"""
from __future__ import annotations

import re
from datetime import timedelta
from html.parser import HTMLParser

import pytest

from src.content import tcg_hub_page as page
from src.tcg import buyback as bb
from src.tcg.hub import product_view as pv
from tests.test_tcg_buyback import CFG, NOW, row
from tests.test_tcg_runtime_freshness import _apply, _elements, needs_node

DECK_JAN, BOX_JAN, SOLO_JAN, OP_JAN = "4500000000111", "4500000000222", "4500000000333", "4500000000444"
CFG2 = {**CFG, "targets": [
    *CFG["targets"],
    {"product_id": "solo", "tcg": "POKEMON", "name": "ソロ", "unit": "SET", "jan": SOLO_JAN},
    {"product_id": "op1", "tcg": "ONE_PIECE", "name": "OP ブースター", "unit": "BOX", "jan": OP_JAN},
]}


def _master(pid, name, ptype="CONSTRUCTED_DECK", rel="2026-12-01", **kw):
    return {"tcg": "POKEMON", "product_id": pid, "name": name, "product_type": ptype, "release_date": rel,
            "official_url": "https://www.pokemon-card.com/ex/" + pid + "/", **kw}


def _msrp(pid, price, ptype="CONSTRUCTED_DECK"):
    return {"tcg": "POKEMON", "product_id": pid, "product_type": ptype, "retail_price": price, "basis": "product_unit",
            "checked_at": "2026-11-21", "official_url": "https://www.pokemon-card.com/ex/" + pid + "/"}


def _ev(pid="deck", name="デッキセット", n=1, tcg="POKEMON", **kw):
    d = {"lottery_id": f"L-{pid}-{n}", "tcg": tcg, "product_name": name, "retailer": "GEO", "retailer_name": f"店{n}",
         "store_name": f"店{n}", "event_type": "LOTTERY", "product_id": pid, "product_match": "exact",
         "application_start": "2026-11-19T10:00:00+09:00", "application_end": "2026-11-25T23:59:00+09:00",
         "source_url": f"https://www.geo-online.co.jp/store/news/{n}", "source_type": "STORE_OFFICIAL", "verified": True,
         "entry_url": f"https://draw.geo-online.co.jp/lottery/{n}00"}
    d.update(kw)
    return d


def _build(rows, events=(), master=None, msrp=None, monkeypatch=None):
    monkeypatch.setattr(bb, "load_config", lambda path=bb.CONFIG_PATH: CFG2)
    reg = {"generated_at": NOW.isoformat(), "products": master if master is not None else [
        _master("deck", "デッキセット"), _master("box", "拡張パック BOX", "BOOSTER_BOX", "2026-12-05"),
        _master("solo", "ソロ", rel="2026-01-01")]}
    ms = {"generated_at": NOW.isoformat(), "verified": msrp if msrp is not None else [_msrp("deck", 6200), _msrp("solo", 5000)]}
    lots = {"generated_at": NOW.isoformat(), "evaluated_at": NOW.isoformat(), "items": list(events)}
    return pv.build_hub(lots, reg, ms, NOW, {"rows": rows})


def _html(hub):
    return page.render(hub, generated_label="x")


def _cards(html: str) -> dict:
    """{data-card-key: <article> の HTML}。"""
    out = {}
    for m in re.finditer(r'<article class="tcard"[^>]*data-card-key="([^"]+)"', html):
        out[m.group(1)] = html[m.start():html.index("</article>", m.start()) + 10]
    return out


def _order(html: str) -> list:
    return re.findall(r'<article class="tcard"[^>]*data-card-key="([^"]+)"', html)


ROWS = [row(price=8000, jan=DECK_JAN), row(shop="kaitorishouten", price=9000, jan=DECK_JAN, upd="2026-11-21"),
        row(shop="kaitorishouten", price=9500, jan=DECK_JAN, cond=bb.C_NEW, upd="2026-11-21")]


class _Walk(HTMLParser):
    """カードの HTML を歩き、live / stale の外に出ている文字と属性値、live の中の入れ子（div/span）を集める。"""
    VOID = {"img", "br", "input", "meta", "link", "hr"}

    def __init__(self, hidden=None):
        super().__init__()
        self.stack: list = []            # (tag, kind) kind = "live" / "stale" / ""
        self.outside: list = []          # live・stale の外の文字
        self.attrs_outside: list = []    # live・stale の外の属性値
        self.nest_bad: list = []         # live の内側に出た <div> / <span>
        self.visible: list = []          # hidden を反映したあとに見える文字
        self.k = 0
        self.hidden = hidden or []       # live / stale 要素の出現順の hidden（JS の結果）
        self.hid_depth = 0

    def _in(self, kind):
        return any(k == kind for _t, k in self.stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        kind = "live" if "data-fb-live" in a else ("stale" if "data-fb-stale" in a else "")
        if self._in("live") and tag in ("div", "span"):
            self.nest_bad.append(tag)
        if not (self._in("live") or self._in("stale") or kind):
            self.attrs_outside += [v or "" for v in a.values()]
        hid = False
        if kind:
            hid = bool(self.hidden[self.k]) if self.k < len(self.hidden) else False
            self.k += 1
        if tag not in self.VOID:
            self.stack.append((tag, kind))
            if hid:
                self.hid_depth += 1
                self.stack[-1] = (tag, kind + ":hid")

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                if self.stack[i][1].endswith(":hid"):
                    self.hid_depth -= 1
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not data.strip():
            return
        if not (self._in("live") or self._in("stale") or self._in("live:hid") or self._in("stale:hid")):
            self.outside.append(data)
        if self.hid_depth == 0:
            self.visible.append(data)

    def _in(self, kind):          # noqa: F811 — ":hid" も同じ種別として数える
        return any(k == kind or k.startswith(kind + ":") for _t, k in self.stack)


def _walk(card_html: str, hidden=None) -> _Walk:
    w = _Walk(hidden)
    w.feed(card_html)
    return w


# ── 1 商品 1 カード・並び ──
def test_same_product_is_one_card_with_profit_and_lottery(monkeypatch):
    hub = _build(ROWS + [row(price=9500, jan=SOLO_JAN)], [_ev(), _ev(n=2)], monkeypatch=monkeypatch)
    html = _html(hub)
    keys = _order(html)
    assert len(keys) == len(set(keys)) and keys.count("POKEMON:deck") == 1
    card = _cards(html)["POKEMON:deck"]
    assert "+1,800円" in card and 'data-lot-item' in card                  # 同じ 1 枚に利益と抽選がある
    assert 'class="pcard opp"' not in html.split('id="retailer-box"')[0]    # 旧の利益候補カードは出ない
    assert [c["key"] for c in hub["cards"]] == [tuple(k.split(":")) for k in keys]
    assert sum(1 for c in hub["cards"] if c["product_id"] == "deck") == 1
    assert "POKEMON:solo" in keys                                           # 抽選が無く商品一覧に載らない商品も、利益が出れば 1 枚


def test_cards_order_profit_then_applying_lottery_then_newest_release(monkeypatch):
    master = [_master("deck", "デッキセット", rel="2026-12-01"), _master("solo", "ソロ", rel="2026-01-01"),
              _master("late", "抽選あり", rel="2026-11-01"), _master("old", "古い", rel="2026-12-02"), _master("new", "新しい", rel="2026-12-20"),
              _master("soon", "締切が近い", rel="2026-10-01")]
    rows = [row(price=8000, jan=DECK_JAN), row(price=9500, jan=SOLO_JAN)]
    evs = [_ev("late", "抽選あり", application_end="2026-11-28T23:59:00+09:00"),
           _ev("soon", "締切が近い", n=2, application_end="2026-11-23T23:59:00+09:00")]
    hub = _build(rows, evs, master=master, msrp=[_msrp("deck", 6200), _msrp("solo", 5000)], monkeypatch=monkeypatch)
    order = [k.split(":")[1] for k in _order(_html(hub))]
    # 利益: solo(+4,500) > deck(+1,800)。抽選: 締切が近い soon → late。その他: 発売日が新しい new → old
    assert order[:4] == ["solo", "deck", "soon", "late"], order
    assert order.index("new") < order.index("old") and order.index("late") < order.index("new")


# ── 利益ストリップ ──
def test_profit_strip_values_basis_and_separate_difference_row(monkeypatch):
    html = _html(_build(ROWS, monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    strip = card[card.index("data-strip>"):card.index("</ul>", card.index("data-strip>"))]
    assert re.search(r"<li data-strip-msrp>.*?¥6,200", strip, re.S)                        # 公式定価
    best = re.search(r"<li data-strip-best>(.*?)</li>", strip, re.S).group(1)
    assert "¥9,000" in best and "買取商店" in best and "確認 11/21 18:00" in best and "¥8,000" not in best      # 最高額の 1 店だけ
    profit = re.search(r"<li data-strip-profit>(.*?)</li>", strip, re.S).group(1)
    assert "+1,800円" in profit and "ROI 29.0%" in profit and "基準: 買取ルデヤ 買取 ¥8,000・定価 ¥6,200" in profit
    diff = re.search(r"<li data-strip-diff>(.*?)</li>", strip, re.S).group(1)             # 別行
    assert "+2,800円" in diff and "最高買取 − 定価（費用除く・参考）" in diff
    assert "最高買取の店は送料・費用が未確認のため、利益ではなく差額です" in diff
    assert "最高買取の店（買取商店）と、利益の基準にした店（買取ルデヤ）は別です" in diff
    assert "+2,800円" not in profit and "+1,800円" not in diff                              # 差額を利益に混ぜない


def test_no_difference_row_when_the_best_shop_is_the_base_shop(monkeypatch):
    html = _html(_build([row(price=8000, jan=DECK_JAN)], monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    assert "data-strip-diff" not in card and "+1,800円" in card and "単一ソース" in card


def test_loss_is_shown_with_neg_text_color_not_a_badge_and_no_green_buy_badge(monkeypatch):
    html = _html(_build([row(price=5800, jan=DECK_JAN)], monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    assert '<b class="amt neg">-400円</b>' in card and "赤字です" in card
    ok = _cards(_html(_build([row(price=9000, jan=DECK_JAN)], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert '<b class="amt pos">+2,800円</b>' in ok
    for c in (card, ok):
        assert "購入推奨" not in c and "BUY" not in c and 'class="sb ok"' not in c and "今すぐ買" not in c


def test_missing_msrp_missing_buyback_and_outlier_states(monkeypatch):
    # 定価なし（BOX。パック価格だけの商品）: 金額を出さず「公式定価が未確認のため利益は算出前」。買取は出す
    master = [_master("deck", "デッキセット"), _master("box", "拡張パック BOX", "BOOSTER_BOX", "2026-12-05", pack_price=180, retail_price_basis="pack"),
              _master("solo", "ソロ", rel="2026-01-01")]
    hub = _build([row(price=14000, jan=BOX_JAN, name="拡張パック BOX [M6]")], [_ev("box", "拡張パック BOX")], master=master, msrp=[], monkeypatch=monkeypatch)
    box = _cards(_html(hub))["POKEMON:box"]
    assert "公式定価が未確認のため利益は算出前です" in box and "1 パック ¥180" in box and "BOX の定価はパック価格から計算していません" in box
    assert "¥14,000" in box and not re.search(r"[+\-−][\d,]+円", box)                       # 利益も差額も出さない
    assert "data-strip-diff" not in box
    # 買取なし: 最高買取 未確認
    nob = _cards(_html(_build([], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert "買取店のページに、この商品の買取価格が見つかっていません" in nob and "未確認" in nob and "+" not in re.sub(r"<[^>]+>", "", nob).replace("+0", "")
    assert "data-fb-live" not in nob                                                          # 金額が無いので live も無い
    # 外れ値（1 店だけで定価の 3 倍超）: 確認待ち（利益に使っていません）
    out = _cards(_html(_build([row(price=30000, jan=DECK_JAN)], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert "確認待ち（利益に使っていません）" in out and "¥30,000" not in out and not re.search(r"[+\-−][\d,]+円", out)


# ── 買取店の折りたたみ ──
def test_only_the_highest_shop_is_visible_when_closed_and_others_are_reference(monkeypatch):
    html = _html(_build(ROWS, monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    closed = card[:card.index('<details class="tc-others"')]
    best = re.search(r"<li data-strip-best>(.*?)</li>", closed, re.S).group(1)
    assert "買取商店" in best and "買取ルデヤ" not in best and "条件未確認" not in closed       # 閉じた状態の最高買取は最高額の 1 店だけ（ルデヤは利益の基準の併記・差額の注記に出るだけ）
    assert "data-other-shop" not in closed
    det = card[card.index('<details class="tc-others"'):card.index("</details>", card.index('<details class="tc-others"'))]
    assert "他の買取店（1 店）・同じ店の別条件 1 件" in det and "<details" in det and " open" not in det.split(">")[0]    # 最初は閉じている
    shops = re.findall(r'data-other-shop="([^"]+)" data-other-kind="([^"]+)"', det)
    assert shops == [("rudeya", "executable"), ("kaitorishouten", "reference")]
    assert "条件未確認・参考（条件: NEW）・最高買取にしません" in det


def test_suspended_listed_only_and_new_rows_never_become_the_highest(monkeypatch):
    stopped = {**row(price=12000, jan=DECK_JAN), "accept_state": "STOPPED", "suspended_text": "お申込一時停止中"}
    rows = [stopped, row(shop="kaitorishouten", price=9000, jan=DECK_JAN, upd="2026-11-21"),
            row(shop="kaitorishouten", price=15000, jan=DECK_JAN, cond=bb.C_NEW, upd="2026-11-21")]
    hub = _build(rows, monkeypatch=monkeypatch)
    card = _cards(_html(hub))["POKEMON:deck"]
    best = re.search(r"<li data-strip-best>(.*?)</li>", card, re.S).group(1)
    assert "¥9,000" in best and "¥12,000" not in best and "¥15,000" not in best                 # 停止中・条件 NEW は最高買取ではない
    det = card[card.index('<details class="tc-others"'):card.index("</details>", card.index('<details class="tc-others"'))]
    assert 'data-other-shop="rudeya" data-other-kind="suspended"' in det
    assert "お申込一時停止中（今は買い取っていません）・最高買取にしません" in det
    assert 'data-other-kind="reference"' in det and "条件未確認・参考" in det
    assert "data-strip-profit" in card and "算出前" in card                                       # 基準にできる店（ルデヤ）が停止中: 利益は出さない
    assert not re.search(r"[+\-−][\d,]+円", card)


def test_listed_only_product_has_no_highest_and_lists_references(monkeypatch):
    hub = _build([row(price=8000, jan=DECK_JAN, obs=NOW - timedelta(hours=60))], monkeypatch=monkeypatch)
    card = _cards(_html(hub))["POKEMON:deck"]
    assert "鮮度・条件を確認できた買取価格がありません" in card and "掲載のある買取店（1 店・参考）" in card
    assert not re.search(r"[+\-−][\d,]+円", card)


# ── 鮮度: live の中だけ・入れ子で漏れない・鮮度切れで消える ──
def test_every_buyback_amount_is_inside_live_and_live_has_no_nested_div_or_span(monkeypatch):
    html = _html(_build(ROWS, [_ev()], monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    w = _walk(card)
    assert w.nest_bad == [], w.nest_bad                                                      # live の内側に <div>/<span> を入れ子にしない
    outside = " ".join(w.outside) + " " + " ".join(w.attrs_outside)
    for amt in ("8,000", "9,000", "9,500", "+1,800", "+2,800", "29.0%"):
        assert amt not in outside, (amt, outside)                                           # 定価以外の金額は live の外に無い（title などの属性にも無い）
    assert "6,200" in outside                                                               # 定価は常に出る
    lives = _elements(card)
    assert all(e["hidden"] for e in lives if e["kind"] == "live") and not any(e["hidden"] for e in lives if e["kind"] == "stale")


def test_live_leak_is_detected_by_the_walker():
    """検査自体の確認（変異）: live の内側に <div> を入れると検出し、live の外の金額も検出する。"""
    bad = '<article><span data-fb-live hidden><div>¥9,000</div></span>¥8,000</article>'
    w = _walk(bad)
    assert w.nest_bad == ["div"] and "¥8,000" in " ".join(w.outside)


@needs_node
def test_after_the_freshness_window_best_profit_and_other_prices_disappear(monkeypatch):
    html = _html(_build(ROWS, [_ev()], monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    mx = int(_elements(card)[0]["attrs"]["data-fb-max"])
    fresh = _apply(card, NOW + timedelta(hours=1))
    vis = " ".join(_walk(card, [e["hidden"] for e in fresh]).visible)
    for w in ("¥9,000", "+1,800円", "ROI 29.0%", "+2,800円", "¥8,000", "¥9,500"):
        assert w in vis, w                                                                  # 範囲内は出る（折りたたみ内の他店も）
    assert "価格再確認待ち" not in vis
    late = _apply(card, NOW + timedelta(hours=mx, minutes=1))
    vis = " ".join(_walk(card, [e["hidden"] for e in late]).visible)
    for w in ("¥9,000", "¥8,000", "¥9,500", "+1,800円", "+2,800円", "29.0%", "様子見"):
        assert w not in vis, w                                                              # 最高買取・利益・差額・他店の価格・状態バッジは出ない
    assert "価格再確認待ち" in vis and "取得 11/21 18:00" in vis and "確認待ち" in vis       # stale が出る
    assert "¥6,200" in vis and "店1" in vis and "受付中" in vis                              # 定価・抽選は残る
    assert any(f"取得から{mx}時間以上経過" in e["why"] for e in late if e["kind"] == "stale")


@needs_node
def test_each_other_shop_row_has_its_own_freshness_group(monkeypatch):
    """他店の取得時刻が古くても、最高買取・利益は出続ける（行ごとに別グループ）。"""
    rows = [row(price=8000, jan=DECK_JAN), row(shop="kaitorishouten", price=7500, jan=DECK_JAN, obs=NOW - timedelta(hours=30), upd="2026-11-21")]
    card = _cards(_html(_build(rows, monkeypatch=monkeypatch)))["POKEMON:deck"]
    groups = {e["attrs"]["data-fb-group"] for e in _elements(card)}
    assert groups == {"p0-b", "p0-p", "p0-o0"}                                              # 最高買取+差額 / 利益+状態バッジ / 他店は行ごと
    res = _apply(card, NOW + timedelta(hours=10))                                           # 他店は取得から 40 時間（>36）、最高買取は 10 時間
    vis = " ".join(_walk(card, [e["hidden"] for e in res]).visible)
    assert "¥8,000" in vis and "+1,800円" in vis and "¥7,500" not in vis and "価格再確認待ち" in vis


# ── 抽選 ──
def test_lottery_details_max_three_sorted_by_deadline_with_status(monkeypatch):
    evs = [_ev(n=1, application_end="2026-11-25T23:59:00+09:00"),                                   # 受付中
           _ev(n=2, application_end="2026-11-22T10:00:00+09:00"),                                   # 締切間近（24 時間以内）
           _ev(n=3, application_start="2026-11-24T10:00:00+09:00", application_end="2026-11-28T23:59:00+09:00"),   # 近日開始
           _ev(n=4, application_end="2026-11-20T23:59:00+09:00", winner_announcement_at="2026-11-23T12:00:00+09:00"),     # 結果待ち
           _ev(n=5, application_start="2026-11-01T10:00:00+09:00", application_end="2026-11-02T23:59:00+09:00")]      # 終了（出さない）
    hub = _build([], evs, monkeypatch=monkeypatch)
    card = _cards(_html(hub))["POKEMON:deck"]
    det = card[card.index("data-lot-details>"):card.index("</details>", card.index("data-lot-details>"))]
    assert "抽選 4 件（受付中・締切間近 → 開始前 → 日程未確認 → 結果待ち・購入期間の順・同じ段階は締切が近い順・最大 3 件。受付中・締切間近は必ず含みます）" in det                                                 # 終了は数えない
    items = re.findall(r'data-lot-item data-lot-status="([^"]+)"', det)
    assert items == ["ENDING_SOON", "OPEN", "UPCOMING"]                                              # 最大 3 件・締切が近い順（段階順）
    assert "店2" in det and "店1" in det and "店4" not in det and "店5" not in det
    assert "表で見る（この商品の抽選 4 件）" in det and 'data-pf="p0"' in det
    for chip in ("<b>1</b>受付中", "<b>1</b>締切間近", "<b>1</b>当選発表待ち", "<b>1</b>近日開始"):
        assert chip in card
    assert re.search(r'class="chip info" data-rb-card data-rb-until="[^"]+"><span data-rb-open><b>1</b>受付中', card)       # 締切のある件数は JS_RB で失効する
    assert re.search(r'class="chip danger" data-rb-card data-rb-until="[^"]+"><span data-rb-open><b>1</b>締切間近', card)
    assert 'class="chip warn"><b>1</b>当選発表待ち' in card                                                               # 結果待ちは締切で失効しない


def test_ended_application_is_not_shown_as_newly_applicable_and_winner_period_is_a_separate_badge(monkeypatch):
    pending = _ev(n=1, application_end="2026-11-20T23:59:00+09:00", winner_announcement_at="2026-11-23T12:00:00+09:00")
    winner = _ev(n=2, application_end="2026-11-18T23:59:00+09:00", purchase_start="2026-11-20T00:00:00+09:00",
                 purchase_end="2026-11-30T23:59:00+09:00", winner_announcement_at="2026-11-19T12:00:00+09:00")
    card = _cards(_html(_build([], [pending, winner], monkeypatch=monkeypatch)))["POKEMON:deck"]
    li = re.findall(r"<li data-lot-item.*?</li>", card, re.S)
    assert len(li) == 2
    for x in li:
        assert "応募ページ" not in x                                                              # 応募済み・結果待ち・購入期間: 新規応募のリンクを出さない
    assert 'data-lot-status="WINNER_PURCHASE_PERIOD"' in card and "購入期間中（当選者のみ）" in card
    assert "応募は締切済み" in card
    chips = card[card.index('class="chips"'):card.index("</div>", card.index('class="chips"'))]
    assert "購入期間中（当選者のみ）" in chips and "受付中" not in chips                            # 一般の購入可否・受付中と混ぜない
    assert "この商品に紐付いた、応募受付中の抽選はありません" in card


def test_open_lottery_has_application_link_but_unverified_does_not_count_as_open(monkeypatch):
    ok = _cards(_html(_build([], [_ev()], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert 'href="https://draw.geo-online.co.jp/lottery/100"' in ok and "<b>1</b>受付中" in ok
    un = _cards(_html(_build([], [_ev(verified=False)], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert "<b>1</b>受付中" not in un and "未確認（公式で再確認待ち）" in un and "https://draw.geo-online.co.jp/lottery/100" not in un
    assert "この商品に紐付いた、応募受付中の抽選はありません" in un


def test_unbound_applying_guidance_is_kept(monkeypatch):
    ended = _ev(application_start="2026-11-01T10:00:00+09:00", application_end="2026-11-02T23:59:00+09:00")
    unlinked = _ev(n=3, product_match="none", product_id=None, product_name="二種（再販）")
    html = _html(_build([], [ended, unlinked], monkeypatch=monkeypatch))
    assert "この商品に紐付いた、応募受付中の抽選はありません。紐付け前の告知は抽選一覧を参照" in html


# ── 画像 ──
def test_pokemon_image_only_from_official_https_alt_is_name_and_credit_once(monkeypatch):
    img = "https://www.pokemon-card.com/products/2026/images/x.jpg"
    master = [_master("deck", "デッキセット", official_image_url=img), _master("solo", "ソロ", rel="2026-01-01", official_image_url="https://evil.example/x.jpg")]
    html = _html(_build(ROWS + [row(price=9500, jan=SOLO_JAN)], master=master, monkeypatch=monkeypatch))
    cards = _cards(html)
    assert f'src="{img}"' in cards["POKEMON:deck"] and 'alt="デッキセット"' in cards["POKEMON:deck"]
    assert 'referrerpolicy="no-referrer"' in cards["POKEMON:deck"] and 'loading="lazy"' in cards["POKEMON:deck"] and 'width="320" height="240"' in cards["POKEMON:deck"]
    assert "<img" not in cards["POKEMON:solo"] and "evil.example" not in html                 # 公式以外のドメインは使わない
    assert 'role="img"' in cards["POKEMON:solo"] and "<small>ポケカ</small>" in cards["POKEMON:solo"]
    assert html.count("画像の権利は各権利者に帰属します") == 1                                   # 出典表記はページに 1 か所
    assert "ポケモンカードゲーム公式サイトの画像を参照表示しています" in html


def test_one_piece_card_is_a_placeholder_even_if_an_image_url_is_given(monkeypatch):
    hub = _build([row(price=9000, jan=OP_JAN, name="OP BOX")], [_ev("op1", "OP ブースター", tcg="ONE_PIECE")], monkeypatch=monkeypatch)
    for c in hub["cards"]:
        if c["tcg"] == "ONE_PIECE":
            c["image_url"] = "https://www.pokemon-card.com/x.jpg"
    html = _html(hub)
    op = _cards(html)["ONE_PIECE:op1"]
    assert "<img" not in op and "<small>ワンピ</small>" in op and "<b>OP</b>" in op
    assert "商品画像なし" in op and "公式に商品固有の画像がないため" in html


# ── 構造・安全 ──
def test_page_has_no_green_buy_badge_and_cards_keep_the_old_safety_texts(monkeypatch):
    html = _html(_build(ROWS, [_ev()], monkeypatch=monkeypatch))
    cards_html = "".join(_cards(html).values())
    assert "購入推奨" not in cards_html and 'class="sb ok"' not in cards_html and "BUY" not in cards_html
    assert "最高買取の店と利益の基準にした店は別です" not in cards_html                          # 旧文言は差額の注記に置き換わった
    assert "最高買取の店（買取商店）と、利益の基準にした店（買取ルデヤ）は別です" in cards_html
    assert "店頭受取 → 店頭持込" in cards_html and "交通費・時間は含みません" in cards_html


def test_cards_do_not_overflow_on_a_375px_phone_by_css_contract():
    css = page.CSS
    assert ".tcard{" in css and "min-width:0" in css.split(".tcard{")[1].split("}")[0]
    assert "minmax(300px,1fr)" in css                                                         # 375px で 1 列
    assert "font-variant-numeric:tabular-nums" in css.split(".tc-strip{")[1].split("}")[0]
    assert "overflow-wrap:anywhere" in css.split(".tc-others li,.tc-lotd li{")[1].split("}")[0] and "overflow-wrap:anywhere" in css
    assert "table.lt{min-width:0}" in css and "tcard{padding:8px}" in css                    # 狭い幅の調整


@pytest.mark.parametrize("mutate", [
    lambda h: h.replace(" hidden>", ">", 1),                                  # live の hidden を外す（fail-open）
    lambda h: re.sub(r"(<span data-fb-live[^>]*>)<b class=\"amt\">(¥9,000)</b>", r"\2\1", h, count=1),     # 金額を live の外へ出す
])
def test_mutations_are_caught_by_the_card_checks(monkeypatch, mutate):
    card = _cards(_html(_build(ROWS, monkeypatch=monkeypatch)))["POKEMON:deck"]
    bad = mutate(card)
    w = _walk(bad)
    elements = _elements(bad)
    leak = "9,000" in " ".join(w.outside)
    fail_open = not all(e["hidden"] for e in elements if e["kind"] == "live")
    assert leak or fail_open


# ═══════════ 独立レビュー・監査の指摘（M1〜M3・L1〜L7）の回帰 ═══════════
def _lot_lis(card: str) -> list:
    return re.findall(r"<li data-lot-item.*?</li>", card, re.S)


@pytest.mark.parametrize("ev,expect", [
    (dict(verified=False), "公式で再確認待ちのため、応募の可否を断定しません"),                       # 未確認（締切 11/25）
    (dict(conflict=True), "情報源で日程が食い違っています（公式で確認してください）"),                  # 日程の食い違い
    (dict(application_end=None), "日程が未確認です（締切 未公表）。応募できるかどうかは公式ページで確認してください"),   # 締切なし（発売直前の追加抽選など）
])
def test_unknown_lottery_is_never_called_closed_and_has_no_apply_link(monkeypatch, ev, expect):
    """【M1】状態が UNKNOWN の抽選を『応募は締切済み』と断定しない。理由別の本文・応募リンクなし・公式の告知へのリンクは可。"""
    card = _cards(_html(_build([], [_ev(**ev)], monkeypatch=monkeypatch)))["POKEMON:deck"]
    li = _lot_lis(card)
    assert len(li) == 1 and expect in li[0], li
    assert "締切済み" not in card and "応募ページ" not in li[0] and "https://draw.geo-online.co.jp/lottery/100" not in card
    assert 'data-lot-status="UNKNOWN"' in li[0] and "公式の告知" in li[0]


def test_unknown_lottery_has_its_own_chip_and_is_not_counted_as_open(monkeypatch):
    evs = [_ev(n=1), _ev(n=2, verified=False), _ev(n=3, conflict=True), _ev(n=4, application_end=None)]
    hub = _build([], evs, monkeypatch=monkeypatch)
    cn = hub["products"][0]["counts"]
    assert cn["open"] == 1 and cn["unknown"] == 3                                   # 受付中に入るのは確認済み・食い違いなしだけ
    card = _cards(_html(hub))["POKEMON:deck"]
    assert "<b>1</b>受付中" in card and 'data-chip-unknown>日程未確認 <b>3</b>' in card
    assert "<b>3</b>受付中" not in card and "<b>4</b>受付中" not in card


def test_unknown_lottery_is_not_hidden_behind_the_top_three(monkeypatch):
    """【M1】応募できる抽選が 4 件あっても、日程未確認の抽選が 3 件の外に隠れて見えなくならない。並びは 応募できる状態 → 日程未確認 → 結果待ち。"""
    evs = [_ev(n=i, application_end=f"2026-11-2{i + 2}T23:59:00+09:00") for i in range(1, 5)]           # 受付中 4 件（締切 11/23〜11/26）
    evs.append(_ev(n=5, application_end=None))                                                          # 日程未確認
    evs.append(_ev(n=6, application_end="2026-11-20T23:59:00+09:00", winner_announcement_at="2026-11-23T12:00:00+09:00"))   # 結果待ち
    hub = _build([], evs, monkeypatch=monkeypatch)
    items = hub["products"][0]["lottery_items"]
    assert [i["eff_status"] for i in items] == ["OPEN", "OPEN", "OPEN", "OPEN", "UNKNOWN", "RESULT_PENDING"]
    card = _cards(_html(hub))["POKEMON:deck"]
    shown = re.findall(r'data-lot-item data-lot-status="([^"]+)"', card)
    assert len(shown) == 3 and "UNKNOWN" in shown and "RESULT_PENDING" not in shown
    assert shown == sorted(shown, key=lambda s: ["OPEN", "UNKNOWN"].index(s))             # 並び（応募できる状態 → 未確認）は保つ


def test_ended_item_is_never_first_and_summary_text_matches_the_real_order(monkeypatch):
    evs = [_ev(n=1, application_end="2026-11-20T23:59:00+09:00", winner_announcement_at="2026-11-23T12:00:00+09:00"),      # 結果待ち（締切済み）
           _ev(n=2, application_end="2026-11-28T23:59:00+09:00"),                                                          # 受付中
           _ev(n=3, application_end=None)]                                                                                 # 日程未確認
    card = _cards(_html(_build([], evs, monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert re.findall(r'data-lot-item data-lot-status="([^"]+)"', card) == ["OPEN", "UNKNOWN", "RESULT_PENDING"]
    assert "受付中・締切間近 → 開始前 → 日程未確認 → 結果待ち・購入期間の順" in card


def test_ended_application_is_still_not_open_and_only_verified_counts(monkeypatch):
    """既存の安全規則: 応募終了後は新規応募できるように見せない・受付中に数えるのは verified かつ conflict なしだけ。"""
    ended = _ev(n=1, application_end="2026-11-20T23:59:00+09:00", winner_announcement_at="2026-11-23T12:00:00+09:00")
    card = _cards(_html(_build([], [ended], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert "応募は締切済み" in card and "応募ページ" not in card and "受付中" not in card.split('class="chips"')[1].split("</div>")[0]


# ── M3: マスタに無い商品でも、利益候補を捨てない ──
def test_product_without_master_keeps_its_profit_opportunity_when_a_lottery_block_exists(monkeypatch):
    msrp = [{"tcg": "ONE_PIECE", "product_id": "op1", "retail_price": 5500, "basis": "product_unit", "checked_at": "2026-11-21",
             "official_url": "https://www.onepiece-cardgame.com/products/op1/"}]
    ev = _ev("op1", "OP ブースター", tcg="ONE_PIECE")
    hub = _build([row(price=9000, jan=OP_JAN, name="OP BOX")], [ev], msrp=msrp, monkeypatch=monkeypatch)
    assert any(o["product_id"] == "op1" for o in hub["opportunities"])                       # 利益候補がある
    card = [c for c in hub["cards"] if c["product_id"] == "op1"]
    assert len(card) == 1 and card[0]["profit"]["net_profit"] == 3500 and card[0]["state"] == pv.O_PROFIT
    assert card[0]["has_events"] and card[0]["lottery_items"] and card[0]["in_products"]      # 抽選はブロック側から補う
    assert hub["stats"]["opportunities"] == sum(1 for c in hub["cards"] if c["state"] in (pv.O_PROFIT, pv.O_WATCH))
    html = _cards(_html(hub))["ONE_PIECE:op1"]
    assert "+3,500円" in html and "data-lot-item" in html


# ── L7: 買取があるのにカードが無い商品 ──
def test_buyback_only_product_gets_a_card_without_profit_and_no_row_means_no_card(monkeypatch):
    hub = _build([row(price=6000, jan=SOLO_JAN)], monkeypatch=monkeypatch, msrp=[])          # solo: 発売済み・定価なし・抽選なし（以前は漏れていた）
    cards = _cards(_html(hub))
    assert "POKEMON:solo" in cards and "ONE_PIECE:op1" not in cards                          # 買取の行が無い op1 は出さない
    solo = cards["POKEMON:solo"]
    assert "公式定価が未確認のため利益は算出前です" in solo and "¥6,000" in solo and not re.search(r"[+\-−][\d,]+円", solo)
    assert hub["stats"]["cards"] == len(hub["cards"]) == len(_order(_html(hub)))
    html = _html(hub)
    assert f'商品と利益（{len(hub["cards"])}）' in html and f'<b>{len(hub["cards"])}</b>商品数' in html     # 見出しの数え方をカード数に揃える


# ── L1・L2・L3・L4 ──
def test_others_guide_text_is_accurate_and_shops_are_counted_by_shop_not_row(monkeypatch):
    """【L1/L2】折りたたみの説明は『実行可能な店の中での最高額』。店数は重複しない店（最高買取の店の別条件の行は数えない）。"""
    rows = [row(price=8000, jan=DECK_JAN), row(shop="kaitorishouten", price=9000, jan=DECK_JAN, upd="2026-11-21"),
            row(shop="kaitorishouten", price=43000, jan=DECK_JAN, cond=bb.C_NEW, upd="2026-11-21")]
    card = _cards(_html(_build(rows, monkeypatch=monkeypatch)))["POKEMON:deck"]
    det = card[card.index('<details class="tc-others"'):card.index("</details>", card.index('<details class="tc-others"'))]
    assert "実行可能（受付中・条件を確認できた）な店の中での最高額を上に出しています" in det and "最高額の店だけを上に出しています" not in det
    assert "価格が高くても参考で、最高買取にしません" in det
    assert "他の買取店（1 店）・同じ店の別条件 1 件" in det and "（2 店）" not in det
    assert det.count("同じ店の別条件です（店数には数えません）") == 1


def test_no_best_card_does_not_claim_the_highest_shop_is_shown(monkeypatch):
    out = _cards(_html(_build([row(price=30000, jan=DECK_JAN)], monkeypatch=monkeypatch)))["POKEMON:deck"]          # 外れ値
    assert "最高買取は確認待ち（外れ値確認中）" in out or "掲載のある買取店" not in out
    listed = _cards(_html(_build([row(price=8000, jan=DECK_JAN, obs=NOW - timedelta(hours=60))], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert "最高額の店だけを上に出しています" not in listed and "最高買取は確認できていません" in listed


def test_profit_premise_says_msrp_purchase_availability_is_not_shown(monkeypatch):
    """【L3】利益の前提に、定価で購入できるか（在庫・抽選）は示していない旨がカード内にある（live の中。利益と一緒に出る）。"""
    card = _cards(_html(_build(ROWS, monkeypatch=monkeypatch)))["POKEMON:deck"]
    s = "この利益は、公式定価で購入できた場合の計算です。購入できるかどうか（在庫・抽選）は示していません"
    assert s in card
    profit_li = re.search(r"<li data-strip-profit>.*?</li>", card, re.S).group(0)
    assert s in profit_li and profit_li.index("data-fb-live") < profit_li.index(s)


def test_unbound_applying_note_is_per_tcg(monkeypatch):
    """【L4】ポケカの未紐付けの受付中の案内が、ONE PIECE のカードに付かない（その逆も）。"""
    ended_p = _ev(application_start="2026-11-01T10:00:00+09:00", application_end="2026-11-02T23:59:00+09:00")
    ended_o = _ev("op1", "OP ブースター", n=2, tcg="ONE_PIECE", application_start="2026-11-01T10:00:00+09:00", application_end="2026-11-02T23:59:00+09:00")
    unlinked_p = _ev(n=3, product_match="none", product_id=None, product_name="二種（再販）")
    hub = _build([], [ended_p, ended_o, unlinked_p], monkeypatch=monkeypatch)
    assert hub["stats"]["unbound_applying_by_tcg"] == {"POKEMON": 1}
    cards = _cards(_html(hub))
    assert "紐付け前の告知は抽選一覧を参照" in cards["POKEMON:deck"]
    assert "紐付け前の告知は抽選一覧を参照" not in cards["ONE_PIECE:op1"] and "この商品に紐付いた、応募受付中の抽選はありません" in cards["ONE_PIECE:op1"]


# ── 独立レビュー M1: 開始前が受付中を押し出さない ──
def _lot_shown(card: str) -> list:
    return re.findall(r'data-lot-item data-lot-status="([^"]+)"', card)


def test_open_lottery_is_not_pushed_out_by_three_upcoming_ones(monkeypatch):
    """開始前 3 件（締切 11/26・27・28）＋受付中 1 件（締切 11/30）。締切順だけだと開始前だけが表示され、受付中が details に出なかった。"""
    evs = [_ev(n=i, application_start="2026-11-24T10:00:00+09:00", application_end=f"2026-11-2{i + 5}T23:59:00+09:00") for i in range(1, 4)]
    evs.append(_ev(n=4, application_end="2026-11-30T23:59:00+09:00"))
    hub = _build([], evs, monkeypatch=monkeypatch)
    assert [i["eff_status"] for i in hub["products"][0]["lottery_items"]] == ["OPEN", "UPCOMING", "UPCOMING", "UPCOMING"]
    card = _cards(_html(hub))["POKEMON:deck"]
    assert "<b>1</b>受付中" in card
    assert _lot_shown(card) == ["OPEN", "UPCOMING", "UPCOMING"]                                   # 受付中が先頭。開始前は締切順
    assert "店4" in card and "店3" not in card


def test_four_open_lotteries_show_three_by_deadline(monkeypatch):
    evs = [_ev(n=i, application_end=f"2026-11-{d}T23:59:00+09:00") for i, d in ((1, 29), (2, 26), (3, 28), (4, 27))]
    card = _cards(_html(_build([], evs, monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert _lot_shown(card) == ["OPEN", "OPEN", "OPEN"]
    shops = re.findall(r"<li data-lot-item[^>]*><b>([^<]+)</b>", card)
    assert shops == ["店2", "店4", "店3"]                                                          # 締切 11/26・27・28。11/29 の店1 は 4 件目で出ない


def test_unknown_swap_never_drops_every_open_lottery(monkeypatch):
    evs = [_ev(n=1, application_end="2026-11-30T23:59:00+09:00"),                                   # 受付中 1 件
           *[_ev(n=i, application_start="2026-11-24T10:00:00+09:00", application_end=f"2026-11-2{i + 5}T23:59:00+09:00") for i in range(2, 5)],   # 開始前 3 件
           _ev(n=5, application_end=None)]                                                          # 日程未確認
    card = _cards(_html(_build([], evs, monkeypatch=monkeypatch)))["POKEMON:deck"]
    shown = _lot_shown(card)
    assert shown == ["OPEN", "UPCOMING", "UNKNOWN"]                                                # 未確認は 3 件目と入れ替えて 1 件見せる。受付中は落とさない


def test_lot_phase_orders_open_before_upcoming_before_unknown():
    mk = lambda e: {"eff_status": e}                                                              # noqa: E731
    ph = {e: pv._lot_phase(mk(e)) for e in ("OPEN", "ENDING_SOON", "UPCOMING", "UNKNOWN", "RESULT_PENDING", "WINNER_PURCHASE_PERIOD")}
    assert ph["OPEN"] == ph["ENDING_SOON"] < ph["UPCOMING"] < ph["UNKNOWN"] < ph["RESULT_PENDING"] == ph["WINNER_PURCHASE_PERIOD"]


# ── 独立監査 M1: 販売店の BOX 価格の節で応募受付中の行がある商品に、案内を出す ──
def _rb_ref(pid="deck", state="OPEN", kind="NOT_CALCULATED", human=False, **kw):
    d = {"id": "R1", "tcg": "POKEMON", "product_id": pid, "shop": "ホビーステーション", "unit": "BOX", "price_jpy": 6000, "accept_state": state,
         "accept_label": "応募受付中" if state == "OPEN" else "応募終了", "kind": kind, "reason": "買取価格の不足", "human_confirmed": human,
         "apply_end": "2026-11-26", "source_url": "https://www.hbst.net/x/", "verified_at": "2026-11-25"}
    d.update(kw)
    return d


HINT = "販売店の告知で応募受付中の行があります"


def test_retailer_open_row_adds_a_hint_to_the_product_card(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    hub["retailer_references"] = [_rb_ref("deck", human=False)]
    cards = _cards(_html(hub))
    assert HINT in cards["POKEMON:deck"] and "商品の紐付けは未確認" in cards["POKEMON:deck"] and "data-rb-hint" in cards["POKEMON:deck"]
    assert HINT not in cards["POKEMON:box"]                                                       # 別の product_id のカードには出ない
    hub["retailer_references"] = [_rb_ref("deck", human=True)]
    c2 = _cards(_html(hub))["POKEMON:deck"]
    assert HINT in c2 and "紐付けは未確認" not in c2


def test_retailer_hint_is_not_shown_for_closed_or_rejected_rows_and_is_not_a_chip(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    for r in (_rb_ref("deck", state="ENDED"), _rb_ref("deck", state="WINNERS_ONLY"), _rb_ref("deck", kind="REJECTED")):
        hub["retailer_references"] = [r]
        assert HINT not in _cards(_html(hub))["POKEMON:deck"], r
    hub["retailer_references"] = [_rb_ref("deck")]
    card = _cards(_html(hub))["POKEMON:deck"]
    assert 'class="chip' not in card.split("data-rb-hint")[0].split('class="tc-lot"')[1]           # チップ（受付中の数）には入れない
    assert "<b>1</b>受付中" not in card and "応募受付中の抽選はありません" in card                    # 抽選側の判定は変えない


# ── 独立監査 L4: 店名は日本語名（列挙値のまま出さない） ──
def test_pokemon_center_is_shown_with_its_japanese_name(monkeypatch):
    ev = _ev(n=1, retailer="POKEMON_CENTER_ONLINE")
    for k in ("retailer_name", "store_name"):
        ev.pop(k)
    ev2 = _ev(n=2, retailer="POKEMON_CENTER_ONLINE", retailer_name="ポケモンセンターオンライン")
    ev2.pop("store_name")
    hub = _build([], [ev, ev2], monkeypatch=monkeypatch)
    html = _html(hub)
    assert [i["shop"] for i in hub["products"][0]["lottery_items"]] == ["ポケモンセンターオンライン"] * 2
    card = _cards(html)["POKEMON:deck"]
    assert "POKEMON_CENTER_ONLINE" not in card
    sel = re.search(r'<select name="retailer">.*?</select>', html, re.S).group(0)
    assert re.findall(r'<option value="([^"]*)">([^<]*)</option>', sel).count(("POKEMON_CENTER_ONLINE", "ポケモンセンターオンライン")) == 1
    assert sel.count('value="POKEMON_CENTER_ONLINE"') == 1 and ">POKEMON_CENTER_ONLINE<" not in sel
    tbl = html[html.index('id="lottery"'):]
    assert ">POKEMON_CENTER_ONLINE<" not in tbl and "<b>POKEMON_CENTER_ONLINE" not in tbl


# ══════════════ レビュー指摘の回帰テスト ══════════════
import json  # noqa: E402
import subprocess  # noqa: E402


class _RbWalk(HTMLParser):
    """JS_RB を node で動かした結果を反映して、見える文字を集める（data-rb-card ごとに失効 → data-rb-open を隠し data-rb-expired を出す）。"""
    VOID = {"img", "br", "input", "meta", "link", "hr"}

    def __init__(self, result=None):
        super().__init__()
        self.cards: list = []            # 文書順の data-rb-card: {"until", "n_exp"}
        self.result = result             # node の結果 [{expired, hidden:[...]}]
        self.stack: list = []            # (tag, hide, card_index)
        self.visible: list = []
        self.ci = -1
        self.ei: dict = {}

    def _card_of(self):
        for _t, _h, c in reversed(self.stack):
            if c is not None:
                return c
        return None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.VOID:
            return
        hide = False
        card = None
        if "data-rb-card" in a:
            if self.result is None:
                self.cards.append({"until": a.get("data-rb-until"), "n_exp": 0})
            self.ci += 1
            card = self.ci
        cur = card if card is not None else self._card_of()
        if cur is not None and self.result is None and "data-rb-expired" in a and card is None:
            self.cards[cur]["n_exp"] += 1
        if cur is not None and self.result is not None:
            r = self.result[cur]
            if "data-rb-open" in a and r["expired"]:
                hide = True
            if "data-rb-expired" in a and card is None:
                k = self.ei.get(cur, 0)
                self.ei[cur] = k + 1
                hide = bool(r["hidden"][k])
        self.stack.append((tag, hide, card))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not data.strip() or any(t in ("script", "style") for t, _h, _c in self.stack):
            return
        if not any(h for _t, h, _c in self.stack):
            self.visible.append(data.strip())


def _rb_visible(html: str, now_iso: str) -> str:
    """生成した HTML に、実際の JS_RB を now_iso の時点で適用したあとの、見える文字。"""
    w0 = _RbWalk()
    w0.feed(html)
    script = r"""
const vm=require('vm');
const cards=%s;
const mk=(c)=>{const exp=[];for(let i=0;i<c.n_exp;i++)exp.push({hidden:true});
 return {exp:exp,cls:{},getAttribute:(k)=>k==='data-rb-until'?c.until:null,classList:{toggle:(n,v)=>{this._v=v;mk.last=v}},querySelectorAll:()=>exp};};
const els=cards.map((c)=>{const e=mk(c);e.expired=false;e.classList={toggle:(n,v)=>{e.expired=!!v}};return e;});
const ctx={window:{addEventListener:()=>{}},document:{querySelectorAll:(q)=>q==='[data-rb-card]'?els:[],addEventListener:()=>{}},
 setInterval:()=>0,Date:{now:()=>Date.parse(%s),parse:Date.parse},isNaN:isNaN};
vm.createContext(ctx);vm.runInContext(%s,ctx);
console.log(JSON.stringify(els.map((e)=>({expired:e.expired,hidden:e.exp.map((x)=>x.hidden)}))));
""" % (json.dumps(w0.cards), json.dumps(now_iso), json.dumps(page.JS_RB))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, env={"TZ": "UTC", "PATH": "/usr/bin:/usr/local/bin:/opt/homebrew/bin"})
    assert out.returncode == 0, out.stderr
    w1 = _RbWalk(json.loads(out.stdout))
    w1.feed(html)
    return " ".join(w1.visible)


# ── Reviewer M1 / Auditor L1: 店名・商品種別の列挙値を出さない ──
def test_enum_valued_retailer_name_falls_back_to_the_registry_japanese_name():
    ev = {"retailer": "POKEMON_CENTER_ONLINE", "retailer_name": "POKEMON_CENTER_ONLINE", "store_name": None}
    assert pv.retailer_label(ev) == "ポケモンセンターオンライン" and pv.retailer_label(ev, store=False) == "ポケモンセンターオンライン"
    assert pv.retailer_label({**ev, "store_name": "POKEMON_CENTER_ONLINE"}) == "ポケモンセンターオンライン"
    assert pv.retailer_label({"retailer": "GEO", "retailer_name": "ゲオ", "store_name": "ゲオ新宿店"}) == "ゲオ新宿店"      # 日本語の名前は従来どおり
    assert pv.retailer_label({"retailer": "UNKNOWN_SHOP_X", "retailer_name": "UNKNOWN_SHOP_X"}) == "店舗不明"             # 日本語名が無ければ列挙値を出さない
    assert pv.retailer_label({"retailer": "shop-a", "retailer_name": "shop-a"}) == "店舗不明"                              # retailer のキーと同じ文字列も採用しない


def test_enum_valued_retailer_name_is_not_shown_in_table_or_filter(monkeypatch):
    ev = _ev(n=1, retailer="POKEMON_CENTER_ONLINE", retailer_name="POKEMON_CENTER_ONLINE", store_name=None)
    ev2 = _ev(n=2, retailer="POKEMON_CENTER_ONLINE", retailer_name="PCO", store_name="PCO 店頭受付")      # 同じ小売が複数（ラベルが違う）
    hub = _build([], [ev, ev2], monkeypatch=monkeypatch)
    html = _html(hub)
    tbl = html[html.index('id="lottery"'):]
    assert ">POKEMON_CENTER_ONLINE<" not in tbl and "<b>POKEMON_CENTER_ONLINE" not in tbl and "<small>POKEMON_CENTER_ONLINE" not in tbl
    assert "ポケモンセンターオンライン" in tbl
    sel = re.search(r'<select name="retailer">.*?</select>', html, re.S).group(0)
    opts = re.findall(r'<option value="([^"]*)">([^<]*)</option>', sel)
    assert ("POKEMON_CENTER_ONLINE", "ポケモンセンターオンライン") in opts and ">POKEMON_CENTER_ONLINE<" not in sel      # 代表ラベルは日本語名に固定
    assert len([o for o in opts if o[0] == "POKEMON_CENTER_ONLINE"]) == 1
    assert 'data-retailer="POKEMON_CENTER_ONLINE"' in tbl                                                                 # フィルタの value と行の data-retailer は一致


def test_raw_product_type_enum_is_not_shown_in_the_card_meta(monkeypatch):
    master = [_master("deck", "デッキセット"), _master("enh", "強化拡張パック テスト", "ENHANCED_BOOSTER")]
    evs = [_ev("deck", "デッキセット", 1), _ev("enh", "強化拡張パック テスト", 2)]
    html = _html(_build([], evs, master=master, monkeypatch=monkeypatch))
    cards = _cards(html)
    assert "ENHANCED_BOOSTER" not in cards["POKEMON:enh"]                                       # 日本語ラベルが無い種別は、生の値を出さず省く
    assert "構築済みデッキ" in cards["POKEMON:deck"]                                              # ラベルのある種別は従来どおり


# ── Reviewer M2: 販売店告知の案内にも期限を併記し、期限後は JS_RB で切り替える ──
def test_retailer_hint_carries_deadline_and_switches_after_it(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    hub["retailer_references"] = [_rb_ref("deck", apply_end="2026-11-26T23:59:00+09:00"), _rb_ref("deck", apply_end="2026-11-29T23:59:00+09:00")]
    card = _cards(_html(hub))["POKEMON:deck"]
    assert re.search(r'data-rb-hint data-rb-card data-rb-until="2026-11-26T23:59:00\+09:00"', card)       # 複数行は最も早い期限
    assert "応募期限 2026-11-26 23:59まで・生成時点の判定" in card
    assert HINT in _rb_visible(card, "2026-11-26T12:00:00+09:00")                                       # 期限内は案内が見える
    after = _rb_visible(card, "2026-11-27T00:30:00+09:00")
    assert HINT not in after and "応募期限を過ぎました" in after                                          # 期限後は受付中の行があるとは言わない


# ── Auditor M1: 抽選の受付中・締切間近・購入期間中が、締切後に失効する ──
def _lot_hub(monkeypatch, evs):
    return _build([], evs, monkeypatch=monkeypatch)


def test_lottery_open_states_expire_after_deadline_in_rows_chips_links_and_summary(monkeypatch):
    evs = [_ev(n=1, application_end="2026-11-26T23:59:00+09:00"),                                   # 受付中
           _ev(n=2, application_end="2026-11-22T10:00:00+09:00")]                                   # 締切間近（NOW から 24 時間以内）
    html = _html(_lot_hub(monkeypatch, evs))
    card = _cards(html)["POKEMON:deck"]
    # 期限内（11/22 09:00）: 何も変わらない
    before = _rb_visible(html, "2026-11-22T09:00:00+09:00")
    assert "受付中" in before and "応募ページ" in before and "応募期限を過ぎました" not in before and "期限が過ぎた抽選" not in before
    # 11/22 10:30: 締切間近の行・チップ・集計は切り替わる。受付中（11/26）の行はそのまま
    mid = _rb_visible(card, "2026-11-22T10:30:00+09:00")
    assert "締切間近（生成時点）" not in mid and "期限が過ぎた抽選があります" in mid
    assert "受付中（生成時点）" in mid and "応募期限を過ぎました" in mid           # 受付中のチップと行は生き、締切間近の行だけ失効
    # 11/27: すべて失効。応募リンクは隠れ、受付中の表示は残らない
    after_card = _rb_visible(card, "2026-11-27T00:30:00+09:00")
    assert "応募ページ" not in after_card and "受付中（生成時点）" not in after_card and "締切間近（生成時点）" not in after_card
    assert after_card.count("応募期限を過ぎました") >= 2 and "期限が過ぎた抽選があります" in after_card
    tbl_after = _rb_visible(html[html.index('id="lt-live"'):html.index("</table>", html.index('id="lt-live"'))], "2026-11-27T00:30:00+09:00")
    assert "応募ページ" not in tbl_after and tbl_after.count("応募期限を過ぎました") == 2 and "受付中" not in tbl_after      # 抽選表の行（状態バッジ・応募リンク）
    tbl_before = _rb_visible(html[html.index('id="lt-live"'):html.index("</table>", html.index('id="lt-live"'))], "2026-11-22T09:00:00+09:00")
    assert tbl_before.count("応募ページ") == 2 and "応募期限を過ぎました" not in tbl_before
    sum_after = re.search(r'<div class="sum">.*?</div></div>|<div class="sum">.*?(?=<details|<h2)', html, re.S)
    assert sum_after and 'data-rb-card' in sum_after.group(0) and "（生成時点）" in sum_after.group(0)
    top = _rb_visible(sum_after.group(0), "2026-11-27T00:30:00+09:00")
    assert "期限が過ぎた抽選があります" in top and "受付中（締切間近・未確認を含む）（生成時点）" not in top


def test_lottery_without_deadline_is_not_switched_and_has_no_rb_attrs(monkeypatch):
    evs = [_ev(n=1, application_end=None)]                                                           # 日程未確認（締切が無い）
    html = _html(_lot_hub(monkeypatch, evs))
    row = re.search(r'<tr class="ev[^>]*>', html).group(0)
    assert "data-rb-until" not in row and "data-rb-card" not in row
    li = re.search(r"<li data-lot-item[^>]*>", _cards(html)["POKEMON:deck"]).group(0)
    assert "data-rb-until" not in li
    tbl = html[html.index('id="lt-live"'):html.index("</table>", html.index('id="lt-live"'))]
    assert _rb_visible(tbl, "2030-01-01T00:00:00+09:00") == _rb_visible(tbl, "2026-11-22T00:00:00+09:00")        # 締切の無い行は、いつ見ても何も変わらない


def test_winner_purchase_period_expires_at_purchase_end(monkeypatch):
    winner = _ev(n=1, application_end="2026-11-18T23:59:00+09:00", purchase_start="2026-11-20T00:00:00+09:00",
                 purchase_end="2026-11-30T23:59:00+09:00", winner_announcement_at="2026-11-19T12:00:00+09:00")
    card = _cards(_html(_lot_hub(monkeypatch, [winner])))["POKEMON:deck"]
    assert re.search(r'data-lot-status="WINNER_PURCHASE_PERIOD" data-rb-card data-rb-until="2026-11-30T23:59:00\+09:00"', card)
    assert "購入期間中（当選者のみ）" in _rb_visible(card, "2026-11-29T00:00:00+09:00")
    after = _rb_visible(card, "2026-12-01T00:00:00+09:00")
    assert "購入期間中（当選者のみ）" not in after and "購入期間は終了しました" in after


def test_static_open_labels_carry_a_generated_time_note(monkeypatch):
    html = _html(_lot_hub(monkeypatch, [_ev(n=1, application_end="2026-11-26T23:59:00+09:00")]))
    assert "（生成時点）" in html and re.search(r'<span data-rb-open><span class="sb info">受付中</span><small>（生成時点）</small>', html)


# ── Auditor M2: 未確認の紐付けを商品名つきで断定しない ──
def test_unconfirmed_retailer_row_is_marked_in_box_section_and_references(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    hub["retailer_references"] = [_rb_ref("deck", human=False, kind="NOT_CALCULATED"), _rb_ref("deck", human=True, kind="NOT_CALCULATED", shop="確認済み店")]
    html = _html(hub)
    li = re.findall(r"<li[^>]*>(?:(?!</li>).)*</li>", html[html.index("応募受付中だが条件付き利益を計算できない"):], re.S)
    unconfirmed = next(x for x in li if "ホビーステーション" in x)
    confirmed = next(x for x in li if "確認済み店" in x)
    assert "（商品の紐付けは未確認）" in unconfirmed and "（商品の紐付けは未確認）" not in confirmed
    assert re.search(r"ホビーステーション・[^・<]+（商品の紐付けは未確認）", unconfirmed)                    # 商品名の直後


def test_unconfirmed_retailer_row_is_marked_on_the_conditional_card():
    from tests import test_tcg_retailer_box as RB
    h = RB.hub([RB.ent(human_confirmed=False)])
    sec = page.render(h)
    sec = sec[sec.index('id="retailer-box"'):sec.index('id="products"')]
    assert "（商品の紐付けは未確認）" in sec
    h2 = RB.hub([RB.ent(human_confirmed=True)])
    sec2 = page.render(h2)
    sec2 = sec2[sec2.index('id="retailer-box"'):sec2.index('id="products"')]
    assert "（商品の紐付けは未確認）" not in sec2


# ── Auditor L9: アンカーナビが共通ナビ（767px 以下で固定）と重ならない ──
def test_anchor_nav_top_is_below_the_fixed_site_nav_on_mobile():
    assert "@media(max-width:767px){nav.jump{top:53px}" in page.CSS            # 同じ media に scroll-margin 用の変数も入る（下のテスト）


# ══════════════ 独立監査・レビュー（第 2 回）の回帰テスト ══════════════
def _open_refs_html(hub) -> str:
    h = _html(hub)
    return h[h.index('id="retailer-open-refs"'):h.index("</details>", h.index('id="retailer-open-refs"'))]


# ── Auditor M1: 「応募受付中だが…」の見出し・本文も期限後に切り替わる ──
@needs_node
def test_open_refs_section_heading_and_body_switch_after_the_earliest_deadline(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    hub["retailer_references"] = [_rb_ref("deck", apply_end="2026-11-28"), _rb_ref("deck", shop="早い店", apply_end="2026-11-26T23:59:00+09:00")]
    html = _html(hub)
    sec = _open_refs_html(hub)
    assert re.search(r'<summary><span data-rb-card data-rb-until="2026-11-26T23:59:00\+09:00"><span data-rb-open>応募受付中だが条件付き利益を計算できない（2）</span>', sec)
    assert page.RB_EXPIRED_SECTION_HEAD in sec and page.RB_EXPIRED_SECTION_BODY in sec
    before = _rb_visible(html, "2026-11-26T12:00:00+09:00")
    assert "応募受付中だが条件付き利益を計算できない（2）" in before and "応募期間中の価格ですが" in before
    after = _rb_visible(html, "2026-11-27T12:00:00+09:00")                  # 早い行だけ失効（もう一方は 11/28 まで）
    assert "応募受付中だが" not in after and "応募期間中の価格ですが" not in after
    assert page.RB_EXPIRED_SECTION_HEAD in after and "（2）" in after.split(page.RB_EXPIRED_SECTION_HEAD)[1][:6]      # 件数は再計算しない
    assert "<li" in sec and sec.count("<li") == 2                             # 節は空にならない


def test_open_refs_section_without_deadline_stays_static_but_says_generated_time(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    hub["retailer_references"] = [_rb_ref("deck", apply_end=None)]
    sec = _open_refs_html(hub)
    assert "応募受付中だが条件付き利益を計算できない（1）（生成時点）" in sec and "data-rb-until" not in sec.split("<ul>")[0]


# ── Auditor M2: 抽選一覧の表でも、購入期間中は当選者のみ・新規応募不可 ──
def test_winner_purchase_period_row_in_the_table_says_winners_only(monkeypatch):
    winner = _ev(n=1, application_end="2026-11-18T23:59:00+09:00", purchase_start="2026-11-20T00:00:00+09:00",
                 purchase_end="2026-11-30T23:59:00+09:00", winner_announcement_at="2026-11-19T12:00:00+09:00")
    html = _html(_lot_hub(monkeypatch, [winner]))
    tbl = html[html.index('id="lt-live"') if 'id="lt-live"' in html else html.index('id="lottery"'):]
    row_ = re.search(r'<tr class="ev[^>]*>.*?</tr>', tbl, re.S).group(0)
    assert "購入期間中（当選者のみ・新規応募不可）" in row_ and "購入期間中</span>" not in row_ and "購入期間中（生成時点）" not in row_
    if _has_node():
        assert "購入期間は終了しました" in _rb_visible(row_, "2026-12-01T00:00:00+09:00")           # 期限後の文言は維持
        assert "当選者のみ" not in _rb_visible(row_, "2026-12-01T00:00:00+09:00")


def _has_node() -> bool:
    import shutil
    return shutil.which("node") is not None


# ── Auditor M3: 告知名の食い違い（ホビーステーション「二種」）を併記する ──
def _hbst_hub(monkeypatch, ann_name="拡張パック二種（再販）", url="https://hbst.net/?p=412193", human=False):
    ev = _ev(n=9, name=ann_name, product_id=None, product_match="none", retailer="HOBBY_STATION", retailer_name="ホビーステーション",
             store_name="ホビーステーション", source_url=url, application_end="2026-11-26T23:59:00+09:00")
    hub = _build([], [ev], monkeypatch=monkeypatch)
    hub["retailer_references"] = [_rb_ref("deck", human=human, display_name="ハドウシーカー", source_url=url)]
    return hub


def test_announcement_name_is_shown_next_to_the_ledger_product_when_it_is_multi_product(monkeypatch):
    html = _html(_hbst_hub(monkeypatch))
    sec = _open_refs_html(_hbst_hub(monkeypatch))
    assert "告知名は「拡張パック二種（再販）」です。二種のうちどちらの価格かは公式ページで確認してください" in sec
    assert "（商品の紐付けは未確認）" in sec
    card = _cards(html)["POKEMON:deck"]
    assert "告知名は「拡張パック二種（再販）」です" in card                                  # 商品カードの案内にも短く併記


def test_announcement_name_is_not_added_without_a_matching_url_or_a_multi_product_word(monkeypatch):
    other = _open_refs_html(_hbst_hub(monkeypatch, url="https://hbst.net/?p=1"))              # 同じ URL の抽選なし（台帳側だけ別 URL）
    hub = _hbst_hub(monkeypatch)
    hub["retailer_references"][0]["source_url"] = "https://hbst.net/?p=999"
    assert "告知名は" not in _open_refs_html(hub)
    single = _hbst_hub(monkeypatch, ann_name="ハドウシーカー BOX")
    assert "告知名は" not in _open_refs_html(single) and "告知名は" not in _cards(_html(single))["POKEMON:deck"]
    assert "告知名は" in other                                                                # 上は同 URL（p=1）で併記される対照


# ── Reviewer L1: カレンダーの副表示 store も列挙値を出さない ──
def test_calendar_store_enum_value_is_not_shown(monkeypatch):
    ev = _ev(n=1, retailer="POKEMON_CENTER_ONLINE", retailer_name="POKEMON_CENTER_ONLINE", store_name="POKEMON_CENTER_ONLINE",
             application_end="2026-11-28T23:59:00+09:00")
    hub = _build([], [ev], monkeypatch=monkeypatch)
    assert all(c["store"] != "POKEMON_CENTER_ONLINE" for c in hub["calendar"])
    html = _html(hub)
    cal = html[html.index('id="calendar"'):]
    assert "POKEMON_CENTER_ONLINE" not in cal
    assert "ポケモンセンターオンライン" in cal
    assert "POKEMON_CENTER_ONLINE" not in page._cal_item({"kind": hub["calendar"][0]["kind"], "time": None, "verified": True, "label": "x",
                                                         "retailer": "", "store": "POKEMON_CENTER_ONLINE"})


# ── Reviewer L3 / Auditor L6: アンカーのジャンプ先が固定ナビの下に隠れない ──
def test_scroll_margin_clears_the_fixed_navs_per_media_query():
    css = page.CSS
    for sel in (".tcard{", ".pcard{", "h2{"):
        assert re.search(re.escape(sel) + r"[^}]*scroll-margin-top:var\(--jump-offset\)", css), sel
    assert "scroll-margin-top:56px" not in css
    assert re.search(r":root\{--jump-offset:(\d+)px\}", css)
    base = int(re.search(r":root\{--jump-offset:(\d+)px\}", css).group(1))
    mob = int(re.search(r"@media\(max-width:767px\)\{[^@]*:root\{--jump-offset:(\d+)px\}", css).group(1))
    assert base >= 56 + 4                                   # 768px 以上: nav.jump（約 56px）に隠れない
    assert mob >= 53 + 56 + 4                               # 767px 以下: 共通ナビ（53px）+ nav.jump（約 56px）


# ── Reviewer L5: 期限後は状態フィルタの data-state からも「受付中」等を外す ──
@needs_node
def test_expired_row_leaves_the_open_state_filter(monkeypatch):
    html = _html(_lot_hub(monkeypatch, [_ev(n=1, application_end="2026-11-26T23:59:00+09:00")]))
    state = re.search(r'<tr class="ev[^>]*data-state="([^"]*)"', html).group(1)
    until = re.search(r'<tr class="ev[^>]*data-rb-until="([^"]+)"', html).group(1)
    assert "open" in state.split()

    def run(now):
        script = r"""
const vm=require('vm');
const attrs={'data-state':%s,'data-rb-until':%s};let changed=0;
const row={classList:{toggle:()=>{}},getAttribute:(k)=>k in attrs?attrs[k]:null,setAttribute:(k,v)=>{attrs[k]=v},querySelectorAll:()=>[]};
const ctx={window:{addEventListener:()=>{}},Event:function(t){this.type=t},document:{querySelectorAll:(q)=>q==='[data-rb-card]'?[row]:[],
 getElementById:(i)=>i==='flt'?{dispatchEvent:()=>{changed++}}:null,addEventListener:()=>{}},setInterval:()=>0,Date:{now:()=>Date.parse(%s),parse:Date.parse},isNaN:isNaN};
vm.createContext(ctx);vm.runInContext(%s,ctx);
console.log(JSON.stringify({state:attrs['data-state'],changed:changed}));
""" % (json.dumps(state), json.dumps(until), json.dumps(now), json.dumps(page.JS_RB))
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, env={"TZ": "UTC", "PATH": "/usr/bin:/usr/local/bin:/opt/homebrew/bin"})
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    assert run("2026-11-26T12:00:00+09:00")["state"] == state                         # 期限内は変えない
    after = run("2026-11-27T00:00:00+09:00")
    assert not ({"open", "ending", "upcoming", "today", "deadline"} & set(after["state"].split())) and after["changed"] == 1      # 期限後は外し、フィルタを再実行させる


def test_long_status_badges_wrap_and_do_not_widen_the_mobile_table(monkeypatch):
    # 本番（375px）で、抽選表の長いバッジ『購入期間中（当選者のみ・新規応募不可）（生成時点）』が折り返されず、
    # 表のセルを押し広げて横スクロール（スクロール幅 445px）が出た。バッジは折り返せること・スマホ表示のセルは min-width:0 であること
    html = _html(_build([], monkeypatch=monkeypatch))
    badge = re.search(r"\.sb\{[^}]*\}", html).group(0)
    assert "white-space:normal" in badge and "overflow-wrap:anywhere" in badge and "max-width:100%" in badge
    assert "white-space:nowrap" not in badge
    assert ".lt td{min-width:0}" in html
