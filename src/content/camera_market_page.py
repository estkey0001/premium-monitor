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

from src.content.iphone_buyback_page import CSS as _CSS, age_banner
from src.tcg.models import parse_dt

JST = timezone(timedelta(hours=9))

COND = {"NEW": "新品", "UNOPENED": "新品未開封", "LIKE_NEW": "新品同様", "USED": "中古", "UNKNOWN": "状態不明"}
STOCK = {"AVAILABLE": "購入できる", "OUT_OF_STOCK": "在庫なし", "LOTTERY_DEPENDENT": "抽選に当選が必要", "RESERVATION": "予約のみ", "UNKNOWN": "在庫不明"}
PTYPE = {"BUYBACK_PRICE": "買取価格", "SOLD_MEDIAN": "成約中央値", "OFFICIAL_RETAIL": "公式の販売価格", "RETAIL_PRICE": "販売店の価格",
         "LISTING_LOW": "出品中の最安（売れた価格ではない）"}
DECISION = {"BUY": "BUY（買う）", "WATCH": "WATCH（要確認）", "WAIT": "WAIT（待つ）", "SKIP": "SKIP（見送り）"}
PROFIT = {"PROFITABLE": "黒字", "NO_PROFIT": "赤字・利益なし", "NOT_CALCULATED": "未計算"}
REASON = {
    "no_profit": "利益が出ない", "stock_lottery_dependent": "抽選に当選しないと買えない", "stock_reservation": "予約のみで今は買えない",
    "out_of_stock": "在庫なし", "stock_unknown": "在庫が確認できない", "unregistered_product": "正本に未登録の機種",
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
    "duplicate_sold": "同じ成約の重複", "no_item_url": "個別の成約ページの URL がない",
    "price_kind_OPEN_PRICE": "オープン価格で金額が確認できない", "price_kind_NOT_FOUND": "公式の価格を確認できない",
}


MKT_STATUS = {"AVAILABLE": "取得できた", "PARTIAL": "一部取得", "BLOCKED": "取得できない（未取得）", "FAILED": "取得に失敗（未取得）", "NOT_SUPPORTED": "提供されていない（未取得）"}
MKT_REASON = {
    "no_official_api_search_scrape_prohibited": "公式 API が無く、検索結果の取得は行わない方針のため",
    "official_api_discontinued": "公式 API が 2020 年に終了しているため",
    "no_official_api_robots_disallow_search": "公式 API が無く、robots.txt が検索を禁止しているため",
    "official_api_not_configured": "公式 API の資格情報が未登録（NOT_CONFIGURED）のため",
    "official_api_not_enabled": "公式 API が有効化されていないため",
    "adapter_not_implemented": "公式 API のアダプターが未実装のため",
    "rows_from_research_file": "調査員が根拠 URL つきで読んだ行だけ",
    "adapter_not_run": "公式 API のアダプターを今回は実行していないため",
    "api_listing_only": "公式 API で出品中の価格だけ（成約は審査制で未承認）", "api_ok": "公式 API で取得",
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
        f'<tr><th scope="row">{_e(m.get("label"))}</th><td><b>{_e(MKT_STATUS.get(m.get("status"), m.get("status")))}</b></td>'
        f'<td>{_e(MKT_REASON.get(m.get("reason"), m.get("reason")))}{"（公式 API の取得に失敗しました）" if m.get("api_error") else ""}</td><td>{_e(CRED.get(m.get("credentials"), m.get("credentials")))}</td>'
        f'<td class="num">{_e(_rows(m.get("listing_rows")))}</td><td class="num">{_e(_rows(m.get("sold_rows")))}</td>'
        f'<td>{_e(FEE_STATUS.get(m.get("fee_status"), m.get("fee_status")))}{" ・" + str(round(100 * m["fee_rate"], 1)) + "%" if m.get("fee_rate") else ""}</td>'
        f'<td>{_e(m.get("checked_on"))}</td></tr>' for m in mk)
    apis = "".join(f'<li>{_e(a.get("label"))}の公式 API: {_e(CRED.get(a.get("reason"), "未登録" if a.get("reason") == "NOT_CONFIGURED" else "未有効・未実装"))}（{_e(a.get("scope"))}）</li>'
                   for a in market.get("retail_apis") or [])
    return ('<h2>二次流通の取得状況（市場ごと）</h2>'
            '<div class="note">取得できなかった市場は「未取得」であって、出品や成約が無いという意味ではありません。検索結果の取得は行わず、公式 API と、根拠 URL つきで読んだ行だけを使います。</div>'
            '<div class="tw"><table><thead><tr><th>市場</th><th>状態</th><th>理由</th><th>API 資格情報</th><th>出品（Listing）</th><th>成約（Sold）</th><th>販売手数料</th><th>確認日</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
            + (f'<ul class="mut">{apis}</ul>' if apis else ""))


