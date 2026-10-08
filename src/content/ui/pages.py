"""新UIの画面（UI Phase 1: ジャンル起点の HOME と、目的別のページの枠）。

HOME はジャンル → 目的 → 補助リンクの順だけで作り、長いページにしない。
目的のページ（利益商品・抽選・予約・在庫再開・せどりルート）は、現在地・ジャンルの切り替え・
絞り込みの枠・一覧（実データ）・空状態を持つ。並べ替え・キーワード検索は Phase 2 以降（準備中と明記）。

件数・一覧は catalog.py の定義だけを使う。ジャンル（category）は URL に持ち、ページを移っても保つ。
"""

from __future__ import annotations

from src.content.ui import catalog as cl
from src.content.ui import categories as cats
from src.content.ui import components as c
from src.content.ui import lottery_card
from src.content.ui.components import esc
from src.content.ui.icons import icon
from src.content.ui.navigation import page_href

# 目的（HOME の入口・ページの見出し）
PURPOSE_INFO: dict[str, dict[str, str]] = {
    "opportunities": {"label": "利益商品", "icon": "trend",
                      "desc": "仕入れ値と費用を引いても、売却で利益が出る商品（買取価格・成約中央値で確認できたものだけ）"},
    "lottery": {"label": "抽選・予約", "icon": "ticket",
                "desc": "今応募できる抽選・今日の締切・これからの予約や発売（公式情報で日程を確認できたものだけ）"},
    "restock": {"label": "在庫再開", "icon": "package",
                "desc": "今買える商品（在庫を確認できたものだけ）と、在庫が戻った履歴"},
    "routes": {"label": "せどりルート", "icon": "route",
               "desc": "どこで買い、どこで売れば利益が残るか（成約価格か買取価格で売値を確認できたルートだけ）"},
}

# 空状態（一般向けの言葉だけ。技術的な理由は出さない）
EMPTY: dict[str, tuple[str, str]] = {
    "opportunities": ("条件を満たす利益商品は、今はありません",
                      "定価と買取価格を確認できた商品だけを掲載しています。毎日 12:00 に更新します。"),
    "lottery": ("現在、このジャンルで受付中・予定中の抽選や予約はありません",
                "新しい抽選の情報や予約・発売の情報が入りしだい表示します。"),
    "restock": ("在庫再開の情報は、今はありません",
                "再入荷・販売開始の情報が入りしだい表示します。"),
    "routes": ("成約価格を確認できる利益ルートは、今はありません",
               "データ準備中です。売れた価格（成約価格）を確認できしだい表示します。"),
}

# ページの下に出す、掲載の決まり（誤解を防ぐための1行）
RULES: dict[str, str] = {
    "opportunities": ("定価の確認日が分からない商品・出品価格や種別不明の価格・14日より古い価格で計算した利益は"
                      "掲載していません。純利益は送料・手数料などの必要な費用を差し引いた見込みです。"),
    "lottery": ("受付期間・締切は閲覧時の時刻で判定し、締切を過ぎたら応募ボタンを消します。"
                "日程・価格は公式に発表されたものだけを載せています。応募の前に必ず公式ページでご確認ください。"),
    "restock": ("「購入可能」は在庫ありを確認してから一定時間（公式ストア 3時間・TCG の入荷情報 15分〜2時間）だけ表示し、"
                "過ぎたら「在庫未確認（更新待ち）」にします。再開の時刻と最終確認の時刻は別です。購入の前に必ず販売ページでご確認ください。"),
    "routes": ("売値には買取価格か、確認できた成約価格（件数3件以上・集計期間あり）だけを使います。出品価格では計算しません。"
               "仕入れ・売却の商品と状態が一致し、送料・手数料がすべて分かるルートだけを確定として表示します。"),
}

# 今の並び順（変更は Phase 2 以降）
SORT_LABEL: dict[str, str] = {
    "opportunities": "利益が大きい順", "lottery": "締切間近 → 受付中 → まもなく開始",
    "restock": "取得した順", "routes": "利益が大きい順",
}

# 似た目的への1行（利益商品とせどりルートの違いを示す）
RELATED: dict[str, tuple[str, str]] = {
    "opportunities": ("店・フリマで仕入れるルートだけを見るなら", "routes"),
    "routes": ("定価で買える場合は", "opportunities"),
}

