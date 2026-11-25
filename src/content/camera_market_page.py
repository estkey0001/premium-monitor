"""カメラ せどり判断ページ（docs/camera-research.html）の描画。

入力は exports/camera_research/camera_market.json（src/research/camera_refresh.py が作る）。
「どこで買い・いくらで・どこで売り・いくらで・利益と ROI はいくらか・その売値は買取か成約中央値か」を 1 枚で判断できるようにする。
- 価格の種別を混ぜない（買取価格 / 成約中央値 / 出品中の価格）。出品の最高値は売値にしない（参考として別枠に出すだけ）。
- 計算できないルートは、理由を出して「未計算」と書く（0 円・架空の商品で埋めない）。利益商品が 0 件なら 0 件と書く。
- 調査が古いときは BUY を出さず「調査が古い」と書く（ページを作るたびに現在日時で決める）。
- すべての文字は HTML エスケープ。リンクは http(s) だけ。
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime, timedelta, timezone

from src.content.iphone_buyback_page import CSS as _CSS, age_banner, _md, _plain
from src.content.ui.shared_css import legacy_css, site_nav
from src.tcg.models import parse_dt

JST = timezone(timedelta(hours=9))

COND = {"NEW": "新品", "UNOPENED": "新品未開封", "LIKE_NEW": "新品同様", "USED": "中古", "UNKNOWN": "状態不明"}
STOCK = {"AVAILABLE": "購入できる", "OUT_OF_STOCK": "在庫なし", "LOTTERY_DEPENDENT": "抽選に当選が必要", "RESERVATION": "予約のみ", "UNKNOWN": "在庫不明"}
PTYPE = {"BUYBACK_PRICE": "買取価格", "SOLD_MEDIAN": "成約中央値", "OFFICIAL_RETAIL": "公式の販売価格", "RETAIL_PRICE": "販売店の価格",
         "LISTING_LOW": "出品中の最安（売れた価格ではない）"}
DECISION = {"BUY": "BUY（買う）", "WATCH": "WATCH（様子見・要確認）", "WAIT": "WAIT（待つ）", "SKIP": "SKIP（見送り）"}
DECISION_JA = {"BUY": "購入候補", "WATCH": "様子見", "WAIT": "様子見", "SKIP": "見送り"}
CONF_JA = {"high": "高", "medium": "中", "low": "低"}
PROFIT = {"PROFITABLE": "黒字", "NO_PROFIT": "赤字・利益なし", "NOT_CALCULATED": "未計算"}
REASON = {
    "conditional_price": "条件つきの価格（無条件の確定価格ではない）", "no_profit": "利益が出ない", "stock_lottery_dependent": "抽選に当選しないと買えない", "stock_reservation": "予約のみで今は買えない",
    "out_of_stock": "在庫なし", "stock_unknown": "在庫が確認できない", "unregistered_product": "監視対象に未登録の機種",
    "roi_below_threshold": "ROI が基準（8%）に届かない", "single_buyback_shop": "買取が 1 店だけ（比較できない）",
    "buyback_outlier_review": "買取の最高が他店より極端に高い（外れ値の確認）", "buyback_update_date_unknown": "買取の更新日が不明",
    "secondary_route_not_auto_buy": "二次流通の売値は成約の実在を人が確認するまで BUY にしない", "not_executable": "実行できる条件がそろっていない",
    "condition_mismatch": "買う状態と売る状態が違う", "sold_insufficient": "成約が足りない（3 件以上・期間・個別の根拠が必要）",
    "sold_none": "成約の実績なし", "fee_unconfirmed": "売り先の販売手数料が確認済み（一次情報の本文）でない", "purchase_shipping_unknown": "購入送料が不明",
    "no_buy_candidate": "買える価格が確認できていない", "no_buyback": "買取価格が確認できていない",
    "price_missing": "価格が読めていない", "not_product_page": "商品ページでない（一覧だけ）", "model_not_in_title": "商品名が機種と一致しない",
    "variant_mismatch": "版・仕様が違う", "item_title_missing": "商品名を確認できない", "buy_stale": "仕入れ価格が古い",
    "buy_unknown_freshness": "仕入れ価格の日付を確認できない", "sell_stale": "買取価格が古い", "sell_unknown_freshness": "買取価格の日付を確認できない",
    "not_purchasable_now": "今買えるか確認できない", "condition_unknown": "状態を確認できない", "retail_not_new": "新品でない",
    "host_not_allowed": "価格の根拠にできないサイト", "aggregator_source": "集約サイト由来（採用しない）", "not_item_page": "商品ページでない（検索・一覧）",
    "title_condition_mismatch": "商品名の状態が申告と違う", "junk_or_defective": "ジャンク・訳あり・付属品など", "model_continues": "別の機種の表記",
    "price_implausible": "価格が不自然（誤取得の疑い）", "roi_implausible": "ROI が不自然（誤取得の疑い）", "stock_check_old": "在庫の確認が古い",
    "cross_border_cost_unknown": "海外の出品（送料・関税が不明のため仕入れに使わない）", "fx_unconfirmed": "為替が未確認（円換算しない）", "fx_mismatch": "円換算が為替と合わない", "currency_unspecified": "通貨・原価格の記載がない（海外の行は必須）",
    "duplicate_sold": "同じ成約の重複", "no_item_url": "個別の成約ページの URL がない",
    "price_kind_OPEN_PRICE": "オープン価格で金額が確認できない", "price_kind_NOT_FOUND": "公式の価格を確認できない",
}


MKT_STATUS = {"AVAILABLE": "取得できた", "PARTIAL": "一部取得", "BLOCKED": "取得できない（未取得）", "FAILED": "取得に失敗（未取得）", "NOT_SUPPORTED": "提供されていない（未取得）",
              "NOT_CONFIGURED": "未設定（未取得）", "PENDING_APPROVAL": "承認待ち（未取得）"}
MKT_REASON = {
    "no_official_api_search_scrape_prohibited": "公式 API が無く、検索結果の取得は行わない方針のため",
    "official_api_discontinued": "公式 API が 2020 年に終了しているため",
    "no_official_api_robots_disallow_search": "公式 API が無く、robots.txt が検索を禁止しているため",
    "official_api_not_configured": "公式 API の資格情報が未登録のため",
    "official_api_not_enabled": "公式 API が有効化されていないため",
    "adapter_not_implemented": "公式 API のアダプターが未実装のため",
    "rows_from_research_file": "調査員が根拠 URL つきで読んだ行だけ",
    "adapter_not_run": "公式 API のアダプターを今回は実行していないため",
    "api_listing_only": "公式 API で出品中の価格だけ（成約は審査制で未承認）", "api_ok": "公式 API で取得",
    "api_dry_run": "API_DRY_RUN が有効のため通信していない", "ebay_insights_not_approved": "成約（Marketplace Insights）が未承認のため",
    "sold_license_unconfirmed": "成約データの保存ライセンスが未確認のため", "listing_failed_sold_ok": "出品の取得に失敗（成約だけ取得）",
}
FEE_STATUS = {"CONFIRMED": "確認済み（一次情報の本文）", "UNVERIFIED": "未検証（本文を読めていない）", "UNKNOWN": "不明", "NOT_APPLICABLE": "なし（買取）"}
CRED = {"NOT_CONFIGURED": "未登録", "CONFIGURED": "登録済み", "NOT_REQUIRED": "不要（API なし）"}


def _rows(n) -> str:
    return "未取得" if n is None else f"{int(n)} 件"        # 未取得（None）を「0 件」と書かない


def _markets(market: dict) -> str:
    mk = market.get("secondary_markets") or []
    if not mk:
        return ""
    rows = "".join(
        f'<tr><th scope="row">{_e(m.get("label"))}</th><td><b title="{_e(m.get("status"))}">{_e(MKT_STATUS.get(m.get("status"), "状態を確認中"))}</b></td>'
        f'<td>{_e(MKT_REASON.get(m.get("reason"), m.get("reason")))}{"（公式 API の取得に失敗しました）" if m.get("api_error") else ""}</td><td>{_e(CRED.get(m.get("credentials"), m.get("credentials")))}</td>'
        f'<td class="num">{_e(_rows(m.get("listing_rows")))}</td><td class="num">{_e(_rows(m.get("sold_rows")))}</td>'
        f'<td>{_e(FEE_STATUS.get(m.get("fee_status"), m.get("fee_status")))}{" ・" + str(round(100 * m["fee_rate"], 1)) + "%" if m.get("fee_rate") else ""}</td>'
        f'<td>{_e(m.get("checked_on"))}</td></tr>' for m in mk)
    apis = "".join(f'<li>{_e(a.get("label"))}の公式 API: {_e(CRED.get(a.get("reason"), "未登録" if a.get("reason") == "NOT_CONFIGURED" else "未有効・未実装"))}（{_e(a.get("scope"))}）</li>'
                   for a in market.get("retail_apis") or [])
    return ('<h2>二次流通の取得状況（市場ごと）</h2>'
            '<div class="note">取得できなかった市場は「未取得」であって、出品や成約が無いという意味ではありません。検索結果の取得は行わず、公式 API と、根拠 URL つきで読んだ行だけを使います。</div>'
            '<details class="spec"><summary>市場ごとの表を開く</summary><div class="tw"><table><thead><tr><th>市場</th><th>状態</th><th>理由</th><th>API 資格情報</th><th>出品（Listing）</th><th>成約（Sold）</th><th>販売手数料</th><th>確認日</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></details>'
            + (f'<ul class="mut">{apis}</ul>' if apis else ""))


def _kinds(summ: dict, market: dict | None = None) -> str:
    fd = summ.get("found") or {}
    mk = (market or {}).get("secondary_markets") or []
    no_l = bool(mk) and all(m.get("listing_rows") is None for m in mk)      # 全市場が未取得なら「0 件」と書かない
    no_s = bool(mk) and all(m.get("sold_rows") is None for m in mk)
    return ('<h2>価格の種類ごとの確認状況</h2><div class="grid">'
            f'<div class="kv"><span title="Primary Market">新品の公式・販売店の価格</span><b>{_e(fd.get("official_or_retail_prices"))} 件</b></div>'
            f'<div class="kv"><span title="Buyback">買取価格</span><b>{_e(fd.get("buyback"))} 件</b></div>'
            f'<div class="kv"><span title="Secondary Listings">二次流通の出品中</span><b>{"未取得（全市場）" if no_l and not fd.get("listing") else _e(fd.get("listing")) + " 件"}</b></div>'
            f'<div class="kv"><span title="Secondary Sold">二次流通の成約</span><b>{"未取得（全市場）" if no_s and not fd.get("sold") else _e(fd.get("sold")) + " 件"}</b></div></div>')


def _e(v) -> str:
    return _html.escape("" if v is None else str(v))


def _yen(v) -> str:
    return "—" if v is None else f"¥{int(v):,}"


def _signed(v) -> str:
    return "—" if v is None else ("+" if v > 0 else "−" if v < 0 else "") + f"¥{abs(int(v)):,}"


def _link(url, label) -> str:
    u = str(url or "")
    safe = u.startswith(("http://", "https://")) and not re.search(r"[\\\s\x00-\x1f\x7f@]", u)
    return f'<a href="{_e(u)}" target="_blank" rel="noopener nofollow">{_e(label)}</a>' if safe else _e(label)


def _reasons(rs) -> str:
    return "、".join(REASON.get(r, r) for r in rs or []) or "—"


BASIS = {"STAMPED_WARRANTY": "保証書に店舗印ありの価格（完品より減額）"}
BASIS_SHORT = {"STAMPED_WARRANTY": "店舗印ありの価格"}


def _basis(s) -> str:
    """売値の基準の注記（店で買った新品を売る前提の価格など）。"""
    return BASIS.get((s or {}).get("basis"), "")


def _why_sell(s: dict) -> str:
    """「なぜこの売値か」。買取か成約中央値か、その根拠。"""
    if not s:
        return "—"
    ev = s.get("evidence") or {}
    if s.get("price_type") == "SOLD_MEDIAN":
        return f"成約中央値（{ev.get('sample_count')}件・期間 {ev.get('period')}・{COND.get(s.get('condition'), s.get('condition'))}）"
    upd = s.get("source_updated_at") or "更新日不明"
    note = f"・{_basis(s)}" if _basis(s) else ""
    return (f"買取価格（{COND.get(s.get('condition'), '')}・{s.get('source')}{note}・店の更新 {upd}・"
            f"比較できた買取 {ev.get('shops', 1)} 店）")


def _row_stale(r: dict, now: datetime, buy_days: int = 2, sell_days: int = 7) -> bool:
    """行ごとの古さ。仕入れ（在庫）は buy_days 日、売値は sell_days 日を超えたら、BUY を出さない。未来の日付も古い扱い。"""
    out = []
    for x, lim in ((r.get("buy") or {}, buy_days), (r.get("sell") or {}, sell_days)):
        d = parse_dt(x.get("checked_at")) if x.get("checked_at") else None
        if d is None or d > now + timedelta(days=1) or (now - d).days > lim:
            out.append(True)
    return bool(out)


ROUTE_SHORT = {"A": "正規店→買取", "B": "正規店→二次流通", "C": "二次流通→買取", "D": "二次流通→二次流通"}


def _route_short(r: dict) -> str:
    return ROUTE_SHORT.get(r.get("route_type"), str(r.get("route_type") or "—"))


def _route_html(r: dict) -> str:
    """ルート名。矢印の前後で自然に折り返し、語の途中（買／取）では折らない。"""
    return f'<span class="rt">{"→<wbr>".join(_e(x) for x in _route_short(r).split("→"))}</span>'


_CAMERA_CSS = (
    "main{max-width:1240px}.rt{white-space:nowrap}"
    "@media (max-width:639px){.dcard .hero .m--route{grid-column:1/-1}.dcard .hero .m--route b{font-size:1rem}"
    ".dcard .why{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}"
)


def _roi(v) -> str:
    """ROI の表示。値は変えず、負の符号だけ金額と同じ U+2212 にそろえる。"""
    return "—" if v is None else f"{v}%".replace("-", "−")


def _badge(label: str, tone: str) -> str:
    return f'<span class="sbadge sbadge--{_e(tone)}">{_e(label)}</span>'


def _decision_badge(r: dict, stale: bool, registered: bool = True) -> str:
    """判断（BUY/WATCH/WAIT/SKIP）の新語バッジ。購入候補=緑（調査が古い・未登録なら緑にしない）。利益の色とは別軸。"""
    d = r.get("decision")
    if d == "BUY":
        if stale:
            return _badge("調査が古い（参考）", "off")
        return _badge("購入候補", "buy") if registered else _badge("参考（未登録）", "wait")
    if d in ("WATCH", "WAIT"):
        return _badge("様子見", "wait")
    return _badge("見送り", "off")


def _is_go(r: dict, registered: bool = True, stale: bool = False) -> bool:
    """緑にしてよいのは購入候補（登録済み・判断が BUY・調査が古くない）だけ。様子見・確認待ち・未登録・古い調査は中立色。"""
    return bool(registered) and not stale and r.get("decision") == "BUY"


def _profit_badge(r: dict, registered: bool = True, stale: bool = False) -> str:
    """利益の状態（黒字/赤字）。判断とは別に出す。赤字は net_profit が負のときだけ。黒字は購入候補のときだけ緑、それ以外は中立（灰）。"""
    net = r.get("net_profit")
    if r.get("profit_status") == "PROFITABLE" and (net or 0) > 0:
        if not registered:
            return _badge("黒字（参考）", "off")
        return _badge("黒字", "profit") if _is_go(r, registered, stale) else _badge("黒字", "off")
    if net is not None and net < 0:
        return _badge("赤字", "loss")
    return _badge("利益なし", "off") if net is not None else ""


def _card(p: dict, r: dict, stale: bool) -> str:
    """判断カード（商品・買値・売値・利益/ROI・ルート・判断）。表の詳細をたたんで持つ。ルートは A〜D の記号でなく語で出す。"""
    b, sl = r["buy"], r["sell"]
    reg = bool(p.get("registered"))
    net = r.get("net_profit")
    net_cls = "pos" if (net or 0) > 0 and _is_go(r, reg, stale) else "neg" if (net or 0) < 0 else ""        # 緑は購入候補だけ。様子見・未登録・古い調査の黒字は中立色
    ref = "" if reg else ' <span class="chip chip--ref">未登録・参考</span>'
    status = STOCK.get(b.get("stock"), b.get("stock"))
    return (f'<article class="dcard{" dcard--off" if r.get("decision") != "BUY" or stale else ""}">'
            f'<header><h3>{_e(p["product"])}{ref}</h3><div class="badges">{_decision_badge(r, stale, reg)}{_profit_badge(r, reg, stale)}</div></header>'
            f'<div class="hero"><div class="m"><span>買値</span><b>{_yen(b["price"])}</b><em>{_e(b["source"])}</em></div>'
            f'<div class="m"><span>売値</span><b>{_yen(sl["price"]) if sl else "—"}</b><em>{_e(sl["source"]) if sl else ""}（{_e(PTYPE.get(sl["price_type"], sl["price_type"])) if sl else ""}{("・" + _e(_basis(sl))) if _basis(sl) else ""}）</em></div>'
            f'<div class="m"><span>利益</span><b class="{net_cls}">{_signed(net) if net is not None else "未計算"}</b></div>'
            f'<div class="m"><span>ROI</span><b>{_e(_roi(r.get("roi_pct")))}</b></div>'
            f'<div class="m m--route"><span>買い方→売り方</span><b>{_route_html(r)}</b></div>'
            f'<div class="m"><span>買える状態</span><b>{_e(status)}</b></div></div>'
            f'<div class="mut why">判断の理由: {_e(_reasons(r.get("reasons")))}</div>'
            f'<details><summary>買う場所・売る場所・確認日</summary>'
            f'<div>買う場所: {_link(b.get("url"), b["source"])}（{_e(PTYPE.get(b["price_type"], b["price_type"]))}・{_e(COND.get(b["condition"], b["condition"]))}）</div>'
            f'<div>売る場所: {_link(sl.get("url"), sl["source"]) if sl else "—"}</div>'
            f'<div class="mut">確認日 {_md(b.get("checked_at"))}／信頼度 <span title="confidence: {_e(r.get("confidence"))}">{_e(CONF_JA.get(r.get("confidence"), r.get("confidence")))}</span>'
            f'／内部参照: ルート {_e(r["route_type"])}</div></details></article>')


def _row(p: dict, r: dict, stale: bool) -> str:
    """詳細表の 1 行（8 列。旧表記の判断語はこの表に残す）。"""
    b, s = r["buy"], r["sell"]
    dec_html = ('調査が古い（参考）' if (stale and r["decision"] == "BUY") else
                f'<span title="{_e(DECISION.get(r["decision"], r["decision"]))}">{_e(DECISION_JA.get(r["decision"], r["decision"]))}</span>')
    net = (f'{_signed(r["net_profit"])}' if r["net_profit"] is not None else "未計算")
    roi = _roi(r["roi_pct"])
    cls = "ok" if r["decision"] == "BUY" and not stale else ""
    net_cls = "pos" if (r["net_profit"] or 0) > 0 and _is_go(r, bool(p.get("registered")), stale) else "neg" if (r["net_profit"] or 0) < 0 else ""
    c_ = r.get("costs") or {}
    cost = _yen(sum(int(c_.get(k) or 0) for k in ("purchase_shipping", "outbound_shipping", "selling_fee", "other"))) if c_ else "—"
    carried = "（買取は引き継ぎ・古い確認）" if (s and s.get("carried")) or b.get("carried") else ""
    return (f'<tr class="{cls}"><th scope="row" data-label="商品"><div class="v">{_e(p["product"])}{"" if p.get("registered") else " <span class=mut>（未登録・参考）</span>"}</div></th>'
            f'<td data-label="買う場所・買値"><div class="v">{_link(b.get("url"), b["source"])} <b>{_yen(b["price"])}</b><br>'
            f'<span class="mut">{_e(PTYPE.get(b["price_type"], b["price_type"]))}・{_e(COND.get(b["condition"], b["condition"]))}・{_e(STOCK.get(b.get("stock"), b.get("stock")))}</span></div></td>'
            f'<td data-label="売る場所・売値"><div class="v">{_link(s.get("url"), s["source"]) if s else "—"} <b>{_yen(s["price"]) if s else "—"}</b><br>'
            f'<span class="mut">{_e(PTYPE.get(s["price_type"], s["price_type"])) if s else "—"}{("・" + _e(_basis(s))) if _basis(s) else ""}</span></div></td>'
            f'<td class="num" data-label="費用"><div class="v">{cost}</div></td><td class="num" data-label="純利益"><div class="v {net_cls}">{net}</div></td>'
            f'<td class="num" data-label="ROI"><div class="v">{_e(roi)}</div></td>'
            f'<td data-label="ルート"><div class="v">{_route_html(r)}<br><span class="mut" title="Route {_e(r["route_type"])}">ルート {_e(r["route_type"])}</span></div></td>'
            f'<td data-label="判断"><div class="v"><b>{dec_html}</b><br><span class="mut">{_e(_reasons(r.get("reasons")))}</span><br>'
            f'<span class="mut">確認日 {_md(b.get("checked_at"))}{carried}／信頼度 <span title="confidence: {_e(r.get("confidence"))}">{_e(CONF_JA.get(r.get("confidence"), r.get("confidence")))}</span></span></div></td></tr>')


def _detail(p: dict, r: dict, common_why: frozenset = frozenset()) -> str:
    c = r["costs"] or {}
    why = _why_sell(r["sell"])
    why_t = "共通の根拠" if why in common_why else why
    return (f'<li><b>{_e(p["product"])} / {_e(_route_short(r))}</b>: '
            f'売値 {_yen(r["sell"]["price"])}（{_e(why_t)}）− 仕入れ {_yen(r["buy"]["price"])} − 購入送料 {_yen(c.get("purchase_shipping"))}'
            f' − 発送など {_yen(c.get("outbound_shipping"))} − 販売手数料 {_yen(c.get("selling_fee"))}'
            f'{"（" + str(round(100 * c["selling_fee_rate"])) + "%・" + _e(FEE_STATUS.get(r.get("fee_status"), r.get("fee_status"))) + "）" if c.get("selling_fee_rate") else "（買取は手数料なし）"}'
            f' − その他 {_yen(c.get("other"))} = 純利益 {_signed(r["net_profit"])}</li>')


def _secondary(p: dict) -> str:
    sec = p.get("secondary") or {}
    if not sec.get("listing") and not sec.get("sold") and not sec.get("listing_foreign"):
        return ""
    lf = "".join(f'<tr><th scope="row">{_e(v["market"])}（{_e(COND.get(v["family"], v["family"]))}）</th><td class="num">{_e(v["currency"])} {v["low"]:,.2f}</td>'
                 f'<td class="num">{_e(v["currency"])} {v["high"]:,.2f}</td><td class="num">{v["n"]}</td><td>{"円換算あり" if v.get("fx_status") == "CONFIRMED" else "為替が未確認のため円換算なし"}</td></tr>'
                 for v in (sec.get("listing_foreign") or {}).values())
    ls = "".join(f'<tr><th scope="row">{_e(COND.get(k, k))}</th><td class="num">{_yen(v["low"])}</td><td class="num">{_yen(v["high"])}</td>'
                 f'<td class="num">{v["n"]}</td><td>{_e(v["low_source"])}</td></tr>' for k, v in (sec.get("listing") or {}).items())
    sd = "".join(f'<tr><th scope="row">{_e(v["market"])}（{_e(COND.get(v["family"], v["family"]))}）</th><td class="num">{_yen(v["low"])}</td>'
                 f'<td class="num">{_yen(v["high"])}</td><td class="num">{_yen(v["median"])}</td><td class="num">{v["sample_count"]}</td>'
                 f'<td>{_e(v["period_start"])}〜{_e(v["period_end"])}</td><td>{"売値に使える" if v["eligible"] else "件数不足・売値にしない"}</td></tr>'
                 for v in (sec.get("sold") or {}).values())
    return (f'<section class="sku"><h3>{_e(p["product"])} — 二次流通</h3>'
            + (f'<div class="tw"><table><thead><tr><th>出品中（状態）</th><th title="Listing Low">出品の最安</th><th title="Listing High">出品の最高</th><th>件数</th><th>最安の出品元</th></tr></thead>'
               f'<tbody>{ls}</tbody></table></div><div class="mut">出品中の価格は売れた価格ではありません。出品の最高値は売値に使いません。</div>' if ls else "")
            + (f'<div class="tw"><table><thead><tr><th>海外の出品中（市場・状態）</th><th title="Listing Low">出品の最安（原通貨）</th><th title="Listing High">出品の最高（原通貨）</th><th>件数</th><th>為替</th></tr></thead>'
               f'<tbody>{lf}</tbody></table></div><div class="mut">海外の出品は希望価格で、売れた価格ではありません。送料・関税が不明のため、仕入れの利益計算には使いません。</div>' if lf else "")
            + (f'<div class="tw"><table><thead><tr><th>成約（市場・状態）</th><th title="SOLD Low">成約の最安</th><th title="SOLD High">成約の最高</th><th title="SOLD Median">成約の中央値</th><th title="SOLD Samples">成約の件数</th><th>期間</th><th>扱い</th></tr></thead>'
               f'<tbody>{sd}</tbody></table></div>' if sd else "")
            + "</section>")


def _live(l: dict, now: datetime) -> str:
    end = parse_dt(l.get("application_end")) if l.get("application_end") else None
    if end is None:
        return "応募期限を確認できません"
    return "終了" if end < now else "受付中・予定"


def _verdict(picks: list) -> str:
    """最上部の結論バー（2 行に圧縮）。今日買えるもの（購入候補）と黒字の件数・商品名。値は既存のルートの再表示だけ。
    黒字の件数に数えるのは、登録済みで調査が古くないルートだけ。未登録・古い調査は「参考」として別に数える（緑にしない）。
    緑は購入候補（登録済み・実行可能）だけ。様子見の黒字は中立色。"""
    buy = [(p, r) for p, r, st in picks if r["decision"] == "BUY" and not st and p.get("registered")]
    plus = [(p, r) for p, r, st in picks if (r.get("net_profit") or 0) > 0 and p.get("registered") and not st]
    ref_n = sum(1 for p, r, st in picks if (r.get("net_profit") or 0) > 0 and not (p.get("registered") and not st))

    def line(p, r):
        stock = STOCK.get((r.get("buy") or {}).get("stock"), "")
        return f'{_e(p["product"])}（{_signed(r["net_profit"])}・{_e(stock)}）'
    if buy:
        head = f'<span class="sbadge sbadge--buy">今日買えるもの {len(buy)} 件</span>'
        who = "、".join(line(p, r) for p, r in buy[:2])
    else:
        head = '<span class="sbadge sbadge--off">今日すぐ買えるもの 0 件</span>'
        who = "買ってよいと言えるルートはありません。"
    green = bool(buy) and bool(plus)
    ph = f'<span class="sbadge sbadge--{"profit" if green else "off"}">黒字 {len(plus)} 件</span>'
    if plus:
        pw = "、".join(line(p, r) for p, r in plus[:2]) + (f" ほか {len(plus) - 2} 件" if len(plus) > 2 else "")
        if not buy:
            pw += "（様子見）"
    else:
        pw = "黒字になるルートは確認できません。"
    if ref_n:
        pw += f"（参考 {ref_n} 件は除く）"
    return (f'<section class="verdict" aria-label="今日の結論"><p class="vline">{head}<span>{who}</span></p>'
            f'<p class="vline">{ph}<span>{pw}</span></p></section>')


_TABLE_RE = re.compile(r"<table(?P<attrs>[^>]*)>(?P<body>.*?)</table>", re.S)
_ROW_RE = re.compile(r"<tr(?P<ra>[^>]*)>(?P<cells>.*?)</tr>", re.S)
_CELL_RE = re.compile(r"(<t[dh])(?P<ca>[^>]*)>(?P<inner>.*?)(</t[dh]>)", re.S)


def _stack_tables(html: str) -> str:
    """まだカード化していない表を、スマホ幅で 1 行 1 カードに積む表（nu-table--stack）にする。
    見出し（thead の th）をセルの data-label にし、中身を div.v で包む。結合セル（colspan）の行は触らない。"""
    def one(m):
        if "nu-table--stack" in m.group("attrs") or "data-label" in m.group("body"):
            return m.group(0)
        head = re.search(r"<thead>(.*?)</thead>", m.group("body"), re.S)
        if not head:
            return m.group(0)
        labels = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", head.group(1), re.S)]
        tb = re.search(r"<tbody>(.*?)</tbody>", m.group("body"), re.S)
        if not tb:
            return m.group(0)

        def row(rm):
            if "colspan" in rm.group("cells"):
                return rm.group(0)
            i = [0]

            def cell(cm):
                lab = labels[i[0]] if i[0] < len(labels) else ""
                i[0] += 1
                inner = cm.group("inner") if cm.group(1) == "<th" and "<" not in cm.group("inner") else f'<div class="v">{cm.group("inner")}</div>'
                return f'{cm.group(1)}{cm.group("ca")} data-label="{_e(lab)}">{inner}{cm.group(4)}'
            return f'<tr{rm.group("ra")}>' + _CELL_RE.sub(cell, rm.group("cells")) + "</tr>"
        new_tb = _ROW_RE.sub(row, tb.group(1))
        body = m.group("body").replace(tb.group(0), "<tbody>" + new_tb + "</tbody>")
        attrs = m.group("attrs")
        attrs = (attrs.replace('class="', 'class="nu-table--stack ', 1) if 'class="' in attrs else attrs + ' class="nu-table--stack"')
        return f"<table{attrs}>{body}</table>"
    return _TABLE_RE.sub(one, html)


def render(market: dict, *, now: datetime | None = None) -> str:
    now = now or datetime.now(JST)
    rd = market.get("research_date")
    try:
        d_ = (now.date() - datetime.strptime(str(rd), "%Y-%m-%d").date()).days
        stale = d_ > 2 or d_ < 0
    except (TypeError, ValueError):
        stale = True
    prods = market.get("products") or []
    calc_rows, details, nocalc, cards, picks = [], [], [], [], []
    for p in prods:
        calc = [r for r in p["routes"] if r["profit_status"] != "NOT_CALCULATED"]
        for r in sorted(calc, key=lambda r: -(r["net_profit"] or 0)):
            st_ = stale or _row_stale(r, now)
            calc_rows.append(_row(p, r, st_))
            cards.append((0 if (r["net_profit"] or 0) > 0 else 1 if r["decision"] in ("WAIT", "WATCH") else 2, len(cards), _card(p, r, st_)))
            picks.append((p, r, st_))
            details.append((p, r))
        if not calc:
            best = next((r for r in p["routes"] if r["route_type"] == "A" and r.get("buy")), None) or next((r for r in p["routes"] if r.get("buy")), None)
            why = sorted({x for r in p["routes"] for x in r.get("reasons") or []})
            if any(o.get("price") and not o.get("reasons") for o in p["observations"]) or best:
                nocalc.append((p, _reasons(why)))
    why_cnt: dict = {}
    for _p, _r in details:                                   # 同じ売値の根拠が 2 ルート以上で並ぶなら 1 回にまとめる
        _w = _why_sell(_r["sell"])
        why_cnt[_w] = why_cnt.get(_w, 0) + 1
    common_why = frozenset(w for w, n in why_cnt.items() if n >= 2 and w != "—")
    why_note = ("<p class=\"mut\">共通の根拠: " + "／".join(_e(w) for w in sorted(common_why)) + "</p>") if common_why else ""
    details = [_detail(p, r, common_why) for p, r in details]
    rs_cnt: dict = {}
    for _p, _t in nocalc:                                    # 計算できなかった理由も、同じ文が 2 機種以上なら 1 回にまとめる
        rs_cnt[_t] = rs_cnt.get(_t, 0) + 1
    common_rs = frozenset(t for t, n in rs_cnt.items() if n >= 2 and t != "—")
    rs_note = ('<p class="mut">共通の理由: ' + "／".join(_e(t) for t in sorted(common_rs, key=lambda t: -rs_cnt[t])) + "</p>") if common_rs else ""
    nocalc = [f'<tr><th scope="row">{_e(p["product"])}{"" if p.get("registered") else " <span class=mut>（未登録・参考）</span>"}</th>'
              f'<td>{_e(_buy_summary(p))}</td><td>{_e(_sell_summary(p))}</td><td>{"上記の共通の理由" if t in common_rs else _e(t)}</td></tr>'
              for p, t in nocalc]
    summ = market.get("summary") or {}
    rt = summ.get("routes") or {}
    fd = summ.get("found") or {}
    buy_n = sum(1 for p in prods for r in p["routes"] if r["decision"] == "BUY" and not (stale or _row_stale(r, now)))
    empty = ('<div class="note">計算できる利益ルートは 0 件です。確認できた価格だけで計算し、架空の商品や推測の価格で埋めていません。'
             '下の「計算できなかった機種と理由」を見てください。判断カードは、価格を確認できた商品が出たときに表示されます。</div>') if not calc_rows else ""
    cards = [c for _, _, c in sorted(cards, key=lambda x: (x[0], x[1]))]          # 黒字・様子見を先頭、赤字・見送りを後ろ（同じ商品内の利益順は維持）
    verdict = _verdict(picks)
    src = _source_rows(market.get("source_results") or [])
    lots = "".join(
        f'<li><b>{_link(l.get("official_url"), l.get("product"))}</b> — {_e(l.get("retailer"))}／応募 {_e((l.get("application_start") or "")[:10])}〜{_e((l.get("application_end") or "")[:10])}'
        f'／{_e(_live(l, now))}／根拠: {_e(l.get("evidence"))}</li>' for l in market.get("lotteries") or []) or "<li>公式ページで確認できた抽選はありません</li>"
    hc = (market.get("hidden_counts") or {}).get("discovered_products_unverified", 0)
    html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>カメラ せどり判断 | プレ値速報</title><meta name="robots" content="index,follow"><style>{legacy_css()}{_CSS}{_CAMERA_CSS}</style></head>
<body>{site_nav("camera")}<main>
<p><a class="back" href="./">← プレ値速報へ戻る</a></p>
<h1>カメラ せどり判断</h1>
{verdict}
<p class="mut">調査日 {_md(rd)}（週 1 回の調査）</p>
{age_banner(rd, now)}
{empty}
<h2>判断カード</h2>
{"".join(cards) or '<p class="mut">判断できる商品はありません。</p>'}
<details class="note"><summary><b>この調査について</b>（確認できた価格だけで計算します）</summary><p>カードは黒字・様子見が先、赤字・見送りは後に並べています。購入・売却の前に各公式ページで最新の情報を確認してください。</p><p>{_plain(market.get("note"))}</p>
<p class="mut">調査データの生成 {_e(market.get("generated_at"))}／このページの状態は {_e(now.strftime("%Y-%m-%d %H:%M"))} 時点の判定です</p></details>
<div class="grid"><div class="kv"><span>調べた機種</span><b>{_e(summ.get("products_checked"))}</b></div>
<div class="kv"><span>買取価格を確認</span><b>{_e(fd.get("buyback"))} 件</b></div>
<div class="kv"><span>利益を計算できたルート</span><b>{_e(rt.get("confirmed"))} / {_e(rt.get("total"))}</b></div>
<div class="kv"><span>購入候補のルート</span><b>{_e(buy_n)} 件</b></div></div>
<h2>判断一覧（買う場所 → 売る場所）</h2>
<details class="spec"><summary>判断一覧の表を開く（カードと同じ内容を表で見る）</summary>
<div class="tw"><table class="nu-table--stack"><thead><tr><th>商品</th><th>買う場所・買値</th><th>売る場所・売値</th><th>費用</th><th>純利益</th><th>ROI</th><th>ルート</th><th>判断</th></tr></thead>
<tbody>{"".join(calc_rows) or '<tr><td colspan="8">計算できたルートはありません</td></tr>'}</tbody></table></div></details>
<div class="mut">黒字でも購入候補とは限りません（抽選・在庫・ROI・比較できる買取の数も条件です）。</div>
<details class="spec"><summary>買い方→売り方の4種類（正規店→買取など）</summary><div class="mut">A=正規店→買取（正規店・メーカーで買い、買取店へ売る）／B=正規店→二次流通（成約中央値で売る）／C=二次流通→買取（二次流通の最安で買い、買取店へ売る）／D=二次流通→二次流通（成約中央値で売る）。</div></details>
<h2>なぜこの売値か（計算の内訳）</h2>{why_note}<ul>{"".join(details) or "<li>計算できたルートはありません</li>"}</ul>
<h2>計算できなかった機種と理由</h2>
{rs_note}
<details class="spec"><summary>計算できなかった機種の表を開く（{len(nocalc)}件）</summary><div class="tw"><table><thead><tr><th>商品</th><th>確認できた買う側</th><th>確認できた売る側</th><th>計算できなかった理由</th></tr></thead><tbody>{"".join(nocalc) or '<tr><td colspan="4">なし</td></tr>'}</tbody></table></div></details>
{_kinds(summ, market)}
{_markets(market)}
<h2>二次流通（出品と成約は別物。最高の出品価格を売れる価格にしません）</h2>{"".join(_secondary(p) for p in prods) or "<p>確認できた二次流通の価格はありません（フリマ・オークションは検索結果を取得せず、成約は件数 3 以上・期間・個別の根拠が揃うものだけを使います）。</p>"}
<h2>抽選・予約（公式ページで確認できたもの）</h2><ul>{lots}</ul>
<h2>取得元の結果（読めた・読めなかった）</h2>
<details class="spec"><summary>取得元の表を開く（読めた・読めなかった）</summary><div class="tw"><table><thead><tr><th>取得元</th><th>種類</th><th>読めたブランド</th><th>読めなかったブランドと理由</th></tr></thead><tbody>{src}</tbody></table></div></details>
<ul><li>未確認の新商品 {_e(hc)} 件は、確認できるまで公開していません</li></ul>
<p class="mut">週次の調査で、価格・在庫・抽選の状況は変わっている場合があります。購入・売却の前に必ず各公式ページで最新の情報を確認してください。</p>
</main></body></html>"""
    return _stack_tables(html)