def _kinds(summ: dict, market: dict | None = None) -> str:
    fd = summ.get("found") or {}
    mk = (market or {}).get("secondary_markets") or []
    no_l = bool(mk) and all(m.get("listing_rows") is None for m in mk)      # 全市場が未取得なら「0 件」と書かない
    no_s = bool(mk) and all(m.get("sold_rows") is None for m in mk)
    return ('<h2>価格の種類ごとの確認状況</h2><div class="grid">'
            f'<div class="kv"><span>Primary Market（公式・販売店）</span><b>{_e(fd.get("official_or_retail_prices"))} 件</b></div>'
            f'<div class="kv"><span>Buyback（買取）</span><b>{_e(fd.get("buyback"))} 件</b></div>'
            f'<div class="kv"><span>Secondary Listings（出品中）</span><b>{"未取得（全市場）" if no_l and not fd.get("listing") else _e(fd.get("listing")) + " 件"}</b></div>'
            f'<div class="kv"><span>Secondary Sold（成約）</span><b>{"未取得（全市場）" if no_s and not fd.get("sold") else _e(fd.get("sold")) + " 件"}</b></div></div>')


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


def _why_sell(s: dict) -> str:
    """「なぜこの売値か」。買取か成約中央値か、その根拠。"""
    if not s:
        return "—"
    ev = s.get("evidence") or {}
    if s.get("price_type") == "SOLD_MEDIAN":
        return f"成約中央値（{ev.get('sample_count')}件・期間 {ev.get('period')}・{COND.get(s.get('condition'), s.get('condition'))}）"
    upd = s.get("source_updated_at") or "更新日不明"
    return (f"買取価格（{COND.get(s.get('condition'), '')}・{s.get('source')}・店の更新 {upd}・"
            f"比較できた買取 {ev.get('shops', 1)} 店）")


def _row_stale(r: dict, now: datetime, buy_days: int = 2, sell_days: int = 7) -> bool:
    """行ごとの古さ。仕入れ（在庫）は buy_days 日、売値は sell_days 日を超えたら、BUY を出さない。未来の日付も古い扱い。"""
    out = []
    for x, lim in ((r.get("buy") or {}, buy_days), (r.get("sell") or {}, sell_days)):
        d = parse_dt(x.get("checked_at")) if x.get("checked_at") else None
        if d is None or d > now + timedelta(days=1) or (now - d).days > lim:
            out.append(True)
    return bool(out)


def _row(p: dict, r: dict, stale: bool) -> str:
    b, s = r["buy"], r["sell"]
    dec = "調査が古い（参考）" if (stale and r["decision"] == "BUY") else DECISION.get(r["decision"], r["decision"])
    net = (f'{_signed(r["net_profit"])}' if r["net_profit"] is not None else "未計算")
    roi = f'{r["roi_pct"]}%' if r["roi_pct"] is not None else "—"
    cls = "ok" if r["decision"] == "BUY" and not stale else ""
    c_ = r.get("costs") or {}
    cost = _yen(sum(int(c_.get(k) or 0) for k in ("purchase_shipping", "outbound_shipping", "selling_fee", "other"))) if c_ else "—"
    return (f'<tr class="{cls}"><th scope="row">{_e(p["product"])}{"" if p.get("registered") else " <span class=mut>（未登録・参考）</span>"}</th>'
            f'<td>{_e(COND.get(b["condition"], b["condition"]))}</td>'
            f'<td>{_link(b.get("url"), b["source"])}<br><span class="mut">{_e(PTYPE.get(b["price_type"], b["price_type"]))}</span></td>'
            f'<td class="num">{_yen(b["price"])}</td><td>{_e(STOCK.get(b.get("stock"), b.get("stock")))}</td>'
            f'<td>{_link(s.get("url"), s["source"]) if s else "—"}</td><td class="num">{_yen(s["price"]) if s else "—"}</td>'
            f'<td>{_e(PTYPE.get(s["price_type"], s["price_type"])) if s else "—"}</td>'
            f'<td class="num">{cost}</td><td class="num">{net}</td><td class="num">{roi}</td><td>{_e(r["route_type"])}</td>'
            f'<td>{_e(b.get("checked_at"))}{"（買取は引き継ぎ・古い確認）" if (s and s.get("carried")) or b.get("carried") else ""}</td><td>{_e(r.get("confidence"))}</td><td><b>{_e(dec)}</b><br>'
            f'<span class="mut">{_e(_reasons(r.get("reasons")))}</span></td></tr>')