DISCLAIMER = "掲載情報は取得時点の参考です。購入・応募の前に必ず公式サイトでご確認ください。"


def _count_text(n: int) -> str:
    return f"{n}件"


# ── HOME ──────────────────────────────────────────────────────────

def _category_card(cat: cats.Category, n: int) -> str:
    return (f'<li><a class="nu-cat" href="{esc(page_href("home", category=cat.key))}" data-nu-cat-link="{cat.key}"'
            f' aria-label="{esc(cat.label)} {n}件">'
            f'<span class="nu-cat__icon">{icon(cat.icon, size=22)}</span>'
            f'<span class="nu-cat__label">{esc(cat.label)}</span>'
            f'<span class="nu-cat__count" data-nu-catcount="{cat.key}">{_count_text(n)}</span></a></li>')


def _purpose_card(purpose: str, n: int) -> str:
    info = PURPOSE_INFO[purpose]
    return (f'<li><a class="nu-purpose" href="{esc(page_href(purpose))}" data-nu-keepcat'
            f' data-nu-purpose-link="{purpose}">'
            f'<span class="nu-purpose__icon">{icon(info["icon"], size=22)}</span>'
            f'<span class="nu-purpose__body"><span class="nu-purpose__label">{esc(info["label"])}</span>'
            f'<span class="nu-purpose__desc">{esc(info["desc"])}</span></span>'
            f'<span class="nu-purpose__count" data-nu-count="{purpose}">{_count_text(n)}</span>'
            f'<span class="nu-purpose__chev">{icon("chevron", size=18)}</span></a></li>')


def _quick_links() -> str:
    # 「今すぐ狙う TOP10」は利益商品を利益が大きい順に上位10件だけ出す（top=10）
    live = (f'<a class="nu-quick" href="{esc(page_href("opportunities") + "&top=10")}" data-nu-keepcat>'
            f'{icon("target", size=16)}今すぐ狙う TOP10</a>')
    soon = "".join(
        f'<span class="nu-quick nu-quick--soon" aria-disabled="true">{icon(ic, size=16)}{esc(lbl)}'
        f'<span class="nu-quick__tag">準備中</span></span>'
        for ic, lbl in (("flame", "買取急騰"), ("sparkle", "新着商品")))
    return f'<div class="nu-quicks" aria-label="よく使うリンク">{live}{soon}</div>'


def render_home(catalog: cl.Catalog, *, source_issue: bool = False) -> str:
    """HOME（ジャンル → 目的 → 補助リンクの順だけ）。"""
    cat_cards = "".join(_category_card(cat, catalog.category_total(cat.key)) for cat in cats.CATEGORIES)
    purpose_cards = "".join(_purpose_card(p, catalog.count(p)) for p in cl.PURPOSES)
    issue = (c.notice("一部の情報源を取得できていません。必ず公式サイトでもご確認ください。")
             if source_issue else "")
    return (
        '<section class="nu-page nu-home" data-nu-page="home" aria-labelledby="nu-home-title">'
        '<h1 id="nu-home-title" class="nu-home__title">利益が出る商品と抽選を、ジャンルから探す</h1>'
        '<p class="nu-lead nu-lead--home">定価・買取価格・抽選・在庫を毎日チェックしています（毎日 12:00 更新）。</p>'
        f'{issue}'
        '<h2 class="nu-h2" id="nu-genres">ジャンルから探す</h2>'
        f'<ul class="nu-cats" role="list">{cat_cards}</ul>'
        '<div class="nu-h2row"><h2 class="nu-h2">目的から探す</h2>'
        '<p class="nu-ctx" data-nu-home-ctx hidden><span data-nu-catlabel></span>で絞り込み中'
        f'<a class="nu-ctx__clear" href="{esc(page_href("home"))}">すべてのジャンル</a></p></div>'
        f'<ul class="nu-purposes" role="list">{purpose_cards}</ul>'
        f'{_actionable_line(catalog)}'
        f'{_quick_links()}'
        '</section>'
    )


