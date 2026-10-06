"""新UIの「在庫再開」ページ（UI Phase 4）。

タブは「購入可能」（既定）と「再開履歴すべて」。1件を1要素で描画し、PC（1024px 以上）は比較しやすい行、
モバイルはカード（抽選・予約のページと同じ部品の見た目）。
「購入可能」かどうか・ボタン・件数は、ブラウザ側（shell の router の stockRuntime）が閲覧時の時刻と
data-fresh-until で判定し直す（確認から時間が経った在庫ありは「在庫未確認（更新待ち）」に落とす）。
ここでは生成時点の値を入れておくだけ。
"""

from __future__ import annotations

from datetime import datetime

from src.content.ui.components import esc
from src.content.ui.icons import icon
from src.content.ui.navigation import page_href
from src.content.ui.restock_view import RestockView
from src.market import stock_state as ss
from src.tcg.models import parse_dt

PAGE_SIZE = 20
VIEWS = (("", "購入可能"), ("history", "再開履歴すべて"))
# 再開の絞り込みは再入荷（在庫切れ → 在庫あり）の時刻だけで判定する（初めての在庫確認は入れない）
WHENS = (("", "全期間"), ("today", "本日再開"), ("24h", "24時間以内"))
SORTS = (("rec", "再開・確認が新しい"), ("checked", "確認が新しい"), ("profit", "利益が高い"), ("price", "価格が安い"))
TONE = {"available": "success", ss.OUT_OF_STOCK: "danger", "stale": "neutral", ss.UNKNOWN: "neutral",
        ss.LOTTERY: "info", ss.RESERVATION: "warning", ss.PREORDER: "warning", ss.RELEASE_WAIT: "info"}


def _ms(iso: str) -> str:
    d = parse_dt(iso) if iso else None
    return str(int(d.timestamp() * 1000)) if d else ""


def _abs(iso: str) -> str:
    d = parse_dt(iso) if iso else None
    return d.strftime("%m/%d %H:%M") if d else ""


def _time(iso: str, suffix: str) -> str:
    """時刻（閲覧時に「本日 13:42 再開」「2分前確認」などに書き換える）。"""
    if not iso:
        return ""
    return (f'<time datetime="{esc(iso)}" data-nu-rtime="{esc(iso)}" data-nu-suffix="{esc(suffix)}">'
            f'{esc(_abs(iso))} {esc(suffix)}</time>')


def _cta(v: RestockView, avail: bool) -> str:
    """購入可能は「購入する」（primary）。それ以外で販売ページがあれば「販売ページを見る」（secondary）。"""
    if not v.purchase_url:
        return ""
    kind, label, style = ("buy", "購入する", "primary") if avail else ("page", "販売ページを見る", "secondary")
    return (f'<a class="nu-btn nu-btn--{style}" href="{esc(v.purchase_url)}" target="_blank" rel="noopener nofollow"'
            f' data-nu-rcta="{kind}" data-track="restock_click">{label}</a>')


def _restock_text(v: RestockView) -> str:
    if v.restocked_at:
        return _time(v.restocked_at, "再開")
    if v.first_seen_at:
        # 在庫切れを確認したことが無いので「再入荷」とは言わない
        return _time(v.first_seen_at, "在庫確認")
    return '<span class="nu-lrow__val--muted">—</span>'


def _details(v: RestockView, state_label: str, pd_ids: set | None = None) -> str:
    rows = [
        ("今の状態", "\0STATE"),
        ("前回の状態", ss.STATE_LABELS.get(v.previous_stock_state, "") if v.previous_stock_state else ""),
        ("再開（再入荷）", _abs(v.restocked_at) or "まだ確認していません"),
        ("初めて在庫を確認", _abs(v.first_seen_at)),
        ("在庫の最終確認", _abs(v.last_checked_at)),
        ("価格の確認", _abs(v.price_observed_at)),
        ("購入制限", v.purchase_limit or "制限未確認"),
        ("商品の状態", v.variant),
        ("情報の種類", {"official_store": "公式ストアの在庫表示", "tcg_event": "公式・販売店の販売情報",
                    "manual_verified": "公式ページを人が確認"}.get(v.source_type, "")),
    ]
    # 「今の状態」はバッジと同じ文言（閲覧時に stockRuntime が両方を書き換える）
    body = "".join(f"<dt>{esc(k)}</dt><dd>{esc(val)}</dd>" if val != "\0STATE"
                   else f'<dt>{esc(k)}</dt><dd data-nu-rstate>{esc(state_label)}</dd>' for k, val in rows if val)
    link = ""
    if v.source_url and v.source_url != v.purchase_url:
        link = (f'<a class="nu-btn nu-btn--secondary nu-lrow__src" href="{esc(v.source_url)}" target="_blank"'
                f' rel="noopener nofollow" data-track="restock_info_click">情報元を開く</a>')
    if pd_ids and v.product_id in pd_ids:
        from src.content.ui import product_page
        link += product_page.link(v.product_id) + product_page.watch_button(v.product_id, v.product_name)
    return (f'<details class="nu-ldetail" data-track="restock_detail_open"><summary>詳細'
            f'<span class="nu-sr">（{esc(v.product_name)}）</span></summary>'
            f'<dl class="nu-ldetail__dl">{body}</dl>{link}</details>')


