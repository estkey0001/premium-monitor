"""新UIの「抽選・予約」ページ（UI Phase 3）。

1件を1つの要素（article.nu-lrow）で描画し、CSS で PC では比較しやすい行、モバイルではカードにする
（同じ件を2回描画しない。runtime の updateCard が状態・残り時間・ボタンを書き換えるため）。
状態・残り時間・ボタンは runtime（derive_runtime_state / lottery_runtime.js）の結果だけを使い、
ここでは生成時点の値を入れておくだけ。絞り込み・並べ替え・検索・ページ切り替えは shell の router（renderLot）が
data-* 属性で行い、状態は URL（st / sort / q / page_num）に持つ。
"""

from __future__ import annotations

from src.content.ui import runtime as rt
from src.content.ui.components import esc
from src.content.ui.icons import icon
from src.content.ui.lottery_card import cta_html
from src.content.ui.lottery_view import REQUIREMENTS_UNKNOWN, LotteryReservationView
from src.content.ui.navigation import page_href

PAGE_SIZE = 20
# 状態の絞り込み（「当選・購入」は補助）
STATUS_TABS = (("", "すべての状態"), ("open", "抽選受付中"), ("today", "今日締切"), ("wait", "予約・発売待ち"),
               ("result", "当選・購入期限"))
SORTS = (("rec", "おすすめ"), ("deadline", "締切が近い"), ("start", "開始が近い"), ("updated", "更新が新しい"),
         ("profit", "想定利益が高い"))


def _yen(v) -> str:
    return f"¥{int(v):,}" if v is not None else ""


def _ms(iso: str, *, end: bool = False) -> str:
    """ISO 日時・日付 → ミリ秒（並べ替え用）。無ければ空。

    日付だけ（時刻未公表）は、開始は JST の 0 時、締切は翌日の 0 時（runtime の「過ぎたと言える時刻」と同じ。
    今日が締切の日付だけの抽選を、当日の 0 時を過ぎても「締切が近い」の先頭に並べるため）。
    """
    if not iso:
        return ""
    from datetime import timedelta
    from src.tcg.models import parse_dt
    d = parse_dt(iso if "T" in iso else iso + "T00:00:00+09:00")
    if d and end and "T" not in iso:
        d = d + timedelta(days=1)
    return str(int(d.timestamp() * 1000)) if d else ""


def _when_abs(iso: str) -> str:
    if not iso:
        return ""
    return rt._fmt_exact(iso) if "T" in iso else f"{rt._fmt_day(iso)}（時刻未公表）"


def _period(a: str, b: str) -> str:
    x, y = _when_abs(a), _when_abs(b)
    return f"{x} 〜 {y}" if x and y else (x or y)


def _time(iso: str) -> str:
    """情報を確認した日時（閲覧時に「3分前確認」などに書き換える）。生成時刻は使わない。"""
    if not iso:
        return '<span class="nu-time">確認日時なし</span>'
    from src.tcg.models import parse_dt
    d = parse_dt(iso.replace(" ", "T", 1))
    if not d:
        return '<span class="nu-time">確認日時なし</span>'
    return (f'<time class="nu-time" datetime="{esc(d.isoformat())}" data-nu-time="{esc(d.isoformat())}">'
            f'{d.strftime("%m/%d %H:%M")}確認</time>')


def _chips(v: LotteryReservationView) -> str:
    out = [f'<span class="nu-lchip">{esc(v.kind_label)}</span>']
    if v.variant:
        out.append(f'<span class="nu-lchip">{esc(v.variant)}</span>')
    # 応募条件の要約（支払い・地域を除く短い条件を2つまで。全部は詳細で）
    for r in [r for r in v.requirements if not r.startswith(("支払い", "地域")) and r != REQUIREMENTS_UNKNOWN][:2]:
        out.append(f'<span class="nu-lchip">{esc(r)}</span>')
    if v.source_conflict:
        out.append('<span class="nu-lchip nu-lchip--warn">⚠️ 日程要確認</span>')
    elif not v.human_confirmed:
        # 人による確認がまだの情報（応募ボタンは出さない）
        out.append(f'<span class="nu-lchip nu-lchip--warn">⚠️ {esc(v.confidence or "確認待ち")}</span>')
    return "".join(out)


