"""新UIの「商品詳細」ページ（UI Phase 6）。

ProductDetailView（product_detail.py）の確定した値だけを描画する。利益・ROI・取得原価はここでも JS でも計算しない。
商品ごとに1つの article を作り、ブラウザ側（shell の router の renderProduct）が URL の product_id で1つだけ出す。
タブ（買う・売る / 価格履歴 / 最近の変化）は URL の tab に持つ。

表は PC では表、640px 未満では各行をカードとして並べる（横スクロールさせない）。
"""

from __future__ import annotations

from src.content.ui import components as c
from src.content.ui import product_detail as pd
from src.content.ui import runtime as rt
from src.content.ui.components import esc
from src.content.ui.lottery_card import cta_html
from src.content.ui.navigation import page_href
from src.market import price_history as ph
from src.market import price_types as pt
from src.tcg.models import JST, parse_dt

TABS = (("buy", "買う・売る"), ("history", "価格履歴"), ("changes", "最近の変化"))
STATUS_TONE = {"AVAILABLE": "success", "LOTTERY": "info", "OUT_OF_STOCK": "danger", "STOCK_UNKNOWN": "neutral",
               "MONITORING": "neutral", "SALE_METHOD": "info"}
QUALITY_TONE = {pd.VERIFIED: "success", pd.REFERENCE: "neutral", pd.STALE: "warning", pd.UNVERIFIED: "warning"}
KIND_DASH = {ph.KIND_RETAIL: "", ph.KIND_BUYBACK: "6 3", ph.KIND_LISTING: "2 3", ph.KIND_SOLD_MEDIAN: "10 3 2 3"}


def _yen(v) -> str:
    try:
        return f"¥{int(round(float(v))):,}"
    except (TypeError, ValueError):
        return "—"


def _time(iso: str, *, suffix: str = "確認") -> str:
    """確認時刻（閲覧時に「21分前確認（本日 13:32）」「更新遅延」などに書き換える）。生成時刻は使わない。"""
    if iso and len(str(iso)) == 10:                             # 日付だけの確認（定価の確認日など）。時刻を作らない
        return f'<span class="nu-time">{esc(str(iso)[5:].replace("-", "/"))}{suffix}（日付のみ）</span>'
    d = parse_dt(str(iso or "").replace(" ", "T", 1)) if iso else None
    if d is None:
        return '<span class="nu-time">確認日時なし</span>'
    return (f'<time class="nu-time" datetime="{esc(d.isoformat())}" data-nu-time="{esc(d.isoformat())}"'
            f' data-nu-time-both>{d.strftime("%m/%d %H:%M")}{suffix}</time>')


def _quality(row: pd.PriceRow) -> str:
    return (f'<span class="nu-badge nu-tone-{QUALITY_TONE.get(row.quality, "neutral")} nu-pd-q">'
            f'{esc(row.quality_label)}</span>')


def _cta(row: pd.PriceRow, *, label: str = "", primary: bool | None = None) -> str:
    if not row.cta_label or not c.safe_href(row.url).startswith("https://"):
        return ""
    attrs = ""
    if row.cta_primary and row.stock_until_ms:
        # 在庫ありと言える期限を過ぎたら、ブラウザで「販売ページを見る」（控えめなボタン）に落とす
        attrs = (f' data-nu-pd-until="{row.stock_until_ms}" data-nu-pd-stale-text="販売ページを見る"'
                 ' data-nu-pd-stale-class="nu-btn nu-btn--secondary nu-btn--sm"')
    kind = "primary" if (row.cta_primary if primary is None else primary) else "secondary"
    return (f'<a class="nu-btn nu-btn--{kind} nu-btn--sm" href="{esc(c.safe_href(row.url))}" target="_blank"'
            f' rel="noopener noreferrer" data-track="product_{row.role}_click"{attrs}>{esc(label or row.cta_label)}'
            '<span class="nu-sr">（外部サイト）</span></a>')


def _split(rows: list, keep) -> tuple[list, list]:
    """表に出す行（確認済みと、最安・最高の印の行）と、折りたたむ参考の行。確認済みが無ければ全部を表に出す。"""
    main = [r for r in rows if r.usable or r is keep]
    return (main, [r for r in rows if r not in main]) if main else (rows, [])


def _more(kind: str, n: int, table: str) -> str:
    return (f'<details class="nu-pd-morerows"><summary>参考の{esc(kind)}（{n}件・確認済みではない値）</summary>'
            f'{table}</details>')