def _row(v: RestockView, idx: int, now: datetime, pd_ids: set | None = None) -> str:
    avail = v.available(now)
    label = ss.STATE_LABELS[ss.IN_STOCK] if avail else v.label(now)
    tone = TONE["available"] if avail else (TONE["stale"] if v.stock_state == ss.IN_STOCK
                                              else TONE.get(v.stock_state, "neutral"))
    search = " ".join(x for x in (v.product_name, v.retailer, v.variant) if x).lower()
    price = (f'<span class="nu-lrow__lbl">販売価格</span><span class="nu-lrow__val">¥{v.price:,}</span>'
             if v.price is not None else
             '<span class="nu-lrow__lbl">販売価格</span><span class="nu-lrow__val nu-lrow__val--muted">価格未取得</span>')
    profit = (f'<span class="nu-lrow__lbl">想定利益</span><span class="nu-lrow__val nu-profit">+¥{v.profit:,}</span>'
              f'<span class="nu-lrow__ref">ROI {v.roi * 100:.1f}%</span>' if v.profit is not None and v.roi is not None
              else '<span class="nu-lrow__lbl">想定利益</span><span class="nu-lrow__val nu-lrow__val--muted">算出前</span>')
    limit = v.purchase_limit or "制限未確認"
    return (
        f'<article class="nu-lrow nu-rrow" data-nu-rs="{esc(v.key)}" data-state="{esc(v.stock_state)}"'
        f' data-fresh-until="{_ms(v.fresh_until)}" data-has-url="{"1" if v.purchase_url else "0"}"'
        f' data-avail="{"1" if avail else "0"}" data-nu-cat="{esc(v.category)}" data-restock="{_ms(v.restocked_at)}"'
        f' data-first="{_ms(v.first_seen_at)}" data-checked="{_ms(v.last_checked_at)}"'
        f' data-profit="{v.profit if v.profit is not None else ""}" data-price="{v.price if v.price is not None else ""}"'
        f' data-idx="{idx}" data-search="{esc(search)}" data-track="restock_view">'
        f'<div class="nu-lrow__status"><span class="nu-badge nu-tone-{tone}" data-nu-rbadge>'
        f'{esc(label)}</span></div>'
        f'<div class="nu-lrow__main"><h3 class="nu-lrow__title">{esc(v.product_name)}</h3>'
        f'<p class="nu-lrow__shop">{esc(v.retailer)}<span class="nu-lrow__cat"> ・ {esc(v.category_label)}</span></p>'
        f'<p class="nu-lrow__chips"><span class="nu-lchip">{esc(limit)}</span>'
        + (f'<span class="nu-lchip">{esc(v.variant)}</span>' if v.variant else "") + '</p></div>'
        f'<div class="nu-lrow__price">{price}</div>'
        f'<div class="nu-lrow__profit">{profit}</div>'
        f'<div class="nu-lrow__when"><span class="nu-when">{_restock_text(v)}</span>'
        f'<span class="nu-lrow__upd">{_time(v.last_checked_at, "確認")}</span></div>'
        f'<div class="nu-lrow__cta" data-nu-rcta-slot>{_cta(v, avail)}</div>'
        f'{_details(v, label, pd_ids)}'
        '</article>'
    )


