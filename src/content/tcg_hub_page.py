# -*- coding: utf-8 -*-
"""TCG Lottery Hub（docs/tcg.html）の描画。入力は src.tcg.hub.product_view.build_hub の結果。

- 商品に紐付けできた抽選だけを商品ごとに束ね、紐付けできていない抽選は別枠（紐付け率も画面に出す）。
- 状態は生成時刻から導出し直したもの。確認日は元データの値をそのまま出す（ページの生成時刻を確認時刻にしない）。
- 利益は定価（検証済み）だけ。純利益・ROI は根拠が無いので「算出前」と書き、利益の並び替えは出さない。
- すべての文字は HTML エスケープ。リンクは https の公式ドメインだけ（応募の URL は検証を通ったものだけ・無ければリンクを作らない）。
- JS は絞り込みだけ（data 属性の表示切り替え。外部の値は埋め込まない）。JS が無くても全件が見える。
"""
from __future__ import annotations

import html as _html
from datetime import datetime
from typing import Optional

from src.tcg import action_url as au
from src.tcg.hub import product_view as pv
from src.tcg.hub import status as st
from src.tcg.hub.product_view import build_hub
from src.tcg.lottery import schema as ls
from src.tcg.models import JST, now_jst

TCG_LABEL = {"POKEMON": "ポケモンカード", "ONE_PIECE": "ONE PIECE カード"}
CANON_LABEL = {pv.C_MASTER: "商品マスタと一致", pv.C_DISCOVERED: "イベントから発見（商品マスタ外）",
               pv.C_AMBIGUOUS: "商品が複数に当てはまる", pv.C_UNMATCHED: "商品に紐付けできていない"}
PRIO_LABEL = {st.P_S: "S 今すぐ", st.P_A: "A 応募したい", st.P_B: "B 余裕あり", st.P_WATCH: "WATCH 要確認"}
CHANNEL_LABEL = {au.CH_WEB_OFFICIAL: "公式の応募ページ", au.CH_EXTERNAL_FORM: "外部の応募フォーム", au.CH_APP: "アプリ",
                 au.CH_SNS: "SNS（フォロー＆リポスト）", au.CH_MEMBER_LOGIN: "会員ログイン", au.CH_STORE_COUNTER: "店頭",
                 au.CH_UNKNOWN: "応募経路は未確認"}
REQ_LABEL = {au.R_MEMBERSHIP: "会員登録", au.R_APP: "アプリ", au.R_PURCHASE_HISTORY: "購入履歴", au.R_IDENTITY: "本人確認",
             au.R_STORE_PICKUP: "店頭受取", au.R_SNS: "SNS フォロー＆リポスト"}
KIND_LABEL = {"PREORDER": "予約", "STORE_LOTTERY": "店舗の抽選", "APP_LOTTERY": "アプリ抽選", "WEB_LOTTERY": "WEB 抽選", "LOTTERY": "抽選"}
PTYPE_LABEL = {"BOOSTER_BOX": "拡張パック（BOX）", "STARTER_DECK": "スターター", "CONSTRUCTED_DECK": "構築済みデッキ",
               "SPECIAL_SET": "スペシャルセット", "PREMIUM_COLLECTION": "プレミアムコレクション", "OTHER": "その他"}
WEEKDAY = "月火水木金土日"
PRODUCT_HOSTS = ("pokemon-card.com",)          # 商品の公式ページとして許可するドメイン（サブドメイン可）

