"""新UIの「利益商品」ページ（UI Phase 2）。

OpportunityView（opportunity.py）の確定した値だけを描画する。利益・ROI はここでも JS でも計算しない。
同じ1件を、PC 向けの比較テーブルの行（1200px 以上）とカード（1200px 未満。640px 以上は2列）の両方に描画し、
CSS でどちらかを出す（モバイルでテーブルを横スクロールさせない）。

並べ替え・絞り込み・ページ切り替え・一覧内の検索はブラウザ側（shell の router の NuOpp）で、
各行の data-* 属性（ここで確定した値）を使って行う。状態は URL（sort / filter / q / page_num / top）に持つ。
"""

from __future__ import annotations

from src.content.ui import categories as cats
from src.content.ui import components as c
from src.content.ui import opportunity as opp
from src.content.ui.components import esc
from src.content.ui.icons import icon
from src.content.ui.navigation import page_href

PAGE_SIZE = 20

SORTS = (("rec", "おすすめ"), ("profit", "利益が高い"), ("roi", "ROIが高い"), ("updated", "更新が新しい"))
# 絞り込み。実データで判定できるものだけ有効（在庫あり = 公式の在庫表示が「在庫あり」）
FILTERS_LIVE = (("instock", "在庫あり"),)
FILTERS_SOON = ("在庫復活", "買取急騰", "新着")   # データが揃うまで押せない（1つの「準備中」チップにまとめる）

STOCK_TONE = {"IN_STOCK": "success", "OUT_OF_STOCK": "danger", "UNKNOWN": "neutral",
              "RESERVATION": "warning", "LOTTERY": "info"}


def _yen(v) -> str:
    try:
        return f"¥{int(round(float(v))):,}"
    except (TypeError, ValueError):
        return "—"


def _roi(v: opp.OpportunityView) -> str:
    return f"{v.roi * 100:.1f}%" if v.roi is not None else "算出前"


def _time(iso: str, *, fixed: bool = False) -> str:
    """確認時刻（閲覧時にブラウザが「3分前確認」などに書き換える。ここは生成時点の表示）。

    fixed=True は定価の確認日（固定値。最長180日まで有効）で、「更新遅延」と出さずに日付だけ出す。
    """
    if not iso:
        return '<span class="nu-time">確認日時なし</span>'
    d = opp._dt(iso)
    if fixed:
        return f'<time class="nu-time" datetime="{esc(iso)}">{d.strftime("%m/%d")}確認（定価）</time>'
    return (f'<time class="nu-time" datetime="{esc(iso)}" data-nu-time="{esc(iso)}">'
            f'{d.strftime("%m/%d %H:%M")}確認</time>')


def _stock(v: opp.OpportunityView) -> str:
    tone = STOCK_TONE.get(v.buy_stock, "neutral")
    return f'<span class="nu-badge nu-tone-{tone}">{esc(v.stock_label)}</span>'


def _sell_note(v: opp.OpportunityView) -> str:
    note = v.sell_type_label
    if v.sell_price_type == "SOLD_MEDIAN" and v.sell_period and v.sell_samples:
        note += f"・{v.sell_period} / {v.sell_samples}件"
    return note