def _buy_rows_html(rows: list, best) -> str:
    trs = []
    for r in rows:
        acq = _yen(r.acquisition) if r.acquisition is not None else "算出前"
        # 0円の費用は「無料」「なし」と書く（取得失敗の 0 円と見分けがつくように。¥0 は出さない）
        ship = ("無料" if r.shipping == 0 else _yen(r.shipping) if r.shipping is not None else "未確認")
        req = ("なし" if r.required_cost == 0 else _yen(r.required_cost) if r.required_cost is not None else "未確認")
        stock = ""
        if r.stock_label:
            until = (f' data-nu-pd-until="{r.stock_until_ms}" data-nu-pd-stale-text="在庫未確認（更新待ち）"'
                     if r.stock_until_ms else "")
            stock = (f'<span{until}>{esc(r.stock_label)}</span>'
                     + (f'<span class="nu-osub">在庫 {_time(r.stock_checked_at)}</span>' if r.stock_checked_at else ""))
        note = r.note
        if r.price_type == pt.LISTING and not note:
            note = "個人の出品（1件ごとに価格が変わる）・送料と手数料は出品ページで確認"
        trs.append(
            f'<tr class="nu-pd-tr{" nu-pd-best" if r is best else ""}">'
            f'<th scope="row" data-label="仕入れ先">{esc(r.source)}'
            + ('<span class="nu-pd-bestmark">最安（取得原価）</span>' if r is best else "")
            + (f'<span class="nu-osub">{esc(note)}</span>' if note else "") + '</th>'
            f'<td data-label="価格" class="nu-num">{_yen(r.price)}<span class="nu-osub">{esc(r.type_label)}'
            + (f'・{esc(r.condition)}' if r.condition else "") + '</span></td>'
            f'<td data-label="送料" class="nu-num">{esc(ship)}<span class="nu-osub">{esc(r.shipping_label)}</span></td>'
            f'<td data-label="購入時の費用" class="nu-num">{esc(req)}</td>'
            f'<td data-label="取得原価" class="nu-num nu-pd-acq">{esc(acq)}</td>'
            f'<td data-label="在庫">{stock or "—"}</td>'
            f'<td data-label="確認">{_quality(r)}<span class="nu-osub">価格 {_time(r.checked_at)}</span></td>'
            f'<td data-label="" class="nu-pd-ctacell">{_cta(r)}</td></tr>')
    return ('<table class="nu-pd-table"><caption class="nu-sr">仕入れ先の比較（取得原価が安い順。確認済みを先に）</caption>'
            '<thead><tr><th scope="col">仕入れ先</th><th scope="col">価格</th><th scope="col">送料</th>'
            '<th scope="col">購入時の費用</th><th scope="col">取得原価</th><th scope="col">在庫</th>'
            '<th scope="col">確認</th><th scope="col"><span class="nu-sr">リンク</span></th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table>')


def _buy_table(v: pd.ProductDetailView) -> str:
    if not v.buy_rows:
        return '<p class="nu-pd-empty">仕入れ先の価格はまだありません。</p>'
    best = v.best_buy
    main, rest = _split(v.buy_rows, best)
    return _buy_rows_html(main, best) + (_more("仕入れ先", len(rest), _buy_rows_html(rest, best)) if rest else "")


def _profit_sell(v: pd.ProductDetailView, r: pd.PriceRow) -> bool:
    """利益の計算に使った売却先の行か（OpportunityView の売却先・価格と同じ行）。"""
    o = v.opportunity
    return o is not None and r.source == o.sell_source and o.sell_price is not None and r.price == int(o.sell_price)


def _sell_rows_html(v: pd.ProductDetailView, rows: list, best) -> str:
    used = any(_profit_sell(v, r) for r in v.sell_rows)
    trs = []
    for r in rows:
        extra = ""
        if r.samples is not None or r.period:
            extra = f'<span class="nu-osub">{r.samples or "—"}件・{esc(r.period or "期間不明")}</span>'
        mine = _profit_sell(v, r)
        marks = ""
        if mine:
            marks += '<span class="nu-pd-bestmark">利益の計算に使った売却先</span>'
        if r is best and not mine:
            marks += '<span class="nu-pd-bestmark">最高（有効な売却価格・手数料前）</span>'
        trs.append(
            f'<tr class="nu-pd-tr{" nu-pd-best" if (mine or (r is best and not used)) else ""}">'
            f'<th scope="row" data-label="売却先">{esc(r.source)}{marks}'
            + (f'<span class="nu-osub">{esc(r.note)}</span>' if r.note else "") + '</th>'
            f'<td data-label="価格" class="nu-num">{_yen(r.price)}<span class="nu-osub">{esc(r.type_label)}'
            + (f'・{esc(r.condition)}' if r.condition else "") + f'</span>{extra}</td>'
            f'<td data-label="手数料・発送費"><span class="nu-osub nu-pd-cost">{esc(r.cost_note)}</span></td>'
            f'<td data-label="確認">{_quality(r)}<span class="nu-osub">価格 {_time(r.checked_at)}</span></td>'
            # 主なボタンは利益の計算に使った売却先だけ（ほかは控えめなボタン）
            f'<td data-label="" class="nu-pd-ctacell">{_cta(r, primary=mine)}</td></tr>')
    return ('<table class="nu-pd-table nu-pd-table--sell"><caption class="nu-sr">売却先の比較（確認済みの買取価格・成約中央値を先に）'
            '</caption><thead><tr><th scope="col">売却先</th><th scope="col">価格</th><th scope="col">手数料・発送費</th>'
            '<th scope="col">確認</th><th scope="col"><span class="nu-sr">リンク</span></th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table>')


def _sell_table(v: pd.ProductDetailView) -> str:
    if not v.sell_rows:
        return ('<p class="nu-pd-empty">売却価格 <b>未取得</b>（買取価格・成約中央値が見つかっていません）。'
                '利益は算出前です。</p>')
    best = v.best_sell
    main, rest = _split(v.sell_rows, best)
    note = ""
    if v.opportunity is not None:
        note = ('<p class="nu-osub">価格は手数料・送料を引く前の額です。利益の計算に使った費用（前提）は'
                '「利益の根拠」に出しています。</p>')
    return (note + _sell_rows_html(v, main, best)
            + (_more("売却先", len(rest), _sell_rows_html(v, rest, best)) if rest else ""))


