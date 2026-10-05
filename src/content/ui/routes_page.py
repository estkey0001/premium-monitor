"""新UIの「せどりルート」ページ（UI Phase 5）。

上: 確定ルート（RouteView。成約中央値か買取で売値の根拠があるもの）。1件1要素で、PC（1024px 以上）は比較しやすい行、
モバイルはカード。利益・ROI は RouteView の確定値をそのまま描画し、画面では計算しない。
下: 出品価格の参考（ListingRef）。利益・ROI は出さず、確定ルートと見た目でも分ける。
絞り込み・並べ替え・検索・ページは shell の router（renderRoutes）が data-* 属性で行う（URL: tab / filter / sort / q / page_num）。
"""

from __future__ import annotations

from src.content.ui.components import esc
from src.content.ui.icons import icon
from src.content.ui.navigation import page_href
from src.content.ui.route_view import ListingRef, RouteView
from src.market import stock_state as ss
from src.tcg.models import parse_dt

PAGE_SIZE = 20
TABS = (("", "すべて"), ("retail", "正規 → 二次"), ("secondary", "二次 → 二次"), ("other", "その他（買取店）"))
# 在庫確認済みはルートの仕入先の在庫を判定できるデータが無いので準備中（押せない）
FILTERS = (("highroi", "高ROI（20%以上）"),)
FILTERS_SOON = ("在庫確認済み",)
SORTS = (("profit", "純利益が高い"), ("roi", "ROIが高い"), ("updated", "更新が新しい"), ("samples", "成約件数が多い"))
HIGH_ROI = 0.20


def _yen(v) -> str:
    return f"¥{int(round(v)):,}" if v is not None else "—"


def _ms(iso: str) -> int:
    d = parse_dt(iso) if iso else None
    return int(d.timestamp() * 1000) if d else 0


def _abs(iso: str) -> str:
    d = parse_dt(iso) if iso else None
    return d.strftime("%m/%d %H:%M") if d else ""


def _time(iso: str) -> str:
    if not iso:
        return '<span class="nu-time">確認日時なし</span>'
    return f'<time class="nu-time" datetime="{esc(iso)}" data-nu-time="{esc(iso)}">{esc(_abs(iso))}確認</time>'


def _cond(v: RouteView) -> str:
    from src.models.sale_price import CONDITION_LABELS
    return CONDITION_LABELS.get(v.condition, "") if v.condition else ""


def _period(v: RouteView) -> str:
    a, b = parse_dt(v.sell_period_start) if v.sell_period_start else None, parse_dt(v.sell_period_end) if v.sell_period_end else None
    return f"{a.strftime('%m/%d')}〜{b.strftime('%m/%d')}" if a and b else ""


def _evidence_short(v: RouteView) -> str:
    """一覧の行に出す短い根拠（範囲などは詳細で）。"""
    if v.sell_price_type == "SOLD_MEDIAN":
        return f"成約中央値・{v.sell_sample_count}件（{_period(v)}）"
    return v.sell_type_label


def _evidence(v: RouteView) -> str:
    """売値の根拠（成約中央値なら期間・件数・範囲。買取なら買取価格）。"""
    if v.sell_price_type == "SOLD_MEDIAN":
        period = _period(v)
        rng = (f"最安 {_yen(v.sell_min)} ／ 最高 {_yen(v.sell_max)}"
               if v.sell_min is not None and v.sell_max is not None else "範囲 未取得")
        return f"成約中央値・{v.sell_sample_count}件・{period}（{rng}）"
    return v.sell_type_label