def _detail(v: opp.OpportunityView, pd_ids: set | None = None) -> str:
    """1段だけの詳細（価格の内訳・情報元・確認日時・在庫・価格種別・費用）。入れ子にしない。"""
    # 売る値段から、仕入れ値と費用を引いた残りが純利益（上から順に読めば計算が追える並び）
    rows = [f'<li><span>売却価格（{esc(_sell_note(v))}）</span><b>{_yen(v.sell_price)}</b></li>',
            f'<li><span>仕入価格（{esc(v.buy_price_label)}）</span><b>−{_yen(v.buy_price)}</b></li>']
    if v.breakdown_ok:
        for label, amount in v.cost_lines:
            rows.append(f'<li><span>{esc(label)}</span><b>−{_yen(amount)}</b></li>')
    rows.append(f'<li class="nu-break__total"><span>＝ 想定純利益</span><b>+{_yen(v.net_profit)}</b></li>')
    if not v.breakdown_ok:
        rows.append('<li class="nu-break__note">費用の内訳は算出前です（合計は確認済み）</li>')
    acq = (f'<li><span>取得原価</span><b>{_yen(v.acquisition_cost)}</b></li>'
           f'<li><span>ROI（純利益 ÷ 取得原価）</span><b>{esc(_roi(v))}</b></li>')
    src = (
        f'<li><span>買う</span><b>{esc(v.buy_source)}</b></li>'
        f'<li><span>　確認</span><b>{_time(v.buy_checked_at, fixed=v.kind == "official_to_buyback")}</b></li>'
        f'<li><span>　在庫</span><b>{esc(v.stock_label)}'
        + (f'（{opp._dt(v.stock_checked_at).strftime("%m/%d %H:%M")}時点）' if v.stock_checked_at else "") + '</b></li>'
        f'<li><span>売る</span><b>{esc(v.sell_source)}（{esc(v.sell_type_label)}）</b></li>'
        f'<li><span>　確認</span><b>{_time(v.sell_checked_at)}</b></li>')
    links = []
    for label, href in (("公式ストアを開く" if v.kind == "official_to_buyback" else "仕入れ先を開く", v.buy_url),
                        ("売却先を開く", v.sell_url)):
        if c.safe_href(href).startswith("https://"):
            links.append(c.button(label, href, kind="secondary", external=True, track="opportunity_link"))
    if v.flags.get("href"):
        links.append(c.button("旧表示で詳しく見る", v.flags["href"], kind="secondary"))
    if pd_ids and v.product_id in pd_ids:
        from src.content.ui import product_page
        links.append(product_page.link(v.product_id))
        links.append(product_page.watch_button(v.product_id, v.product_name))
    return (f'<div class="nu-odetail__grid"><div><h4 class="nu-odetail__h">価格の内訳</h4>'
            f'<ul class="nu-break">{"".join(rows)}</ul><ul class="nu-break nu-break--sub">{acq}</ul></div>'
            f'<div><h4 class="nu-odetail__h">情報元</h4><ul class="nu-break">{src}</ul>'
            f'<div class="nu-odetail__links">{"".join(links)}</div></div></div>')


def _attrs(v: opp.OpportunityView, idx: int) -> str:
    updated = opp._dt(v.last_verified_at)
    search = " ".join(x for x in (v.product_name, v.model, v.capacity, v.variant) if x).lower()
    return (f' data-nu-oid="{esc(v.id)}" data-nu-cat="{esc(v.category)}" data-profit="{int(v.net_profit or 0)}"'
            f' data-roi="{v.roi or 0:.6f}" data-updated="{int(updated.timestamp() * 1000) if updated else 0}"'
            f' data-rec="{idx}" data-stock="{esc(v.buy_stock)}" data-search="{esc(search)}"')


def _row(v: opp.OpportunityView, idx: int, pd_ids: set | None = None) -> str:
    did = f"nu-od-{idx}"
    cat = cats.LABELS.get(v.category, "その他")
    return (
        f'<tr class="nu-orow"{_attrs(v, idx)}>'
        f'<th scope="row" class="nu-ocol-name"><span class="nu-oname">{esc(v.product_name)}</span>'
        + (f'<span class="nu-omodel">{esc(v.model)}</span>' if v.model else "") + '</th>'
        f'<td class="nu-ocol-cat">{esc(cat)}</td>'
        f'<td class="nu-ocol-src">{esc(v.buy_source)}<span class="nu-osub">{esc(v.buy_price_label)}</span></td>'
        f'<td class="nu-num">{_yen(v.buy_price)}</td>'
        f'<td class="nu-ocol-src">{esc(v.sell_source)}<span class="nu-osub">{esc(_sell_note(v))}</span></td>'
        f'<td class="nu-num">{_yen(v.sell_price)}</td>'
        f'<td class="nu-num nu-profit"><span class="nu-sr">想定純利益 </span>+{_yen(v.net_profit)}'
        '<span class="nu-osub">費用差引後</span></td>'
        f'<td class="nu-num nu-roi">{esc(_roi(v))}</td>'
        f'<td>{_stock(v)}</td>'
        f'<td class="nu-ocol-time">{_time(v.last_verified_at)}</td>'
        f'<td><button type="button" class="nu-rowbtn" aria-expanded="false" aria-controls="{did}"'
        f' data-nu-toggle>詳細<span class="nu-sr">（{esc(v.product_name)}）</span></button></td></tr>'
        f'<tr class="nu-odetail-row" id="{did}" data-nu-detail-of="{esc(v.id)}" hidden>'
        f'<td colspan="11">{_detail(v, pd_ids)}</td></tr>'
    )