CSS = """
:root{--bg:#f6f7f9;--fg:#1c2330;--mut:#5b6575;--card:#fff;--line:#d9dee6;--acc:#1f5fbf;--ok:#17703a;--warn:#a45a00;--bad:#b3261e}
@media(prefers-color-scheme:dark){:root{--bg:#10141b;--fg:#e6e9ef;--mut:#9aa4b2;--card:#181e28;--line:#2b3442;--acc:#7fb0ff;--ok:#5fcf8a;--warn:#e0a24a;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"Hiragino Sans",sans-serif}
main{max-width:980px;margin:0 auto;padding:16px}h1{font-size:1.4rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.6em 0 .5em;border-bottom:2px solid var(--line);padding-bottom:.2em}
h3{font-size:1rem;margin:.9em 0 .3em}a{color:var(--acc)}.mut{color:var(--mut);font-size:.88em}
nav.jump{display:flex;flex-wrap:wrap;gap:6px;margin:.6em 0}nav.jump a{border:1px solid var(--line);background:var(--card);border-radius:999px;padding:3px 12px;text-decoration:none;font-size:.9em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.stat b{display:block;font-size:1.4rem}.box{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:8px 0}
.warn{border-color:var(--warn)}.ev{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:8px 0}
.ev[hidden]{display:none}.ev h4{margin:0 0 .3em;font-size:.98rem}.badge{display:inline-block;border:1px solid var(--line);border-radius:4px;padding:0 6px;font-size:.8em;margin-right:4px}
.b-open,.b-ending{border-color:var(--ok);color:var(--ok)}.b-ending{border-color:var(--bad);color:var(--bad)}.b-watch{border-color:var(--warn);color:var(--warn)}
dl.kv{display:grid;grid-template-columns:7.5em 1fr;gap:2px 8px;margin:.3em 0}dl.kv dt{color:var(--mut)}dl.kv dd{margin:0;overflow-wrap:anywhere}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:.6em 0}.filters label{font-size:.85em;color:var(--mut)}.filters select{display:block;max-width:100%}
.cal li{margin:.15em 0}details summary{cursor:pointer;color:var(--mut)}footer{margin:2em 0 1em;color:var(--mut);font-size:.85em}
"""

JS = """
(function(){try{
var f=document.getElementById('flt');if(!f)return;
function run(){var v={};['tcg','product','retailer','region','state'].forEach(function(k){v[k]=f.elements[k].value;});
document.querySelectorAll('.ev').forEach(function(e){var d=e.dataset,ok=true;
['tcg','product','retailer','region'].forEach(function(k){if(v[k]&&d[k]!==v[k])ok=false;});
if(v.state&&(' '+d.state+' ').indexOf(' '+v.state+' ')<0)ok=false;e.hidden=!ok;});}
f.addEventListener('change',run);}catch(e){}})();
"""


def _short(v) -> str:
    """確認日時の表示（元の値の先頭 16 文字 = 分まで。値そのものは変えない）。"""
    t = str(v or "").strip()
    return t[:16].replace("T", " ") if t else "不明"


def _e(v) -> str:
    return _html.escape("" if v is None else str(v), quote=True)


def _link(url, label) -> str:
    return f'<a href="{_e(url)}" target="_blank" rel="noopener nofollow">{_e(label)}</a>' if url else ""


def _product_link(url) -> str:
    r = au.safe_https(url)
    if r and any(r[0] == h or r[0].endswith("." + h) for h in PRODUCT_HOSTS):
        return _link(r[1], "公式の商品ページ")
    return ""


def _fmt(w: dict) -> str:
    """日付だけの項目は時刻を作らず、日付だけだと明示する。"""
    if not w or not w.get("date"):
        return "未公表"
    return f'{w["date"]} {w["time"]}' if w.get("time") else f'{w["date"]}（日付のみ・時刻未公表）'


def _range(a: dict, b: dict) -> str:
    """期間の表示。両端が日付だけなら「（日付のみ）」を 1 回だけ付ける。どちらも無ければ未公表。"""
    if not (a.get("date") or b.get("date")):
        return "未公表"
    if a.get("date") and b.get("date") and not a.get("time") and not b.get("time"):
        return f'{a["date"]}〜{b["date"]}（日付のみ・時刻未公表）'
    return f'{_fmt(a)}〜{_fmt(b)}'


def _yen(n) -> str:
    return f"¥{int(n):,}"


def _wd(date: str) -> str:
    try:
        return WEEKDAY[datetime.strptime(date, "%Y-%m-%d").weekday()]
    except ValueError:
        return ""


def _badge(text, cls="") -> str:
    return f'<span class="badge {cls}">{_e(text)}</span>'


def _status_badge(v: dict) -> str:
    cls = {"OPEN": "b-open", "ENDING_SOON": "b-ending"}.get(v["status"], "")
    return _badge(v["status_label"], cls)