def _src_link(url: str, text: str) -> str:
    if not url or not c.safe_href(url).startswith("https://"):
        return ""
    return (f' <a href="{esc(c.safe_href(url))}" target="_blank" rel="noopener noreferrer">{esc(text)}'
            '<span class="nu-sr">（外部サイト）</span></a>')


def _profit(v: pd.ProductDetailView) -> str:
    """利益の根拠（OpportunityView の値をそのまま。計算し直さない）。各行に情報元・確認時刻を付ける。"""
    o = v.opportunity
    pid = esc(f"pd-{v.alias}")
    if o is None:
        why = "".join(f"<li>{esc(x)}</li>" for x in v.profit_reasons[:4])
        return ('<section class="nu-pd-box nu-pd-profit" id="{0}-pfbox" tabindex="-1" aria-labelledby="{0}-pf">'
                '<h3 id="{0}-pf" class="nu-pd-h">利益の根拠</h3><p class="nu-pd-none">利益 <b>算出前</b>'
                '（確定の条件を満たす組み合わせがありません）</p>'
                '<p class="nu-osub">監視中の理由</p><ul class="nu-pd-why">{1}</ul></section>').format(pid, why)
    # 仕入価格の確認時刻は、表の公式の行と同じ値（公式の定価の確認日）を使う。案件の時刻（DB の更新時刻）で新しく見せない
    off = next((r for r in v.buy_rows if r.official), None)
    buy_at = (off.checked_at if (o.kind == "official_to_buyback" and off is not None and off.checked_at
                                 and o.buy_price is not None and off.price == int(o.buy_price)) else o.buy_checked_at)
    sell_t = _time(o.sell_checked_at) if o.sell_checked_at else "確認日時なし"
    buy_t = _time(buy_at) if buy_at else "確認日時なし"
    rows = [f'<li><span>売却価格（{esc(o.sell_source)}・{esc(o.sell_type_label)}）'
            f'<span class="nu-osub">確認済み・{sell_t}{_src_link(o.sell_url, "買取ページ")}</span></span>'
            f'<b>{_yen(o.sell_price)}</b></li>',
            f'<li><span>仕入価格（{esc(o.buy_source)}・{esc(o.buy_price_label)}）'
            f'<span class="nu-osub">確認済み・{buy_t}{_src_link(o.buy_url, "販売ページ")}</span></span>'
            f'<b>−{_yen(o.buy_price)}</b></li>']
    labels = [lbl for lbl, _a in o.cost_lines]
    if o.buy_shipping == 0 and "購入送料" not in labels:
        # 0円の購入送料も、確認した値として行に出す（確認したのか抜けているのかを見分けられるように）
        how = off.shipping_label if (off is not None and off.shipping == 0) else "確認済み"
        rows.append(f'<li><span>購入送料<span class="nu-osub">{esc(how)}</span></span><b>無料</b></li>')
    for label, amount in o.cost_lines:
        tag = ('<span class="nu-osub">確認済み</span>' if label == "購入送料"
               else '<span class="nu-osub"><span class="nu-pd-assume">前提（固定）</span>計算に使う決まった額</span>')
        rows.append(f'<li><span>{esc(label)}{tag}</span><b>−{_yen(amount)}</b></li>')
    rows.append(f'<li class="nu-break__total"><span>＝ 想定純利益</span><b>+{_yen(o.net_profit)}</b></li>')
    roi = f"{o.roi * 100:.1f}%" if o.roi is not None else "算出前"
    sub = (f'<li><span>取得原価（仕入価格 + 購入送料 + 購入時の費用）</span><b>{_yen(o.acquisition_cost)}</b></li>'
           f'<li><span>ROI（純利益 ÷ 取得原価）</span><b>{esc(roi)}</b></li>')
    # 根拠（買い値・売り値）のうち確認が古い方（どちらかの確認日時が無ければ出さない）
    seen = [t for t in (buy_at, o.sell_checked_at) if t]
    old_at = min(seen, key=lambda t: pd._ms(t) or 0) if len(seen) == 2 else ""
    oldest = f'<p class="nu-osub">根拠のうち一番古い確認: {_time(old_at)}</p>' if old_at else ""
    return (f'<section class="nu-pd-box nu-pd-profit" id="{pid}-pfbox" tabindex="-1" aria-labelledby="{pid}-pf">'
            f'<h3 id="{pid}-pf" class="nu-pd-h">利益の根拠</h3>'
            f'<p class="nu-osub">新品・未開封1台を {esc(o.buy_source)} で買い、{esc(o.sell_source)} に売る場合</p>'
            f'<ul class="nu-break">{"".join(rows)}</ul><ul class="nu-break nu-break--sub">{sub}</ul>{oldest}</section>')