def _actionable_line(catalog: cl.Catalog) -> str:
    """今すぐ行動できる利益商品の件数（Phase 18。判定は src/market/actionability。利益があるだけでは数えない）。

    ページは1日1回作るので、件数は各商品の「行動できると言える期限」（生成時に決めた値）のうち、閲覧時より後の
    ものだけをブラウザで数える（期限の過ぎた在庫ありを数えない。判定はし直さない）。
    """
    os_ = getattr(catalog, "opportunity_set", None)
    acts = [v.action for v in (getattr(os_, "eligible", None) or []) if getattr(v, "actionable", False)]
    untils = ",".join(str(int(a.until_ms)) for a in acts if a.until_ms)
    n = sum(1 for a in acts if a.until_ms)
    return ('<p class="nu-ctx nu-home-act">今すぐ行動できる利益商品（購入可能・抽選受付中・予約受付中の確認がそろうもの）: '
            f'<b data-nu-act-untils="{esc(untils)}">{n}件</b>'
            # ページは生成時に判定する（閲覧時は期限を過ぎたものを除くだけ。新しく行動できるようになったものは次の生成まで出ない）
            '<span class="nu-osub">（ページの生成時の判定。期限を過ぎたものは閲覧時に除く）</span></p>')


# ── 目的のページ ────────────────────────────────────────────────────

def _crumbs(purpose: str) -> str:
    return ('<nav class="nu-crumbs" aria-label="現在地"><ol>'
            f'<li><a href="{esc(page_href("home"))}">HOME</a></li>'
            f'<li data-nu-crumb-cat hidden><a href="{esc(page_href("home"))}" data-nu-crumb-catlink>'
            '<span data-nu-catlabel></span></a></li>'
            f'<li><span aria-current="page">{esc(PURPOSE_INFO[purpose]["label"])}</span></li></ol></nav>')


def _cat_switch(purpose: str) -> str:
    chips = [f'<a class="nu-chip" href="{esc(page_href(purpose))}" data-nu-switch="{cats.ALL}">すべて</a>']
    chips += [f'<a class="nu-chip" href="{esc(page_href(purpose, category=cat.key))}" data-nu-switch="{cat.key}">'
              f'{esc(cat.label)}</a>' for cat in cats.CATEGORIES]
    return f'<nav class="nu-chips" aria-label="ジャンルで絞り込む">{"".join(chips)}</nav>'


def _filter_bar(purpose: str, n: int) -> str:
    """絞り込みの枠。キーワード検索は Phase 2 以降（押せないことを明記する）。並び順は今の並びを文字で示す。"""
    return (
        '<div class="nu-filter">'
        f'<label class="nu-filter__search">{icon("search", size=16)}'
        f'<span class="nu-sr">キーワードで絞り込む（準備中）</span>'
        '<input type="search" placeholder="キーワードで絞り込む（準備中）" disabled aria-disabled="true"></label>'
        f'<span class="nu-filter__sort">並び: {esc(SORT_LABEL[purpose])}</span>'
        f'<span class="nu-filter__count"><span data-nu-count="{purpose}">{_count_text(n)}</span></span>'
        '</div>'
    )


def _items_html(purpose: str, catalog: cl.Catalog, model) -> str:
    if purpose == "lottery":
        rows = []
        for kind, _bucket, _sort, idx, vm in model.ordered_cards():
            if kind != "lot" or vm["id"] not in catalog.lottery_cats:
                continue
            st = model.states[vm["id"]]
            hide = not catalog.lottery_active.get(vm["id"])
            rows.append(f'<li data-nu-item data-nu-cat="{esc(catalog.lottery_cats[vm["id"]])}"'
                        f'{" hidden" if hide else ""}>{lottery_card.render(vm, st, idx)}</li>')
        return "".join(rows)
    items = sorted(catalog.items[purpose], key=lambda it: it.sort_key)
    return "".join(f'<li data-nu-item data-nu-cat="{esc(it.category)}">{it.card.render()}</li>'
                   for it in items)


def _related(purpose: str) -> str:
    if purpose not in RELATED:
        return ""
    lead, target = RELATED[purpose]
    return (f'<p class="nu-related">{esc(lead)} '
            f'<a href="{esc(page_href(target))}" data-nu-keepcat>{esc(PURPOSE_INFO[target]["label"])}を見る</a></p>')