def _state_tokens(v: dict) -> str:
    toks = []
    if v["status"] == ls.L_OPEN:
        toks.append("open")
    if v["status"] == ls.L_ENDING_SOON:
        toks.append("ending")
    if v["status"] == ls.L_UPCOMING:
        toks.append("upcoming")
    return " ".join(toks)


def _ev_card(v: dict, pidx: dict, *, with_product: bool) -> str:
    ev = v["ev"]
    shop = ev.get("store_name") or ev.get("retailer_name") or ev.get("retailer") or "店舗不明"
    region = ev.get("prefecture") or ""
    p_key = pidx.get((ev.get("tcg"), ev.get("product_id"))) if v.get("canonical") in (pv.C_MASTER, pv.C_DISCOVERED) else None
    attrs = (f'data-tcg="{_e(ev.get("tcg"))}" data-product="{_e(p_key or "none")}" data-retailer="{_e(ev.get("retailer"))}" '
             f'data-region="{_e(region or "unknown")}" data-state="{_e(_state_tokens(v))}"')
    purchase = _range(v["purchase_start"], v["purchase_end"])
    reqs = [REQ_LABEL.get(r, r) for r in v["requirements"]]
    elig = (str(ev.get("eligibility_text") or "")[:200]) or None
    links = [_link(v["application_url"], "公式の応募ページ"), _link(v["announcement_url"], "公式の告知")]
    links = [x for x in links if x]
    head = (f'{_e(ev.get("product_name") or "商品名不明")}<br>' if with_product else "")
    prio = _badge(PRIO_LABEL[v["priority"]], "b-watch" if v["priority"] == st.P_WATCH else "") if v["priority"] else ""
    return (f'<article class="ev" {attrs}><h4>{head}{_status_badge(v)}{prio}{_e(shop)}'
            f' <span class="mut">{_e(ev.get("retailer_name") or "")}{"・" + _e(region) if region else ""}</span></h4><dl class="kv">'
            f'<dt>種別</dt><dd>{_e(KIND_LABEL.get(v["entry_kind"], v["entry_kind"]))}</dd>'
            f'<dt>応募開始</dt><dd>{_e(_fmt(v["start"]))}</dd><dt>応募期限</dt><dd>{_e(_fmt(v["end"]))}</dd>'
            f'<dt>当選発表</dt><dd>{_e(_fmt(v["result"]))}</dd><dt>購入期間</dt><dd>{_e(purchase)}</dd>'
            f'<dt>応募経路</dt><dd>{_e(CHANNEL_LABEL.get(v["channel"], v["channel"]))}</dd>'
            f'<dt>応募条件</dt><dd>{_e("、".join(reqs)) if reqs else "明記なし"}{"（原文: " + _e(elig) + "）" if elig else ""}</dd>'
            f'<dt>確認</dt><dd>{"確認済み" if v["verified"] else "未確認（公式での再確認待ち）"}'
            f'{"・日程に食い違いあり" if ev.get("conflict") else ""}'
            f' <span class="mut">確認日 {_e(ev.get("last_verified_at") or ev.get("observed_at") or "不明")}</span></dd>'
            f'<dt>リンク</dt><dd>{" / ".join(links) if links else "応募ページの URL は未確認（リンクを作っていません）"}</dd>'
            f'</dl></article>')


def _cards(views, pidx, *, with_product=True, empty="該当なし") -> str:
    return "".join(_ev_card(v, pidx, with_product=with_product) for v in views) or f'<p class="mut">{_e(empty)}</p>'