def _price(v: LotteryReservationView) -> str:
    if v.retail_price is not None:
        return (f'<span class="nu-lrow__lbl">{esc(v.retail_price_label)}</span>'
                f'<span class="nu-lrow__val">{_yen(v.retail_price)}</span>')
    return (f'<span class="nu-lrow__lbl">販売価格</span>'
            f'<span class="nu-lrow__val nu-lrow__val--muted">{esc(v.retail_price_label)}</span>')


def _profit(v: LotteryReservationView) -> str:
    if v.estimated_profit is not None:
        val = f'<span class="nu-lrow__val nu-profit">+{_yen(v.estimated_profit)}</span>'
    else:
        val = '<span class="nu-lrow__val nu-lrow__val--muted">算出前</span>'
    ref = (f'<span class="nu-lrow__ref">{esc(v.market_reference_type)} {_yen(v.market_reference_price)}</span>'
           if v.market_reference_price is not None and v.market_reference_type
           else '<span class="nu-lrow__ref">市場参考 未取得</span>')
    return f'<span class="nu-lrow__lbl">想定利益</span>{val}{ref}'


def _details(v: LotteryReservationView, cta_kind: str = "", pd_ids: set | None = None) -> str:
    rows: list[tuple[str, str]] = []
    if v.source_conflict:
        # 公式情報どうしで日程が食い違うときは、どちらかの日程を確定値のように出さない
        rows.append(("日程", "公式ページで確認（公式情報どうしで食い違っています）"))
    elif v.kind == rt.KIND_RELEASE:
        rows.append(("発売日", _when_abs(v.release_at) or "未発表"))
    else:
        rows.append(("応募期間" if v.kind == rt.KIND_LOTTERY else "予約期間",
                     _period(v.application_start, v.application_end) or "公式ページで確認"))
        if v.kind == rt.KIND_LOTTERY:
            rows.append(("当選発表", _when_abs(v.winner_announcement_at) or "未発表（公式ページで確認）"))
            # 当選後の購入期限は、応募の締切とは別に出す
            rows.append(("当選者の購入期間", _period(v.purchase_start, v.purchase_end) or "未発表（公式ページで確認）"))
    if v.kind != rt.KIND_RELEASE:
        reqs = v.requirements or [REQUIREMENTS_UNKNOWN]
        rows.append(("応募条件" if v.kind == rt.KIND_LOTTERY else "予約の条件", "・".join(reqs)))
    if v.eligibility:
        text = v.eligibility if len(v.eligibility) <= 240 else v.eligibility[:240] + "…"
        rows.append(("条件の詳細（公式の告知より）", text))
    # 地域は国内（JP）なら出さない（内部のコードを見せない）
    region = "" if v.region in ("", "JP") else v.region
    if v.store or region:
        rows.append(("販売店・地域", " / ".join(x for x in (v.store, region) if x)))
    rows.append(("情報の確かさ", v.confidence or "公式情報"))
    if v.source_conflict:
        rows.append(("ご注意", "公式情報どうしで日程が食い違っています。応募前に公式ページで日程をご確認ください。"))
    elif not v.human_confirmed:
        rows.append(("ご注意", "告知の転記を人が確認するまで、応募ボタンは出していません。公式ページでご確認ください。"))
    body = "".join(f"<dt>{esc(k)}</dt><dd>{esc(val)}</dd>" for k, val in rows if val)
    link = ""
    # ボタンが「公式情報を見る」（同じ URL）になるものは、詳細に同じリンクを重ねない
    if v.source_url and cta_kind not in ("", "info") and v.source_url != v.official_url:
        link = (f'<a class="nu-btn nu-btn--secondary nu-lrow__src" href="{esc(v.source_url)}" target="_blank"'
                f' rel="noopener nofollow" data-track="lottery_info_click">情報元を開く</a>')
    if pd_ids and v.product_id in pd_ids:
        from src.content.ui import product_page
        link += product_page.link(v.product_id)
    return (f'<details class="nu-ldetail" data-track="lottery_detail_open"><summary>詳細'
            f'<span class="nu-sr">（{esc(v.product_name)}）</span></summary>'
            f'<dl class="nu-ldetail__dl">{body}</dl>{link}</details>')