def _buy_summary(p: dict) -> str:
    xs = [f'{o["source"]} {_yen(o["price"])}（{STOCK.get(o.get("stock"), "在庫不明")}）' for o in p["observations"]
          if o["kind"] in ("official", "retail") and o.get("price") and not o["reasons"]]
    return "、".join(xs) or "確認できていない"


def _sell_summary(p: dict) -> str:
    xs = [f'{o["source"]} {_yen(o["price"])}（{COND.get(o["condition"], "")}{"・" + BASIS_SHORT[o["basis"]] if o.get("basis") in BASIS_SHORT else ""}）' for o in p["observations"]
          if o["kind"] == "buyback" and o.get("price") and not o["reasons"] and o["freshness"] == "FRESH"]
    return "、".join(xs[:3]) + ("…" if len(xs) > 3 else "") or "確認できていない"


def _source_rows(results: list) -> str:
    """取得元ごと（店・種類）に、読めたブランドと読めなかったブランド（理由つき）をまとめる。"""
    g: dict = {}
    for v in results:
        g.setdefault((v["shop"], v["role"]), []).append(v)
    out = []
    for (shop, role), vs in sorted(g.items()):
        okr = ("FOUND", "NO_EVENT_FOUND", "CONFIRMED_NO_CURRENT_EVENT", "NOT_LISTED")       # 成功の許可リスト（それ以外は読めなかった）
        ok = [x["brand"] for x in vs if str(x["result"]).upper() in okr]
        ng = [x for x in vs if str(x["result"]).upper() not in okr]
        bad = "；".join(f"{x['brand']}: {(x.get('reason') or '-')[:40]}" for x in ng[:4])
        out.append(f'<tr><th scope="row">{_e(shop)}</th><td>{"買取" if role == "buyback" else "販売・公式"}</td>'
                   f'<td>{_e("、".join(ok)) or "—"}</td><td>{_e(bad) or "—"}</td></tr>')
    return "".join(out)