def _lottery_details(lv, cta_url: str) -> str:
    """抽選・予約の日程・条件（折りたたみ。日程は公式の告知の値だけ。食い違うときは日程を出さない）。"""
    from src.content.ui.lottery_page import _period, _when_abs
    from src.content.ui.lottery_view import REQUIREMENTS_UNKNOWN
    rows: list[tuple[str, str]] = []
    if lv.source_conflict:
        rows.append(("日程", "日程要確認（公式情報どうしで食い違っています）"))
    elif lv.kind == rt.KIND_RELEASE:
        rows.append(("発売日", _when_abs(lv.release_at) or "未発表"))
    else:
        rows.append(("応募期間" if lv.kind == rt.KIND_LOTTERY else "予約期間",
                     _period(lv.application_start, lv.application_end) or "公式ページで確認"))
        if lv.kind == rt.KIND_LOTTERY:
            rows.append(("当選発表", _when_abs(lv.winner_announcement_at) or "未発表（公式ページで確認）"))
            rows.append(("当選者の購入期間", _period(lv.purchase_start, lv.purchase_end) or "未発表（公式ページで確認）"))
        rows.append(("応募条件" if lv.kind == rt.KIND_LOTTERY else "予約の条件",
                     "・".join(lv.requirements or [REQUIREMENTS_UNKNOWN])))
    rows.append(("販売価格", (f"¥{lv.retail_price:,}" if lv.retail_price else lv.retail_price_label)))
    rows.append(("情報の確かさ", lv.confidence or "公式情報"))
    if not lv.human_confirmed:
        rows.append(("ご注意", "告知の転記を人が確認するまで、応募ボタンは出していません。"))
    body = "".join(f"<dt>{esc(k)}</dt><dd>{esc(val)}</dd>" for k, val in rows if val)
    body += f"<dt>最終確認</dt><dd>{_time(lv.last_verified_at)}</dd>"
    link = ""
    # 応募ボタンと同じ URL の「公式情報を見る」は重ねない
    if lv.source_url and c.safe_href(lv.source_url).startswith("https://") and lv.source_url != cta_url:
        link = (f'<a class="nu-btn nu-btn--secondary nu-btn--sm" href="{esc(c.safe_href(lv.source_url))}" target="_blank"'
                ' rel="noopener noreferrer" data-track="product_lottery_info_click">公式情報を見る'
                '<span class="nu-sr">（外部サイト）</span></a>')
    return (f'<details class="nu-ldetail nu-pd-lotdet"><summary>抽選の詳細<span class="nu-sr">（{esc(lv.product_name)}）'
            f'</span></summary><dl class="nu-ldetail__dl">{body}</dl>{link}</details>')


def _lotteries(v: pd.ProductDetailView) -> str:
    if not v.lotteries:
        return ""
    rows = []
    for lv, st in v.lotteries:
        shop = " ".join(x for x in (lv.retailer, lv.store) if x) or "販売店は公式ページで確認"
        rows.append(
            f'<article class="nu-pd-lot" data-nu-lot="{esc(lv.event_id)}" data-nu-bucket="{st["bucket"]}"'
            f' data-nu-sort="{st["sort"]}" data-nu-status="{esc(st["status"])}">'
            f'<span class="nu-badge nu-tone-{esc(st["tone"])}" data-status="{esc(st["status"])}">'
            f'<span aria-hidden="true">{esc(st["icon"])}</span> {esc(st["label"])}</span>'
            f'<span class="nu-pd-lot__main"><b>{esc(lv.kind_label)}</b>・{esc(shop)}'
            f'<span class="nu-osub"><span class="nu-when">{esc(st["when"])}</span> <span class="nu-cd">{esc(st["cd_text"])}</span>'
            f'</span></span><span class="nu-pd-lot__cta" data-nu-cta-slot>{cta_html(st["cta"])}</span>'
            f'{_lottery_details(lv, (st.get("cta") or {}).get("url", ""))}</article>')
    return (f'<section class="nu-pd-box" aria-labelledby="pd-{esc(v.alias)}-lot"><h3 id="pd-{esc(v.alias)}-lot"'
            f' class="nu-pd-h">抽選・予約</h3>{"".join(rows)}'
            f'<a class="nu-pd-more" href="{esc(page_href("lottery"))}" data-nu-keepcat>抽選・予約の一覧で見る</a></section>')


def _refs(v: pd.ProductDetailView) -> str:
    """出品価格・件数や期間が足りない成約の参考（利益・ROI・想定売値には使わない）。"""
    items = []
    for r in v.listing_refs:
        items.append(f'<li><span>{esc(r.marketplace)}（出品・代表値）</span><b>{_yen(r.price)}</b>'
                     f'<span class="nu-osub">{(str(r.count) + "件・") if r.count else ""}{_time(r.observed_at)}'
                     f'{"・古い" if r.stale else ""}</span></li>')
    for r in v.sold_refs:
        items.append(f'<li><span>{esc(r.source)}（成約参考・{esc(r.note)}）</span><b>{_yen(r.price)}</b>'
                     f'<span class="nu-osub">{_time(r.checked_at)}</span></li>')
    if not items:
        return ""
    return (f'<section class="nu-pd-box nu-pd-refs" aria-labelledby="pd-{esc(v.alias)}-ref">'
            f'<h3 id="pd-{esc(v.alias)}-ref" class="nu-pd-h">市場の参考</h3>'
            '<p class="nu-osub">出品価格や、件数・期間が足りない成約です。想定売値・利益・ROI には使いません。</p>'
            f'<ul class="nu-pd-reflist">{"".join(items)}</ul></section>')