def _detail(p: dict, r: dict) -> str:
    c = r["costs"] or {}
    return (f'<li><b>{_e(p["product"])} / ルート {_e(r["route_type"])}（{_e(r["route_label"])}）</b>: '
            f'売値 {_yen(r["sell"]["price"])}（{_e(_why_sell(r["sell"]))}）− 仕入れ {_yen(r["buy"]["price"])} − 購入送料 {_yen(c.get("purchase_shipping"))}'
            f' − 発送など {_yen(c.get("outbound_shipping"))} − 販売手数料 {_yen(c.get("selling_fee"))}'
            f'{"（" + str(round(100 * c["selling_fee_rate"])) + "%・" + _e(FEE_STATUS.get(r.get("fee_status"), r.get("fee_status"))) + "）" if c.get("selling_fee_rate") else "（買取は手数料なし）"}'
            f' − その他 {_yen(c.get("other"))} = 純利益 {_signed(r["net_profit"])}</li>')


def _secondary(p: dict) -> str:
    sec = p.get("secondary") or {}
    if not sec.get("listing") and not sec.get("sold"):
        return ""
    ls = "".join(f'<tr><th scope="row">{_e(COND.get(k, k))}</th><td class="num">{_yen(v["low"])}</td><td class="num">{_yen(v["high"])}</td>'
                 f'<td class="num">{v["n"]}</td><td>{_e(v["low_source"])}</td></tr>' for k, v in (sec.get("listing") or {}).items())
    sd = "".join(f'<tr><th scope="row">{_e(v["market"])}（{_e(COND.get(v["family"], v["family"]))}）</th><td class="num">{_yen(v["low"])}</td>'
                 f'<td class="num">{_yen(v["high"])}</td><td class="num">{_yen(v["median"])}</td><td class="num">{v["sample_count"]}</td>'
                 f'<td>{_e(v["period_start"])}〜{_e(v["period_end"])}</td><td>{"売値に使える" if v["eligible"] else "件数不足・売値にしない"}</td></tr>'
                 for v in (sec.get("sold") or {}).values())
    return (f'<section class="sku"><h3>{_e(p["product"])} — 二次流通</h3>'
            + (f'<div class="tw"><table><thead><tr><th>出品中（状態）</th><th>Listing Low</th><th>Listing High</th><th>件数</th><th>最安の出品元</th></tr></thead>'
               f'<tbody>{ls}</tbody></table></div><div class="mut">出品中の価格は売れた価格ではありません。Listing High は売値に使いません。</div>' if ls else "")
            + (f'<div class="tw"><table><thead><tr><th>成約（市場・状態）</th><th>SOLD Low</th><th>SOLD High</th><th>SOLD Median</th><th>SOLD Samples</th><th>期間</th><th>扱い</th></tr></thead>'
               f'<tbody>{sd}</tbody></table></div>' if sd else "")
            + "</section>")


def _live(l: dict, now: datetime) -> str:
    end = parse_dt(l.get("application_end")) if l.get("application_end") else None
    if end is None:
        return "応募期限を確認できません"
    return "終了" if end < now else "受付中・予定"


def render(market: dict, *, now: datetime | None = None) -> str:
    now = now or datetime.now(JST)
    rd = market.get("research_date")
    try:
        d_ = (now.date() - datetime.strptime(str(rd), "%Y-%m-%d").date()).days
        stale = d_ > 2 or d_ < 0
    except (TypeError, ValueError):
        stale = True
    prods = market.get("products") or []
    calc_rows, details, nocalc = [], [], []
    for p in prods:
        calc = [r for r in p["routes"] if r["profit_status"] != "NOT_CALCULATED"]
        for r in sorted(calc, key=lambda r: -(r["net_profit"] or 0)):
            calc_rows.append(_row(p, r, stale or _row_stale(r, now)))
            details.append(_detail(p, r))
        if not calc:
            best = next((r for r in p["routes"] if r["route_type"] == "A" and r.get("buy")), None) or next((r for r in p["routes"] if r.get("buy")), None)
            why = sorted({x for r in p["routes"] for x in r.get("reasons") or []})
            if any(o.get("price") and not o.get("reasons") for o in p["observations"]) or best:
                nocalc.append(f'<tr><th scope="row">{_e(p["product"])}{"" if p.get("registered") else " <span class=mut>（未登録・参考）</span>"}</th>'
                              f'<td>{_e(_buy_summary(p))}</td><td>{_e(_sell_summary(p))}</td><td>{_e(_reasons(why))}</td></tr>')
    summ = market.get("summary") or {}
    rt = summ.get("routes") or {}
    fd = summ.get("found") or {}
    buy_n = sum(1 for p in prods for r in p["routes"] if r["decision"] == "BUY" and not (stale or _row_stale(r, now)))
    empty = ('<div class="note">計算できる利益ルートは 0 件です。確認できた価格だけで計算し、架空の商品や推測の価格で埋めていません。'
             '下の「計算できなかった理由」を見てください。</div>') if not calc_rows else ""
    src = _source_rows(market.get("source_results") or [])
    lots = "".join(
        f'<li><b>{_link(l.get("official_url"), l.get("product"))}</b> — {_e(l.get("retailer"))}／応募 {_e((l.get("application_start") or "")[:10])}〜{_e((l.get("application_end") or "")[:10])}'
        f'／{_e(_live(l, now))}／根拠: {_e(l.get("evidence"))}</li>' for l in market.get("lotteries") or []) or "<li>公式ページで確認できた抽選はありません</li>"
    hc = (market.get("hidden_counts") or {}).get("discovered_products_unverified", 0)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>カメラ せどり判断 | プレ値速報</title><meta name="robots" content="index,follow"><style>{_CSS}</style></head>
