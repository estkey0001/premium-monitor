"""カメラの週次調査ページ（docs/camera-research.html）の描画。

入力は exports/camera_research/camera_research_weekly.json（src/research/weekly_import.py が作る）。
利益商品を無理に作らない。抽選に当たらないと仕入れられないものは LOTTERY_DEPENDENT（即時の BUY ではない）。
二次流通は出品と成約を分け、期待売値は作らない。純利益は「参考の推定」だけで、確定のルートとは書かない。
すべての文字は HTML エスケープ。リンクは http(s) だけ。
"""
from __future__ import annotations

import html as _html
from datetime import datetime, timedelta, timezone

from src.content.iphone_buyback_page import CSS as _CSS, age_banner
from src.tcg.models import parse_dt

JST = timezone(timedelta(hours=9))

STATUS_LABEL = {
    "LOTTERY_DEPENDENT": "LOTTERY_DEPENDENT（抽選に当たらないと仕入れられない・即時の BUY ではない）",
    "OUT_OF_STOCK": "OUT_OF_STOCK（公式は在庫なし・購入できない）",
    "UNCONFIRMED": "仕入れの条件を確認できていない",
}


def _e(v) -> str:
    return _html.escape("" if v is None else str(v))


def _yen(v) -> str:
    return "—" if v is None else f"¥{int(v):,}"


def _signed(v) -> str:
    return "—" if v is None else ("+" if v > 0 else "−" if v < 0 else "") + f"¥{abs(int(v)):,}"


def _link(url, label) -> str:
    u = str(url or "")
    return f'<a href="{_e(u)}" target="_blank" rel="noopener nofollow">{_e(label)}</a>' if u.startswith(("http://", "https://")) else _e(label)


def _product(p: dict) -> str:
    cands = "".join(
        f'<tr class="{"ok" if c.get("executable_candidate") else "ng"}"><th scope="row">{_e(c.get("where"))}</th>'
        f'<td class="num">{_yen(c.get("price")) if c.get("price") else _e(c.get("range") or "—")}</td>'
        f'<td>{_e("、".join(c.get("reasons") or [])) or "売却先の候補（確認済みの店・新しい価格）"}</td></tr>'
        for c in p.get("sell_candidates") or [])
    net = "".join(f"<li>{_e(n.get('where'))}: 売値 {_yen(n.get('sell'))} → 純利益 {_signed(n.get('net_before_purchase_shipping'))}"
                  f"{('（ROI ' + _e(n.get('roi_pct')) + '%）') if n.get('roi_pct') is not None else ''}（購入送料を含まない）</li>"
                  for n in p.get("reference_net") or []) or "<li>使える売却先の価格が無いため、計算していません</li>"
    buy = p.get("buy") or {}
    return (f'<section class="sku"><h3>{_e(p.get("product"))} <span class="chip chip--ref">{_e(STATUS_LABEL.get(p.get("status"), p.get("status")))}</span></h3>'
            f'<div class="grid"><div class="kv"><span>仕入れ先</span><b>{_e(buy.get("where"))}</b><em>{_e(buy.get("availability"))}</em></div>'
            f'<div class="kv"><span>仕入れ価格</span><b>{_yen(buy.get("price"))}</b><em>{_e(buy.get("price_note") or "")}</em></div>'
            f'<div class="kv"><span>即時の購入</span><b>できません</b><em>確定のルートではありません</em></div></div>'
            f'<div class="tw"><table><thead><tr><th>売却先の候補</th><th>価格</th><th>扱い</th></tr></thead><tbody>{cands}</tbody></table></div>'
            f'<details><summary>参考の推定（{_e(p.get("reference_label"))}）</summary><ul>{net}</ul></details>'
            f'<div class="mut">{_e(p.get("note"))}</div></section>')


def _secondary(x: dict) -> str:
    ls, sd = x.get("listing") or {}, x.get("sold") or {}
    return (f'<section class="sku"><h3>{_e(x.get("product"))} — 二次流通（新品）</h3><div class="grid">'
            f'<div class="kv"><span>出品中（LISTING）の最安</span><b>{_yen(ls.get("low"))}</b><em>最高 {_yen(ls.get("high"))}・{_e(ls.get("n") or "")}件 {_e(ls.get("note") or "")}</em></div>'
            f'<div class="kv"><span>成約（SOLD）の最安〜最高</span><b>{_yen(sd.get("low"))} 〜 {_yen(sd.get("high"))}</b><em>{_e(sd.get("n") or "")}件・期間 {_e(sd.get("period"))}</em></div>'
            f'<div class="kv"><span>成約の中央値</span><b>{_yen(sd.get("median"))}</b><em>{"確認できていない" if sd.get("median") is None else ""}</em></div>'
            f'<div class="kv"><span>期待売値</span><b>作りません</b><em>{_e(x.get("expected_sell_price_reason"))}</em></div></div>'
            f'<div class="mut">{_e(x.get("evidence"))}</div></section>')


def _live(l: dict, now: datetime) -> str:
    """応募期限と現在の日時から、ページを作るたびに決める（週次の JSON に状態を焼き込まない）。"""
    end = parse_dt(l.get("application_end")) if l.get("application_end") else None
    if end is None:
        return "応募期限を確認できません"
    return "終了" if end < now else "受付中・予定"


def render(summary: dict, *, now: datetime | None = None) -> str:
    now = now or datetime.now(JST)
    prods = "".join(_product(p) for p in summary.get("products") or [])
    sec = "".join(_secondary(x) for x in summary.get("secondary_market") or [])
    lots = "".join(
        f'<li><b>{_link(l.get("official_url"), l.get("product"))}</b> — {_e(l.get("retailer"))}／応募 {_e((l.get("application_start") or "")[:10])}〜{_e((l.get("application_end") or "")[:10])}'
        f'／{_e(_live(l, now))}／根拠: {_e(l.get("evidence"))}</li>' for l in summary.get("lotteries") or [])
    hc = summary.get("hidden_counts") or {}
    disc = (f'<li>未確認の新商品 {_e(hc.get("discovered_products_unverified", 0))} 件・未確認の抽選 {_e(hc.get("unverified_lotteries", 0))} 件・'
            f'原本を確認していない売却先の価格 {_e(hc.get("unverified_sell_candidates", 0))} 件は、確認できるまで公開していません</li>')
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>カメラ 週次調査 | プレ値速報</title><meta name="robots" content="index,follow"><style>{_CSS}</style></head>
<body><main>
<p><a href="./">← プレ値速報へ戻る</a></p>
<h1>カメラ 週次調査（参考）</h1>
<p class="mut">調査日 {_e(summary.get("research_date"))}（週1回の Web 調査・調査データの生成 {_e(summary.get("generated_at"))}）／このページの抽選の状態は {_e(now.strftime("%Y-%m-%d %H:%M"))} 時点の判定です</p>
{age_banner(summary.get("research_date"), now)}
<div class="note">{_e(summary.get("note"))}</div>
<h2>機種ごとの仕入れと売却</h2>{prods}
<h2>二次流通（出品と成約は別物。最高の出品価格・成約価格を売れる価格にしません）</h2>{sec}
<h2>抽選・予約</h2><ul>{lots}</ul>
<h2>確認できるまで公開していないもの</h2><ul>{disc}</ul>
<p class="mut">週次の調査で、価格・在庫・抽選の状況は変わっている場合があります。購入・売却の前に必ず各公式ページで最新の情報を確認してください。</p>
</main></body></html>"""