def _product_block(p: dict, i: int, pidx: dict) -> str:
    pr = p["profit"]
    m = pr["msrp"]
    price = (f'{_yen(m["retail_price"])}（公式・確認日 {_e(m["checked_at"] or "不明")}）' if m else "未確認（検証済みの定価がありません）")
    live = [v for v in p["events"] if v["status"] != ls.L_ENDED]
    ended = [v for v in p["events"] if v["status"] == ls.L_ENDED]
    c = p["counts"]
    meta = (f'{_e(TCG_LABEL.get(p["tcg"], p["tcg"]))}・{_e(CANON_LABEL[p["canonical"]])}'
            f'{"・" + _e(PTYPE_LABEL.get(p["product_type"], p["product_type"])) if p["product_type"] else ""}')
    rel = _e(p["release_date"]) if p["release_date"] else ("商品マスタが無いため未取得" if p["canonical"] == pv.C_DISCOVERED else "未公表")
    body = _cards(live, pidx, with_product=False, empty="現在受付中・開始前の抽選・予約は確認できていません（終了したものは下に表示）")
    if ended:
        body += f'<details><summary>終了した抽選 {len(ended)} 件</summary>{_cards(ended, pidx, with_product=False)}</details>'
    return (f'<section class="box" id="p{i}"><h3>{_e(p["name"])}</h3><div class="mut">{meta}</div><dl class="kv">'
            f'<dt>発売日</dt><dd>{rel}</dd><dt>定価</dt><dd>{price}</dd>'
            f'<dt>利益</dt><dd>{_e(pr["label"])}（{_e(pr["reason"])}）</dd>'
            f'<dt>状態</dt><dd>{_status_badge({"status": p["status"], "status_label": st.STATUS_LABEL[p["status"]]})}'
            f'{_badge("優先度 " + PRIO_LABEL[p["priority"]]) if p["priority"] else ""}</dd>'
            f'<dt>抽選の件数</dt><dd>現在 {c["live"]} 件（受付中 {c["open"]}・締切間近 {c["ending_soon"]}・近日開始 {c["upcoming"]}・今日応募可能 {c["today"]}）</dd>'
            f'<dt>公式</dt><dd>{_product_link(p["official_url"]) or "公式ページの URL は未確認"}</dd></dl>{body}</section>')


def _calendar(cal: list) -> str:
    if not cal:
        return '<p class="mut">これから先の日程は確認できていません。</p>'
    out, cur = [], None
    for c in cal:
        if c["date"] != cur:
            if cur is not None:
                out.append("</ul>")
            cur = c["date"]
            out.append(f'<h3>{_e(cur)}（{_e(_wd(cur))}）</h3><ul class="cal">')
        t = f'{_e(c["time"])} ' if c["time"] else ""
        where = " ".join(x for x in (c["retailer"], c["store"]) if x)
        out.append(f'<li><b>{_e(pv.KIND_LABEL[c["kind"]])}</b> {t}'
                   f'{"" if c["time"] or c["kind"] == pv.K_RELEASE else "<span class=mut>（日付のみ）</span> "}'
                   f'{_e(c["label"])}{"　" + _e(where) if where else ""}{"" if c["verified"] else " <span class=mut>[未確認]</span>"}</li>')
    out.append("</ul>")
    return "".join(out)