def _details(v: RouteView, pd_ids: set | None = None) -> str:
    """利益の内訳（売値から順に引く）と、根拠・確認時刻。"""
    lines = [("想定売値", _yen(v.sell_price)), ("売値の根拠", _evidence(v)),
             ("− 仕入価格", "−" + _yen(v.buy_price)), ("仕入れ値の種類", v.buy_price_label),
             ("− 購入送料", "−" + _yen(v.buy_shipping)), ("− 購入時の費用", "−" + _yen(v.buy_required_cost))]
    for label, amount in v.cost_lines:
        lines.append((f"− {label}", "−" + _yen(amount)))
    lines.append(("＝ 想定純利益", "+" + _yen(v.net_profit)))
    lines.append(("必要な仕入れ資金（取得原価）", _yen(v.acquisition_cost)))
    lines.append(("ROI（純利益 ÷ 取得原価）", f"{v.roi * 100:.1f}%" if v.roi is not None else "算出前"))
    info = [("仕入れの確認", _abs(v.buy_last_verified_at)), ("売値の確認", _abs(v.sell_last_verified_at)),
            ("仕入先の在庫", ss.STATE_LABELS.get(v.stock_state, "在庫未確認")),
            ("商品の同一性", "仕入れ・売却とも確認済み"), ("商品の状態", _cond(v))]
    body = "".join(f"<dt>{esc(k)}</dt><dd>{esc(val)}</dd>" for k, val in lines + info if val)
    links = ""
    if v.sell_url:
        links = (f'<a class="nu-btn nu-btn--secondary nu-lrow__src" href="{esc(v.sell_url)}" target="_blank"'
                 f' rel="noopener nofollow" data-track="route_market_click">'
                 '売却先を見る</a>')
    if pd_ids and v.product_id in pd_ids:
        from src.content.ui import product_page
        links += product_page.link(v.product_id)
    return (f'<details class="nu-ldetail" data-track="route_detail_open"><summary>詳細（内訳・根拠）'
            f'<span class="nu-sr">（{esc(v.product_name)}）</span></summary>'
            f'<dl class="nu-ldetail__dl">{body}</dl>{links}</details>')


def _row(v: RouteView, idx: int, pd_ids: set | None = None) -> str:
    search = " ".join(x for x in (v.product_name, v.model, v.buy_source, v.sell_source) if x).lower()
    # 「更新が新しい」は古い方の確認時刻で並べる（ルートの鮮度は古い側で決まる）
    upd = min(_ms(v.buy_last_verified_at), _ms(v.sell_last_verified_at))
    stock = ss.STATE_LABELS.get(v.stock_state, "在庫未確認")
    samples = f'<span class="nu-lchip">成約 {v.sell_sample_count}件</span>' if v.sell_sample_count else ""
    cta = (f'<a class="nu-btn nu-btn--secondary" href="{esc(v.buy_url)}" target="_blank" rel="noopener nofollow"'
           f' data-track="route_buy_click">仕入先を見る</a>' if v.buy_url else "")
    return (
        f'<article class="nu-lrow nu-route" data-nu-route="{esc(v.route_id)}" data-rt-tab="{esc(v.tab)}"'
        f' data-nu-cat="{esc(v.category)}" data-profit="{int(v.net_profit or 0)}" data-roi="{v.roi or 0:.6f}"'
        f' data-upd="{upd}" data-samples="{v.sell_sample_count or 0}" data-stock="{esc(v.stock_state)}"'
        f' data-idx="{idx}" data-search="{esc(search)}" data-track="route_view">'
        f'<div class="nu-lrow__status"><span class="nu-badge nu-tone-info">{esc(v.route_label)}</span>'
        f'<span class="nu-lrow__sub">仕入先: {esc(stock)}</span></div>'
        f'<div class="nu-lrow__main"><h3 class="nu-lrow__title">{esc(v.product_name)}</h3>'
        f'<p class="nu-lrow__shop">{esc(v.category_label)}{" ・ " + esc(_cond(v)) if _cond(v) else ""}</p>'
        f'<p class="nu-lrow__chips">{samples}</p></div>'
        f'<div class="nu-lrow__price"><span class="nu-lrow__lbl">買う</span>'
        f'<span class="nu-lrow__shopname">{esc(v.buy_source)}</span>'
        f'<span class="nu-lrow__val">{_yen(v.buy_price)}</span>'
        f'<span class="nu-lrow__ref">{esc(v.buy_price_label)}</span>'
        f'<span class="nu-lrow__ref">{_time(v.buy_last_verified_at)}</span></div>'
        f'<div class="nu-lrow__profit"><span class="nu-lrow__lbl">売る</span>'
        f'<span class="nu-lrow__shopname">{esc(v.sell_source)}</span>'
        f'<span class="nu-lrow__val">{_yen(v.sell_price)}</span>'
        f'<span class="nu-lrow__ref">{esc(_evidence_short(v))}</span>'
        f'<span class="nu-lrow__ref">{_time(v.sell_last_verified_at)}</span></div>'
        f'<div class="nu-lrow__when"><span class="nu-lrow__lbl">想定純利益（費用差引後）</span>'
        f'<span class="nu-lrow__val nu-profit">+{_yen(v.net_profit)}</span>'
        f'<span class="nu-lrow__sub">ROI {v.roi * 100:.1f}%</span></div>'
        f'<div class="nu-lrow__cta">{cta}</div>'
        f'{_details(v, pd_ids)}'
        '</article>'
    )


