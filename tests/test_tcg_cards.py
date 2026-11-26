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


def _lhtml(hub):
    """抽選のページ（docs/tcg-lottery.html）。"""
    return page.render_lottery(hub, generated_label="x")


def _rows(html: str) -> str:
    """抽選一覧の行（<tr class="ev">）だけを続けた HTML。"""
    return "".join(re.findall(r'<tr class="ev.*?</tr>', html, re.S))


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
    assert "¥9,000" in best and "買取商店" in best and "¥8,000" not in best and '<small class="u">セット</small>¥9,000' in best      # 最高額の 1 店だけ・金額に単位
    profit = re.search(r"<li data-strip-profit>(.*?)</li>", strip, re.S).group(1)
    assert "+1,800円" in profit and "ROI 29%" in profit and "買取ルデヤ" in profit                 # 利益の売却先（費用が分かる基準店）を併記
    diff = re.search(r"<li data-strip-diff>(.*?)</li>", strip, re.S).group(1)             # 別行
    assert "<em>差額</em>" in diff and "+2,800円" in diff and "買取商店・費用未確認" in diff      # 最高買取の店は費用未確認なので、利益ではなく差額
    assert "+2,800円" not in profit and "+1,800円" not in diff                              # 差額を利益に混ぜない


def test_no_difference_row_when_the_best_shop_is_the_base_shop(monkeypatch):
    html = _html(_build([row(price=8000, jan=DECK_JAN)], monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    assert "data-strip-diff" not in card and "+1,800円" in card and "1店のみ" in card


def test_loss_is_shown_with_neg_text_color_not_a_badge_and_no_green_buy_badge(monkeypatch):
    html = _html(_build([row(price=5800, jan=DECK_JAN)], monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    assert '<b class="amt neg">-400円</b>' in card and "・赤字" in card
    ok = _cards(_html(_build([row(price=9000, jan=DECK_JAN)], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert '<b class="amt pos">+2,800円</b>' in ok
    for c in (card, ok):
        assert "購入推奨" not in c and "BUY" not in c and 'class="sb ok"' not in c and "今すぐ買" not in c


def test_missing_msrp_missing_buyback_and_outlier_states(monkeypatch):
    # 定価なし（BOX。パック価格だけの商品）: 定価の欄は公式の 1 パック価格だけ（BOX の定価は作らない）。利益は「—」。買取は出す
    master = [_master("deck", "デッキセット"), _master("box", "拡張パック BOX", "BOOSTER_BOX", "2026-12-05", pack_price=180, retail_price_basis="pack"),
              _master("solo", "ソロ", rel="2026-01-01")]
    hub = _build([row(price=14000, jan=BOX_JAN, name="拡張パック BOX [M6]")], [_ev("box", "拡張パック BOX")], master=master, msrp=[], monkeypatch=monkeypatch)
    box = _cards(_html(hub))["POKEMON:box"]
    assert '<b class="amt pack">1パック ¥180</b>' in box and "¥1,440" not in box and "未確認" not in re.sub(r"<[^>]+>", "", box)
    profit = re.search(r"<li data-strip-profit>(.*?)</li>", box, re.S).group(1)
    assert profit == '<em>純利益</em><span class="tc-val"><b class="amt na">—</b></span>'      # 単位が違う（1 パックと BOX）: 利益は灰色の「—」
    assert "¥14,000" in box and not re.search(r"[+\-−][\d,]+円", box)                       # 利益も差額も出さない
    assert "data-strip-diff" not in box
    # 買取なし: 最高買取は灰色の「—」だけ（中身の無い説明は出さない）
    nob = _cards(_html(_build([], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert re.search(r"<li data-strip-best><em>.*?</em><span class=\"tc-val\"><b class=\"amt na\">—</b></span></li>", nob) and "+" not in re.sub(r"<[^>]+>", "", nob).replace("+0", "")
    assert "data-fb-live" not in nob                                                          # 金額が無いので live も無い
    # 外れ値（1 店だけで定価の 3 倍超）: 最高買取は「確認待ち」・価格も利益も出さない
    out = _cards(_html(_build([row(price=30000, jan=DECK_JAN)], monkeypatch=monkeypatch)))["POKEMON:deck"]
    best = re.search(r"<li data-strip-best>(.*?)</li>", out, re.S).group(1)
    assert "確認待ち" in best and "¥30,000" not in out and not re.search(r"[+\-−][\d,]+円", out) and "¥" not in best
    assert re.search(r'<span data-fb-live[^>]*hidden><small>確認待ち</small></span><span data-fb-stale', best)   # 理由のラベルも鮮度の判定の中


# ── 買取店の折りたたみ ──
def test_only_the_highest_shop_is_visible_when_closed_and_others_are_reference(monkeypatch):
    html = _html(_build(ROWS, monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    closed = card[:card.index('<details class="tc-others"')]
    best = re.search(r"<li data-strip-best>(.*?)</li>", closed, re.S).group(1)
    assert "買取商店" in best and "買取ルデヤ" not in best and "条件未確認" not in closed       # 閉じた状態の最高買取は最高額の 1 店だけ（ルデヤは利益の基準の併記・差額の注記に出るだけ）
    assert "data-other-shop" not in closed
    det = card[card.index('<details class="tc-others"'):card.index("</details>", card.index('<details class="tc-others"'))]
    assert "その他の売却先（2）" in det and "<details" in det and " open" not in det.split(">")[0]    # 最初は閉じている
    shops = re.findall(r'data-other-shop="([^"]+)" data-other-kind="([^"]+)"', det)
    assert shops == [("rudeya", "executable"), ("kaitorishouten", "reference")]
    ref = re.search(r'<li data-other-shop="kaitorishouten".*?</li>', det, re.S).group(0)
    assert "<small>参考</small>" in ref and "純利益 —" in ref and "同じ店の別条件" in ref                  # 参考（最高買取にしない）・費用未確認の他店は純利益「—」
    rud = re.search(r'<li data-other-shop="rudeya".*?</li>', det, re.S).group(0)
    assert "純利益 —" not in rud                                                                      # 費用の分かる基準店は「—」にしない


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
    assert "<small>受付停止</small>" in det
    assert 'data-other-kind="reference"' in det and "<small>参考</small>" in det
    assert "data-strip-profit" in card and "算出前" in card                                       # 基準にできる店（ルデヤ）が停止中: 利益は出さない
    assert not re.search(r"[+\-−][\d,]+円", card)


def test_listed_only_product_has_no_highest_and_lists_references(monkeypatch):
    hub = _build([row(price=8000, jan=DECK_JAN, obs=NOW - timedelta(hours=60))], monkeypatch=monkeypatch)
    card = _cards(_html(hub))["POKEMON:deck"]
    best = re.search(r"<li data-strip-best>(.*?)</li>", card, re.S).group(1)
    assert '<b class="amt na">—</b>' in best and "data-fb-live" not in best and "その他の売却先（1）" in card and "<small>参考</small>" in card
    assert "参考（受付・条件未確認）" in card
    assert not re.search(r"[+\-−][\d,]+円", card)


# ── 鮮度: live の中だけ・入れ子で漏れない・鮮度切れで消える ──
def test_every_buyback_amount_is_inside_live_and_live_has_no_nested_div_or_span(monkeypatch):
    html = _html(_build(ROWS, [_ev()], monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    w = _walk(card)
    assert w.nest_bad == [], w.nest_bad                                                      # live の内側に <div>/<span> を入れ子にしない
    outside = " ".join(w.outside) + " " + " ".join(w.attrs_outside)
    for amt in ("8,000", "9,000", "9,500", "+1,800", "+2,800", "29%"):
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
    for w in ("¥9,000", "+1,800円", "ROI 29%", "+2,800円", "¥8,000", "¥9,500"):
        assert w in vis, w                                                                  # 範囲内は出る（折りたたみ内の他店も）
    assert "再確認待ち" not in vis
    late = _apply(card, NOW + timedelta(hours=mx, minutes=1))
    vis = " ".join(_walk(card, [e["hidden"] for e in late]).visible)
    for w in ("¥9,000", "¥8,000", "¥9,500", "+1,800円", "+2,800円", "29%", "様子見"):
        assert w not in vis, w                                                              # 最高買取・利益・差額・他店の価格・状態バッジは出ない
    assert "再確認待ち" in vis and "確認待ち" in vis and "取得 11/21 18:00" not in vis       # stale は短いラベルだけ（取得時刻は表の上の注記に 1 回）
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
    assert "¥8,000" in vis and "+1,800円" in vis and "¥7,500" not in vis and "再確認待ち" in vis


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
    assert "この商品の抽選（4）" in det                                                 # 終了は数えない
    items = re.findall(r'data-lot-item data-lot-status="([^"]+)"', det)
    assert items == ["ENDING_SOON", "OPEN", "UPCOMING"]                                              # 最大 3 件・締切が近い順（段階順）
    assert "店2" in det and "店1" in det and "店4" not in det and "店5" not in det
    assert 'href="tcg-lottery.html#prod-p0">この商品の抽選をすべて見る（4）' in card                  # 抽選ページの、この商品で絞り込んだ一覧へ
    for chip in ("受付中<b>1</b>件", "締切間近<b>1</b>件", "当選発表待ち<b>1</b>件", "近日開始<b>1</b>件"):
        assert chip in card
    assert re.search(r'class="chip info" data-rb-card data-rb-until="[^"]+"><span data-rb-open>受付中<b>1</b>件', card)       # 締切のある件数は JS_RB で失効する
    assert re.search(r'class="chip danger" data-rb-card data-rb-until="[^"]+"><span data-rb-open>締切間近<b>1</b>件', card)
    assert 'class="chip warn">当選発表待ち<b>1</b>件' in card                                                               # 結果待ちは締切で失効しない


def test_ended_application_is_not_shown_as_newly_applicable_and_winner_period_is_a_separate_badge(monkeypatch):
    pending = _ev(n=1, application_end="2026-11-20T23:59:00+09:00", winner_announcement_at="2026-11-23T12:00:00+09:00")
    winner = _ev(n=2, application_end="2026-11-18T23:59:00+09:00", purchase_start="2026-11-20T00:00:00+09:00",
                 purchase_end="2026-11-30T23:59:00+09:00", winner_announcement_at="2026-11-19T12:00:00+09:00")
    card = _cards(_html(_build([], [pending, winner], monkeypatch=monkeypatch)))["POKEMON:deck"]
    li = re.findall(r"<li data-lot-item.*?</li>", card, re.S)
    assert len(li) == 2
    for x in li:
        assert "応募する" not in x and "btn cta" not in x                                          # 応募済み・結果待ち・購入期間: 新規応募のボタンを出さない
    assert 'data-lot-status="WINNER_PURCHASE_PERIOD"' in card and "当選者のみ" in card and "購入期間中（当選者のみ）" in card
    assert "結果待ち" in card
    chips = card[card.index('class="chips"'):card.index("</div>", card.index('class="chips"'))]
    assert "購入期間中（当選者のみ）" in chips and "受付中" not in chips                            # 一般の購入可否・受付中と混ぜない


def test_open_lottery_has_application_link_but_unverified_does_not_count_as_open(monkeypatch):
    ok = _cards(_html(_build([], [_ev()], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert 'href="https://draw.geo-online.co.jp/lottery/100"' in ok and "受付中<b>1</b>件" in ok
    un = _cards(_html(_build([], [_ev(verified=False)], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert "受付中<b>1</b>件" not in un and '<span class="sb out">未確認</span>' in un and "https://draw.geo-online.co.jp/lottery/100" not in un
    assert "公式ページで応募する" not in un and "data-chip-unknown" in un                        # 未確認は「日程未確認」の件数に分ける


def test_unbound_applying_guidance_is_kept(monkeypatch):
    ended = _ev(application_start="2026-11-01T10:00:00+09:00", application_end="2026-11-02T23:59:00+09:00")
    unlinked = _ev(n=3, product_match="none", product_id=None, product_name="二種（再販）")
    html = _html(_build([], [ended, unlinked], monkeypatch=monkeypatch))
    assert re.search(r'<a href="tcg-lottery.html#lt-open">このほかの受付中の抽選 <span data-cnt-untils="[^"]*" data-cnt-hide="\.unb">1</span>件</a>', html) and "受付中<b>1</b>件" not in html


# ── 画像 ──
def test_pokemon_image_only_from_official_https_alt_is_name_and_credit_once(monkeypatch):
    monkeypatch.setattr(__import__("src.tcg.verified_products", fromlist=["x"]), "IMAGE_USE_CLEARED", {"POKEMON": "test", "ONE_PIECE": "test"})
    img = "https://www.pokemon-card.com/products/2026/images/x.jpg"
    master = [_master("deck", "デッキセット", official_image_url=img), _master("solo", "ソロ", rel="2026-01-01", official_image_url="https://evil.example/x.jpg")]
    html = _html(_build(ROWS + [row(price=9500, jan=SOLO_JAN)], master=master, monkeypatch=monkeypatch))
    cards = _cards(html)
    assert f'src="{img}"' in cards["POKEMON:deck"] and 'alt="デッキセット"' in cards["POKEMON:deck"]
    assert 'referrerpolicy="no-referrer"' in cards["POKEMON:deck"] and 'loading="lazy"' in cards["POKEMON:deck"] and 'width="320" height="240"' in cards["POKEMON:deck"]
    assert "<img" not in cards["POKEMON:solo"] and "evil.example" not in html                 # 公式以外のドメインは使わない
    assert 'role="img"' in cards["POKEMON:solo"] and "<small>ポケカ</small>" in cards["POKEMON:solo"]
    assert html.count(page.IMG_CREDIT) == 1 and "公式サイトの画像を参照表示しています" in html          # 出典表記はページに 1 か所


@pytest.mark.parametrize("url,ok", [
    ("https://www.onepiece-cardgame.com/images/products/boosters/op18/img_thumbnail.png", True),
    ("https://onepiece-cardgame.com/x.png", True),
    ("https://www.pokemon-card.com/x.jpg", False),                  # ポケカのホストは ONE PIECE の画像にしない
    ("https://evil.example/x.png", False), ("http://www.onepiece-cardgame.com/x.png", False),
    ("https://www.onepiece-cardgame.com/images/common/noimage.png", False), ("javascript:alert(1)", False),
])
def test_one_piece_card_image_only_from_onepiece_official_https(monkeypatch, url, ok):
    """ONE PIECE は onepiece-cardgame.com の https なら画像。ポケカのホスト・外部ホスト・http・noimage はプレースホルダ。"""
    monkeypatch.setattr(__import__("src.tcg.verified_products", fromlist=["x"]), "IMAGE_USE_CLEARED", {"POKEMON": "test", "ONE_PIECE": "test"})
    hub = _build([row(price=9000, jan=OP_JAN, name="OP BOX")], [_ev("op1", "OP ブースター", tcg="ONE_PIECE")], monkeypatch=monkeypatch)
    for c in hub["cards"]:
        if c["tcg"] == "ONE_PIECE":
            c["image_url"], c["canonical"] = url, pv.C_MASTER
    html = _html(hub)
    op = _cards(html)["ONE_PIECE:op1"]
    if ok:
        assert f'src="{url}"' in op and 'referrerpolicy="no-referrer"' in op and "onerror=" in op
    else:
        assert "<img" not in op and "<small>ワンピ</small>" in op and "<b>OP</b>" in op and "商品画像なし" in op
        assert "evil.example" not in html and "javascript:" not in html
    assert "公式に商品固有の画像がない" not in html


# ── 構造・安全 ──
def test_page_has_no_green_buy_badge_and_cards_keep_the_old_safety_texts(monkeypatch):
    html = _html(_build(ROWS, [_ev()], monkeypatch=monkeypatch))
    cards_html = "".join(_cards(html).values())
    assert "購入推奨" not in cards_html and 'class="sb ok"' not in cards_html and "BUY" not in cards_html
    assert "買取商店・費用未確認" in cards_html                                                   # 最高買取の店（差額）と利益の基準店を混ぜない
    for note in ("基準:", "前提:", "この利益は", "（生成時点）", "単一ソース"):                       # 注記の文章は出さない（ラベルだけ）
        assert note not in html, note


def test_cards_do_not_overflow_on_a_375px_phone_by_css_contract():
    css = page.CSS
    assert ".tcard{" in css and "min-width:0" in css.split(".tcard{")[1].split("}")[0]
    assert "minmax(min(100%,420px),1fr)" in css and ".tcard{display:grid;grid-template-columns:96px minmax(0,1fr)" in css     # 狭い幅: 商品の行は 画像 | 名前（その下に数字 3 つ）
    assert "font-variant-numeric:tabular-nums" in css.split(".tc-strip{")[1].split("}")[0]
    assert "overflow-wrap:anywhere" in css.split(".tc-others li,.tc-lotd li{")[1].split("}")[0] and "overflow-wrap:anywhere" in css
    assert "min-width:0" in css.split("table.lt{")[1].split("}")[0] and ".tcard{padding:10px 0}" in css     # 狭い幅の調整
    assert "data-theme" not in css and "prefers-color-scheme" not in css and "999px" not in css and "box-shadow:0" not in css   # 白固定・ピルと影なし


@pytest.mark.parametrize("mutate", [
    lambda h: h.replace(" hidden>", ">", 1),                                  # live の hidden を外す（fail-open）
    lambda h: re.sub(r"(<span data-fb-live[^>]*>)<b class=\"amt\"><small class=\"u\">[^<]*</small>(¥9,000)</b>", r"\2\1", h, count=1),     # 金額を live の外へ出す
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
    (dict(verified=False), '<span class="sb out">未確認</span>'),                                  # 未確認（締切 11/25）
    (dict(conflict=True), '<span class="sb out">日程に食い違い</span>'),                            # 日程の食い違い
    (dict(application_end=None), '<span class="sb out">日程未確認</span><small>締切 未公表</small>'),   # 締切なし（発売直前の追加抽選など）
])
def test_unknown_lottery_is_never_called_closed_and_has_no_apply_link(monkeypatch, ev, expect):
    """【M1】状態が UNKNOWN の抽選を『応募は締切済み』と断定しない。理由別の本文・応募リンクなし・公式の告知へのリンクは可。"""
    card = _cards(_html(_build([], [_ev(**ev)], monkeypatch=monkeypatch)))["POKEMON:deck"]
    li = _lot_lis(card)
    assert len(li) == 1 and expect in li[0], li
    assert "締切済み" not in card and "応募する" not in li[0] and "https://draw.geo-online.co.jp/lottery/100" not in card
    assert 'data-lot-status="UNKNOWN"' in li[0] and "公式の告知" in li[0]


def test_unknown_lottery_has_its_own_chip_and_is_not_counted_as_open(monkeypatch):
    evs = [_ev(n=1), _ev(n=2, verified=False), _ev(n=3, conflict=True), _ev(n=4, application_end=None)]
    hub = _build([], evs, monkeypatch=monkeypatch)
    cn = hub["products"][0]["counts"]
    assert cn["open"] == 1 and cn["unknown"] == 3                                   # 受付中に入るのは確認済み・食い違いなしだけ
    card = _cards(_html(hub))["POKEMON:deck"]
    assert "受付中<b>1</b>件" in card and 'data-chip-unknown>日程未確認 <b>3</b>' in card
    assert "受付中<b>3</b>件" not in card and "受付中<b>4</b>件" not in card


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
    assert "この商品の抽選（3）" in card


def test_ended_application_is_still_not_open_and_only_verified_counts(monkeypatch):
    """既存の安全規則: 応募終了後は新規応募できるように見せない・受付中に数えるのは verified かつ conflict なしだけ。"""
    ended = _ev(n=1, application_end="2026-11-20T23:59:00+09:00", winner_announcement_at="2026-11-23T12:00:00+09:00")
    card = _cards(_html(_build([], [ended], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert "結果待ち" in card and "応募する" not in card and "受付中" not in card.split('class="chips"')[1].split("</div>")[0]


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
    profit = re.search(r"<li data-strip-profit>(.*?)</li>", solo, re.S).group(1)
    assert "<b class=\"amt na\">—</b>" in profit and "¥6,000" in solo and not re.search(r"[+\-−][\d,]+円", solo) and solo.count("未確認") == 1
    assert hub["stats"]["cards"] == len(hub["cards"]) == len(_order(_html(hub)))
    html = _html(hub)
    assert f'商品と利益（{len(hub["cards"])}）' in html and html.count("data-pt>") <= len(hub["cards"])        # 見出しの数え方をカード数に揃える（画像で選ぶ帯は、買取情報のない商品を除く）


# ── L1・L2・L3・L4 ──
def test_others_guide_text_is_accurate_and_shops_are_counted_by_shop_not_row(monkeypatch):
    """【L1/L2】最高買取は実行可能な店の中での最高額。参考（条件未確認）は価格が高くても最高買取にせず「参考」と示す。同じ店の別条件はその旨を 1 行だけ示す。"""
    rows = [row(price=8000, jan=DECK_JAN), row(shop="kaitorishouten", price=9000, jan=DECK_JAN, upd="2026-11-21"),
            row(shop="kaitorishouten", price=43000, jan=DECK_JAN, cond=bb.C_NEW, upd="2026-11-21")]
    card = _cards(_html(_build(rows, monkeypatch=monkeypatch)))["POKEMON:deck"]
    det = card[card.index('<details class="tc-others"'):card.index("</details>", card.index('<details class="tc-others"'))]
    best = re.search(r"<li data-strip-best>(.*?)</li>", card, re.S).group(1)
    assert "¥9,000" in best and "¥43,000" not in best
    ref = re.search(r'<li data-other-shop="kaitorishouten" data-other-kind="reference">.*?</li>', det, re.S).group(0)
    assert "¥43,000" in ref and "<small>参考</small>" in ref
    assert "その他の売却先（2）" in det and det.count("同じ店の別条件") == 1


def test_no_best_card_does_not_claim_the_highest_shop_is_shown(monkeypatch):
    out = _cards(_html(_build([row(price=30000, jan=DECK_JAN)], monkeypatch=monkeypatch)))["POKEMON:deck"]          # 外れ値
    best = re.search(r"<li data-strip-best>(.*?)</li>", out, re.S).group(1)
    assert "確認待ち" in best and "¥" not in best and "¥30,000" not in out
    listed = _cards(_html(_build([row(price=8000, jan=DECK_JAN, obs=NOW - timedelta(hours=60))], monkeypatch=monkeypatch)))["POKEMON:deck"]
    best = re.search(r"<li data-strip-best>(.*?)</li>", listed, re.S).group(1)
    assert '<b class="amt na">—</b>' in best and "data-fb-live" not in best


def test_profit_cell_is_entirely_gated_and_the_page_has_one_purchase_note(monkeypatch):
    """【L3】利益の欄（金額・ROI・売却先）は、ラベル以外すべて鮮度の判定（live / stale）の中。購入前に公式で確認する旨は最下部の 1 か所だけ。"""
    html = _html(_build(ROWS, monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    profit_li = re.search(r"<li data-strip-profit>.*?</li>", card, re.S).group(0)
    w = _walk(profit_li)
    assert w.outside == ["純利益"], w.outside                                                   # live / stale の外はラベルだけ
    assert html.count(page.FOOT_NOTE) == 1 and "応募・購入の前に公式ページで確認してください" in page.FOOT_NOTE


def test_unbound_applying_note_is_per_tcg(monkeypatch):
    """【L4】ポケカの未紐付けの受付中の案内が、ONE PIECE のカードに付かない（その逆も）。"""
    ended_p = _ev(application_start="2026-11-01T10:00:00+09:00", application_end="2026-11-02T23:59:00+09:00")
    ended_o = _ev("op1", "OP ブースター", n=2, tcg="ONE_PIECE", application_start="2026-11-01T10:00:00+09:00", application_end="2026-11-02T23:59:00+09:00")
    unlinked_p = _ev(n=3, product_match="none", product_id=None, product_name="二種（再販）")
    hub = _build([], [ended_p, ended_o, unlinked_p], monkeypatch=monkeypatch)
    assert hub["stats"]["unbound_applying_by_tcg"] == {"POKEMON": 1}
    cards = _cards(_html(hub))
    html = _html(hub)
    pok = html[html.index('id="cat-pokemon"'):html.index('id="cat-onepiece"')]
    op = html[html.index('id="cat-onepiece"'):html.index('id="opportunities"') if html.index('id="opportunities"') > html.index('id="cat-onepiece"') else None]
    op = op.split('class="plist"')[0]
    assert re.search(r"このほかの受付中の抽選 <span[^>]*>1</span>件", pok.split('class="plist"')[0])   # 見出しの下に TCG ごとに 1 回
    assert "商品未特定の受付中" not in op and "受付中<b>1</b>件" not in cards["ONE_PIECE:op1"]
    assert "商品未特定の受付中" not in cards["POKEMON:deck"]                                   # 行ごとには繰り返さない


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
    assert "受付中<b>1</b>件" in card
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


HINT = "販売店の抽選（条件付き）"


def test_retailer_open_row_adds_a_hint_to_the_product_card(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    hub["retailer_references"] = [_rb_ref("deck", human=False)]
    cards = _cards(_html(hub))
    assert HINT in cards["POKEMON:deck"] and "data-rb-hint" in cards["POKEMON:deck"] and "紐付け" not in cards["POKEMON:deck"]
    assert HINT not in cards["POKEMON:box"]                                                       # 別の product_id のカードには出ない
    hub["retailer_references"] = [_rb_ref("deck", human=True)]
    c2 = _cards(_html(hub))["POKEMON:deck"]
    assert HINT in c2


def test_retailer_hint_is_not_shown_for_closed_or_rejected_rows_and_is_not_a_chip(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    for r in (_rb_ref("deck", state="ENDED"), _rb_ref("deck", state="WINNERS_ONLY"), _rb_ref("deck", kind="REJECTED")):
        hub["retailer_references"] = [r]
        assert HINT not in _cards(_html(hub))["POKEMON:deck"], r
    hub["retailer_references"] = [_rb_ref("deck")]
    card = _cards(_html(hub))["POKEMON:deck"]
    assert 'class="chip' not in card.split("data-rb-hint")[0].split('class="tc-lot"')[1]           # チップ（受付中の数）には入れない
    assert "受付中<b>1</b>件" not in card and "data-lot-item" not in card                               # 抽選側の判定は変えない（チップにも抽選の一覧にも入れない）


# ── 独立監査 L4: 店名は日本語名（列挙値のまま出さない） ──
def test_pokemon_center_is_shown_with_its_japanese_name(monkeypatch):
    ev = _ev(n=1, retailer="POKEMON_CENTER_ONLINE")
    for k in ("retailer_name", "store_name"):
        ev.pop(k)
    ev2 = _ev(n=2, retailer="POKEMON_CENTER_ONLINE", retailer_name="ポケモンセンターオンライン")
    ev2.pop("store_name")
    hub = _build([], [ev, ev2], monkeypatch=monkeypatch)
    html = _lhtml(hub)
    assert [i["shop"] for i in hub["products"][0]["lottery_items"]] == ["ポケモンセンターオンライン"] * 2
    card = _cards(_html(hub))["POKEMON:deck"]
    assert "POKEMON_CENTER_ONLINE" not in re.sub(r"<[^>]+>", " ", card)                       # 画面の文字に列挙値を出さない（属性の data-retailer は内部用）
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
    html = _lhtml(hub)
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
    assert "販売店の抽選は応募期限を過ぎました" in card                                             # 期限後の文言（期限は data-rb-until）
    assert HINT in _rb_visible(card, "2026-11-26T12:00:00+09:00")                                       # 期限内は案内が見える
    after = _rb_visible(card, "2026-11-27T00:30:00+09:00")
    assert HINT not in after and "応募期限を過ぎました" in after                                          # 期限後は受付中の行があるとは言わない


# ── Auditor M1: 抽選の受付中・締切間近・購入期間中が、締切後に失効する ──
def _lot_hub(monkeypatch, evs):
    return _build([], evs, monkeypatch=monkeypatch)


def test_lottery_open_states_expire_after_deadline_in_rows_chips_links_and_summary(monkeypatch):
    evs = [_ev(n=1, application_end="2026-11-26T23:59:00+09:00"),                                   # 受付中
           _ev(n=2, application_end="2026-11-22T10:00:00+09:00")]                                   # 締切間近（NOW から 24 時間以内）
    hub = _lot_hub(monkeypatch, evs)
    html, lot = _html(hub), _lhtml(hub)
    card = _cards(html)["POKEMON:deck"]
    G = page.RB_EXPIRED_GROUP
    # 期限内（11/22 09:00）: 何も変わらない
    before = _rb_visible(html + lot, "2026-11-22T09:00:00+09:00")
    assert "受付中" in before and "公式ページで応募する" in before and "応募期限を過ぎました" not in before and G not in before
    # 11/22 10:30: 締切間近の行・チップは切り替わる。受付中（11/26）の行はそのまま
    mid = _rb_visible(card, "2026-11-22T10:30:00+09:00")
    assert "締切間近" not in mid and G in mid
    assert "受付中" in mid and "応募期限を過ぎました" in mid           # 受付中のチップと行は生き、締切間近の行だけ失効
    # 11/27: すべて失効。応募ボタンは隠れ、受付中の表示は残らない
    after_card = _rb_visible(card, "2026-11-27T00:30:00+09:00")
    assert "公式ページで応募する" not in after_card and "受付中" not in after_card and "締切間近" not in after_card
    assert after_card.count("応募期限を過ぎました") >= 2 and G in after_card
    rows = _rows(lot)
    tbl_after = _rb_visible(rows, "2026-11-27T00:30:00+09:00")
    assert "公式ページで応募する" not in tbl_after and tbl_after.count("応募期限を過ぎました") == 2 and "受付中" not in tbl_after      # 抽選一覧の行（状態バッジ・応募ボタン）
    tbl_before = _rb_visible(rows, "2026-11-22T09:00:00+09:00")
    assert tbl_before.count("公式ページで応募する") == 2 and "応募期限を過ぎました" not in tbl_before
    # 期限切れの注記は一覧の中に 1 回（タブ名には混ぜない）。最も早い締切を過ぎたら出る
    tabs = lot[lot.index('class="lt-tabs"'):lot.index("</nav>", lot.index('class="lt-tabs"'))]
    assert "data-rb-card" not in tabs and G not in tabs
    note = re.search(r'<p class="pnote expn"[^>]*>.*?</p>', lot, re.S).group(0)
    assert lot.count('class="pnote expn"') == 1 and 'data-rb-until="2026-11-22T10:00:00+09:00"' in note
    N = "締切を過ぎた抽選があります"
    assert N not in _rb_visible(note, "2026-11-22T09:00:00+09:00") and N in _rb_visible(note, "2026-11-22T10:30:00+09:00")
    # 商品ページの「締切が近い抽選」の帯: 期限後は応募ボタンを隠して「応募期限を過ぎました」
    band = html[html.index('id="soon"'):html.index("</section>", html.index('id="soon"'))]
    assert band.count("<li") == 2
    band_after = _rb_visible(band, "2026-11-27T00:30:00+09:00")
    assert "公式ページで応募する" not in band_after and band_after.count("応募期限を過ぎました") == 2
    assert "受付中" not in band_after.replace("受付中の抽選はありません", "")                    # 受付中が 0 件のときの 1 行（JS が出す）以外に「受付中」は無い
    assert 'data-soon-expired hidden>締切を過ぎた抽選 <b>0</b>件' in band and "data-soon-none hidden>受付中の抽選はありません" in band
    assert "sb.querySelectorAll('li.sr')" in page.JS_LEFT and "li.hidden=gone" in page.JS_LEFT       # 締切を過ぎた行は外し、末尾の 1 行にまとめる


def test_lottery_without_deadline_is_not_switched_and_has_no_rb_attrs(monkeypatch):
    evs = [_ev(n=1, application_end=None)]                                                           # 日程未確認（締切が無い）
    hub = _lot_hub(monkeypatch, evs)
    html = _lhtml(hub)
    row = re.search(r'<tr class="ev[^>]*>', html).group(0)
    assert "data-rb-until" not in row and "data-rb-card" not in row
    li = re.search(r"<li data-lot-item[^>]*>", _cards(_html(hub))["POKEMON:deck"]).group(0)
    assert "data-rb-until" not in li
    tbl = _rows(html)
    assert _rb_visible(tbl, "2030-01-01T00:00:00+09:00") == _rb_visible(tbl, "2026-11-22T00:00:00+09:00")        # 締切の無い行は、いつ見ても何も変わらない


def test_winner_purchase_period_expires_at_purchase_end(monkeypatch):
    winner = _ev(n=1, application_end="2026-11-18T23:59:00+09:00", purchase_start="2026-11-20T00:00:00+09:00",
                 purchase_end="2026-11-30T23:59:00+09:00", winner_announcement_at="2026-11-19T12:00:00+09:00")
    card = _cards(_html(_lot_hub(monkeypatch, [winner])))["POKEMON:deck"]
    assert re.search(r'data-lot-status="WINNER_PURCHASE_PERIOD"[^>]* data-rb-card data-rb-until="2026-11-30T23:59:00\+09:00"', card)
    assert "購入期間中（当選者のみ）" in _rb_visible(card, "2026-11-29T00:00:00+09:00")
    after = _rb_visible(card, "2026-12-01T00:00:00+09:00")
    assert "購入期間中（当選者のみ）" not in after and "購入期間は終了しました" in after


def test_static_open_labels_switch_at_the_deadline_and_the_page_states_the_update_time_once(monkeypatch):
    """静的な「受付中」は JS_RB の open 側にだけ置く（期限後は消える）。生成時点は行ごとに繰り返さず、ページ上部の更新時刻 1 か所で示す。"""
    hub = _lot_hub(monkeypatch, [_ev(n=1, application_end="2026-11-26T23:59:00+09:00")])
    for html in (_html(hub), _lhtml(hub)):
        assert "（生成時点）" not in html and html.count('<p class="upd">') == 1 and "更新</p>" in html
    assert re.search(r'<span data-rb-open><span class="sb info">受付中</span></span><span data-rb-expired hidden>', _lhtml(hub))


# ── Auditor M2: 未確認の紐付けを商品名つきで断定しない ──
def test_unconfirmed_retailer_row_is_marked_in_box_section_and_references(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    hub["retailer_references"] = [_rb_ref("deck", human=False, kind="NOT_CALCULATED"), _rb_ref("deck", human=True, kind="NOT_CALCULATED", shop="確認済み店")]
    html = page._rb_refs(hub["retailer_references"])          # 運用者向けの描画（公開ページには出さない。下の test_public_page_has_no_operator_diagnostics）
    li = re.findall(r"<li[^>]*>(?:(?!</li>).)*</li>", html[html.index("応募受付中だが条件付き利益を計算できない"):], re.S)
    unconfirmed = next(x for x in li if "ホビーステーション" in x)
    confirmed = next(x for x in li if "確認済み店" in x)
    assert "（商品の紐付けは未確認）" in unconfirmed and "（商品の紐付けは未確認）" not in confirmed
    assert re.search(r"ホビーステーション・[^・<]+（商品の紐付けは未確認）", unconfirmed)                    # 商品名の直後


def test_unconfirmed_retailer_row_is_marked_on_the_conditional_card():
    from tests import test_tcg_retailer_box as RB
    h = RB.hub([RB.ent(human_confirmed=False)])
    sec = page.render(h)
    sec = sec[sec.index('id="retailer-box"'):sec.index('id="page-foot"')]
    assert "対象商品は公式で確認" in sec and "紐付け" not in sec
    h2 = RB.hub([RB.ent(human_confirmed=True)])
    sec2 = page.render(h2)
    sec2 = sec2[sec2.index('id="retailer-box"'):sec2.index('id="page-foot"')]
    assert "対象商品は公式で確認" not in sec2


# ── Auditor L9: アンカーナビが共通ナビ（767px 以下で固定）と重ならない ──
def test_anchor_nav_top_is_below_the_fixed_site_nav_on_mobile():
    assert "@media(max-width:767px){nav.jump{top:53px}" in page.CSS            # 同じ media に scroll-margin 用の変数も入る（下のテスト）


# ══════════════ 独立監査・レビュー（第 2 回）の回帰テスト ══════════════
def _open_refs_html(hub) -> str:
    """運用者向けの参考情報の描画（_rb_refs）。公開ページには出さないが、描画したときの規則（期限での切り替え等）は保つ。"""
    h = page._rb_refs(hub.get("retailer_references") or [], page._announce_index(hub.get("events")))
    return h[h.index('id="retailer-open-refs"'):h.index("</details>", h.index('id="retailer-open-refs"'))]


# ── Auditor M1: 「応募受付中だが…」の見出し・本文も期限後に切り替わる ──
@needs_node
def test_open_refs_section_heading_and_body_switch_after_the_earliest_deadline(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    hub["retailer_references"] = [_rb_ref("deck", apply_end="2026-11-28"), _rb_ref("deck", shop="早い店", apply_end="2026-11-26T23:59:00+09:00")]
    html = page._rb_refs(hub["retailer_references"])
    sec = _open_refs_html(hub)
    assert re.search(r'<summary><span data-rb-card data-rb-until="2026-11-26T23:59:00\+09:00"><span data-rb-open>応募受付中だが条件付き利益を計算できない（2）</span>', sec)
    assert page.RB_EXPIRED_SECTION_HEAD in sec
    before = _rb_visible(html, "2026-11-26T12:00:00+09:00")
    assert "応募受付中だが条件付き利益を計算できない（2）" in before
    after = _rb_visible(html, "2026-11-27T12:00:00+09:00")                  # 早い行だけ失効（もう一方は 11/28 まで）
    assert "応募受付中だが" not in after
    assert page.RB_EXPIRED_SECTION_HEAD in after and "（2）" in after.split(page.RB_EXPIRED_SECTION_HEAD)[1][:6]      # 件数は再計算しない
    assert "<li" in sec and sec.count("<li") == 2                             # 節は空にならない


def test_open_refs_section_without_deadline_stays_static_but_says_generated_time(monkeypatch):
    hub = _build([], [], monkeypatch=monkeypatch)
    hub["retailer_references"] = [_rb_ref("deck", apply_end=None)]
    sec = _open_refs_html(hub)
    assert "応募受付中だが条件付き利益を計算できない（1）" in sec and "data-rb-until" not in sec.split("<ul>")[0]
    assert "応募期限 未確認" in sec                                                     # 期限が無い行は「受付中」と断定せず、期限が未確認と示す


# ── Auditor M2: 抽選一覧の表でも、購入期間中は当選者のみ・新規応募不可 ──
def test_winner_purchase_period_row_in_the_table_says_winners_only(monkeypatch):
    winner = _ev(n=1, application_end="2026-11-18T23:59:00+09:00", purchase_start="2026-11-20T00:00:00+09:00",
                 purchase_end="2026-11-30T23:59:00+09:00", winner_announcement_at="2026-11-19T12:00:00+09:00")
    html = _lhtml(_lot_hub(monkeypatch, [winner]))
    row_ = re.search(r'<tr class="ev[^>]*>.*?</tr>', html, re.S).group(0)
    assert "購入期間中・当選者のみ" in row_ and "購入期間中</span>" not in row_ and "応募する" not in row_
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
    assert "告知名「拡張パック二種（再販）」・対象商品は未確認" in sec
    assert "（商品の紐付けは未確認）" in sec
    card = _cards(html)["POKEMON:deck"]
    assert HINT in card and "告知名" not in card and "紐付け" not in card                     # 商品カードには販売店の抽選へのリンクだけ


def test_announcement_name_is_not_added_without_a_matching_url_or_a_multi_product_word(monkeypatch):
    other = _open_refs_html(_hbst_hub(monkeypatch, url="https://hbst.net/?p=1"))              # 同じ URL の抽選なし（台帳側だけ別 URL）
    hub = _hbst_hub(monkeypatch)
    hub["retailer_references"][0]["source_url"] = "https://hbst.net/?p=999"
    assert "告知名" not in _open_refs_html(hub)
    single = _hbst_hub(monkeypatch, ann_name="ハドウシーカー BOX")
    assert "告知名" not in _open_refs_html(single) and "告知名" not in _cards(_html(single))["POKEMON:deck"]
    assert "告知名" in other                                                                # 上は同 URL（p=1）で併記される対照


# ── Reviewer L1: カレンダーの副表示 store も列挙値を出さない ──
def test_calendar_store_enum_value_is_not_shown(monkeypatch):
    ev = _ev(n=1, retailer="POKEMON_CENTER_ONLINE", retailer_name="POKEMON_CENTER_ONLINE", store_name="POKEMON_CENTER_ONLINE",
             application_end="2026-11-28T23:59:00+09:00")
    hub = _build([], [ev], monkeypatch=monkeypatch)
    assert all(c["store"] != "POKEMON_CENTER_ONLINE" for c in hub["calendar"])
    html = _lhtml(hub)
    cal = html[html.index('id="calendar"'):html.index('id="lottery"')]
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
    html = _lhtml(_lot_hub(monkeypatch, [_ev(n=1, application_end="2026-11-26T23:59:00+09:00")]))
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
    html = _lhtml(_build([], monkeypatch=monkeypatch))
    badge = re.search(r"\.sb\{[^}]*\}", html).group(0)
    assert "white-space:normal" in badge and "overflow-wrap:anywhere" in badge and "max-width:100%" in badge
    assert "white-space:nowrap" not in badge
    assert ".lt td{min-width:0}" in html


# ══════════════ 2 ページ化（商品と利益 / 抽選）・白背景の作り直しの回帰テスト ══════════════
def test_apply_button_only_for_verified_open_lottery_with_application_url(monkeypatch):
    """「公式ページで応募する」は、応募 URL があり、受付中・締切間近・確認済み・日程の食い違いなしの行だけ（帯・一覧・商品カードのどこでも）。"""
    evs = [_ev(n=1),                                                                                    # 受付中・確認済み → ボタン
           _ev(n=2, verified=False),                                                                    # 未確認 → なし
           _ev(n=3, conflict=True),                                                                     # 日程の食い違い → なし
           _ev(n=4, application_start="2026-11-24T10:00:00+09:00", application_end="2026-11-28T23:59:00+09:00"),   # 開始前 → なし
           _ev(n=5, application_end="2026-11-20T23:59:00+09:00", winner_announcement_at="2026-11-23T12:00:00+09:00")]  # 結果待ち → なし
    hub = _build([], evs, monkeypatch=monkeypatch)
    html, lot = _html(hub), _lhtml(hub)
    for doc in (html, lot):
        assert doc.count("公式ページで応募する") == (2 if doc is html else 1), doc.count("公式ページで応募する")   # 商品ページ = 帯 1 + カード 1
    assert 'href="https://draw.geo-online.co.jp/lottery/100"' in lot
    for n in (2, 3, 4, 5):
        assert f"https://draw.geo-online.co.jp/lottery/{n}00" not in html + lot, n
    row1 = re.search(r'<tr class="ev[^>]*id="L-L-deck-1".*?</tr>', lot, re.S)
    assert row1 is None or "公式ページで応募する" in row1.group(0)
    for m in re.finditer(r'<tr class="ev[^>]*>.*?</tr>', lot, re.S):
        tr = m.group(0)
        if "公式ページで応募する" in tr:
            assert 'data-verified="1"' in tr and 'data-lot-state="OPEN"' in tr and "data-conflict" not in tr
            assert re.search(r'<span data-rb-open><a class="btn cta"', tr)                             # 期限後は JS_RB が隠す


def test_lottery_page_has_calendar_first_and_rows_ordered_by_deadline(monkeypatch):
    evs = [_ev(n=1, application_end="2026-11-28T23:59:00+09:00"), _ev(n=2, application_end="2026-11-22T10:00:00+09:00"),
           _ev(n=3, application_start="2026-11-24T10:00:00+09:00", application_end="2026-11-26T23:59:00+09:00"),
           _ev(n=4, application_start="2026-11-01T10:00:00+09:00", application_end="2026-11-02T23:59:00+09:00")]     # 終了
    lot = _lhtml(_build([], evs, monkeypatch=monkeypatch))
    assert lot.index('id="calendar"') < lot.index('id="lottery"') < lot.index('id="lt-live"')        # カレンダーが上、その下に一覧
    live = lot[lot.index('id="lt-live"'):lot.index("<!--/lt-live-->")]
    shops = re.findall(r'<td data-label="店舗"><b>([^<]+)</b>', live)
    assert shops == ["店2", "店1", "店3"]                                                              # 締切間近 → 受付中 → 開始予定（同じ段階は締切が近い順）
    assert "店4" not in live and re.search(r'<details class="note lt-more" data-lt-group="ended"><summary>終了（1件）</summary>', lot)   # 終了は閉じた details
    assert 'id="lt-upcoming"' in live and 'data-tab="upcoming"' not in lot and 'data-tab="after"' not in lot       # タブは すべて・締切間近・受付中 だけ
    cal = lot[lot.index('id="calendar"'):lot.index('id="lottery"')]
    for target in re.findall(r'<a href="#(L-[^"]+)">', cal):                                          # カレンダーの項目から一覧の該当行へ
        assert f'id="{target}"' in lot, target


def test_cross_links_between_the_two_pages_point_to_existing_anchors(monkeypatch):
    hub = _build(ROWS, [_ev(n=1), _ev(n=2, application_end="2026-11-28T23:59:00+09:00")], monkeypatch=monkeypatch)
    html, lot = _html(hub), _lhtml(hub)
    for a in set(re.findall(r'href="tcg-lottery\.html#(L-[^"]+)"', html)):                           # 商品ページ → 抽選の行
        assert f'id="{a}"' in lot, a
    for a in set(re.findall(r'href="tcg\.html#([^"]+)"', lot)):                                       # 抽選の行 → 商品カード
        assert f'id="{a}"' in html, a
    for a in set(re.findall(r'href="#([^"]+)"', html)):                                                # ページ内アンカー
        assert f'id="{a}"' in html, a
    assert 'href="tcg-lottery.html#prod-p0"' in html and 'value="p0"' in lot                         # 商品で絞り込んだ抽選一覧（JS が #prod-p0 を読む）
    assert "'#prod-'" in page.JS


def test_suspended_only_buyback_is_shown_grey_and_never_counted_as_highest(monkeypatch):
    """受付停止中の店の価格しか無い商品: 最高買取の欄に「¥X（受付停止）」を灰色で出す（鮮度の判定の中）。最高買取・利益には数えない。"""
    stopped = {**row(price=12000, jan=DECK_JAN), "accept_state": "STOPPED", "suspended_text": "お申込一時停止中"}
    hub = _build([stopped], monkeypatch=monkeypatch)
    card = _cards(_html(hub))["POKEMON:deck"]
    best = re.search(r"<li data-strip-best>(.*?)</li>", card, re.S).group(1)
    assert best.startswith('<em>') and '<b class="amt na">—</b><span data-fb-live' in best and "¥" not in best     # 最高買取の欄に金額を出さない
    assert re.search(r'hidden><small>受付停止中</small></span><span data-fb-stale[^>]*>再確認待ち', best)      # 理由も鮮度の判定の中（鮮度切れでは「再確認待ち」）
    det = card[card.index('<details class="tc-others"'):]
    assert "¥12,000" in det and 'data-other-kind="suspended"' in det                         # 金額は「その他の売却先」の中だけ（参考の段）
    li = re.search(r'<li data-other-shop="rudeya" data-other-kind="suspended">.*?</li>', det, re.S).group(0)
    assert li.index("data-fb-live") < li.index("¥12,000") < li.index("受付停止")               # 受付状態のラベルも鮮度の判定の中
    assert hub["cards"][[c["product_id"] for c in hub["cards"]].index("deck")]["buyback"].get("highest_executable") is None
    profit = re.search(r"<li data-strip-profit>(.*?)</li>", card, re.S).group(1)
    assert '<b class="amt na">—</b>' in profit and not re.search(r"[+\-−][\d,]+円", card)


def test_unconfirmed_word_appears_at_most_once_per_card(monkeypatch):
    master = [_master("deck", "デッキセット"), _master("box", "拡張パック BOX", "BOOSTER_BOX", "2026-12-05"), _master("solo", "ソロ", rel="2026-01-01")]
    hub = _build([row(price=14000, jan=BOX_JAN, name="拡張パック BOX [M6]"), row(price=6000, jan=SOLO_JAN)], master=master, msrp=[], monkeypatch=monkeypatch)
    for k, c in _cards(_html(hub)).items():
        assert re.sub(r"<[^>]+>", "", c).count("未確認") <= 1, k


def test_page_is_light_fixed_and_has_no_explanatory_paragraphs(monkeypatch):
    hub = _build(ROWS, [_ev()], monkeypatch=monkeypatch)
    for doc in (_html(hub), _lhtml(hub)):
        assert '<html lang="ja" data-theme="light">' in doc and '<meta name="color-scheme" content="light">' in doc
        assert doc.count(page.FOOT_NOTE) == 1
        for old in ("このページの見方", "件数の数え方", "（生成時点）", "単一ソース", "前提:", "基準:"):
            assert old not in doc, old


def test_buyback_only_card_carries_pack_price_and_release_date_from_the_registry(monkeypatch):
    """買取だけがある商品のカード（_card_from_target）にも、登録簿の 1 パック価格・発売日を載せる（表示用。BOX の定価は作らない）。"""
    master = [_master("deck", "デッキセット"), _master("solo", "ソロ", "BOOSTER_BOX", rel="2026-01-01", pack_price=240, retail_price_basis="pack")]
    hub = _build([row(price=6000, jan=SOLO_JAN)], master=master, msrp=[], monkeypatch=monkeypatch)
    solo = [c for c in hub["cards"] if c["product_id"] == "solo"][0]
    assert solo["pack_price"] == 240 and solo["release_date"] == "2026-01-01" and solo["msrp"] is None and solo["profit"].get("net_profit") is None
    card = _cards(_html(hub))["POKEMON:solo"]
    assert '<b class="amt pack">1パック ¥240</b>' in card and "発売" in card and "¥1," not in card
    master2 = [_master("deck", "デッキセット"), _master("solo", "ソロ", rel="2026-01-01", pack_price=240)]       # basis が pack でなければ載せない
    hub2 = _build([row(price=6000, jan=SOLO_JAN)], master=master2, msrp=[], monkeypatch=monkeypatch)
    assert [c for c in hub2["cards"] if c["product_id"] == "solo"][0]["pack_price"] is None


# ══════════════ デザインレビュー（58 点）の修正の回帰テスト ══════════════
def test_other_sellers_are_split_into_confirmed_and_reference(monkeypatch):
    """最高買取より高い参考価格（条件未確認）は、「参考（受付・条件未確認）」の段に灰色で出し、最高買取・利益に数えない。"""
    rows = [row(price=8000, jan=DECK_JAN), row(shop="kaitorishouten", price=9000, jan=DECK_JAN, upd="2026-11-21"),
            row(shop="kaitorishouten", price=43000, jan=DECK_JAN, cond=bb.C_NEW, upd="2026-11-21")]
    card = _cards(_html(_build(rows, monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert "最高買取<span class=\"emx\">（受付確認済み）</span>" in card
    det = card[card.index('<details class="tc-others"'):card.index("</details>", card.index('<details class="tc-others"'))]
    ok_part = det[det.index("受付確認済み</p>"):det.index("参考（受付・条件未確認）")]
    ref_part = det[det.index("参考（受付・条件未確認）"):]
    assert 'data-other-kind="executable"' in ok_part and "data-other-kind=\"reference\"" not in ok_part
    assert '<ul class="ref">' in ref_part and "¥43,000" in ref_part and 'data-other-kind="executable"' not in ref_part
    best = re.search(r"<li data-strip-best>(.*?)</li>", card, re.S).group(1)
    assert "¥43,000" not in best and "¥9,000" in best


def test_amounts_carry_their_unit_and_unit_mismatch_has_no_profit(monkeypatch):
    html = _html(_build(ROWS, monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    msrp = re.search(r"<li data-strip-msrp>(.*?)</li>", card, re.S).group(1)
    assert '<b class="amt"><small class="u">セット</small>¥6,200</b>' in msrp
    master = [_master("deck", "デッキセット"), _master("box", "拡張パック BOX", "BOOSTER_BOX", "2026-12-05", pack_price=180, retail_price_basis="pack")]
    box = _cards(_html(_build([row(price=14000, jan=BOX_JAN, name="拡張パック BOX [M6]")], master=master, msrp=[], monkeypatch=monkeypatch)))["POKEMON:box"]
    best = re.search(r"<li data-strip-best>(.*?)</li>", box, re.S).group(1)
    assert "1パック ¥180" in box and "¥" not in best and "単位違い" in best                  # 1 パックと BOX: 最高買取の欄に金額を出さない
    det = box[box.index('<details class="tc-others"'):]
    assert "¥14,000" in det and "単位違い（定価と比較不可）" in det                           # 金額は「その他の売却先」の中（単位違い）
    assert re.search(r'<li data-strip-profit><em>純利益</em><span class="tc-val"><b class="amt na">—</b></span></li>', box)


def test_products_without_any_price_are_folded_at_the_end(monkeypatch):
    master = [_master("deck", "デッキセット"), _master("solo", "ソロ", rel="2026-01-01"), _master("none", "情報なし", rel="2026-02-01")]
    hub = _build(ROWS, [_ev("none", "情報なし", 9, application_start="2026-11-01T10:00:00+09:00", application_end="2026-11-02T23:59:00+09:00")],
                 master=master, msrp=[_msrp("deck", 6200)], monkeypatch=monkeypatch)
    html = _html(hub)
    fold = html[html.index("ほかの商品（"):]
    fold = fold[:fold.index("</details>")]
    assert 'data-card-key="POKEMON:none"' in fold and 'data-card-key="POKEMON:deck"' not in fold
    thumbs = html[html.index('class="thumbs"'):html.index("</nav>", html.index('class="thumbs"'))]
    assert 'href="#p0"' in thumbs or 'data-pt' in thumbs
    assert all(f'href="#{d}"' in html for d in re.findall(r'<a class="th" href="#([^"]+)"', thumbs))


def test_lottery_buttons_follow_state_and_confirmation(monkeypatch):
    """受付中・確認済みで応募 URL が無い行は「応募方法を見る（公式）」（告知へ・橙）。未確認・開始前は枠線の告知。結果待ちは灰色の小さなリンク。"""
    evs = [_ev(n=1, entry_url=None), _ev(n=2, entry_url=None, verified=False),
           _ev(n=3, entry_url=None, application_start="2026-11-24T10:00:00+09:00", application_end="2026-11-28T23:59:00+09:00"),
           _ev(n=4, entry_url=None, application_end="2026-11-20T23:59:00+09:00", winner_announcement_at="2026-11-23T12:00:00+09:00")]
    lot = _lhtml(_build([], evs, monkeypatch=monkeypatch))
    rows = {m.group(1): m.group(0) for m in re.finditer(r'<tr class="ev[^>]*id="(L-L-deck-\d)".*?</tr>', lot, re.S)}
    assert f'class="btn cta" href="https://www.geo-online.co.jp/store/news/1"' in rows["L-L-deck-1"] and page.APPLY_HOWTO in rows["L-L-deck-1"]
    for k in ("L-L-deck-2", "L-L-deck-3", "L-L-deck-4"):
        assert "btn cta" not in rows[k] and page.APPLY_HOWTO not in rows[k], k
    assert 'class="lk"' in rows["L-L-deck-4"] and 'class="btn"' in rows["L-L-deck-3"]
    assert re.search(r'<span data-rb-open><a class="btn cta"', rows["L-L-deck-1"])            # 期限後は JS_RB が隠す
    import scripts.deploy_check as dc
    assert dc.check_tcg_apply_buttons(lot, "x") == []
    bad = lot.replace('<a class="btn" href="https://www.geo-online.co.jp/store/news/3"',
                      '<a class="btn cta" href="https://www.geo-online.co.jp/store/news/3"', 1)
    assert bad != lot and any("確認済み以外" in x for x in dc.check_tcg_apply_buttons(bad, "x"))   # 開始前に橙のボタンを付けたら検出


def test_calendar_shows_only_lottery_kinds_with_short_labels_and_left_time_is_runtime(monkeypatch):
    winner = _ev(n=1, application_end="2026-11-18T23:59:00+09:00", purchase_start="2026-11-24T00:00:00+09:00",
                 purchase_end="2026-11-30T23:59:00+09:00", winner_announcement_at="2026-11-19T12:00:00+09:00")
    lot = _lhtml(_build([], [winner, _ev(n=2, application_end="2026-11-25T23:59:00+09:00")], monkeypatch=monkeypatch))
    cal = lot[lot.index('id="calendar"'):lot.index('id="lottery"')]
    assert "k-PURCHASE_START" not in cal and "k-PURCHASE_END" not in cal and "購入開始" not in cal
    assert '<span class="ks">締</span>1' in cal
    rows = _rows(lot)
    assert rows.count("data-left-until=") == 1 and 'data-left-until="2026-11-25T23:59:00+09:00"' in rows      # 受付中の行だけ
    assert "data-left-until" in page.JS_LEFT and page.JS_LEFT in lot and page.JS_LEFT in _html(_build([], [_ev(n=2)], monkeypatch=monkeypatch))


def test_internal_labels_are_not_shown_to_users(monkeypatch):
    lot = _lhtml(_build([], [_ev(n=1, application_end="2026-11-20T23:59:00+09:00")], monkeypatch=monkeypatch))
    vis = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", lot, flags=re.S))
    for w in ("S 今すぐ", "A 応募したい", "B 余裕あり", "外部フォーム", "確認 11/"):
        assert w not in vis, w


def test_public_page_has_no_operator_diagnostics(monkeypatch):
    """公開ページに、運用者向けの診断（参考情報の節・台帳との食い違い・0 件の販売店 BOX の節・商品未特定・紐付け未確認）を出さない。"""
    hub = _hbst_hub(monkeypatch)
    hub["retailer_validation_errors"] = [{"kind": "PRICE_MISMATCH", "shop": "x", "display_name": "y", "manual_price": 1, "collector_price": 2}]
    for doc in (_html(hub), _lhtml(hub)):
        for w in ("応募受付中だが条件付き利益を計算できない", "過去の参考情報", "台帳と自動取得の食い違い", "商品未特定", "紐付け未確認",
                  "紐付けは未確認", "告知名", 'id="retailer-box"', "該当なし", "（0）"):
            assert w not in doc, w


# ══════════════ 再レビュー（70 点）の修正の回帰テスト ══════════════
def test_unit_mismatch_best_is_grey_with_a_short_label(monkeypatch):
    master = [_master("deck", "デッキセット"), _master("box", "拡張パック BOX", "BOOSTER_BOX", "2026-12-05", pack_price=180, retail_price_basis="pack")]
    box = _cards(_html(_build([row(price=14000, jan=BOX_JAN, name="拡張パック BOX [M6]")], master=master, msrp=[], monkeypatch=monkeypatch)))["POKEMON:box"]
    best = re.search(r"<li data-strip-best>(.*?)</li>", box, re.S).group(1)
    assert '<b class="amt na">—</b><span data-fb-live' in best and "¥" not in best
    assert re.search(r'hidden><small>単位違い</small></span><span data-fb-stale[^>]*>再確認待ち', best)
    li = re.search(r'<li data-other-shop="rudeya" data-other-kind="executable">.*?</li>', box, re.S).group(0)
    assert li.index("data-fb-live") < li.index("¥14,000") and "単位違い（定価と比較不可）" in li
    assert "¥1,440" not in box                                                                   # BOX の定価を掛け算で作らない


def test_reference_above_the_best_is_grey_and_marked_unverified(monkeypatch):
    rows = [row(price=8000, jan=DECK_JAN), row(shop="kaitorishouten", price=9000, jan=DECK_JAN, upd="2026-11-21"),
            row(shop="kaitorishouten", price=43000, jan=DECK_JAN, cond=bb.C_NEW, upd="2026-11-21")]
    card = _cards(_html(_build(rows, monkeypatch=monkeypatch)))["POKEMON:deck"]
    ref = re.search(r'<li data-other-shop="kaitorishouten" data-other-kind="reference">.*?</li>', card, re.S).group(0)
    assert '<small class="unv">受付未確認</small><b class="amt sm">¥43,000</b>' in ref
    assert ref.index("data-fb-live") < ref.index("受付未確認")
    rud = re.search(r'<li data-other-shop="rudeya".*?</li>', card, re.S).group(0)
    assert "受付未確認" not in rud                                                                # 最高額より安い行・受付確認済みの行には付けない


def test_lottery_line_sits_under_the_name_and_table_has_no_lottery_column(monkeypatch):
    html = _html(_build(ROWS, [_ev(n=1, application_end="2026-11-25T23:59:00+09:00")], monkeypatch=monkeypatch))
    card = _cards(html)["POKEMON:deck"]
    tcid = card[card.index('<div class="tc-id">'):card.index('<ul class="tc-strip')]
    assert '<span class="lbl">抽選</span>' in tcid and "受付中<b>1</b>件・締切 11/25" in tcid
    assert "<span>抽選</span>" not in html                                                        # 表の見出しに「抽選」の列は無い
    nolot = _cards(_html(_build(ROWS, [], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert 'class="lbl">抽選' not in nolot                                                       # 抽選が無ければ何も出さない


def test_stale_cells_are_short_and_the_note_is_shown_once_by_js(monkeypatch):
    html = _html(_build(ROWS, [_ev()], monkeypatch=monkeypatch))
    assert html.count("data-stale-note hidden>") == 1 and '<p class="stale-note" data-stale-note hidden>買取価格は ' in html
    assert page.JS_STALE_NOTE in html and "[data-fb-stale]" in page.JS_STALE_NOTE
    card = _cards(html)["POKEMON:deck"]
    for m in re.finditer(r'<span data-fb-stale[^>]*>(.*?)</span>(?=<|$)', card, re.S):
        assert len(re.sub(r"<[^>]+>", "", m.group(1))) <= 6, m.group(1)                        # 各セルは「再確認待ち」程度の短いラベル


def test_short_names_drop_the_common_prefix_only_for_display():
    names = ["「30th CELEBRATION カードセット キモリ・アチャモ」", "「30th CELEBRATION カードセット サルノリ・ヒバニー」", "拡張パック「ハドウシーカー」"]
    assert page.short_name(names[0], names) == "キモリ・アチャモ"
    assert page.short_name(names[2], names) == names[2]                                           # 共通の接頭辞が無ければそのまま


# ══════════════ 独立レビュー・監査（第 3 回）の回帰テスト ══════════════
def test_apply_button_is_js_only_and_has_a_text_fallback(monkeypatch):
    """JS が無いと締切後もボタンが残るので、橙のボタンは JS のときだけ。JS が無いときは「締切 …・公式の告知」のテキストリンク。"""
    lot = _lhtml(_build([], [_ev(n=1)], monkeypatch=monkeypatch))
    row = re.search(r'<tr class="ev.*?</tr>', lot, re.S).group(0)
    assert re.search(r'<a class="btn cta" href="https://draw\.geo-online\.co\.jp/lottery/100"[^>]* data-js-only hidden>公式ページで応募する</a>', row)
    assert re.search(r'<span class="nojs" data-nojs>締切 .*?・<a href="https://www\.geo-online\.co\.jp/store/news/1"[^>]*>公式の告知</a></span>', row)
    assert "[data-js-only]" in page.JS_LEFT and "[data-nojs]" in page.JS_LEFT


def test_roi_is_rounded_once_from_the_raw_values():
    assert page._roi_pr({"net_profit": 2546, "acquisition_cost": 10000, "roi_pct": 25.5}) == "25%"      # 25.46% → 25%（25.5 から丸めない）
    assert page._roi_pr({"net_profit": None, "acquisition_cost": None, "roi_pct": 12.0}) == "12%"


def test_stale_note_uses_the_oldest_observation(monkeypatch):
    rows = [row(price=8000, jan=DECK_JAN), row(price=9500, jan=SOLO_JAN, obs=NOW - timedelta(hours=3))]
    html = _html(_build(rows, monkeypatch=monkeypatch))
    note = re.search(r'<p class="stale-note"[^>]*>(.*?)</p>', html).group(1)
    assert "11/21 15:00" in note                                                                 # 新しい方（18:00）ではなく古い方


def test_card_lottery_items_carry_verification_attributes(monkeypatch):
    card = _cards(_html(_build([], [_ev(n=1), _ev(n=2, conflict=True)], monkeypatch=monkeypatch)))["POKEMON:deck"]
    lis = re.findall(r"<li data-lot-item[^>]*>", card)
    assert all('data-verified="1"' in x and 'data-retailer="GEO"' in x for x in lis) and any("data-conflict" in x for x in lis)


def test_counts_drop_expired_lotteries_at_view_time(monkeypatch):
    """見出し・タブ・「このほかの受付中の抽選」の件数は、締切を過ぎた抽選を表示時に外す（JS_LEFT の data-cnt-untils）。0 件のタブ・案内は隠す。"""
    evs = [_ev(n=1, application_end="2026-11-26T23:59:00+09:00"), _ev(n=2, application_end="2026-11-22T10:00:00+09:00"),
           _ev(n=3, product_match="none", product_id=None, product_name="二種（再販）", application_end="2026-11-24T23:59:00+09:00")]
    hub = _build([], evs, monkeypatch=monkeypatch)
    lot, html = _lhtml(hub), _html(hub)
    head = re.search(r'<h2 id="lottery">(.*?)</h2>', lot).group(1)
    assert re.search(r'data-cnt-untils="[^"]*2026-11-22T10:00:00\+09:00[^"]*"', head)
    assert re.search(r'data-tab="ending"[^>]*>締切間近 <b><span data-cnt-untils="2026-11-22T10:00:00\+09:00" data-cnt-hide="a">1</span></b>', lot)
    assert re.search(r'このほかの受付中の抽選 <span data-cnt-untils="2026-11-24T23:59:00\+09:00" data-cnt-hide="\.unb">1</span>件', html)
    assert "data-cnt-untils" in page.JS_LEFT and "c.hidden=(n===0)" in page.JS_LEFT
    assert ":not(.rb-expired)" in page.JS                                                         # 絞り込みの件数・段の表示からも外す


def test_ranking_hides_when_every_row_is_stale_and_other_shop_labels_are_gated(monkeypatch):
    html = _html(_build(ROWS, monkeypatch=monkeypatch))
    assert '<section class="rk-sec" data-rk>' in html and "querySelector('[data-rk]')" in page.JS_STALE_NOTE
    card = _cards(html)["POKEMON:deck"]
    li = re.search(r'<li data-other-shop="rudeya" data-other-kind="executable">.*?</li>', card, re.S).group(0)
    assert li.index("data-fb-live") < li.index("受付中") < li.index("data-fb-stale")            # 受付状態のラベルも鮮度の判定の中


def test_main_list_shows_only_profit_or_open_lottery_rows_and_thumbs_open_folds(monkeypatch):
    hub = _build(ROWS + [row(price=6000, jan=SOLO_JAN)], [_ev("box", "拡張パック BOX", 3)], msrp=[_msrp("deck", 6200)], monkeypatch=monkeypatch)
    html = _html(hub)
    pok = html[html.index('id="cat-pokemon"'):html.index('id="cat-onepiece"')]
    main = pok.split('<details class="note nobb">')[0]
    fold = pok.split('<details class="note nobb">')[1]
    assert 'data-card-key="POKEMON:deck"' in main and 'data-card-key="POKEMON:box"' in main      # 利益あり・受付中の抽選あり
    assert 'data-card-key="POKEMON:solo"' in fold and "ほかの商品（1件）" in fold                 # 利益の出ない行は折りたたみ
    assert re.search(r'<a class="th" href="#c?p?\d+"', html) and "openTo(" in page.JS_LEFT       # 画像の帯は折りたたみの中の行にも飛べる（JS で開く）


# ══════════════ 最終の小修正の回帰テスト ══════════════
def test_unknown_accept_state_only_is_not_called_stopped(monkeypatch):
    unk = {**row(price=12000, jan=DECK_JAN), "accept_state": "UNKNOWN", "suspended_text": "受付状態を確認できません"}
    card = _cards(_html(_build([unk], monkeypatch=monkeypatch)))["POKEMON:deck"]
    best = re.search(r"<li data-strip-best>(.*?)</li>", card, re.S).group(1)
    assert "<small>受付状態不明</small>" in best and "受付停止" not in best                          # 受付状態が読めないだけの店を「停止」と断定しない


def test_nojs_fallback_link_says_application_page_when_there_is_no_announcement():
    html = page._lot_buttons("OPEN", True, False, "https://draw.geo-online.co.jp/lottery/1", None, "", "11/26")
    assert "data-nojs>締切 11/26・<a" in html and ">公式の応募ページ</a>" in html and ">公式の告知</a>" not in html
    html2 = page._lot_buttons("OPEN", True, False, "https://draw.geo-online.co.jp/lottery/1", "https://www.geo-online.co.jp/x", "", "11/26")
    assert ">公式の告知</a>" in html2


def test_summary_separators_and_past_calendar_days(monkeypatch):
    css = page.CSS
    assert ".chip+.chip::before" not in css and ".chip.rb-expired:not(.exp)" in css               # 区切りの「・」を擬似要素で作らない（消えた項目の前後に残らない）
    lot = _lhtml(_build([], [_ev(n=1, application_end="2026-11-25T23:59:00+09:00")], monkeypatch=monkeypatch))
    assert re.search(r'<div[^>]* data-day="2026-11-25"><details>', lot) and "classList.toggle('past'" in page.JS_LEFT
    assert ".cg .past .k{" in css


def test_midnight_deadline_in_the_summary_line_matches_the_expiry(monkeypatch):
    card = _cards(_html(_build([], [_ev(n=1, application_end="2026-11-26T00:00:00+09:00")], monkeypatch=monkeypatch)))["POKEMON:deck"]
    assert "締切 11/26 0:00" in card and 'data-rb-until="2026-11-26T00:00:00+09:00"' in card


def test_today_frame_is_moved_by_js_and_unbound_rows_use_a_shop_tile(monkeypatch):
    evs = [_ev(n=1, application_end="2026-11-25T23:59:00+09:00"),
           _ev(n=2, product_match="none", product_id=None, product_name="二種（再販）", retailer_name="<b>ホビ</b>ステ", store_name="<b>ホビ</b>ステ")]
    lot = _lhtml(_build([], evs, monkeypatch=monkeypatch))
    assert "classList.toggle('today',k===today)" in page.JS_LEFT and re.search(r'<div[^>]*data-day="2026-11-2\d"><span class="d">', lot)
    row = re.search(r'<tr class="ev[^>]*data-product="none".*?</tr>', lot, re.S).group(0)
    assert '<div class="pimg ph shop" role="img"' in row and "<b>&lt;b</b>" in row and "<b>ホビ</b>ステ" not in row   # 店名の頭の文字（エスケープ）
    assert "ポケカ</small>" not in row
    assert "details.note .tc-others ul,details.note .tc-lotd ul{padding-left:0}" in page.CSS