def _toolbar(n: int) -> str:
    base = page_href("restock")
    seg = lambda items, param: "".join(  # noqa: E731
        f'<a class="nu-seg" href="{esc(base + (f"&{param}={k}" if k else ""))}" data-nu-rparam="{param}"'
        f' data-nu-rvalue="{k}">{esc(lbl)}</a>' for k, lbl in items)
    return (
        '<div class="nu-otools">'
        # 表示（購入可能・履歴）と再開の絞り込みは1行（モバイルで操作の行を増やさない）
        '<div class="nu-otools__row"><span class="nu-otools__lbl" id="nu-rview-lbl">表示</span>'
        f'<nav class="nu-segs" aria-labelledby="nu-rview-lbl">{seg(VIEWS, "view")}</nav>'
        f'<nav class="nu-segs" aria-label="再開の時期で絞り込む" data-nu-rs-hide-empty>{seg(WHENS, "when")}</nav></div>'
        '<div class="nu-otools__row" data-nu-rs-hide-empty><span class="nu-otools__lbl" id="nu-rsort-lbl">並び替え</span>'
        f'<nav class="nu-segs" aria-labelledby="nu-rsort-lbl">{seg(SORTS, "sort")}</nav>'
        '<button type="button" class="nu-chip nu-chip--sm" aria-expanded="false" aria-controls="nu-rsearch"'
        f' data-nu-search-toggle>{icon("search", size=16)}商品・販売店で絞り込む</button></div>'
        '<form class="nu-osearch" id="nu-rsearch" role="search" hidden data-nu-search-form>'
        '<label class="nu-filter__search nu-filter__search--live">'
        f'{icon("search", size=16)}<span class="nu-sr">商品名・型番・販売店で絞り込む</span>'
        '<input type="search" name="q" placeholder="商品名・型番・販売店（選んだジャンルの中）" autocomplete="off"'
        ' data-nu-search-input></label></form>'
        f'<p class="nu-oresult" aria-live="polite"><span data-nu-rresult>{n}件</span></p>'
        # 期限切れで「購入する」を押したときのお知らせ（行は購入可能から外れて隠れるので、ページの通知欄に出す）
        '<p class="nu-rmsg" role="status" data-nu-rnotice hidden></p>'
        '</div>'
    )


def render(catalog, *, now: datetime, has_data: bool = True) -> str:
    from src.content.ui import pages
    views = catalog.restock_views
    ids = getattr(catalog, "product_ids", None) or set()
    rows = "".join(_row(v, i, now, ids) for i, v in enumerate(views))
    n = sum(1 for v in views if v.available(now))
    info = pages.PURPOSE_INFO["restock"]
    empty = (
        '<div class="nu-empty" data-nu-rempty="avail" role="status" hidden>'
        '<p class="nu-empty__msg">現在、購入可能を確認できている商品はありません</p>'
        '<p class="nu-empty__hint">在庫の確認は通常1日1回（12:00 ごろ）です。在庫ありを確認した商品は、確認から3時間'
        '（TCG の入荷情報は15分〜2時間）ここに表示します。</p>'
        f'<a class="nu-btn nu-btn--secondary nu-empty__cta" href="{esc(page_href("restock"))}&amp;view=history"'
        ' data-nu-keepcat data-nu-rs-tohist>再開履歴を見る</a>'
        f'<a class="nu-btn nu-btn--secondary nu-empty__cta" href="{esc(page_href("lottery"))}" data-nu-keepcat'
        ' data-nu-rs-tolot hidden>抽選・予約を見る</a></div>'
        '<div class="nu-empty" data-nu-rempty="history" role="status" hidden>'
        '<p class="nu-empty__msg">まだ在庫再開を確認していません</p>'
        '<p class="nu-empty__hint">在庫切れの商品に在庫が戻ったことを確認すると、ここに表示します。</p>'
        f'<a class="nu-btn nu-btn--secondary nu-empty__cta" href="{esc(page_href("lottery"))}" data-nu-keepcat>'
        '抽選・予約を見る</a></div>'
        '<div class="nu-empty" data-nu-rempty="nomatch" role="status" hidden>'
        '<p class="nu-empty__msg">条件に合う商品はありません</p>'
        '<p class="nu-empty__hint">絞り込みや検索の条件を変えてください。</p></div>'
    )
    return (
        '<section class="nu-page" data-nu-page="restock" aria-labelledby="nu-restock-title" hidden>'
        f'{pages._crumbs("restock")}'
        f'<div class="nu-pagehead"><span class="nu-pagehead__icon">{icon(info["icon"], size=22)}</span>'
        f'<div><h1 id="nu-restock-title" class="nu-page__title">{esc(info["label"])}</h1>'
        f'<p class="nu-lead">{esc(info["desc"])}</p></div></div>'
        f'{pages._cat_switch("restock")}'
        f'{_toolbar(n)}'
        '<h2 class="nu-sr">在庫再開の一覧</h2>'
        '<div class="nu-lhead" aria-hidden="true" data-nu-rs-head><span>現在の状態</span><span>商品・販売店</span>'
        '<span>販売価格</span><span>想定利益</span><span>再開・最終確認</span><span></span></div>'
        f'<div class="nu-llist" data-nu-rs-list>{rows}</div>'
        f'{empty}'
        '<nav class="nu-pager" aria-label="ページ" data-nu-rpager hidden></nav>'
        f'<p class="nu-rule">{esc(pages.RULES["restock"])}</p>'
        '</section>'
    )
