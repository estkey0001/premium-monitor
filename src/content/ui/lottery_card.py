"""新UIの抽選カード。

表示は runtime.derive_runtime_state の結果だけから作る。ブラウザ側（lottery_runtime.js の
updateCard）は同じ構造の要素を書き換えるので、ここの構造を変えるときは JS も合わせる。
"""

from __future__ import annotations

from src.content.ui.components import esc
from src.content.ui.product_image import vm_figure
from src.content.ui.runtime import _fmt_day, _fmt_exact, _time_ok


def _period(vm: dict, a: str, ad: str, b: str, bd: str) -> str:
    def one(k, kd):
        if vm.get(k):
            return _fmt_exact(vm[k], _time_ok(vm))
        if vm.get(kd):
            return f"{_fmt_day(vm[kd])}（時刻未公表）"
        return ""
    x, y = one(a, ad), one(b, bd)
    if x and y:
        return f"{x} 〜 {y}"
    return x or y


def _details(vm: dict) -> str:
    rows = [
        ("情報の確かさ", vm.get("conf") or ""),
        ("応募期間", _period(vm, "as", "asd", "ae", "aed")),
        ("当選発表", _period(vm, "wa", "wad", "", "")),
        ("購入期間", _period(vm, "ps", "psd", "pe", "ped")),
    ]
    if vm.get("conflict"):
        rows.append(("ご注意", "公式情報どうしで日程が食い違っています。応募前に公式ページで日程をご確認ください。"))
    body = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows if v)
    return (f'<details class="nu-details" data-track="lottery_detail_open"><summary>詳しく見る</summary>'
            f'<dl>{body}</dl></details>') if body else ""


def cta_html(cta: dict | None) -> str:
    if not cta or not str(cta.get("url") or "").startswith("https://"):
        return ""
    return (f'<a class="nu-btn nu-btn--{esc(cta["style"])}" href="{esc(cta["url"])}" target="_blank"'
            f' rel="noopener nofollow" data-track="{esc(cta["track"])}" data-nu-cta="{esc(cta["kind"])}">'
            f'{esc(cta["label"])}</a>')


_PRIO_TITLE = {"S": "応募優先度 S: 締切間近で、応募ページまで確認できています",
               "A": "応募優先度 A: 受付中で、商品に紐付け済みです"}


def _prio_badge(vm: dict) -> str:
    p = vm.get("prio")
    if p not in _PRIO_TITLE:
        return ""
    return f'<span class="nu-badge nu-tone-info nu-prio" title="{esc(_PRIO_TITLE[p])}">優先 {esc(p)}</span>'


def _profit_badge(vm: dict) -> str:
    """買取店のページの価格から利益を出せた商品の抽選だけ（買取が未確認の商品には出さない）。"""
    pf = vm.get("prof")
    if not isinstance(pf, dict) or not isinstance(pf.get("net"), int):
        return ""
    tip = (f'買取店のページの価格と公式定価の差から計算（店頭受取・店頭持込の前提。交通費は含みません）。純利益 {pf["net"]:+,}円・ROI {pf["roi"]}%'
           + ("。買取は 1 店のみ（単一ソース）" if pf.get("single") else ""))
    from src.tcg import buyback as _bb, runtime_freshness as _rf
    cfg = _bb.load_config()
    g = f'data-fb-group="{esc(vm.get("id"))}"'
    # 閲覧時に取得時刻から鮮度を判定し直す（最初は hidden。FRESH を確認できたときだけ出す）。8 時間を超えたら「再確認待ち」にする
    live = (f'<span class="nu-badge nu-tone-info nu-profit" data-fb-live {g} {_rf.attrs(pf.get("obs"), cfg)} hidden title="{esc(tip)}">'
            f'利益根拠あり</span>')
    stale = (f'<span class="nu-badge nu-tone-neutral" data-fb-stale {g} data-fb-max="{_rf.thresholds(cfg)[0]:g}" '
             f'title="取得から{_rf.thresholds(cfg)[0]:g}時間を超えた買取価格は、利益の根拠にしません">買取価格 再確認待ち</span>')
    return live + stale


def render(vm: dict, state: dict, idx: int, *, hidden: bool = False) -> str:
    parts = [
        f'<article class="nu-card" data-nu-lot="{esc(vm["id"])}" data-nu-bucket="{state["bucket"]}"'
        f' data-nu-sort="{state["sort"]}" data-nu-idx="{idx}" data-nu-status="{esc(state["status"])}"'
        f' data-nu-source="{esc(vm.get("src") or "")}" data-track="lottery_view"'
        f'{" hidden" if hidden else ""}>',
        f'<div class="nu-card__head">{vm_figure(vm, 72)}<h3 class="nu-card__title" style="flex:1;min-width:0">{esc(vm.get("t"))}</h3>'
        f'<span class="nu-badge nu-tone-{esc(state["tone"])}" data-status="{esc(state["status"])}">'
        f'<span aria-hidden="true">{esc(state["icon"])}</span> {esc(state["label"])}</span>{_prio_badge(vm)}{_profit_badge(vm)}</div>',
    ]
    if vm.get("sub"):
        parts.append(f'<p class="nu-card__sub">{esc(vm["sub"])}</p>')
    if vm.get("price"):
        parts.append(f'<p class="nu-card__metric">{esc(vm["price"])}</p>')
    parts.append(f'<p class="nu-card__meta"><span class="nu-when">{esc(state["when"])}</span>'
                 f'<span class="nu-cd">{esc(state["cd_text"])}</span></p>')
    parts.append(cta_html(state["cta"]))
    parts.append(_details(vm))
    parts.append("</article>")
    return "".join(parts)
