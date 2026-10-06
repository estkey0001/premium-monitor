"""新UIの「マイページ」（UI Phase 7）。ウォッチ中の商品・抽選の締切・通知と変化の履歴・通知条件を1か所で見る。

- ログイン・アカウント・クラウド同期・Push 通知は無い（静的サイト）。ウォッチと設定は **このブラウザ**（localStorage）に保存し、
  画面にもそう書く。別の端末には引き継がれない
- 値は商品詳細（ProductDetailView）・利益商品（OpportunityView）・抽選（runtime）の確定値をそのまま出す。
  利益・ROI・最安仕入・有効売却価格は JS でも計算し直さない（並べ替え・絞り込み・件数を数えるだけ）
- Python は全商品のカード・締切の一覧・通知と変化の履歴を作り（非表示）、JS がウォッチ中の商品だけを出す
- 保存はブラウザ側の薄い入口（NuStore: ウォッチ・設定・既読）だけを通す。将来サーバーに移すときはここを差し替える

URL: ?page=mypage&section=watchlist|notifications|settings（古い ?ui=new&page=mypage も同じ）
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from src.content.ui import categories as cats
from src.content.ui import opportunity as opp
from src.content.ui import product_detail as pd
from src.content.ui import product_page
from src.content.ui.components import esc
from src.content.ui.lottery_card import cta_html
from src.content.ui.navigation import page_href
from src.tcg.models import JST, parse_dt

SECTIONS = (("watchlist", "ウォッチ"), ("notifications", "通知"), ("settings", "設定"))
SCHEMA_VERSION = 1

# 利用者向けの通知の種類（管理者向けの HEALTH_ALERT・DATA_RECOVERED は出さない）
NOTICE_LABELS = {"NEW_MAIN": "利益ルートの成立", "WATCH_TO_BUY": "買い時の条件に到達", "PRICE_DROP": "仕入れ価格の値下がり",
                 "PRICE_RISE": "仕入れ価格の値上がり", "ROI_UP": "利益率の上昇", "ROI_DOWN": "利益率の低下"}
# 通知条件のグループ（設定のオン・オフで履歴の表示を絞る。値は変えない）
GROUP_LABELS = {"profit": "利益条件・利益率", "lottery_open": "抽選・予約の受付開始", "lottery_deadline": "抽選・予約の締切",
                "restock": "在庫の変化（再入荷など）", "buyback": "買取価格の変化", "price": "販売価格の変化"}
_CHANGE_GROUP = {"LOTTERY_OPEN": "lottery_open", "PREORDER_OPEN": "lottery_open",
                 "LOTTERY_CLOSE": "lottery_deadline", "PREORDER_CLOSE": "lottery_deadline",
                 "RESTOCK": "restock", "STOCK_IN": "restock", "STOCK_OUT": "restock",
                 "SELL_PRICE_CHANGE": "buyback", "OFFICIAL_PRICE_CHANGE": "price",
                 "PRICE_UP": "price", "PRICE_DOWN": "price"}
_STOCK_CHANGES = ("RESTOCK", "STOCK_IN", "STOCK_OUT")


def _ms(iso: str, *, day_end: bool = False) -> int | None:
    s = str(iso or "")
    if not s:
        return None
    if len(s) == 10:                                        # 日付だけ（時刻を作らない。並べ替えの目安だけに使う）
        s += "T23:59:59+09:00" if day_end else "T00:00:00+09:00"
    d = parse_dt(s.replace(" ", "T", 1))
    return int(d.timestamp() * 1000) if d else None


def _yen(v) -> str:
    try:
        return f"¥{int(round(float(v))):,}"
    except (TypeError, ValueError):
        return "—"


# ── 通知と変化の履歴 ──────────────────────────────────────────────────

def _event_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def _now_text(v: pd.ProductDetailView) -> str:
    """今の状態（当時の通知とは別に、生成時点の確定値で出す）。"""
    o = v.opportunity
    profit = f"利益あり +{_yen(o.net_profit)}" if o is not None else "利益は算出前"
    return f"{v.status_label}・{profit}"


def build_events(details: dict, notifications: list | None, profit_routes: dict | None,
                 now: datetime) -> list[dict]:
    """マイページの「通知と変化の履歴」（商品ごと。新しい順）。

    - 通知（exports/notifications）: 利用者向けの種類だけ。利益ルート由来の通知は、確定ルートの判定を通って作られ
      （route_checked）、そのルート（route_id）が今も確定・参考ルートのものだけ（無効になったルートの値を出さない）
    - 変化（商品詳細の「最近の変化」）: 根拠のある価格・在庫・抽選の変化だけ
    - どちらも「当時」の内容と「今の状態」を分けて出す。時刻は発生した時刻（生成時刻ではない）
    """
    keys = opp.current_route_keys(profit_routes, now)
    out = []
    for e in notifications or []:
        if not isinstance(e, dict):
            continue
        typ, pid = str(e.get("type") or ""), str(e.get("product_id") or "")
        if typ not in NOTICE_LABELS or pid not in details:
            continue
        if not (e.get("route_checked") is True
                and opp.record_route_ok({"route_id": e.get("route_id"), "kind": "main"}, keys)):
            continue
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        what = []
        if isinstance(data.get("net_profit"), (int, float)) and data["net_profit"] > 0:
            what.append(f"利益 {_yen(data['net_profit'])}")
        if isinstance(data.get("roi"), (int, float)) and data["roi"] > 0:
            what.append(f"ROI {data['roi'] * 100:.1f}%")
        if typ in ("PRICE_DROP", "PRICE_RISE") and data.get("prev_price") and data.get("buy_price"):
            what = [f"{_yen(data['prev_price'])} → {_yen(data['buy_price'])}"]
        at = str(e.get("created_at") or "").replace(" JST", "+09:00")
        v = details[pid]
        out.append({"id": _event_id("n", typ, pid, at, e.get("route_id")), "pid": pid, "group": "profit",
                    "label": NOTICE_LABELS[typ], "what": "・".join(what) or "条件の変化", "at": at,
                    "ms": _ms(at), "kind": "notice", "now": _now_text(v), "name": v.product_name})
    for pid, v in details.items():
        for ch in v.changes:
            group = _CHANGE_GROUP.get(ch.get("type"), "")
            if not group:
                continue
            what = (f'{ch["before"]} → {ch["after"]}' if ch.get("before") else str(ch.get("after") or ""))
            src = str(ch.get("source") or "")
            if src and src not in what:                     # 同じ店名を重ねない（抽選の受付は after が店名）
                what += f"（{src}）"
            out.append({"id": _event_id("c", ch["type"], pid, ch["changed_at"], ch.get("after")), "pid": pid,
                        "group": group, "label": ch["label"], "what": what,
                        "at": ch["changed_at"], "ms": _ms(ch["changed_at"]), "kind": "change",
                        "now": _now_text(v), "name": v.product_name, "url": ch.get("url") or ""})
    return sorted(out, key=lambda x: x["ms"] or 0, reverse=True)


def _when(at: str) -> str:
    """発生した時刻（日付だけの値は日付だけ。時刻を作らない）。"""
    s = str(at or "")
    if len(s) == 10:
        return f'<span class="nu-time">{esc(s[5:].replace("-", "/"))}（日付のみ）</span>'
    d = parse_dt(s.replace(" ", "T", 1)) if s else None
    if d is None:
        return '<span class="nu-time">時刻不明</span>'
    return (f'<time class="nu-time" datetime="{esc(d.isoformat())}">'
            f'{d.astimezone(JST).strftime("%m/%d %H:%M")}</time>')


def _event_li(e: dict) -> str:
    link = product_page.link(e["pid"], "商品詳細")
    return (f'<li class="nu-mp-ev" data-nu-mp-ev="{esc(e["id"])}" data-nu-mp-pid="{esc(e["pid"])}"'
            f' data-nu-mp-group="{esc(e["group"])}" data-nu-mp-kind="{esc(e["kind"])}" hidden>'
            '<span class="nu-mp-ev__unread" aria-hidden="true"></span>'
            f'<div class="nu-mp-ev__main"><p class="nu-mp-ev__head"><b>{esc(e["label"])}</b>'
            f'<span class="nu-mp-ev__state" data-nu-mp-evstate>未読</span></p>'
            f'<p class="nu-mp-ev__name">{esc(e["name"])}</p>'
            f'<p class="nu-mp-ev__what">{"当時の通知" if e["kind"] == "notice" else "変化"}: {esc(e["what"])}</p>'
            f'<p class="nu-osub">{"通知" if e["kind"] == "notice" else "発生"} {_when(e["at"])}・'
            f'<span data-nu-mp-evnow>生成時点の状態: {esc(e["now"])}</span></p>'
            f'</div><div class="nu-mp-ev__acts">{link}</div></li>')


# ── ウォッチ中の商品のカード ──────────────────────────────────────────────

def _card(v: pd.ProductDetailView, now_ms: int) -> str:
    o, bb, bs = v.opportunity, v.best_buy, v.best_sell
    sell_val = (_yen(o.sell_price) if o is not None else _yen(bs.price) if bs else "未取得")
    sell_sub = (f"{o.sell_source}（利益の計算に使った売却先）" if o is not None
                else f"{bs.source}（手数料前）" if bs else "買取価格・成約中央値が未取得")
    roi = f"{o.roi * 100:.1f}%" if (o is not None and o.roi is not None) else "算出前"
    net = f"+{_yen(o.net_profit)}" if o is not None else "算出前"
    stock = next((r for r in v.buy_rows if r.official), None)
    stock_txt = stock.stock_label if (stock is not None and stock.stock_label) else "未確認"
    stock_ms = [_ms(c["changed_at"]) for c in v.changes if c.get("type") in _STOCK_CHANGES]
    change_ms = [m for m in (_ms(c["changed_at"]) for c in v.changes) if m]
    ends = [_ms(lv.application_end, day_end=True) for lv, _st in v.lotteries if lv.application_end]
    ends = [m for m in ends if m and m > now_ms]
    until = (f' data-nu-mp-until="{v.status_until_ms}" data-nu-mp-stale="在庫未確認（更新待ち）"'
             if v.status_until_ms else "")
    tone = product_page.STATUS_TONE.get(v.status, "neutral")
    lot_ids = " ".join(lv.event_id for lv, _st in v.lotteries)
    attrs = (f' data-nu-mp-card="{esc(v.product_id)}" data-nu-cat="{esc(v.category)}"'
             f' data-net="{int(o.net_profit) if o is not None and o.net_profit is not None else ""}"'
             f' data-roi="{o.roi if o is not None and o.roi is not None else ""}"'
             f' data-status="{esc(v.status)}" data-change="{max(change_ms) if change_ms else ""}"'
             f' data-stock-change="{max([m for m in stock_ms if m] or [0]) or ""}"'
             f' data-end="{min(ends) if ends else ""}" data-lots="{esc(lot_ids)}"')
    # 在庫ありと言える期限（商品詳細と同じ。過ぎたら「在庫未確認（更新待ち）」に落とす）
    stock_until = (f' data-nu-mp-until="{stock.stock_until_ms}" data-nu-mp-stale="在庫未確認（更新待ち）"'
                   if (stock is not None and stock.stock_until_ms) else "")
    if o is None and bb is None and bs is None:
        # 価格がまだそろっていない商品は、未取得の欄を並べずに1行で
        rows = [("想定純利益", net, "仕入れ・売却の確認済みの価格がまだそろっていません（商品詳細で確認）", "profit", ""),
                ("在庫", stock_txt, "公式ストアの表示", "", stock_until)]
    else:
        rows = [("想定純利益", net, f"ROI {roi}" if o is not None else "確定の条件を満たす組み合わせなし", "profit", ""),
                ("最安仕入（取得原価）", _yen(bb.acquisition) if bb else "未取得",
                 bb.source if bb else "確認済みの仕入れ先なし", "", ""),
                ("有効売却価格", sell_val, sell_sub, "", ""),
                ("在庫", stock_txt, "公式ストアの表示", "", stock_until)]
    cells = "".join(f'<div class="nu-mp-m{" nu-mp-m--profit" if (k == "profit" and o is not None) else ""}">'
                    f'<dt>{esc(lbl)}</dt><dd><b{extra}>{esc(val)}</b><span class="nu-osub">{esc(sub)}</span></dd></div>'
                    for lbl, val, sub, k, extra in rows)
    return (
        f'<li class="nu-mp-card"{attrs} hidden>'
        '<div class="nu-mp-card__head">'
        f'<div class="nu-mp-card__title"><a class="nu-mp-card__name" href="{esc(page_href("product"))}&amp;product_id='
        f'{esc(product_page.quote_id(v.product_id))}">{esc(v.product_name)}</a>'
        f'<span class="nu-osub">{esc(v.category_label)}{(" ・ 型番 " + esc(v.model)) if v.model else ""}</span></div>'
        f'{product_page.watch_button(v.product_id, v.product_name)}</div>'
        f'<p class="nu-mp-card__state"><span class="nu-badge nu-tone-{tone}" data-nu-mp-status="{esc(v.status)}"{until}'
        f' data-nu-mp-fallback="{esc(v.fallback_label)}"'
        f' data-nu-mp-fallback-tone="{product_page.STATUS_TONE.get(v.fallback_status, "neutral")}">{esc(v.status_label)}</span>'
        '<span class="nu-mp-card__lot" data-nu-mp-lotchip hidden></span>'
        f'<span class="nu-osub">最終確認 {product_page._time(v.last_verified_at)}</span></p>'
        f'<dl class="nu-mp-metrics">{cells}</dl>'
        f'<p class="nu-mp-card__foot">{product_page.link(v.product_id)}</p></li>'
    )


def _lottery_entry(v: pd.ProductDetailView, lv, st: dict) -> str:
    """締切の一覧（抽選・予約の runtime がそのまま状態・ボタンを書き換える。応募ボタンは人の確認が済んだものだけ）。"""
    from src.content.ui.lottery_page import _ms as _lms
    shop = " ".join(x for x in (lv.retailer, lv.store) if x) or "販売店は公式ページで確認"
    return (f'<article class="nu-mp-lot" data-nu-lot="{esc(lv.event_id)}" data-nu-bucket="{st["bucket"]}"'
            f' data-nu-sort="{st["sort"]}" data-nu-status="{esc(st["status"])}" data-nu-mp-pid="{esc(v.product_id)}"'
            f' data-ae="{_lms(lv.application_end, end=True)}" hidden>'
            f'<span class="nu-badge nu-tone-{esc(st["tone"])}" data-status="{esc(st["status"])}">'
            f'<span aria-hidden="true">{esc(st["icon"])}</span> {esc(st["label"])}</span>'
            f'<span class="nu-mp-lot__main"><b>{esc(v.product_name)}</b>'
            f'<span class="nu-osub">{esc(lv.kind_label)}・{esc(shop)}</span>'
            f'<span class="nu-osub"><span class="nu-when">{esc(st["when"])}</span> <span class="nu-cd">{esc(st["cd_text"])}</span>'
            '</span><span class="nu-mp-lot__soon" data-nu-mp-soon hidden></span></span>'
            f'<span class="nu-mp-lot__cta" data-nu-cta-slot>{cta_html(st["cta"])}</span></article>')


def _toggle(key: str, label: str) -> str:
    return (f'<label class="nu-mp-switch"><input type="checkbox" data-nu-mp-pref="notify.{esc(key)}">'
            f'<span>{esc(label)}</span></label>')


def _settings_html() -> str:
    cats_html = "".join(f'<label class="nu-mp-switch"><input type="checkbox" data-nu-mp-cat="{esc(c.key)}">'
                        f'<span>{esc(c.label)}</span></label>' for c in cats.CATEGORIES)
    return (
        '<section class="nu-mp-box" aria-labelledby="nu-mp-disp"><h2 id="nu-mp-disp" class="nu-mp-h">表示</h2>'
        '<fieldset class="nu-mp-fs"><legend>カードの表示</legend>'
        '<label class="nu-mp-radio"><input type="radio" name="nu-mp-mode" value="pro" data-nu-mp-mode>'
        '<span>詳細（仕入・売却・在庫まで出す）</span></label>'
        '<label class="nu-mp-radio"><input type="radio" name="nu-mp-mode" value="easy" data-nu-mp-mode>'
        '<span>かんたん（状態・想定純利益・締切だけ）</span></label></fieldset>'
        '<fieldset class="nu-mp-fs"><legend>よく見るジャンル（マイページの最初の絞り込み。選ばなければすべて）</legend>'
        f'<div class="nu-mp-switches">{cats_html}</div></fieldset></section>'
        '<section class="nu-mp-box" aria-labelledby="nu-mp-store"><h2 id="nu-mp-store" class="nu-mp-h">保存について</h2>'
        '<p class="nu-lead">ウォッチ・通知条件・既読は<b>このブラウザにだけ</b>保存しています。'
        'ログイン・アカウントはありません。別の端末やブラウザには引き継がれません（アカウントでの同期は準備中）。</p>'
        '<p class="nu-osub">保存しているのは商品の ID・表示と通知の条件・既読の記録だけです。</p>'
        '<div class="nu-mp-reset"><button type="button" class="nu-btn nu-btn--secondary nu-btn--sm" data-nu-mp-reset>'
        'このブラウザの保存データをリセット</button>'
        '<span class="nu-mp-reset__confirm" data-nu-mp-reset-confirm hidden>ウォッチ・設定・既読をすべて消します。'
        '<button type="button" class="nu-btn nu-btn--danger nu-btn--sm" data-nu-mp-reset-yes>消す</button>'
        '<button type="button" class="nu-btn nu-btn--secondary nu-btn--sm" data-nu-mp-reset-no>やめる</button></span>'
        '<p class="nu-osub" data-nu-mp-reset-done role="status" hidden>リセットしました。</p></div></section>'
    )


def _notify_settings_html() -> str:
    toggles = "".join(_toggle(k, lbl) for k, lbl in GROUP_LABELS.items())
    return (
        '<section class="nu-mp-box" aria-labelledby="nu-mp-cond"><h2 id="nu-mp-cond" class="nu-mp-h">通知条件</h2>'
        '<p class="nu-osub">このブラウザに保存する条件です。今は<b>マイページの表示（件数・履歴・締切の目印）の絞り込み</b>に使います。'
        'メールやスマホへの通知の配信には対応していません。</p>'
        f'<fieldset class="nu-mp-fs"><legend>表示する通知と変化</legend><div class="nu-mp-switches">{toggles}</div></fieldset>'
        '<fieldset class="nu-mp-fs"><legend>利益条件（「利益条件に到達」に数える最低ライン。利益・ROI は計算し直さない）</legend>'
        '<label class="nu-mp-num"><span>想定純利益</span><select data-nu-mp-pref="min_profit">'
        + "".join(f'<option value="{v}">{lbl}</option>' for v, lbl in
                  ((0, "指定なし"), (3000, "¥3,000以上"), (5000, "¥5,000以上"), (10000, "¥10,000以上"),
                   (30000, "¥30,000以上")))
        + '</select></label><label class="nu-mp-num"><span>ROI</span><select data-nu-mp-pref="min_roi">'
        + "".join(f'<option value="{v}">{lbl}</option>' for v, lbl in
                  ((0, "指定なし"), (5, "5%以上"), (10, "10%以上"), (20, "20%以上"), (30, "30%以上")))
        + '</select></label></fieldset>'
        '<fieldset class="nu-mp-fs"><legend>締切の目印（この時間内に締め切る抽選・予約を目立たせる）</legend>'
        '<label class="nu-mp-num"><span>締切まで</span><select data-nu-mp-pref="deadline_hours">'
        + "".join(f'<option value="{v}">{v}時間以内</option>' for v in (1, 6, 24, 72))
        + '</select></label></fieldset></section>'
    )


def render(details: dict, events: list[dict], now: datetime) -> str:
    now_ms = int(now.timestamp() * 1000)
    cards = "".join(_card(v, now_ms) for v in details.values())
    lots = "".join(_lottery_entry(v, lv, st) for v in details.values() for lv, st in v.lotteries)
    evs = "".join(_event_li(e) for e in events[:400])
    tabs = "".join(f'<a class="nu-mp-tab" href="{esc(page_href("mypage"))}&amp;section={k}" data-nu-mp-tab="{k}">'
                   f'{esc(lbl)}<span class="nu-mp-tab__n" data-nu-mp-tabn="{k}"></span></a>' for k, lbl in SECTIONS)
    summary = "".join(
        f'<li class="nu-mp-sum" data-nu-mp-sum="{k}"><span class="nu-mp-sum__label">{esc(lbl)}</span>'
        f'<span class="nu-mp-sum__n" data-nu-mp-n="{k}">0</span><span class="nu-osub">{esc(sub)}</span></li>'
        for k, lbl, sub in (("watched", "ウォッチ中", "商品"), ("profit", "利益条件に到達", "通知条件の最低ラインで数える"),
                            ("lottery", "抽選・予約の受付中", "締切が近い順に表示"),
                            ("stock", "在庫の変化", "30日以内（公式ストア）"), ("unread", "未読の通知・変化", "通知タブで確認")))
    sorts = "".join(f'<option value="{k}">{esc(lbl)}</option>' for k, lbl in
                    (("priority", "今動くべき順"), ("change", "新しい変化の順"), ("profit", "利益の大きい順"),
                     ("added", "追加した順"), ("deadline", "締切の近い順")))
    cat_chips = ('<button type="button" class="nu-chip" data-nu-mp-cat-filter="all" aria-pressed="false">すべて</button>'
                 + "".join(f'<button type="button" class="nu-chip" data-nu-mp-cat-filter="{esc(c.key)}"'
                           f' aria-pressed="false">{esc(c.label)}</button>' for c in cats.CATEGORIES))
    empty = ('<div class="nu-mp-empty" data-nu-mp-empty><p class="nu-mp-empty__title">まだウォッチ中の商品はありません。</p>'
             '<p class="nu-lead">気になる商品の「☆ ウォッチ」を押すと、価格・利益・抽選・在庫の変化をここでまとめて確認できます。</p>'
             '<div class="nu-mp-empty__ctas">'
             f'<a class="nu-btn nu-btn--primary" href="{esc(page_href("search"))}">商品を探す</a>'
             f'<a class="nu-btn nu-btn--secondary" href="{esc(page_href("opportunities"))}">利益商品を見る</a>'
             f'<a class="nu-btn nu-btn--secondary" href="{esc(page_href("lottery"))}">抽選を見る</a></div></div>')
    return (
        '<section class="nu-page nu-mp" data-nu-page="mypage" aria-labelledby="nu-mp-title" hidden>'
        '<div class="nu-mp-titlebar"><h1 id="nu-mp-title" class="nu-page__title" tabindex="-1">マイページ</h1>'
        '<span class="nu-mp-local"><span aria-hidden="true">🔒</span> このブラウザに保存（ログインなし）</span></div>'
        f'<ul class="nu-mp-summary" role="list">{summary}</ul>'
        f'<nav class="nu-mp-tabs" aria-label="マイページの切り替え">{tabs}</nav>'
        # ウォッチ（一覧 + 締切）
        '<div class="nu-mp-panel" data-nu-mp-panel="watchlist"><div class="nu-mp-grid">'
        '<section class="nu-mp-col" aria-labelledby="nu-mp-wl"><div class="nu-mp-colhead">'
        '<h2 id="nu-mp-wl" class="nu-mp-h">ウォッチ中の商品 <span class="nu-mp-count" data-nu-mp-wlcount></span></h2>'
        f'<label class="nu-mp-sort"><span>並べ替え</span><select data-nu-mp-sort>{sorts}</select></label></div>'
        f'<div class="nu-mp-cats" data-nu-mp-cats hidden>{cat_chips}</div>'
        f'{empty}<p class="nu-mp-none" data-nu-mp-catnone hidden>このジャンルのウォッチ中の商品はありません。</p>'
        f'<ul class="nu-mp-cards" data-nu-mp-cards role="list">{cards}</ul></section>'
        '<section class="nu-mp-col nu-mp-side" aria-labelledby="nu-mp-dl">'
        '<h2 id="nu-mp-dl" class="nu-mp-h">締切・受付（ウォッチ中の商品）</h2>'
        f'<div class="nu-mp-lots" data-nu-mp-lots>{lots}</div>'
        '<p class="nu-mp-none" data-nu-mp-lotnone>ウォッチ中の商品に、受付中・受付予定の抽選・予約はありません。</p>'
        '<h2 class="nu-mp-h nu-mp-h--sub">新しい通知・変化</h2><ul class="nu-mp-evs nu-mp-evs--mini" data-nu-mp-mini></ul>'
        f'<a class="nu-mp-more" href="{esc(page_href("mypage"))}&amp;section=notifications" data-nu-mp-tab="notifications">'
        '通知と変化をすべて見る</a></section></div></div>'
        # 通知（履歴 + 条件）
        '<div class="nu-mp-panel" data-nu-mp-panel="notifications" hidden><div class="nu-mp-grid">'
        '<section class="nu-mp-col" aria-labelledby="nu-mp-hist"><div class="nu-mp-colhead">'
        '<h2 id="nu-mp-hist" class="nu-mp-h">通知と変化の履歴（ウォッチ中の商品）</h2>'
        '<button type="button" class="nu-btn nu-btn--secondary nu-btn--sm" data-nu-mp-readall>すべて既読にする</button></div>'
        '<p class="nu-osub">当時の通知・変化と、今の状態を分けて出しています（既読はこのブラウザにだけ記録）。</p>'
        f'<ul class="nu-mp-evs" data-nu-mp-evs role="list">{evs}</ul>'
        '<p class="nu-mp-none" data-nu-mp-evnone>ウォッチ中の商品の通知・変化はまだありません。</p></section>'
        f'<div class="nu-mp-col nu-mp-side">{_notify_settings_html()}</div></div></div>'
        # 設定
        f'<div class="nu-mp-panel" data-nu-mp-panel="settings" hidden>{_settings_html()}</div>'
        '<p class="nu-disclaimer">掲載情報は取得時点の参考です。購入・応募の前に必ず公式サイトでご確認ください。</p>'
        '</section>'
    )


def script(valid_ids) -> str:
    """マイページとウォッチのボタン（ブラウザ側）。保存は NuStore だけを通す（localStorage。壊れていたら初期値）。"""
    import json
    ids = json.dumps(sorted(valid_ids), ensure_ascii=False).replace("</", "<\\/")
    return ("<script>window.NU_MP_IDS=" + ids + ";</script><script>" + _JS.replace("__SCHEMA__", str(SCHEMA_VERSION))
            + "</script>")


_JS = r"""
(function(){
  var root = document.getElementById('new-ui-root');
  if (!root) return;
  var VALID = {};
  (window.NU_MP_IDS || []).forEach(function(id){ VALID[id] = 1; });
  var KEY = 'premium-monitor.mypage', SCHEMA = __SCHEMA__, MAX_READ = 1000;
  var GROUPS = ['profit', 'lottery_open', 'lottery_deadline', 'restock', 'buyback', 'price'];
  function defaults() {
    var n = {}; GROUPS.forEach(function(g){ n[g] = true; });
    return {v: SCHEMA, watch: [], prefs: {notify: n, min_profit: 0, min_roi: 0, deadline_hours: 24, mode: 'pro', cats: []},
            read: []};
  }
  // ── 保存の入口（将来アカウント・サーバーに移すときはここだけ差し替える） ──
  var NuStore = (function(){
    var mem = null;
    function clean(d) {
      var base = defaults();
      if (!d || typeof d !== 'object' || d.v !== SCHEMA) return base;
      var seen = {};
      // 重複・形の違うものは捨てる。今の商品一覧に無い ID は保存には残す（表示しないだけ。一時的に一覧から
      // 外れた商品のウォッチを黙って消さない）。長さは上限まで
      base.watch = (Array.isArray(d.watch) ? d.watch : []).filter(function(w){
        var ok = w && typeof w.id === 'string' && /^[A-Za-z0-9_.-]{1,80}$/.test(w.id) && !seen[w.id];
        if (ok) seen[w.id] = 1;
        return ok;
      }).slice(0, 500).map(function(w){ return {id: w.id, at: +w.at || 0}; });
      var p = d.prefs && typeof d.prefs === 'object' ? d.prefs : {};
      GROUPS.forEach(function(g){ if (p.notify && typeof p.notify[g] === 'boolean') base.prefs.notify[g] = p.notify[g]; });
      ['min_profit', 'min_roi', 'deadline_hours'].forEach(function(k){
        if (isFinite(+p[k]) && +p[k] >= 0) base.prefs[k] = +p[k]; });
      if (p.mode === 'easy' || p.mode === 'pro') base.prefs.mode = p.mode;
      if (Array.isArray(p.cats)) base.prefs.cats = p.cats.filter(function(c){ return typeof c === 'string'; });
      base.read = (Array.isArray(d.read) ? d.read : []).filter(function(x){ return typeof x === 'string'; }).slice(-MAX_READ);
      return base;
    }
    function load() {
      if (mem) return mem;
      var raw = null;
      try { raw = window.localStorage.getItem(KEY); } catch (e) { raw = null; }
      var d = null;
      try { d = raw ? JSON.parse(raw) : null; } catch (e) { d = null; }   // 壊れていたら初期値（エラーを出さない）
      mem = clean(d);
      return mem;
    }
    function save() {
      try { window.localStorage.setItem(KEY, JSON.stringify(mem)); return true; } catch (e) { return false; }
    }
    return {
      data: load,
      reload: function(){ mem = null; return load(); },
      has: function(id){ return load().watch.some(function(w){ return w.id === id; }); },
      // 表示に使うのは今の商品一覧にある ID だけ
      ids: function(){ return load().watch.filter(function(w){ return VALID[w.id]; }); },
      add: function(id){
        if (!VALID[id] || this.has(id) || load().watch.length >= 500) return false;   // 上限500件
        load().watch.push({id: id, at: Date.now()}); save(); return true;
      },
      remove: function(id){
        var d = load(), n = d.watch.length;
        d.watch = d.watch.filter(function(w){ return w.id !== id; }); save(); return d.watch.length !== n;
      },
      setPref: function(path, val){
        var p = load().prefs;
        if (path.indexOf('notify.') === 0) p.notify[path.slice(7)] = !!val; else p[path] = val;
        save();
      },
      markRead: function(ids){
        var d = load(), s = {};
        d.read.forEach(function(x){ s[x] = 1; });
        ids.forEach(function(x){ if (!s[x]) { d.read.push(x); s[x] = 1; } });
        d.read = d.read.slice(-MAX_READ); save();
      },
      isRead: function(id){ return load().read.indexOf(id) >= 0; },
      reset: function(){ mem = defaults(); try { window.localStorage.removeItem(KEY); } catch (e) {} }
    };
  })();
  window.NuStore = NuStore;

  function sec() { return root.querySelector('[data-nu-page="mypage"]'); }
  function q() { return new URLSearchParams(location.search); }
  // ── ウォッチのボタン（全ページ） ──
  function paintButtons() {
    root.querySelectorAll('[data-nu-watch]').forEach(function(b){
      var id = b.getAttribute('data-nu-watch'), on = NuStore.has(id), name = b.getAttribute('data-nu-watch-name') || '';
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.classList.toggle('is-on', on);
      var ic = b.querySelector('.nu-watch__icon'), tx = b.querySelector('.nu-watch__text');
      if (ic) ic.textContent = on ? '★' : '☆';
      if (tx) tx.textContent = on ? 'ウォッチ中' : 'ウォッチ';
      b.setAttribute('aria-label', name + 'をウォッチ');
    });
  }
  // ── マイページ ──
  var BUCKET_OPEN = 1, BUCKET_ENDING = 0;
  function watched() {
    var m = {};
    NuStore.ids().forEach(function(w, i){ m[w.id] = {at: w.at, i: i}; });
    return m;
  }
  function num(el, k) { var v = el.getAttribute(k); return v === '' || v === null ? null : +v; }
  function lotsOf(s, pid) {
    return Array.prototype.slice.call(s.querySelectorAll('[data-nu-mp-lots] [data-nu-mp-pid="' + pid + '"]'));
  }
  function activeLot(s, pid) {
    var ls = lotsOf(s, pid).filter(function(l){ return +l.getAttribute('data-nu-bucket') < 99; });
    ls.sort(function(a, b){ return +a.getAttribute('data-nu-bucket') - +b.getAttribute('data-nu-bucket')
      || +a.getAttribute('data-nu-sort') - +b.getAttribute('data-nu-sort'); });
    return ls[0] || null;
  }
  function profitOk(card, prefs) {
    var net = num(card, 'data-net'), roi = num(card, 'data-roi');
    if (net === null) return false;                                      // 利益が無い（算出前）
    return net >= (prefs.min_profit || 0) && (roi === null ? 0 : roi * 100) >= (prefs.min_roi || 0);
  }
  function priority(card, s, now) {
    // 今動くべき順（既存の状態だけを使う。利益は計算しない）: 締切が近い抽選 → 購入可能で利益あり →
    // 利益あり → 在庫の変化（7日以内）→ 変化（7日以内）→ その他
    var lot = activeLot(s, card.getAttribute('data-nu-mp-card'));
    if (lot && +lot.getAttribute('data-nu-bucket') === BUCKET_ENDING) return 0;
    var b = card.querySelector('[data-nu-mp-status]');
    var net = num(card, 'data-net'), st = b ? b.getAttribute('data-nu-mp-status') : card.getAttribute('data-status');
    if (net !== null && st === 'AVAILABLE') return 1;
    if (net !== null) return 2;
    if (lot && +lot.getAttribute('data-nu-bucket') <= BUCKET_OPEN) return 2.5;
    var week = 7 * 864e5, sc = num(card, 'data-stock-change'), ch = num(card, 'data-change');
    if (sc !== null && now - sc < week) return 3;
    if (ch !== null && now - ch < week) return 4;
    return 5;
  }
  function paintCard(card, s, now, prefs) {
    // 在庫ありと言える期限・抽選の状態（商品詳細と同じ規則。期限が過ぎたら「更新待ち」、受付中が無ければ在庫などの状態）
    var badge = card.querySelector('[data-nu-mp-status]');
    card.querySelectorAll('[data-nu-mp-until]').forEach(function(el){
      if (now < +el.getAttribute('data-nu-mp-until')) return;
      el.textContent = el.getAttribute('data-nu-mp-stale');
      el.removeAttribute('data-nu-mp-until');
      if (el === badge) { badge.className = 'nu-badge nu-tone-neutral'; badge.setAttribute('data-nu-mp-status', 'STOCK_UNKNOWN'); }
    });
    var chip = card.querySelector('[data-nu-mp-lotchip]'), lot = activeLot(s, card.getAttribute('data-nu-mp-card'));
    if (lot) {
      // 抽選の日時だけ（状態は左のバッジ。同じ言葉を重ねない）
      var w = lot.querySelector('.nu-when'), cd = lot.querySelector('.nu-cd');
      chip.textContent = (w ? w.textContent : '') + (cd && cd.textContent ? '（' + cd.textContent + '）' : '');
      chip.hidden = !chip.textContent;
    } else chip.hidden = true;
    if (badge.getAttribute('data-nu-mp-status') === 'LOTTERY' && !lot) {
      badge.textContent = badge.getAttribute('data-nu-mp-fallback') || badge.textContent;
      badge.className = 'nu-badge nu-tone-' + (badge.getAttribute('data-nu-mp-fallback-tone') || 'neutral');
    }
    card.classList.toggle('nu-mp-card--easy', prefs.mode === 'easy');
    card.classList.toggle('nu-mp-card--goal', profitOk(card, prefs));
  }
  function renderMyPage() {
    var s = sec();
    if (!s) return;
    var d = NuStore.data(), prefs = d.prefs, w = watched(), now = Date.now(), qs = q();
    var section = ['watchlist', 'notifications', 'settings'].indexOf(qs.get('section')) >= 0 ? qs.get('section') : 'watchlist';
    s.querySelectorAll('[data-nu-mp-panel]').forEach(function(p){ p.hidden = p.getAttribute('data-nu-mp-panel') !== section; });
    s.querySelectorAll('.nu-mp-tabs [data-nu-mp-tab]').forEach(function(t){
      var on = t.getAttribute('data-nu-mp-tab') === section;
      if (on) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current');
    });
    // ジャンルの絞り込み（設定の「よく見るジャンル」が初期値。URL の mpcat が優先）
    var cat = qs.get('mpcat') || (prefs.cats.length === 1 ? prefs.cats[0] : 'all');
    var catSet = cat === 'all' ? (prefs.cats.length > 1 ? prefs.cats : null) : [cat];
    var list = s.querySelector('[data-nu-mp-cards]');
    var cards = Array.prototype.slice.call(list.querySelectorAll('[data-nu-mp-card]'));
    var mine = cards.filter(function(c){ return w[c.getAttribute('data-nu-mp-card')]; });
    var sort = qs.get('mpsort') || 'priority';
    var sel = s.querySelector('[data-nu-mp-sort]'); if (sel) sel.value = sort;
    mine.forEach(function(c){ paintCard(c, s, now, prefs); });
    var key = {
      priority: function(c){ return [priority(c, s, now), -(num(c, 'data-net') || 0)]; },
      change: function(c){ return [-(num(c, 'data-change') || 0)]; },
      profit: function(c){ var n = num(c, 'data-net'); return [n === null ? 1 : 0, -(n || 0)]; },
      added: function(c){ return [-(w[c.getAttribute('data-nu-mp-card')].at || 0)]; },
      // 締切の近い順（受付中・予定の抽選が無い商品は後ろ。runtime が締め切ったと判定したものは数えない）
      deadline: function(c){ var e = num(c, 'data-end'), live = !!activeLot(s, c.getAttribute('data-nu-mp-card'));
        return [e === null || !live || e < now ? 1 : 0, e || 0]; }
    }[sort] || function(){ return [0]; };
    mine.sort(function(a, b){
      var ka = key(a), kb = key(b);
      for (var i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i] - kb[i];
      return w[a.getAttribute('data-nu-mp-card')].i - w[b.getAttribute('data-nu-mp-card')].i;
    });
    cards.forEach(function(c){ c.hidden = true; });
    var shown = 0;
    mine.forEach(function(c){
      var ok = !catSet || catSet.indexOf(c.getAttribute('data-nu-cat')) >= 0;
      c.hidden = !ok; if (ok) shown++;
      list.appendChild(c);
    });
    s.querySelector('[data-nu-mp-empty]').hidden = mine.length > 0;
    s.querySelector('[data-nu-mp-catnone]').hidden = !(mine.length > 0 && shown === 0);
    s.querySelector('[data-nu-mp-cats]').hidden = mine.length < 2;
    var sortBox = s.querySelector('.nu-mp-sort'); if (sortBox) sortBox.hidden = mine.length < 2;
    s.querySelectorAll('[data-nu-mp-cat-filter]').forEach(function(a){
      a.setAttribute('aria-pressed', a.getAttribute('data-nu-mp-cat-filter') === cat ? 'true' : 'false');
    });
    var wc = s.querySelector('[data-nu-mp-wlcount]'); if (wc) wc.textContent = mine.length ? mine.length + '件' : '';
    // 締切・受付（runtime が状態を書き換えた抽選のうち、ウォッチ中の商品で受付中・予定・当選後の購入期間など）
    var box = s.querySelector('[data-nu-mp-lots]');
    var lots = Array.prototype.slice.call(box.querySelectorAll('[data-nu-mp-pid]'));
    lots.sort(function(a, b){ return +a.getAttribute('data-nu-bucket') - +b.getAttribute('data-nu-bucket')
      || +a.getAttribute('data-nu-sort') - +b.getAttribute('data-nu-sort'); });
    var nl = 0, nOpen = 0, soonMs = (prefs.deadline_hours || 24) * 36e5;
    lots.forEach(function(l){
      var ok = !!w[l.getAttribute('data-nu-mp-pid')] && +l.getAttribute('data-nu-bucket') < 99;
      l.hidden = !ok; box.appendChild(l);
      if (!ok) return;
      nl++;
      var b = +l.getAttribute('data-nu-bucket');
      if (b <= BUCKET_OPEN) nOpen++;
      var ae = +l.getAttribute('data-ae') || 0, soon = l.querySelector('[data-nu-mp-soon]');
      var hit = b <= BUCKET_OPEN && ae > now && ae - now <= soonMs && prefs.notify.lottery_deadline;
      soon.hidden = !hit;
      if (hit) soon.textContent = '締切まで' + (prefs.deadline_hours || 24) + '時間以内（通知条件）';
      l.classList.toggle('nu-mp-lot--soon', !!hit);
    });
    s.querySelector('[data-nu-mp-lotnone]').hidden = nl > 0;
    var urgent = lots.some(function(l){ return !l.hidden && (+l.getAttribute('data-nu-bucket') === BUCKET_ENDING || l.classList.contains('nu-mp-lot--soon')); });
    var grid = s.querySelector('[data-nu-mp-panel="watchlist"] .nu-mp-grid'); if (grid) grid.classList.toggle('nu-mp-grid--urgent', urgent);
    var sumList = s.querySelector('.nu-mp-summary'); if (sumList) sumList.hidden = mine.length === 0;
    // 通知と変化の履歴（ウォッチ中の商品・通知条件でオンの種類だけ。当時の値は書き換えない）
    var evs = Array.prototype.slice.call(s.querySelectorAll('[data-nu-mp-evs] [data-nu-mp-ev]')), ne = 0, unread = 0;
    var mini = s.querySelector('[data-nu-mp-mini]'); mini.textContent = '';
    evs.forEach(function(e){
      var ok = !!w[e.getAttribute('data-nu-mp-pid')] && prefs.notify[e.getAttribute('data-nu-mp-group')] !== false;
      e.hidden = !ok;
      if (!ok) return;
      ne++;
      var card = list.querySelector('[data-nu-mp-card="' + e.getAttribute('data-nu-mp-pid') + '"]'), nowEl = e.querySelector('[data-nu-mp-evnow]');
      if (card && nowEl) {
        var cb = card.querySelector('[data-nu-mp-status]'), cn = card.getAttribute('data-net');
        nowEl.textContent = '今の状態: ' + (cb ? cb.textContent.trim() : '') + '・' + (cn ? '利益あり ' + card.querySelector('.nu-mp-m b').textContent : '利益は算出前');
      }
      var read = NuStore.isRead(e.getAttribute('data-nu-mp-ev'));
      e.classList.toggle('is-unread', !read);
      e.querySelector('[data-nu-mp-evstate]').textContent = read ? '既読' : '未読';
      if (!read) {
        unread++;
        if (mini.children.length < 3) { var c = e.cloneNode(true); c.removeAttribute('data-nu-mp-ev'); c.hidden = false; mini.appendChild(c); }
      }
    });
    s.querySelector('[data-nu-mp-evnone]').hidden = ne > 0;
    if (!mini.children.length) {
      var li = document.createElement('li'); li.className = 'nu-mp-none'; li.textContent = '未読の通知・変化はありません。';
      mini.appendChild(li);
    }
    // 今日の自分向けサマリー（件数はここで数えるだけ。値は確定値のまま）
    var nProfit = mine.filter(function(c){ return profitOk(c, prefs); }).length;
    var nStock = mine.filter(function(c){ var t = num(c, 'data-stock-change'); return t !== null && now - t < 30 * 864e5; }).length;
    var counts = {watched: mine.length, profit: nProfit, lottery: nOpen, stock: nStock, unread: unread};
    Object.keys(counts).forEach(function(k){
      var el = s.querySelector('[data-nu-mp-n="' + k + '"]'); if (el) el.textContent = String(counts[k]);
      var li = s.querySelector('[data-nu-mp-sum="' + k + '"]'); if (li) li.classList.toggle('is-hot', counts[k] > 0 && k !== 'watched');
    });
    var tn = s.querySelector('[data-nu-mp-tabn="notifications"]'); if (tn) tn.textContent = unread ? String(unread) : '';
    var tw = s.querySelector('[data-nu-mp-tabn="watchlist"]'); if (tw) tw.textContent = mine.length ? String(mine.length) : '';
    // 設定の表示
    s.querySelectorAll('[data-nu-mp-pref]').forEach(function(i){
      var k = i.getAttribute('data-nu-mp-pref');
      if (k.indexOf('notify.') === 0) i.checked = prefs.notify[k.slice(7)] !== false;
      else i.value = String(prefs[k]);
    });
    s.querySelectorAll('[data-nu-mp-mode]').forEach(function(i){ i.checked = i.value === prefs.mode; });
    s.querySelectorAll('[data-nu-mp-cat]').forEach(function(i){ i.checked = prefs.cats.indexOf(i.getAttribute('data-nu-mp-cat')) >= 0; });
  }
  function paint() {
    paintButtons();
    if (sec() && !sec().hidden) renderMyPage();
  }
  function go(params) {
    var u = q();
    Object.keys(params).forEach(function(k){ if (params[k] === null) u.delete(k); else u.set(k, params[k]); });
    history.replaceState(history.state, '', location.pathname + '?' + u.toString());
    paint();
  }
  root.addEventListener('nu:render', paint);
  root.addEventListener('click', function(e){
    var b = e.target.closest('[data-nu-watch]');
    if (b) {
      e.preventDefault();
      var id = b.getAttribute('data-nu-watch');
      if (NuStore.has(id)) NuStore.remove(id); else NuStore.add(id);
      paint();
      return;
    }
    var s = sec();
    if (!s || !s.contains(e.target)) return;
    var f = e.target.closest('[data-nu-mp-cat-filter]');
    if (f) { e.preventDefault(); go({mpcat: f.getAttribute('data-nu-mp-cat-filter') === 'all' ? null : f.getAttribute('data-nu-mp-cat-filter')}); return; }
    if (e.target.closest('[data-nu-mp-readall]')) {
      var ids = Array.prototype.slice.call(s.querySelectorAll('[data-nu-mp-evs] [data-nu-mp-ev]'))
        .filter(function(x){ return !x.hidden; }).map(function(x){ return x.getAttribute('data-nu-mp-ev'); });
      NuStore.markRead(ids); paint(); return;
    }
    var ev = e.target.closest('[data-nu-mp-ev]');
    if (ev && e.target.closest('a')) { NuStore.markRead([ev.getAttribute('data-nu-mp-ev')]); }
    var conf = s.querySelector('[data-nu-mp-reset-confirm]'), done = s.querySelector('[data-nu-mp-reset-done]');
    if (e.target.closest('[data-nu-mp-reset]')) { conf.hidden = false; done.hidden = true; var no = conf.querySelector('[data-nu-mp-reset-no]'); if (no) no.focus(); return; }
    if (e.target.closest('[data-nu-mp-reset-no]')) { conf.hidden = true; return; }
    if (e.target.closest('[data-nu-mp-reset-yes]')) { NuStore.reset(); conf.hidden = true; done.hidden = false; paint(); return; }
  });
  root.addEventListener('change', function(e){
    var s = sec();
    if (!s || !s.contains(e.target)) return;
    var i = e.target;
    if (i.matches('[data-nu-mp-sort]')) { go({mpsort: i.value === 'priority' ? null : i.value}); return; }
    if (i.matches('[data-nu-mp-pref]')) {
      var k = i.getAttribute('data-nu-mp-pref');
      NuStore.setPref(k, k.indexOf('notify.') === 0 ? i.checked : +i.value); paint(); return;
    }
    if (i.matches('[data-nu-mp-mode]')) { NuStore.setPref('mode', i.value); paint(); return; }
    if (i.matches('[data-nu-mp-cat]')) {
      var sel = Array.prototype.slice.call(s.querySelectorAll('[data-nu-mp-cat]')).filter(function(x){ return x.checked; })
        .map(function(x){ return x.getAttribute('data-nu-mp-cat'); });
      NuStore.setPref('cats', sel); paint();
    }
  });
  // 別のタブで保存が変わったら読み直す
  window.addEventListener('storage', function(e){ if (e.key === KEY) { NuStore.reload(); paint(); } });
})();
"""