def _routes(v: pd.ProductDetailView) -> str:
    if not v.routes:
        return ""
    lis = "".join(f'<li>{esc(r.route_label)}：{esc(r.buy_source)} {_yen(r.buy_price)} → {esc(r.sell_source)} '
                  f'{_yen(r.sell_price)}（想定純利益 +{_yen(r.net_profit)}）</li>' for r in v.routes)
    return (f'<section class="nu-pd-box" aria-labelledby="pd-{esc(v.alias)}-rt"><h3 id="pd-{esc(v.alias)}-rt"'
            f' class="nu-pd-h">せどりルート</h3><ul class="nu-pd-reflist">{lis}</ul>'
            f'<a class="nu-pd-more" href="{esc(page_href("routes"))}" data-nu-keepcat>せどりルートの一覧で見る</a></section>')


def _chart(v: pd.ProductDetailView) -> str:
    """価格の履歴（実際に観測した点だけ。補間しない）。種別ごとに線の形を変える（色だけで区別しない）。"""
    pts = [(parse_dt(str(p["at"]).replace(" ", "T", 1)), p["price"], s)
           for s in v.history for p in s["points"]]
    pts = [(d, y, s) for d, y, s in pts if d is not None]
    if not pts:
        return ('<p class="nu-pd-empty">価格履歴はまだありません。今後の確認結果から履歴を作成します。</p>')
    xs = [d.timestamp() for d, _y, _s in pts]
    ys = [y for _d, y, _s in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad = max(1, (y1 - y0) * 0.1)
    y0, y1 = y0 - pad, y1 + pad
    w, h, left, r, t, b = 640, 220, 124, 12, 16, 36

    def px(x):
        return left + (w - left - r) * ((x - x0) / (x1 - x0) if x1 > x0 else 0.5)

    def py(y):
        return t + (h - t - b) * (1 - (y - y0) / (y1 - y0))
    lines, legend = [], []
    for i, s in enumerate(v.history):
        sp = sorted(((parse_dt(str(p["at"]).replace(" ", "T", 1)), p["price"]) for p in s["points"]),
                    key=lambda q: q[0] or 0)
        sp = [(d.timestamp(), y) for d, y in sp if d is not None]
        cls = f"nu-hs nu-hs--{esc(s['kind'])}"
        dash = KIND_DASH.get(s["kind"], "")
        if len(sp) >= 2:
            d = " ".join(f"{'M' if j == 0 else 'L'}{px(x):.1f},{py(y):.1f}" for j, (x, y) in enumerate(sp))
            lines.append(f'<path class="{cls}" d="{d}" fill="none"' + (f' stroke-dasharray="{dash}"' if dash else "")
                         + '/>')
        lines += [f'<circle class="{cls}" cx="{px(x):.1f}" cy="{py(y):.1f}" r="3.5"/>' for x, y in sp]
        legend.append(f'<li><svg width="28" height="8" aria-hidden="true"><line class="{cls}" x1="0" y1="4" x2="28"'
                      f' y2="4"' + (f' stroke-dasharray="{dash}"' if dash else "") + '/></svg>'
                      f'{esc(ph.KIND_LABELS.get(s["kind"], ""))}・{esc(s["source"])}（{len(sp)}点）</li>')
    d0 = min(pts, key=lambda q: q[0])[0]
    d1 = max(pts, key=lambda q: q[0])[0]
    # 軸の文字の大きさは SVG の単位（font-size="24"。390px でもおよそ13px）。点が1つ・同じ値・同じ日なら軸の文字は1つだけ
    axis = f'<text x="{left - 8}" y="{py(max(ys)) + 8:.1f}" text-anchor="end" class="nu-hs-ax" font-size="24">{_yen(max(ys))}</text>'
    if min(ys) != max(ys):
        axis += f'<text x="{left - 8}" y="{py(min(ys)) + 8:.1f}" text-anchor="end" class="nu-hs-ax" font-size="24">{_yen(min(ys))}</text>'
    if max(ys) - min(ys) >= 2:
        # 最小と最大の間に1本（目盛りの値は最小と最大のちょうど中間。点の値ではない）
        mid = (max(ys) + min(ys)) / 2
        axis += (f'<line x1="{left}" y1="{py(mid):.1f}" x2="{w - r}" y2="{py(mid):.1f}" class="nu-hs-grid"/>'
                 f'<text x="{left - 8}" y="{py(mid) + 8:.1f}" text-anchor="end" class="nu-hs-ax" font-size="24">{_yen(mid)}</text>')
    if d0.strftime("%m/%d") == d1.strftime("%m/%d"):
        axis += f'<text x="{(left + w - r) / 2:.1f}" y="{h - 6}" text-anchor="middle" class="nu-hs-ax" font-size="24">{d0.strftime("%m/%d")}</text>'
    else:
        axis += (f'<text x="{left}" y="{h - 6}" class="nu-hs-ax" font-size="24">{d0.strftime("%m/%d")}</text>'
                 f'<text x="{w - r}" y="{h - 6}" text-anchor="end" class="nu-hs-ax" font-size="24">{d1.strftime("%m/%d")}</text>')
    trs = "".join(
        f'<tr><th scope="row">{esc(ph.KIND_LABELS.get(s["kind"], ""))}・{esc(s["source"])}</th>'
        f'<td>{_time(p["at"])}</td><td class="nu-num">{_yen(p["price"])}</td></tr>'
        for s in v.history for p in sorted(s["points"], key=lambda p: p["at"], reverse=True))
    return (f'<figure class="nu-pd-chart"><svg viewBox="0 0 {w} {h}" role="img" aria-label="価格の履歴（実際に確認した値だけ）">'
            f'<line x1="{left}" y1="{h - b}" x2="{w - r}" y2="{h - b}" class="nu-hs-base"/>{axis}{"".join(lines)}</svg>'
            f'<figcaption><p class="nu-osub">期間 {d0.strftime("%m/%d")}〜{d1.strftime("%m/%d")}・合計{len(pts)}点'
            f'（点の値は下の表で確認できます）</p><ul class="nu-pd-legend">{"".join(legend)}</ul>'
            '<p class="nu-osub">実際に確認した価格だけを点で示しています（線は同じ種別・同じ店の点を結んだもの。'
            '間の値は推定していません）。</p></figcaption></figure>'
            '<table class="nu-pd-table nu-pd-hist"><caption class="nu-sr">価格の履歴（新しい順）</caption><thead><tr>'
            '<th scope="col">種別・店</th><th scope="col">確認</th><th scope="col">価格</th></tr></thead>'
            f'<tbody>{trs}</tbody></table>')


def _when(iso: str) -> str:
    """変化した時刻（日付だけの値は日付だけ。時刻を作らない）。"""
    s = str(iso or "")
    if len(s) == 10:
        return f'<span class="nu-time">{esc(s[5:].replace("-", "/"))}</span>'
    d = parse_dt(s.replace(" ", "T", 1)) if s else None
    if d is None:
        return '<span class="nu-time">時刻不明</span>'
    return f'<time class="nu-time" datetime="{esc(d.isoformat())}">{d.strftime("%m/%d %H:%M")}</time>'


def _changes(v: pd.ProductDetailView) -> str:
    if not v.changes:
        return '<p class="nu-pd-empty">最近の大きな変化はありません。</p>'
    lis = []
    for ch in v.changes[:20]:
        arrow = {"up": "↑", "down": "↓"}.get(ch.get("direction"), "")
        ba = (f'{esc(ch["before"])} → {esc(ch["after"])}' if ch.get("before") else esc(ch.get("after") or ""))
        src = esc(ch.get("source") or "")
        if ch.get("url") and c.safe_href(ch["url"]).startswith("https://"):
            src = (f'<a href="{esc(c.safe_href(ch["url"]))}" target="_blank" rel="noopener noreferrer">{src}'
                   '<span class="nu-sr">（外部サイト）</span></a>')
        lis.append(f'<li class="nu-pd-chg"><span class="nu-pd-chg__type">{esc(arrow)} {esc(ch["label"])}</span>'
                   f'<span class="nu-pd-chg__ba">{ba}</span>'
                   f'<span class="nu-osub">{_when(ch["changed_at"])}・情報元: {src}</span></li>')
    return f'<ul class="nu-pd-chglist">{"".join(lis)}</ul>'


def _fee_text(v, label_zero: str) -> str:
    return label_zero if v == 0 else _yen(v) if v is not None else "未確認"


def _action_item(o) -> tuple:
    """「今すぐ行動」の欄（Phase 18。src/market/actionability の結果をそのまま出す。判定し直さない）。

    利益があっても、在庫切れ・抽選の受付終了・更新待ちなどなら「できない」と理由を出す。行動できるときだけ、
    購入・申込のページへのボタン（期限を過ぎたら画面で消す）。
    """
    from src.market.actionability import REASONS
    a = o.action
    bits = [a.label]
    d = parse_dt(a.deadline) if a.deadline else None
    if d is not None:
        from src.market.actionability import is_date_only
        dl = d.astimezone(JST).strftime("%m/%d" if is_date_only(a.deadline) else "%m/%d %H:%M")
        bits.append(f'締切 {dl}' + ("" if a.actionable or
                                                                           not a.availability.endswith("CLOSED")
                                                                           else "（終了）"))
    ck = parse_dt(a.checked_at) if a.checked_at else None
    if ck is not None:
        bits.append(f'{ck.astimezone(JST).strftime("%m/%d %H:%M")}確認')
    if not a.actionable:
        why = "・".join(REASONS.get(r, r) for r in a.reasons if r != "not_profitable")
        if why:
            bits.append(f"理由: {why}")
    extra = ""
    val, sub = ("できる" if a.actionable else "できない"), "・".join(bits)
    if a.actionable and a.until_ms:
        # 期限を過ぎたら「できない」「更新待ち・抽選終了など」に落とす（判定はし直さない。レビュー・監査 M）
        val = (val, f' data-nu-pd-until="{int(a.until_ms)}" data-nu-pd-stale-text="できない"')
        sub = (sub, f' data-nu-pd-until="{int(a.until_ms)}"'
                    f' data-nu-pd-stale-text="期限を過ぎました（{esc(a.expired_label)}）"')
    if a.actionable and c.safe_href(a.cta_url).startswith("https://"):
        until = (f' data-nu-pd-until="{int(a.until_ms)}" data-nu-pd-stale-text="" data-nu-pd-stale-hide="1"'
                 if a.until_ms else "")
        extra = (f'<a class="nu-btn nu-btn--primary nu-btn--sm" href="{esc(c.safe_href(a.cta_url))}" target="_blank"'
                 f' rel="noopener noreferrer" data-track="product_action_click"{until}>{esc(a.cta_label)}'
                 '<span class="nu-sr">（外部サイト）</span></a>')
    return ("今すぐ行動", val, sub, extra, "")


def _summary(v: pd.ProductDetailView) -> str:
    """主要な数値（想定純利益を先頭に。値は ProductDetailView / OpportunityView の確定値だけ。計算しない）。"""
    o, bb, bs = v.opportunity, v.best_buy, v.best_sell
    cap = v.required_capital
    roi = f"{o.roi * 100:.1f}%" if (o is not None and o.roi is not None) else "算出前"
    a = esc(v.alias)
    # 最安仕入: 内訳（価格 + 送料 + 費用）と、比べる対象から外した仕入れ先の数
    if bb:
        buy_sub = (f"{bb.source}・{bb.type_label} {_yen(bb.price)} ＋ 送料 {_fee_text(bb.shipping, '無料')}"
                   f" ＋ 購入時の費用 {_fee_text(bb.required_cost, 'なし')}")
        out = sum(1 for r in v.buy_rows if r.usable and r.acquisition is None)
        if out:
            buy_sub += f"。送料などの費用が分かる仕入れ先の中で最安（ほか{out}件は費用が未確認のため比較外）"
    else:
        buy_sub = "確認済みの仕入れ先（送料などの費用が分かるもの）がありません"
    # 売却: 利益があるときは、利益の計算に使った売却先を出す（最高の額面とは別）
    if o is not None:
        sell_lbl, sell_val = "利益の計算に使った売却価格", _yen(o.sell_price)
        sell_sub = f"{o.sell_source}・{o.sell_type_label}（手数料・送料を引く前）"
        if bs is not None and o.sell_price is not None and bs.price > o.sell_price:
            sell_sub += f"。額面の最高は {bs.source}・{bs.type_label} {_yen(bs.price)}"
    else:
        sell_lbl = "最高の有効な売却価格"
        sell_val = _yen(bs.price) if bs else "未取得"
        sell_sub = f"{bs.source}・{bs.type_label}（手数料・送料を引く前）" if bs else "買取価格・成約中央値が未取得"
    if o is not None:
        prof_val = f"+{_yen(o.net_profit)}"
        prof_sub = (f"{o.buy_source}で買い、{o.sell_source}（{o.sell_type_label}）に {_yen(o.sell_price)} で売る場合"
                    f"（新品・未開封1台・ROI {roi}）")
        jump = f'<a class="nu-pd-jump" href="#pd-{a}-pfbox" data-nu-pd-jump="pd-{a}-pfbox">内訳を見る</a>'
    else:
        prof_val, prof_sub, jump = "算出前", "確定の条件を満たす組み合わせなし", (
            f'<a class="nu-pd-jump" href="#pd-{a}-pfbox" data-nu-pd-jump="pd-{a}-pfbox">理由を見る</a>')
    items = [
        ("想定純利益", prof_val, prof_sub, jump, " nu-pd-metric--main" + (" nu-pd-metric--profit" if o is not None else "")),
        *([_action_item(o)] if (o is not None and getattr(o, "action", None) is not None) else []),
        ("最安仕入（取得原価）", (_yen(bb.acquisition) if bb else "未取得"), buy_sub, "", " nu-pd-metric--wide"),
        (sell_lbl, sell_val, sell_sub, "", " nu-pd-metric--wide"),
        ("ROI", roi, "純利益 ÷ 取得原価", "", ""),
        ("必要な仕入れ資金", (_yen(cap) if cap is not None else "算出前"), "仕入価格 + 購入送料 + 購入時の費用", "", ""),
    ]
    def _txt(x):
        # 値・補足は文字列か (文字列, 属性)。属性は期限を過ぎたら画面で文言を落とす印（data-nu-pd-until）など
        return x if isinstance(x, tuple) else (x, "")
    cells = "".join(
        f'<div class="nu-pd-metric{cls}"><dt>{esc(lbl)}</dt><dd><span class="nu-pd-val"{_txt(val)[1]}>'
        f'{esc(_txt(val)[0])}</span><span class="nu-osub"{_txt(sub)[1]}>{esc(_txt(sub)[0])}</span>{extra}</dd></div>'
        for lbl, val, sub, extra, cls in items)
    return f'<dl class="nu-pd-summary">{cells}</dl>'


def _head_state(v: pd.ProductDetailView) -> str:
    """見出しの状態の補足（どこで・いつまで・在庫と価格の確認時刻）と、買える場所へのボタン。"""
    bits = []
    stock_row = next((r for r in v.buy_rows if r.stock_checked_at), None)
    if v.status == "AVAILABLE" and v.stock is not None and v.stock.fresh_until:
        until = parse_dt(v.stock.fresh_until)
        if until is not None:
            bits.append(f'<span class="nu-osub" data-nu-pd-until="{v.status_until_ms}" data-nu-pd-stale-text="">'
                        f'{esc(v.stock.retailer or "公式ストア")}・在庫ありの表示は'
                        f' {until.astimezone(JST).strftime("%m/%d %H:%M")} まで（以後は更新待ち）</span>')
    if stock_row is not None:
        bits.append(f'<span class="nu-osub">在庫 {_time(stock_row.stock_checked_at)}</span>')
    bits.append(f'<span class="nu-osub">価格 {_time(v.last_verified_at)}</span>')
    ident = " ・ ".join(x for x in (v.model and f"型番 {v.model}", v.jan and f"JAN {v.jan}") if x)
    bits.append(f'<span class="nu-osub">{esc(ident or v.identity_status)}</span>')
    bb = v.best_buy
    cta = _cta(bb, label=f"{bb.source}で購入する") if (bb is not None and bb.cta_primary) else ""
    return "".join(bits), (f'<p class="nu-pd-headcta">{cta}</p>' if cta else "")


def _article(v: pd.ProductDetailView) -> str:
    a = esc(v.alias)
    tone = STATUS_TONE.get(v.status, "neutral")
    until = (f' data-nu-pd-until="{v.status_until_ms}" data-nu-pd-stale-text="在庫未確認（更新待ち）"'
             if v.status_until_ms else "")
    meta = " ・ ".join(x for x in (v.model and f"型番 {v.model}", v.capacity, v.category_label, v.condition) if x)
    state_bits, head_cta = _head_state(v)
    tabs = "".join(
        f'<button type="button" role="tab" id="pd-{a}-tab-{k}" aria-controls="pd-{a}-panel-{k}"'
        f' aria-selected="{"true" if k == "buy" else "false"}" tabindex="{0 if k == "buy" else -1}"'
        f' class="nu-pd-tab" data-nu-pdtab="{k}">{esc(lbl)}</button>' for k, lbl in TABS)
    panels = {
        "buy": (_lotteries(v) + _profit(v)
                + f'<section class="nu-pd-box" aria-labelledby="pd-{a}-buy"><h3 id="pd-{a}-buy" class="nu-pd-h">買う</h3>'
                + _buy_table(v) + '</section>'
                + f'<section class="nu-pd-box" aria-labelledby="pd-{a}-sell"><h3 id="pd-{a}-sell" class="nu-pd-h">売る</h3>'
                + _sell_table(v) + '</section>' + _refs(v) + _routes(v)),
        "history": _chart(v),
        "changes": _changes(v),
    }
    body = "".join(f'<div role="tabpanel" id="pd-{a}-panel-{k}" aria-labelledby="pd-{a}-tab-{k}"'
                   f' class="nu-pd-panel"{"" if k == "buy" else " hidden"}>{panels[k]}</div>' for k, _l in TABS)
    return (
        f'<article class="nu-pd" data-nu-pd="{esc(v.product_id)}" data-nu-cat="{esc(v.category)}"'
        f' data-nu-pd-name="{esc(v.product_name)}" hidden>'
        '<header class="nu-pd-head">'
        f'<h1 class="nu-pd-title" tabindex="-1">{esc(v.product_name)}</h1>'
        f'<p class="nu-pd-meta">{esc(meta)}</p>'
        f'<p class="nu-pd-state"><span class="nu-badge nu-tone-{tone}" data-nu-pd-status="{esc(v.status)}"{until}'
        f' data-nu-pd-fallback="{esc(v.fallback_label)}"'
        f' data-nu-pd-fallback-tone="{STATUS_TONE.get(v.fallback_status, "neutral")}">'
        f'{esc(v.status_label)}</span>{state_bits}</p>'
        f'<div class="nu-pd-headacts">{head_cta}{watch_button(v.product_id, v.product_name, compact=False)}</div></header>'
        f'{_summary(v)}'
        f'<div class="nu-pd-tabs" role="tablist" aria-label="{esc(v.product_name)}の情報">{tabs}</div>{body}'
        '</article>'
    )


def render(views: dict) -> str:
    arts = "".join(_article(v) for v in views.values())
    return (
        '<section class="nu-page nu-pd-page" data-nu-page="product" aria-label="商品詳細" hidden>'
        f'<a class="nu-pd-back" href="{esc(page_href("search"))}" data-nu-back data-nu-keepcat>'
        '<span aria-hidden="true">← </span>戻る</a>'
        '<div class="nu-pd-missing" data-nu-pd-missing hidden><h1 class="nu-page__title" tabindex="-1">商品が見つかりません</h1>'
        '<p class="nu-lead">URL の商品が見つかりませんでした。商品一覧から探してください。</p>'
        f'<a class="nu-btn nu-btn--primary" href="{esc(page_href("search"))}">商品一覧へ戻る</a></div>'
        f'{arts}</section>'
    )


def quote_id(product_id: str) -> str:
    from urllib.parse import quote
    return quote(product_id, safe="")


def watch_button(product_id: str, name: str, *, compact: bool = True) -> str:
    """ウォッチの切り替え（マイページ。product_id で保存し、商品名では照合しない）。押した状態はブラウザ側で付け直す。
    主なボタン（購入・応募・商品詳細）より目立たせない。"""
    cls = "nu-watch nu-watch--sm" if compact else "nu-watch"
    return (f'<button type="button" class="{cls}" data-nu-watch="{esc(product_id)}" aria-pressed="false"'
            f' aria-label="{esc(name)}をウォッチ" data-nu-watch-name="{esc(name)}">'
            '<span class="nu-watch__icon" aria-hidden="true">☆</span>'
            '<span class="nu-watch__text">ウォッチ</span></button>')


def link(product_id: str, label: str = "商品詳細を見る") -> str:
    """一覧から商品詳細へのリンク（既存のボタンは置き換えずに足す）。"""
    from urllib.parse import quote
    return (f'<a class="nu-pdlink" href="{esc(page_href("product"))}&amp;product_id={esc(quote(product_id, safe=""))}"'
            ' data-nu-keepcat>'
            f'{esc(label)}</a>')