def _ref_row(r: ListingRef) -> str:
    link = (f'<a class="nu-btn nu-btn--secondary nu-refrow__btn" href="{esc(r.url)}" target="_blank" rel="noopener nofollow"'
            f' data-track="route_listing_click">市場を見る</a>' if r.url else "")
    count = f"{r.count}件" if r.count else "件数 未取得"
    return (
        f'<li class="nu-refrow" data-nu-cat="{esc(r.category)}" data-nu-ref>'
        f'<div class="nu-refrow__main"><span class="nu-refrow__name">{esc(r.product_name)}</span>'
        f'<span class="nu-refrow__market">{esc(r.marketplace)}（出品）{" ・ " + esc(r.condition) if r.condition else ""}</span></div>'
        f'<div class="nu-refrow__price"><span class="nu-lrow__lbl">出品価格（代表値・種類不明）</span>'
        f'<span class="nu-refrow__val">{_yen(r.price)}</span>'
        f'<span class="nu-lrow__ref">{esc(count)} ・ 最安・最高・中央値の区別 未取得</span></div>'
        f'<div class="nu-refrow__time">{_time(r.observed_at)}'
        + ('<span class="nu-lchip nu-lchip--warn">古い情報</span>' if r.stale else "") + '</div>'
        f'{link}</li>'
    )


def _toolbar(n: int) -> str:
    base = page_href("routes")
    seg = lambda items, param: "".join(  # noqa: E731
        f'<a class="nu-seg" href="{esc(base + (f"&{param}={k}" if k else ""))}" data-nu-tparam="{param}"'
        f' data-nu-tvalue="{k}">{esc(lbl)}</a>' for k, lbl in items)
    chips = "".join(f'<a class="nu-chip nu-chip--sm" href="{esc(base)}&amp;filter={k}" data-nu-tparam="filter"'
                    f' data-nu-tvalue="{k}">{esc(lbl)}</a>' for k, lbl in FILTERS)
    chips += "".join(f'<span class="nu-chip nu-chip--sm nu-chip--soon" aria-disabled="true">{esc(lbl)}'
                     '<span class="nu-quick__tag">準備中</span></span>' for lbl in FILTERS_SOON)
    return (
        f'<div class="nu-otools" data-nu-rt-hide-empty{"" if n else " hidden"}>'
        '<div class="nu-otools__row"><span class="nu-otools__lbl" id="nu-ttab-lbl">ルート</span>'
        f'<nav class="nu-segs" aria-labelledby="nu-ttab-lbl">{seg(TABS, "tab")}</nav></div>'
        '<div class="nu-otools__row"><span class="nu-otools__lbl" id="nu-tsort-lbl">並び替え</span>'
        f'<nav class="nu-segs" aria-labelledby="nu-tsort-lbl">{seg(SORTS, "sort")}</nav>'
        f'<div class="nu-ofilters" role="group" aria-label="絞り込み">{chips}</div>'
        '<button type="button" class="nu-chip nu-chip--sm" aria-expanded="false" aria-controls="nu-tsearch"'
        f' data-nu-search-toggle>{icon("search", size=16)}商品・仕入先・売却先で絞り込む</button></div>'
        '<form class="nu-osearch" id="nu-tsearch" role="search" hidden data-nu-search-form>'
        '<label class="nu-filter__search nu-filter__search--live">'
        f'{icon("search", size=16)}<span class="nu-sr">商品名・型番・仕入先・売却先で絞り込む</span>'
        '<input type="search" name="q" placeholder="商品名・型番・仕入先・売却先" autocomplete="off"'
        ' data-nu-search-input></label></form>'
        f'<p class="nu-oresult" aria-live="polite"><span data-nu-tresult>{n}件</span></p>'
        '</div>'
    )