<body><main>
<p><a href="./">← プレ値速報へ戻る</a></p>
<h1>カメラ せどり判断</h1>
<p class="mut">調査日 {_e(rd)}（週 1 回の調査・生成 {_e(market.get("generated_at"))}）／このページの状態は {_e(now.strftime("%Y-%m-%d %H:%M"))} 時点の判定です</p>
{age_banner(rd, now)}
<div class="note">{_e(market.get("note"))}</div>
<div class="grid"><div class="kv"><span>調べた機種</span><b>{_e(summ.get("products_checked"))}</b></div>
<div class="kv"><span>買取価格を確認</span><b>{_e(fd.get("buyback"))} 件</b></div>
<div class="kv"><span>利益を計算できたルート</span><b>{_e(rt.get("confirmed"))} / {_e(rt.get("total"))}</b></div>
<div class="kv"><span>今 BUY のルート</span><b>{_e(buy_n)} 件</b></div></div>
{empty}
{_kinds(summ, market)}
{_markets(market)}
<h2>判断一覧（買う場所 → 売る場所）</h2>
<div class="tw"><table><thead><tr><th>商品</th><th>状態</th><th>買う場所</th><th>買値</th><th>買える状態</th><th>売る場所</th><th>売値</th><th>売値タイプ</th><th>費用</th><th>純利益</th><th>ROI</th><th>Route</th><th>checked_at</th><th>confidence</th><th>判断</th></tr></thead>
<tbody>{"".join(calc_rows) or '<tr><td colspan="15">計算できたルートはありません</td></tr>'}</tbody></table></div>
<div class="mut">Route A=正規店・メーカー→買取店／B=正規店・メーカー→二次流通（成約中央値）／C=二次流通の最安→買取店／D=二次流通の最安→二次流通（成約中央値）。黒字でも BUY とは限りません（抽選・在庫・ROI・比較できる買取の数も条件です）。</div>
<h2>なぜこの売値か（計算の内訳）</h2><ul>{"".join(details) or "<li>計算できたルートはありません</li>"}</ul>
<h2>計算できなかった機種と理由</h2>
<div class="tw"><table><thead><tr><th>商品</th><th>確認できた買う側</th><th>確認できた売る側</th><th>計算できなかった理由</th></tr></thead><tbody>{"".join(nocalc) or '<tr><td colspan="4">なし</td></tr>'}</tbody></table></div>
<h2>二次流通（出品と成約は別物。最高の出品価格を売れる価格にしません）</h2>{"".join(_secondary(p) for p in prods) or "<p>確認できた二次流通の価格はありません（フリマ・オークションは検索結果を取得せず、成約は件数 3 以上・期間・個別の根拠が揃うものだけを使います）。</p>"}
<h2>抽選・予約（公式ページで確認できたもの）</h2><ul>{lots}</ul>
<h2>取得元の結果（読めた・読めなかった）</h2>
<div class="tw"><table><thead><tr><th>取得元</th><th>種類</th><th>読めたブランド</th><th>読めなかったブランドと理由</th></tr></thead><tbody>{src}</tbody></table></div>
<ul><li>未確認の新商品 {_e(hc)} 件は、確認できるまで公開していません</li></ul>
<p class="mut">週次の調査で、価格・在庫・抽選の状況は変わっている場合があります。購入・売却の前に必ず各公式ページで最新の情報を確認してください。</p>
</main></body></html>"""


def _buy_summary(p: dict) -> str:
    xs = [f'{o["source"]} {_yen(o["price"])}（{STOCK.get(o.get("stock"), "在庫不明")}）' for o in p["observations"]
          if o["kind"] in ("official", "retail") and o.get("price") and not o["reasons"]]
    return "、".join(xs) or "確認できていない"


def _sell_summary(p: dict) -> str:
    xs = [f'{o["source"]} {_yen(o["price"])}（{COND.get(o["condition"], "")}）' for o in p["observations"]
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