def render(hub: dict, *, generated_label: Optional[str] = None) -> str:
    """hub は build_hub の結果。壊れた hub でも例外にしない（空のページを返す）。"""
    hub = hub if isinstance(hub, dict) else build_hub(None, None, None)
    s = hub["stats"]
    ck = hub["checked_at"]
    products = hub["products"]
    pidx = {(p["tcg"], p["product_id"]): f"p{i}" for i, p in enumerate(products)}
    rate = "—" if s["bind_rate"] is None else f'{round(s["bind_rate"] * 100)}%'
    rate_live = "—" if s["bind_rate_live"] is None else f'{round(s["bind_rate_live"] * 100)}%'
    retailers = sorted({(v["ev"].get("retailer") or "", v["ev"].get("retailer_name") or v["ev"].get("retailer") or "") for v in hub["events"] if v["ev"].get("retailer")})
    regions = sorted({v["ev"].get("prefecture") for v in hub["events"] if v["ev"].get("prefecture")})
    opt = lambda items: "".join(f'<option value="{_e(k)}">{_e(lbl)}</option>' for k, lbl in items)
    filters = (
        '<form id="flt" class="filters" onsubmit="return false">'
        f'<label>TCG<select name="tcg"><option value="">すべて</option>{opt(TCG_LABEL.items())}</select></label>'
        f'<label>商品<select name="product"><option value="">すべて</option>{opt((f"p{i}", p["name"]) for i, p in enumerate(products))}'
        f'<option value="none">商品に紐付けできていない抽選</option></select></label>'
        f'<label>店舗<select name="retailer"><option value="">すべて</option>{opt(retailers)}</select></label>'
        f'<label>地域<select name="region"><option value="">すべて</option>{opt((r, r) for r in regions)}<option value="unknown">地域の記載なし</option></select></label>'
        '<label>状態<select name="state"><option value="">すべて</option><option value="open">受付中</option>'
        '<option value="ending">締切間近</option><option value="upcoming">近日開始</option></select></label></form>')
    stats = "".join(f'<div class="stat"><b>{_e(val)}</b>{_e(lbl)}</div>' for lbl, val in (
        ("今日応募可能", s["today"]), ("今日締切", s["deadline_today"]), ("締切間近", s["ending_soon"]), ("近日開始", s["upcoming"]),
        ("新着（公式の告知から3日以内）", s["new"]), ("抽選・予約（終了を除く）", s["events_live"]),
        ("商品に紐付けできた抽選", f'{s["bound_exact"]} / {s["events_total"]}（{rate}）'), ("商品ブロック", s["products"])))
    answers = (
        '<ul>'
        '<li><b>この新弾は今どこで応募できる？</b> → <a href="#products">商品ごとのブロック</a>の「現在の抽選」を見てください。'
        '商品に紐付けできていない抽選は<a href="#unbound">別枠</a>です。</li>'
        f'<li><b>今日締切は？</b> → <a href="#deadline-today">今日締切 {s["deadline_today"]} 件</a>（今日応募可能は <a href="#today">{s["today"]} 件</a>）。</li>'
        '<li><b>当選発表はいつ？</b> → 各抽選の「当選発表」欄と<a href="#calendar">カレンダー</a>。</li>'
        '<li><b>購入期間は？</b> → 各抽選の「購入期間」欄。未公表のものは「未公表」と出します。</li>'
        '<li><b>利益が高い商品は？</b> → <b>算出前</b>です。TCG の買取・二次流通・eBay の根拠が無いため、利益や順位は出していません。'
        '出せるのは公式の定価だけです。</li></ul>')
    low = (f'<div class="box warn"><b>商品への紐付け率が低い状態です（全体 {_e(rate)}・終了を除くと {_e(rate_live)}）。</b>'
           '商品名が似ているだけでは商品に結ばず、紐付けできていない抽選は下の別枠に出しています。</div>') if (s["bind_rate"] is not None and s["bind_rate"] < 0.5) else ""
    unbound = hub["unbound"]
    ub_live = [v for v in unbound if v["status"] != ls.L_ENDED]
    ub_end = [v for v in unbound if v["status"] == ls.L_ENDED]
    ub_body = _cards(ub_live, pidx, empty="なし")
    if ub_end:
        ub_body += f'<details><summary>終了した抽選 {len(ub_end)} 件</summary>{_cards(ub_end, pidx)}</details>'
    legend = ("<p class='mut'>応募優先度: S=締切間近で応募ページまで確認済み／A=受付中で商品に紐付け済み／B=その他の受付中・開始前／"
              "WATCH=日程未確認・未確認・商品に紐付けできていないもの。利益や点数ではなく、既存の判定を並べたものです。</p>")
    gen = _e(generated_label or hub["now"])
    stale_banner = ""
    try:                                                       # 元の抽選データが古いときは警告（収集が止まっても新鮮に見せない）
        from datetime import date as _date
        gd = _date.fromisoformat(str(ck["lotteries_generated_at"] or "")[:10])
        nd = _date.fromisoformat(str(hub["now"])[:10])
        if (nd - gd).days >= 2:
            stale_banner = f'<div class="box warn"><b>抽選データの取得が {(nd - gd).days} 日前です（取得 {_e(ck["lotteries_generated_at"])}）。</b>最新の状況ではない可能性があります。</div>'
    except (ValueError, TypeError):
        stale_banner = '<div class="box warn"><b>抽選データの取得日時が確認できません。</b>最新の状況ではない可能性があります。</div>'

    body = (
        f'<h1>TCG 抽選ハブ</h1><p class="mut">ポケモンカード・ONE PIECE カードの公式の抽選・予約を、商品ごとにまとめています。'
        f'自動応募はしません。応募は必ず公式のページで確認してください。</p>'
        f'<div class="box warn"><b>この一覧の「受付中」「今日締切」などの状態は {gen} 時点のものです。</b>'
        'このページは 1 日 1 回の更新で、開いている間は進みません。締切を過ぎていないか、応募の前に必ず公式ページで確認してください。</div>'
        f'{stale_banner}'
        '<nav class="jump"><a href="#today">今日応募可能</a><a href="#deadline-today">今日締切</a><a href="#new">新着</a>'
        '<a href="#ending">締切間近</a><a href="#upcoming">近日開始</a><a href="#products">商品ごと</a>'
        '<a href="#unbound">紐付けなし</a><a href="#calendar">カレンダー</a><a href="#checked">確認日</a></nav>'
        f'<div class="grid">{stats}</div>{low}<h2>このページで分かること</h2>{answers}{legend}<h2>絞り込み</h2>{filters}'
        f'<h2 id="today">今日応募可能（{s["today"]}）</h2>{_cards(hub["today_list"], pidx, empty="今日応募できる抽選は確認できていません。")}'
        f'<h2 id="deadline-today">今日締切（{s["deadline_today"]}）</h2>{_cards(hub["deadline_today"], pidx, empty="今日締切の抽選は確認できていません。")}'
        f'<h2 id="new">新着（{s["new"]}）</h2><p class="mut">公式の告知の公開日が分かるものだけ。初めて見つけた日は使っていません。</p>'
        f'{_cards(hub["new"], pidx, empty="新着として出せるものはありません（公式の公開日が確実なものだけを出します）。")}'
        f'<h2 id="ending">締切間近（{s["ending_soon"]}）</h2>{_cards(hub["ending_soon"], pidx, empty="なし")}'
        f'<h2 id="upcoming">近日開始（{s["upcoming"]}）</h2>{_cards(hub["upcoming"], pidx, empty="公式に開始日が確認できた近日開始の抽選はありません。")}'
        f'<h2 id="products">商品ごと（{s["products"]}）</h2>'
        '<p class="mut">商品に束ねたのは、商品 ID まで一致（exact）した抽選だけです。ポケモンカードは公式の商品一覧と照合し、'
        'ONE PIECE は商品一覧が無いため、イベントの商品名だけで表示しています（発売日・定価・画像は出しません）。</p>'
        f'{"".join(_product_block(p, i, pidx) for i, p in enumerate(products)) or "<p class=mut>商品に束ねられた抽選はありません。</p>"}'
        f'<h2 id="unbound">商品に紐付けできていない抽選（{len(unbound)}）</h2>'
        '<p class="mut">商品名が部分的にしか一致しない・該当する商品が無い・複数の商品に当てはまるもの。推測で商品に結んでいません。</p>'
        f'{ub_body}'
        f'<h2 id="calendar">カレンダー（{s["calendar"]}）</h2><p class="mut">今日以降の応募開始・締切・当選発表・購入期間・発売日。日付だけの項目は日付のみ表示します。</p>{_calendar(hub["calendar"])}'
        f'<h2 id="checked">確認日</h2><dl class="kv"><dt>抽選データ</dt><dd>取得 {_e(_short(ck["lotteries_generated_at"]))}／判定 {_e(_short(ck["lotteries_evaluated_at"]))}</dd>'
        f'<dt>商品一覧</dt><dd>{_e(_short(ck["registry_generated_at"]))}</dd><dt>定価</dt><dd>{_e(_short(ck["msrp_generated_at"]))}</dd>'
        f'<dt>状態の導出</dt><dd>{gen}（このページを作った時点。確認時刻ではありません）</dd></dl>'
        '<footer>状態は生成時点のものです。応募・購入の前に必ず公式ページで確認してください。本ページは購入や利益を保証しません。</footer>')
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>TCG 抽選ハブ | プレ値速報</title><meta name="robots" content="index,follow"><style>{CSS}</style></head>'
            f'<body><main>{body}</main><script>{JS}</script></body></html>')


def render_from_json(lotteries, registry, msrp, now: Optional[datetime] = None) -> str:
    """公開済み JSON の辞書から直接ページを作る。"""
    now = (now or now_jst()).astimezone(JST)
    return render(build_hub(lotteries, registry, msrp, now), generated_label=now.strftime("%Y-%m-%d %H:%M JST"))