def render(catalog) -> str:
    from src.content.ui import pages
    routes = catalog.route_views
    refs = catalog.listing_refs
    n = len(routes)
    info = pages.PURPOSE_INFO["routes"]
    ids = getattr(catalog, "product_ids", None) or set()
    rows = "".join(_row(v, i, ids) for i, v in enumerate(routes))
    empty = (
        f'<div class="nu-empty" data-nu-tempty="none" role="status"{"" if not n else " hidden"}>'
        '<p class="nu-empty__msg">現在、成約価格を確認できる利益ルートはありません</p>'
        '<p class="nu-empty__hint">出品価格ではなく、実際の成約データ（件数3件以上・集計期間あり）か買取価格を確認でき、'
        '商品・状態・費用がそろったルートだけを表示します。</p></div>'
        '<div class="nu-empty" data-nu-tempty="nomatch" role="status" hidden>'
        '<p class="nu-empty__msg">条件に合うルートはありません</p>'
        '<p class="nu-empty__hint">ルートの種類・絞り込み・検索の条件を変えてください。</p></div>'
    )
    ref_items = "".join(_ref_row(r) for r in refs)
    reference = (
        '<section class="nu-refs" aria-labelledby="nu-refs-title">'
        '<h2 id="nu-refs-title" class="nu-refs__title">出品価格の参考<span class="nu-refs__tag">参考情報</span></h2>'
        '<p class="nu-refs__note">二次流通で最後に確認した出品価格（商品を照合できた、30日以内のもの）です。'
        '成約価格（実際に売れた価格）ではないので、利益・ROI は出しません。出品価格を売値として扱いません。</p>'
        f'<ul class="nu-refs__list" data-nu-ref-list>{ref_items}</ul>'
        f'<p class="nu-empty__hint" data-nu-ref-empty{"" if not refs else " hidden"}>このジャンルで、商品を照合できた出品価格の情報はありません。</p>'
        '</section>'
    )
    return (
        '<section class="nu-page" data-nu-page="routes" aria-labelledby="nu-routes-title" hidden>'
        f'{pages._crumbs("routes")}'
        f'<div class="nu-pagehead"><span class="nu-pagehead__icon">{icon(info["icon"], size=22)}</span>'
        f'<div><h1 id="nu-routes-title" class="nu-page__title">{esc(info["label"])}</h1>'
        f'<p class="nu-lead">{esc(info["desc"])}</p></div></div>'
        f'{pages._related("routes")}'
        f'{pages._cat_switch("routes")}'
        f'{_toolbar(n)}'
        '<h2 class="nu-sr">確定ルートの一覧</h2>'
        f'<div class="nu-lhead" aria-hidden="true" data-nu-rt-hide-empty{"" if n else " hidden"}><span>ルート</span>'
        '<span>商品</span><span>買う</span><span>売る</span><span>純利益・ROI</span><span></span></div>'
        f'<div class="nu-llist" data-nu-route-list>{rows}</div>'
        f'{empty}'
        '<nav class="nu-pager" aria-label="ページ" data-nu-tpager hidden></nav>'
        f'{reference}'
        f'<p class="nu-rule">{esc(pages.RULES["routes"])}</p>'
        '</section>'
    )
