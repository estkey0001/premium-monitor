"""iPhone 買取比較ページ（docs/iphone-buyback.html）の描画。

入力は exports/iphone_buyback/iphone_buyback_comparison.json（src/research/weekly_import.py が作る週次の調査結果）。
- 買取店ごとの価格を一覧にする（最高値だけにして他店を捨てない）。条件（新品未開封）・色減額・更新日時・状態を出す。
- identity が DISCOVERED の SKU は「参考」と書く（正本に未登録。BUY・確認済みとは書かない）。
- 調査は週 1 回。掲載価格で、買取の確定ではない。ページに調査日を出し、古い調査を現在の価格のように見せない。
- すべての文字は HTML エスケープ。リンクは http(s) だけ。
"""
from __future__ import annotations

import html as _html
from datetime import datetime, timedelta, timezone

_JST = timezone(timedelta(hours=9))

BASIS_LABEL = {
    "uniform": "色で変わらない", "worst_color": "減額が最大の色の価格", "colors_unverified": "色減額 未確認（上限）",
    "indicative": "目安の最大（確定でない）", "range_only": "範囲だけ（価格にしない）",
}
STATUS_LABEL = {"ACTIVE": "取得できた", "NO_PRICE": "価格が見つからない", "BLOCKED": "取得を拒否された", "FAILED": "取得できなかった",
                "STALE": "更新が古い"}
COND_LABEL = {"UNOPENED": "新品未開封", "OPENED_NEW": "開封済み新品・未使用品", "USED": "中古"}