def _sub_line(v: LotteryReservationView, status: str) -> str:
    """締切の下に添える1行（当選発表）。日程の食い違い・結果待ち以降（主の行に出ている）では出さない。"""
    if (v.source_conflict or v.kind != rt.KIND_LOTTERY or not v.winner_announcement_at
            or status in ("RESULT_PENDING", "WINNER_ANNOUNCED", "WINNER_PURCHASE_PERIOD")):
        return ""
    return f'<span class="nu-lrow__sub">当選発表 {esc(_when_abs(v.winner_announcement_at))}</span>'


def _row(v: LotteryReservationView, state: dict, idx: int, pd_ids: set | None = None) -> str:
    vm = v.vm
    search = " ".join(x for x in (v.product_name, v.retailer, v.store, v.variant) if x).lower()
    start = vm.get("as") or vm.get("asd") or (vm.get("rd") if v.kind == rt.KIND_RELEASE else "")
    end = vm.get("ae") or vm.get("aed") or ""
    if v.source_conflict:
        # 日程が食い違うものは、どちらかの日程で並べない（締切・開始の並べ替えでは末尾）
        start = end = ""
    from src.tcg.models import parse_dt
    upd = parse_dt(v.last_verified_at.replace(" ", "T", 1)) if v.last_verified_at else None
    shop = " ".join(x for x in (v.retailer, v.store) if x) or "販売店は公式ページで確認"
    return (
        f'<article class="nu-lrow" data-nu-lot="{esc(v.event_id)}" data-nu-bucket="{state["bucket"]}"'
        f' data-nu-sort="{state["sort"]}" data-nu-idx="{idx}" data-nu-status="{esc(state["status"])}"'
        f' data-nu-today="{"1" if state["ending_today"] else "0"}" data-nu-kind="{esc(v.kind)}"'
        f' data-nu-cat="{esc(v.category)}" data-ae="{_ms(end, end=True)}" data-as="{_ms(start)}"'
        f' data-nu-unv="{"1" if not v.human_confirmed else "0"}"'
        f' data-upd="{int(upd.timestamp() * 1000) if upd else 0}"'
        f' data-profit="{v.estimated_profit if v.estimated_profit is not None else ""}"'
        f' data-search="{esc(search)}" data-track="lottery_view"'
        f'{"" if state["bucket"] < rt.BUCKET_HIDDEN else " hidden"}>'
        f'<div class="nu-lrow__status"><span class="nu-badge nu-tone-{esc(state["tone"])}"'
        f' data-status="{esc(state["status"])}"><span aria-hidden="true">{esc(state["icon"])}</span>'
        f' {esc(state["label"])}</span><span class="nu-cd">{esc(state["cd_text"])}</span></div>'
        f'<div class="nu-lrow__main"><h3 class="nu-lrow__title">{esc(v.product_name)}</h3>'
        f'<p class="nu-lrow__shop">{esc(shop)}<span class="nu-lrow__cat"> ・ {esc(v.category_label)}</span></p>'
        f'<p class="nu-lrow__chips">{_chips(v)}</p></div>'
        f'<div class="nu-lrow__price">{_price(v)}</div>'
        f'<div class="nu-lrow__profit">{_profit(v)}</div>'
        f'<div class="nu-lrow__when"><span class="nu-when">{esc(state["when"])}</span>'
        f'{_sub_line(v, state["status"])}'
        f'<span class="nu-lrow__upd">{_time(v.last_verified_at)}</span></div>'
        f'<div class="nu-lrow__cta" data-nu-cta-slot>{cta_html(state["cta"])}</div>'
        f'{_details(v, (state.get("cta") or {}).get("kind", ""), pd_ids)}'
        '</article>'
    )