def _card(v: opp.OpportunityView, idx: int, pd_ids: set | None = None) -> str:
    did = f"nu-oc-{idx}"
    return (
        f'<li class="nu-ocard"{_attrs(v, idx)}>'
        f'<div class="nu-ocard__head"><div><h3 class="nu-ocard__title">{esc(v.product_name)}</h3>'
        f'<span class="nu-ocard__time">{_time(v.last_verified_at)}</span></div>{_stock(v)}</div>'
        '<dl class="nu-ocard__route">'
        f'<div><dt>買う</dt><dd><span class="nu-ocard__shop">{esc(v.buy_source)}</span>'
        f'<span class="nu-ocard__price">{_yen(v.buy_price)}</span>'
        f'<span class="nu-osub">{esc(v.buy_price_label)}</span></dd></div>'
        f'<div><dt>売る</dt><dd><span class="nu-ocard__shop">{esc(v.sell_source)}</span>'
        f'<span class="nu-ocard__price">{_yen(v.sell_price)}</span>'
        f'<span class="nu-osub">{esc(_sell_note(v))}</span></dd></div></dl>'
        '<div class="nu-ocard__result">'
        f'<div><span class="nu-ocard__lbl">想定純利益（費用差引後）</span><span class="nu-profit nu-ocard__profit">+{_yen(v.net_profit)}</span></div>'
        f'<div><span class="nu-ocard__lbl">ROI</span><span class="nu-roi nu-ocard__roi">{esc(_roi(v))}</span></div>'
        f'<button type="button" class="nu-rowbtn nu-ocard__btn" aria-expanded="false" aria-controls="{did}" data-nu-toggle>'
        f'詳細<span class="nu-sr">（{esc(v.product_name)}）</span></button></div>'
        f'<div class="nu-odetail" id="{did}" hidden>{_detail(v, pd_ids)}</div></li>'
    )


def _toolbar(n: int) -> str:
    hide = " hidden" if not n else ""
    sorts = "".join(f'<a class="nu-seg" href="{esc(page_href("opportunities"))}&amp;sort={k}" data-nu-oparam="sort"'
                    f' data-nu-ovalue="{k}">{esc(lbl)}</a>' for k, lbl in SORTS)
    live = "".join(f'<a class="nu-chip nu-chip--sm" href="{esc(page_href("opportunities"))}&amp;filter={k}"'
                   f' data-nu-oparam="filter" data-nu-ovalue="{k}">{esc(lbl)}</a>' for k, lbl in FILTERS_LIVE)
    soon = (f'<span class="nu-chip nu-chip--sm nu-chip--soon" aria-disabled="true">{esc("・".join(FILTERS_SOON))}'
            '<span class="nu-quick__tag">準備中</span></span>')
    return (
        f'<div class="nu-otools" data-nu-opp-hide-empty{hide}>'
        f'<div class="nu-otools__row"><span class="nu-otools__lbl" id="nu-osort-lbl">並び替え</span>'
        f'<nav class="nu-segs" aria-labelledby="nu-osort-lbl">{sorts}</nav></div>'
        f'<div class="nu-otools__row"><span class="nu-otools__lbl" id="nu-ofilter-lbl">絞り込み</span>'
        f'<div class="nu-ofilters" role="group" aria-labelledby="nu-ofilter-lbl">{live}{soon}</div>'
        '<button type="button" class="nu-chip nu-chip--sm" aria-expanded="false" aria-controls="nu-osearch"'
        f' data-nu-search-toggle>{icon("search", size=16)}商品を絞り込む</button></div>'
        '<form class="nu-osearch" id="nu-osearch" role="search" hidden data-nu-search-form>'
        '<label class="nu-filter__search nu-filter__search--live">'
        f'{icon("search", size=16)}<span class="nu-sr">商品名・型番で絞り込む</span>'
        '<input type="search" name="q" placeholder="商品名・型番（選んだジャンルの中）" autocomplete="off"'
        ' data-nu-search-input></label></form>'
        f'<p class="nu-oresult" aria-live="polite"><span data-nu-oresult>{n}件</span></p>'
        '</div>'
    )