def age_banner(research_date, now) -> str:
    """調査日から日数がたったら警告する（週次の調査。古い調査を現在の価格のように見せない）。"""
    try:
        days = (now.date() - datetime.strptime(str(research_date), "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        return '<div class="note">調査日を確認できません。</div>'
    if days <= 7:
        return ""
    return (f'<div class="note"><b>調査から {days} 日たっています。</b>価格・在庫・抽選の状況は変わっている可能性が高いです。'
            f'次の週次の調査まで、公式ページで必ず最新の情報を確認してください。</div>')


def _e(v) -> str:
    return _html.escape("" if v is None else str(v))


def _yen(v) -> str:
    return "—" if v is None else f"¥{int(v):,}"


def _signed(v) -> str:
    if v is None:
        return "—"
    return ("+" if v > 0 else "−" if v < 0 else "") + f"¥{abs(int(v)):,}"


def _link(url, label) -> str:
    u = str(url or "")
    return f'<a href="{_e(u)}" target="_blank" rel="noopener nofollow">{_e(label)}</a>' if u.startswith(("http://", "https://")) else _e(label)


def _colors(row: dict) -> str:
    ca = row.get("color_adjustments") or {}
    if row.get("basis") == "colors_unverified":
        return "未確認"
    if not ca:
        return "なし（掲載なし）"
    return "、".join(f"{_e(k)} {_e(v)}" for k, v in list(ca.items())[:4])


FRESH_LABEL = {"FRESH": "FRESH（更新が新しい）", "STALE": "STALE（更新が古い）", "UNKNOWN_FRESHNESS": "更新日の記載なし"}
OUTLIER_LABEL = {"NONE": "外れ値なし", "OUTLIER_REVIEW": "OUTLIER_REVIEW（最高値が他店より大きく高い・確認待ち）",
                 "REVIEWED": "外れ値を確認済み", "SINGLE_SOURCE": "比較できる店が1つだけ（確認待ち）", "NO_DATA": "比較できる価格なし"}


def _row_html(r: dict) -> str:
    notes = []
    if r.get("shop_status") != "ACTIVE":
        notes.append(STATUS_LABEL.get(r.get("shop_status"), ""))
    if r.get("condition") != "UNOPENED":
        notes.append("別の状態（利益計算に使わない）")
    if r.get("freshness") == "STALE":
        notes.append("STALE（更新が古く、利益計算の主要価格に使わない。休業日などで更新が無いだけの場合もあり、誤価格とは限らない）")
    if r.get("basis") in BASIS_LABEL and r["basis"] not in ("uniform", "worst_color"):
        notes.append(BASIS_LABEL[r["basis"]])
    price = r.get("executable_price")
    listed = r.get("listed_price")
    shown = _yen(price) if price is not None else (_yen(listed) + "（掲載・上限）" if listed else "—")
    extra = f'<div class="mut">{_e(r["campaign"])}（期間限定・通常価格に含めない）</div>' if r.get("campaign") else ""
    cls = "ok" if r.get("eligible") else "ng"
    age = f"（{r['age_days']}日前）" if r.get("age_days") is not None else ""
    return (f'<tr class="{cls}"><th scope="row">{_link(r.get("price_page_url"), r.get("shop"))}</th><td class="num">{shown}</td>'
            f'<td>{_e(COND_LABEL.get(r.get("condition"), r.get("condition")))}</td><td>{_colors(r)}</td>'
            f'<td>{_e(r.get("updated_on") or "更新日の記載なし")}{_e(age)}<div class="mut">{_e(FRESH_LABEL.get(r.get("freshness"), ""))}</div></td>'
            f'<td>{_e("、".join(n for n in notes if n)) or "利益計算の候補"}{extra}</td></tr>')


def _sku_html(s: dict) -> str:
    ref = s.get("identity") != "REGISTERED"
    badge = ('<span class="chip chip--ref">参考・正本に未登録</span>' if ref else '<span class="chip chip--ok">正本に登録済み</span>')
    hl, hx, unc = s.get("highest_listed"), s.get("highest_executable"), s.get("highest_unconfirmed")
    sec, thi = s.get("second"), s.get("third")

    def one(label, x, extra=""):
        return f'<div class="kv"><span>{label}</span><b>{_e(x["shop"]) if x else "—"}</b><em>{_yen(x["price"]) if x else ""}{extra}</em></div>'
    net = s.get("net_profit")
    net_cls = ("pos" if (net or 0) > 0 and not ref else "neg" if (net or 0) < 0 else "")        # 参考（未登録）の黒字は緑にしない
    out = s.get("outlier_status") or "NO_DATA"
    listed_note = ""
    if hl:
        listed_note = f' ／ {_e(FRESH_LABEL.get(hl.get("freshness"), ""))}／{"利益計算に使う価格" if hl.get("executable") else "利益計算に使わない"}'
    exec_card = one("最高の実行可能買取", hx) if hx else (
        f'<div class="kv"><span>最高の実行可能買取</span><b>確認待ち</b><em>最高値 {_e(unc["shop"])} {_yen(unc["price"])}（{_e(unc["status"])}）</em></div>' if unc
        else '<div class="kv"><span>最高の実行可能買取</span><b>—</b><em>比較できる価格なし</em></div>')
    ref_net = s.get("reference_net_at_second")
    ref_html = (f'<div class="mut">参考: 次点（{_e(ref_net["shop"])} {_yen(ref_net["price"])}）で計算すると純利益 {_signed(ref_net["net_profit"])}。'
                f'次点は最高の実行可能価格ではありません。</div>' if ref_net else "")
    route = (f'<div class="route">最大利益ルート: {_e(s["best_route"])}</div>' if s.get("best_route")
             else f'<div class="route">参考の最大ルート（正本に未登録のため確定ではない）: {_e(s["reference_route"])}</div>' if s.get("reference_route")
             else '<div class="route mut">利益が出るルートは確認できません</div>')
    rows = "".join(_row_html(r) for r in s.get("rows") or [])
    return (f'<section class="sku"><h3>{_e(s["sku"])} {badge}</h3>'
            f'<div class="grid"><div class="kv"><span>Apple 定価（税込）</span><b>{_yen(s["apple_price"])}</b></div>'
            f'{one("掲載の最高値", hl, listed_note)}{exec_card}{one("実行可能 2位", sec)}{one("実行可能 3位", thi)}'
            f'<div class="kv"><span>買取店の数</span><b>{_e(s.get("source_count", 0))} 店</b><em>うち更新が新しい {_e(s.get("fresh_source_count", 0))} 店</em></div>'
            f'<div class="kv"><span>外れ値の判定</span><b>{_e(OUTLIER_LABEL.get(out, out))}</b></div>'
            f'<div class="kv"><span>諸経費</span><b>{_yen(s.get("costs"))}</b></div>'
            f'<div class="kv"><span>純利益{"（参考）" if ref else ""}</span><b class="{net_cls}">{_signed(net)}</b>'
            f'<em>ROI {("%.1f%%" % s["roi_pct"]) if s.get("roi_pct") is not None else "—"}</em></div></div>'
            f'{route}{ref_html}<div class="mut">{_e(s.get("identity_note"))}</div>'
            f'<details><summary>買取店ごとの価格（{len(s.get("rows") or [])} 行）</summary>'
            f'<div class="tw"><table><thead><tr><th>買取店</th><th>買取価格</th><th>条件</th><th>色減額</th><th>更新日・鮮度</th><th>扱い</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></details></section>')


CSS = """
:root{--bg:#fff;--fg:#1c2330;--mut:#667085;--line:#e4e7ec;--card:#f8fafc;--ok:#067647;--ng:#b42318;--ref:#b54708;--link:#1d4ed8}
@media (prefers-color-scheme:dark){:root{--bg:#10141c;--fg:#e8ecf3;--mut:#9aa4b2;--line:#2a3140;--card:#171c26;--ok:#47cd89;--ng:#f97066;--ref:#fdb022;--link:#7aa2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif}
main{max-width:980px;margin:0 auto;padding:16px}a{color:var(--link)}h1{font-size:1.35rem;margin:.2rem 0}h2{font-size:1.1rem;margin:1.6rem 0 .6rem}h3{font-size:1.02rem;margin:0 0 .6rem}
.mut{color:var(--mut);font-size:.85rem}.note{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:.8rem 0}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:.8rem 0}.sum div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px}.sum b{display:block;font-size:1.25rem}
.sku{border:1px solid var(--line);border-radius:12px;padding:12px;margin:12px 0;background:var(--bg)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.kv{background:var(--card);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column}.kv span{color:var(--mut);font-size:.78rem}.kv b{font-size:1.05rem;overflow-wrap:anywhere}.kv em{font-style:normal;color:var(--mut);font-size:.82rem;overflow-wrap:anywhere}
.pos{color:var(--ok)}.neg{color:var(--ng)}.chip{font-size:.72rem;padding:2px 8px;border-radius:99px;border:1px solid var(--line);vertical-align:middle;font-weight:600}.chip--ref{color:var(--ref)}.chip--ok{color:var(--ok)}
.route{margin:.6rem 0 .2rem;font-weight:700}details{margin-top:.6rem}summary{cursor:pointer;color:var(--link)}.tw{overflow-x:auto;margin-top:.5rem}
table{border-collapse:collapse;width:100%;min-width:640px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;font-size:.85rem;vertical-align:top}th[scope=row]{font-weight:600}.num{text-align:right;white-space:nowrap}tr.ng td,tr.ng th{color:var(--mut)}
ul{padding-left:1.1rem}
"""


def render(comp: dict, *, now: datetime | None = None) -> str:
    now = now or datetime.now(_JST)
    counts = comp.get("counts") or {}
    skus = "".join(_sku_html(s) for s in comp.get("skus") or [])
    missing = [s for s in comp.get("shops") or [] if s.get("status") != "ACTIVE" or s.get("rows_count", 0) == 0]
    miss_html = "".join(
        f'<li><b>{_link(s.get("price_page_url") or s.get("official_url"), s.get("shop"))}</b> — {_e(STATUS_LABEL.get(s.get("status"), s.get("status")))}'
        f'{("（新規に発見した店）" if s.get("discovered") else "")}<span class="mut"> {_e(s.get("reason"))}</span></li>' for s in missing)
    events = comp.get("events") or []
    ev_html = ("".join(f"<li>{_e(e.get('type'))}: {_e(e.get('sku'))} {_e(e.get('shop') or e.get('to') or '')}</li>" for e in events)
               or f'<li class="mut">{_e(comp.get("events_note") or "変動の記録はまだありません")}</li>')
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>iPhone 買取比較 | プレ値速報</title><meta name="robots" content="index,follow"><style>{CSS}</style></head>
<body><main>
<p><a href="./">← プレ値速報へ戻る</a></p>
<h1>iPhone 買取比較（新品未開封）</h1>
<p class="mut">調査日 {_e(comp.get("research_date"))}（週1回の Web 調査・調査データの生成 {_e(comp.get("generated_at"))}）／このページの作成 {_e(now.strftime("%Y-%m-%d %H:%M"))}</p>
{age_banner(comp.get("research_date"), now)}
<div class="note">{_e(comp.get("note"))}</div>
<div class="sum"><div><span class="mut">調べた買取店</span><b>{_e(comp.get("shops_researched"))}</b></div>
<div><span class="mut">価格を取れた店</span><b>{_e(counts.get("ACTIVE", 0))}</b></div>
<div><span class="mut">更新が新しい（FRESH）</span><b>{_e(counts.get("FRESH", 0))}</b></div>
<div><span class="mut">更新が古い（STALE）</span><b>{_e(counts.get("STALE", 0))}</b></div>
<div><span class="mut">更新日の記載なし</span><b>{_e(counts.get("UNKNOWN_FRESHNESS", 0))}</b></div>
<div><span class="mut">価格なし</span><b>{_e(counts.get("NO_PRICE", 0))}</b></div>
<div><span class="mut">取得失敗・拒否</span><b>{_e(counts.get("FAILED", 0) + counts.get("BLOCKED", 0))}</b></div></div>
<h2>SKU ごとの比較</h2>
{skus}
<h2>価格を取れなかった店・価格が部分的な店</h2><ul>{miss_html}</ul>
<h2>前回からの変動</h2><ul>{ev_html}</ul>
<p class="mut">この表は週次の調査で、価格が変わっている場合があります。売る前に各店の公式の価格ページで最新の価格・条件（事前申込・検品・減額）を必ず確認してください。取得できない店の回避（認証の突破・過剰なアクセス）は行っていません。</p>
</main></body></html>"""