def render_purpose(purpose: str, catalog: cl.Catalog, model, *, has_data: bool = True) -> str:
    """目的のページ。has_data=False（最初の取得前など、情報そのものが無い）なら NO_DATA の空状態。"""
    info = PURPOSE_INFO[purpose]
    n = catalog.count(purpose)
    if has_data:
        kind, (msg, hint) = "NO_ACTIVE", EMPTY[purpose]
    else:
        kind, msg, hint = "NO_DATA", "まだ情報がありません", "最初の取得が終わると、ここに表示されます。"
    empty = c.empty_state(kind, msg, hint).replace(
        "<div ", f'<div data-nu-empty-for="{purpose}"{" hidden" if n else ""} ', 1)
    return (
        f'<section class="nu-page" data-nu-page="{purpose}" aria-labelledby="nu-{purpose}-title" hidden>'
        f'{_crumbs(purpose)}'
        f'<div class="nu-pagehead"><span class="nu-pagehead__icon">{icon(info["icon"], size=22)}</span>'
        f'<div><h1 id="nu-{purpose}-title" class="nu-page__title">{esc(info["label"])}</h1>'
        f'<p class="nu-lead">{esc(info["desc"])}</p></div></div>'
        f'{_related(purpose)}'
        f'{_cat_switch(purpose)}'
        f'{_filter_bar(purpose, n)}'
        + (f'<p class="nu-topnote" data-nu-topnote hidden>利益が大きい順に上位10件を表示しています'
           '（在庫切れ・抽選などを除く。在庫は7日以内の確認。購入・申込ができるかは各商品の「今すぐ行動」）'
           f'<a href="{esc(page_href(purpose))}" data-nu-keepcat>すべて表示</a></p>' if purpose == "opportunities" else "")
        + f'<h2 class="nu-sr">{esc(info["label"])}の一覧</h2>'
        f'<ul class="nu-list" data-nu-list="{purpose}" role="list">{_items_html(purpose, catalog, model)}</ul>'
        f'{empty}'
        f'<p class="nu-rule">{esc(RULES[purpose])}</p>'
        '</section>'
    )


# ── その他・検索 ────────────────────────────────────────────────────

def render_more(catalog: cl.Catalog) -> str:
    rows = [
        (page_href("routes"), "route", "せどりルート", PURPOSE_INFO["routes"]["desc"],
         f'<span class="nu-purpose__count" data-nu-count="routes">{_count_text(catalog.count("routes"))}</span>', True),
        (page_href("home") + "#nu-genres", "box", "ジャンルから探す", "スマホ・TCG・カメラ・ゲーム・PC・その他", "", False),
        (page_href("mypage"), "star", "マイページ", "ウォッチ中の商品・締切・通知の条件（このブラウザに保存）", "", False),
        (page_href("search"), "search", "商品を検索", "商品名・型番・ジャンルで探す", "", False),
        (page_href("admin"), "more", "運営の管理画面", "取得状況・データ品質・AI 候補・資金配分・実行履歴（読むだけ）", "", False),
    ]
    links = "".join(
        f'<li><a class="nu-purpose" href="{esc(href)}"{" data-nu-keepcat" if keep else ""}>'
        f'<span class="nu-purpose__icon">{icon(ic, size=22)}</span>'
        f'<span class="nu-purpose__body"><span class="nu-purpose__label">{esc(label)}</span>'
        f'<span class="nu-purpose__desc">{esc(desc)}</span></span>{count}'
        f'<span class="nu-purpose__chev">{icon("chevron", size=18)}</span></a></li>'
        for href, ic, label, desc, count, keep in rows)
    return (
        '<section class="nu-page" data-nu-page="more" aria-labelledby="nu-more-title" hidden>'
        '<h1 id="nu-more-title" class="nu-page__title">メニュー</h1>'
        f'<ul class="nu-purposes nu-purposes--list" role="list">{links}</ul>'
        '</section>'
    )


# ご確認ください（旧UIの注意書き _section_caution から移した。全ページ共通のフッターに1回だけ出す）
CAUTIONS = (
    "本ページは価格差の監視結果であり、購入を推奨するものではありません。",
    "利益を保証するものではありません。条件が合えば利益が出る可能性がある情報です。",
    "価格・在庫・買取条件は常に変動します。掲載価格は取得・入力時点の参考値です。",
    "買取条件（新品未開封・SIMフリー等）を満たさない場合、買取価格が大幅に下がります。",
    "海外販売には輸出規制・関税・送料・プラットフォーム手数料等が発生します。",
)