def render(catalog, *, has_data: bool = True) -> str:
    """利益商品のページ（現在地・ジャンル切り替えは pages.py の共通部品を使う）。"""
    from src.content.ui import pages
    views = [it.view for it in catalog.items["opportunities"] if it.view is not None]
    n = len(views)
    ids = getattr(catalog, "product_ids", None) or set()
    rows = "".join(_row(v, i, ids) for i, v in enumerate(views))
    cards = "".join(_card(v, i, ids) for i, v in enumerate(views))
    if has_data:
        msg, hint = "現在、条件を満たす利益商品はありません", "価格・在庫・売却条件を確認できた商品だけを表示します。"
        kind = "NO_ACTIVE"
    else:
        msg, hint, kind = "まだ情報がありません", "最初の取得が終わると、ここに表示されます。", "NO_DATA"
    empty = (f'<div class="nu-empty" data-nu-oempty="none" data-empty="{kind}" role="status"{" hidden" if n else ""}>'
             f'<p class="nu-empty__msg">{esc(msg)}</p><p class="nu-empty__hint">{esc(hint)}</p>'
             f'<a class="nu-btn nu-btn--secondary nu-empty__cta" href="{esc(page_href("home"))}#nu-genres">別のジャンルを見る</a></div>'
             '<div class="nu-empty" data-nu-oempty="nomatch" role="status" hidden>'
             '<p class="nu-empty__msg">条件に合う商品はありません</p>'
             '<p class="nu-empty__hint">絞り込みや検索の条件を変えてください。</p>'
             f'<a class="nu-btn nu-btn--secondary nu-empty__cta" href="{esc(page_href("opportunities"))}" data-nu-keepcat>'
             '絞り込みを解除</a></div>')
    head = ('<tr><th scope="col">商品</th><th scope="col" class="nu-ocol-cat">ジャンル</th><th scope="col">買う場所</th>'
            '<th scope="col" class="nu-num">仕入価格</th><th scope="col">売る場所</th>'
            '<th scope="col" class="nu-num">売却価格</th><th scope="col" class="nu-num">想定純利益</th>'
            '<th scope="col" class="nu-num">ROI</th><th scope="col">在庫・状態</th><th scope="col">情報確認</th>'
            '<th scope="col"><span class="nu-sr">詳細</span></th></tr>')
    info = pages.PURPOSE_INFO["opportunities"]
    hide = " hidden" if not n else ""
    return (
        '<section class="nu-page" data-nu-page="opportunities" aria-labelledby="nu-opportunities-title" hidden>'
        f'{pages._crumbs("opportunities")}'
        f'<div class="nu-pagehead"><span class="nu-pagehead__icon">{icon(info["icon"], size=22)}</span>'
        f'<div><h1 id="nu-opportunities-title" class="nu-page__title">{esc(info["label"])}</h1>'
        f'<p class="nu-lead">{esc(info["desc"])}</p></div></div>'
        f'{pages._related("opportunities")}'
        f'{pages._cat_switch("opportunities")}'
        f'{_toolbar(n)}'
        '<p class="nu-topnote" data-nu-topnote hidden>利益が高い順に上位10件を表示しています'
        f'<a href="{esc(page_href("opportunities"))}" data-nu-keepcat>すべて表示</a></p>'
        '<h2 class="nu-sr">利益商品の一覧</h2>'
        f'<div class="nu-otable-wrap" data-nu-opp-hide-empty{hide}><table class="nu-otable" data-nu-opp-table>'
        '<caption class="nu-sr">利益商品の比較（買う場所・売る場所・想定純利益・ROI）</caption>'
        f'<thead>{head}</thead><tbody>{rows}</tbody></table></div>'
        f'<ul class="nu-ocards" data-nu-opp-cards data-nu-opp-hide-empty role="list"{hide}>{cards}</ul>'
        f'{empty}'
        '<nav class="nu-pager" aria-label="ページ" data-nu-pager hidden></nav>'
        f'<p class="nu-rule">{esc(pages.RULES["opportunities"])}</p>'
        '</section>'
    )