def _toolbar(n: int) -> str:
    base = page_href("lottery")
    tabs = "".join(f'<a class="nu-seg" href="{esc(base + (f"&st={k}" if k else ""))}" data-nu-lparam="st"'
                   f' data-nu-lvalue="{k}">{esc(lbl)}</a>' for k, lbl in STATUS_TABS)
    sorts = "".join(f'<a class="nu-seg" href="{esc(base)}&amp;sort={k}" data-nu-lparam="sort"'
                    f' data-nu-lvalue="{k}">{esc(lbl)}</a>' for k, lbl in SORTS)
    hide = "" if n else " hidden"
    return (
        f'<div class="nu-otools" data-nu-lot-hide-empty{hide}>'
        '<div class="nu-otools__row"><span class="nu-otools__lbl" id="nu-lst-lbl">状態</span>'
        f'<nav class="nu-segs" aria-labelledby="nu-lst-lbl">{tabs}</nav></div>'
        '<div class="nu-otools__row"><span class="nu-otools__lbl" id="nu-lsort-lbl">並び替え</span>'
        f'<nav class="nu-segs" aria-labelledby="nu-lsort-lbl">{sorts}</nav>'
        '<button type="button" class="nu-chip nu-chip--sm" aria-expanded="false" aria-controls="nu-lsearch"'
        f' data-nu-search-toggle>{icon("search", size=16)}商品・販売店で絞り込む</button></div>'
        '<form class="nu-osearch" id="nu-lsearch" role="search" hidden data-nu-search-form>'
        '<label class="nu-filter__search nu-filter__search--live">'
        f'{icon("search", size=16)}<span class="nu-sr">商品名・販売店・型番で絞り込む</span>'
        '<input type="search" name="q" placeholder="商品名・販売店・型番（選んだジャンルの中）" autocomplete="off"'
        ' data-nu-search-input></label></form>'
        f'<p class="nu-oresult" aria-live="polite"><span data-nu-lresult>{n}件</span></p>'
        '</div>'
    )


def render(catalog, model, *, has_data: bool = True) -> str:
    from src.content.ui import pages
    # 生成時点でも、閲覧時と同じ「今行動すべき順」（runtime の bucket → sort → 元の順）に並べておく
    idx_of = {vm["id"]: i for i, vm in enumerate(model.vms)}
    views = sorted((v for v in catalog.lottery_views if v.event_id in model.states),
                   key=lambda v: (model.states[v.event_id]["bucket"], model.states[v.event_id]["sort"],
                                  idx_of.get(v.event_id, 0)))
    ids = getattr(catalog, "product_ids", None) or set()
    rows = "".join(_row(v, model.states[v.event_id], idx_of.get(v.event_id, 0), ids) for v in views)
    n = catalog.count("lottery")
    if has_data:
        msg, hint = pages.EMPTY["lottery"]
        kind = "NO_ACTIVE"
    else:
        msg, hint, kind = "まだ情報がありません", "最初の取得が終わると、ここに表示されます。", "NO_DATA"
    empty = (f'<div class="nu-empty" data-nu-lempty="none" data-empty="{kind}" role="status"{"" if not n else " hidden"}>'
             f'<p class="nu-empty__msg">{esc(msg)}</p><p class="nu-empty__hint">{esc(hint)}</p>'
             f'<a class="nu-btn nu-btn--secondary nu-empty__cta" href="{esc(page_href("home"))}#nu-genres">別のジャンルを見る</a></div>'
             '<div class="nu-empty" data-nu-lempty="nomatch" role="status" hidden>'
             '<p class="nu-empty__msg">条件に合う抽選・予約はありません</p>'
             '<p class="nu-empty__hint">状態の絞り込みや検索の条件を変えてください。</p>'
             f'<a class="nu-btn nu-btn--secondary nu-empty__cta" href="{esc(page_href("lottery"))}" data-nu-keepcat>'
             '絞り込みを解除</a></div>')
    info = pages.PURPOSE_INFO["lottery"]
    return (
        '<section class="nu-page" data-nu-page="lottery" aria-labelledby="nu-lottery-title" hidden>'
        f'{pages._crumbs("lottery")}'
        f'<div class="nu-pagehead"><span class="nu-pagehead__icon">{icon(info["icon"], size=22)}</span>'
        f'<div><h1 id="nu-lottery-title" class="nu-page__title">{esc(info["label"])}</h1>'
        f'<p class="nu-lead">{esc(info["desc"])}</p></div></div>'
        f'{pages._cat_switch("lottery")}'
        f'{_toolbar(n)}'
        '<h2 class="nu-sr">抽選・予約の一覧</h2>'
        f'<div class="nu-lhead" aria-hidden="true" data-nu-lot-hide-empty{"" if n else " hidden"}><span>状態</span><span>商品・販売店</span>'
        '<span>販売価格</span><span>想定利益</span><span>締切・日程</span><span></span></div>'
        f'<div class="nu-llist" data-nu-lot-list>{rows}</div>'
        f'{empty}'
        '<nav class="nu-pager" aria-label="ページ" data-nu-lpager hidden></nav>'
        f'<p class="nu-rule">{esc(pages.RULES["lottery"])}</p>'
        '</section>'
    )