def render_footer(brand: str, cta_links: list | None = None) -> str:
    """全ページ共通のフッター（注意書きはここに1回だけ）。外部リンク（note・LINE など）は設定に URL があるときだけ。"""
    from src.content.ui.components import safe_href
    cta = "".join(f'<a href="{esc(safe_href(url))}" target="_blank" rel="noopener noreferrer" data-track="{esc(track)}">'
                  f'{esc(label)}<span class="nu-sr">（外部サイト）</span></a>'
                  for label, url, track in (cta_links or []) if safe_href(url).startswith("https://"))
    cautions = "".join(f"<li>{esc(t)}</li>" for t in CAUTIONS)
    return ('<footer class="nu-footer"><div class="nu-footer__inner">'
            f'<span class="nu-footer__brand">{esc(brand)} Premium Monitor</span>'
            '<a href="beta/">はじめかた</a>' + cta
            + f'<p class="nu-footer__note">{esc(DISCLAIMER)}</p>'
            f'<ul class="nu-footer__cautions">{cautions}</ul></div></footer>')


def render_search(details: dict | None = None) -> str:
    """商品を検索（商品名・型番・ジャンルで絞り込む商品の一覧。各商品から商品詳細へ）。

    絞り込みはブラウザ側（shell の router の renderSearch）が URL の q（キーワード）と category（ジャンル）で行う。
    """
    from src.content.ui import product_page
    chips = (f'<a class="nu-chip" href="{esc(page_href("search"))}" data-nu-switch="all">すべて</a>'
             + "".join(f'<a class="nu-chip" href="{esc(page_href("search", category=cat.key))}"'
                       f' data-nu-switch="{esc(cat.key)}">{esc(cat.label)}</a>' for cat in cats.CATEGORIES))
    items = []
    for v in (details or {}).values():
        # 商品名・型番・ブランド・ジャンル・容量に加えて、商品に登録済みの検索用キーワード（PS5 Pro・CFI-7000 など）も
        # 検索の対象にする（「PS5」で PlayStation 5 Pro が見つからなかった。Phase 14。別名をここで新しく作らない）
        search = " ".join(x for x in (v.product_name, v.model, getattr(v, "jan", ""), v.brand, v.category_label,
                                      v.capacity, *getattr(v, "keywords", ())) if x).lower()
        items.append(
            f'<li class="nu-srow" data-nu-srow data-nu-cat="{esc(v.category)}" data-search="{esc(search)}">'
            f'<span class="nu-srow__main"><span class="nu-srow__name">{esc(v.product_name)}</span>'
            f'<span class="nu-osub">{esc(" ・ ".join(x for x in (v.model, v.category_label) if x))}</span></span>'
            f'<span class="nu-srow__acts">{product_page.link(v.product_id)}'
            f'{product_page.watch_button(v.product_id, v.product_name)}</span></li>')
    return (
        '<section class="nu-page" data-nu-page="search" aria-labelledby="nu-search-title" hidden>'
        '<h1 id="nu-search-title" class="nu-page__title">商品を検索</h1>'
        '<form class="nu-osearch" role="search" data-nu-search-form>'
        f'<label class="nu-filter__search nu-filter__search--wide nu-filter__search--live">{icon("search", size=16)}'
        '<span class="nu-sr">商品名・型番で探す</span>'
        '<input type="search" name="q" placeholder="商品名・型番（例: PS5 Pro）" autocomplete="off"'
        ' data-nu-search-input data-nu-search-page="search"></label></form>'
        f'<nav class="nu-chips" aria-label="ジャンルで絞り込む">{chips}</nav>'
        f'<p class="nu-oresult" aria-live="polite"><span data-nu-sresult>{len(items)}件</span></p>'
        f'<ul class="nu-slist" data-nu-slist>{"".join(items)}</ul>'
        '<p class="nu-lead" data-nu-sempty hidden>条件に一致する商品がありません。ジャンルや検索語を変更してください。</p>'
        '</section>'
    )
