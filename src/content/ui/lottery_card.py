"""新UIの抽選カード。

表示は runtime.derive_runtime_state の結果だけから作る。ブラウザ側（lottery_runtime.js の
updateCard）は同じ構造の要素を書き換えるので、ここの構造を変えるときは JS も合わせる。
"""

from __future__ import annotations

from src.content.ui.components import esc
from src.content.ui.runtime import _fmt_day, _fmt_exact


def _period(vm: dict, a: str, ad: str, b: str, bd: str) -> str:
    def one(k, kd):
        if vm.get(k):
            return _fmt_exact(vm[k])
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


def render(vm: dict, state: dict, idx: int, *, hidden: bool = False) -> str:
    parts = [
        f'<article class="nu-card" data-nu-lot="{esc(vm["id"])}" data-nu-bucket="{state["bucket"]}"'
        f' data-nu-sort="{state["sort"]}" data-nu-idx="{idx}" data-nu-status="{esc(state["status"])}"'
        f' data-nu-source="{esc(vm.get("src") or "")}" data-track="lottery_view"'
        f'{" hidden" if hidden else ""}>',
        f'<div class="nu-card__head"><h3 class="nu-card__title">{esc(vm.get("t"))}</h3>'
        f'<span class="nu-badge nu-tone-{esc(state["tone"])}" data-status="{esc(state["status"])}">'
        f'<span aria-hidden="true">{esc(state["icon"])}</span> {esc(state["label"])}</span></div>',
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
