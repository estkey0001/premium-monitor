"""新UIの共通部品（バッジ・ボタン・カード・空状態・タイル）。

どの部品も HTML 文字列を返す。値はすべてここでエスケープする。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from src.content.ui import status as st


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def badge(key: str) -> str:
    """状態バッジ（文言＋アイコン＋色）。色だけで伝えない。"""
    s = st.get(key)
    return (f'<span class="nu-badge nu-tone-{s.tone}" data-status="{esc(s.key)}">'
            f'<span aria-hidden="true">{esc(s.icon)}</span> {esc(s.label)}</span>')


def safe_href(href: str) -> str:
    """リンクにしてよい href だけを返す（https: の URL、または ?・./ で始まるサイト内の相対パス）。

    javascript: / data: / vbscript: / http: など、それ以外は空文字（リンクにしない）。
    """
    s = str(href or "").strip()
    if not s or any(ch in s for ch in "\x00\r\n\t"):
        return ""
    if s.startswith(("?", "./", "#")) or re.match(r"^[A-Za-z0-9_\-]+/?(\?|#|$)", s):
        return s
    from src.content.ui.runtime import safe_url
    return safe_url(s)


def button(label: str, href: str, *, kind: str = "primary", external: bool = False,
           track: str = "", aria_label: str = "") -> str:
    """ボタン（高さ44px以上）。kind は primary / secondary / link。"""
    href = safe_href(href)
    if not href:
        return ""
    attrs = [f'class="nu-btn nu-btn--{esc(kind)}"', f'href="{esc(href)}"']
    if external:
        attrs.append('target="_blank" rel="noopener nofollow"')
    if track:
        attrs.append(f'data-track="{esc(track)}"')
    if aria_label:
        attrs.append(f'aria-label="{esc(aria_label)}"')
    return f'<a {" ".join(attrs)}>{esc(label)}</a>'


@dataclass
class Card:
    """共通カード。いつも見せる情報は最大6つ（title / subtitle / status /
    primary_metric / secondary_metric / CTA）。技術的な情報は details へ入れる。"""

    title: str
    subtitle: str = ""
    status: str = ""                    # status.STATUSES のキー
    primary_metric: str = ""
    secondary_metric: str = ""
    cta_label: str = ""
    cta_href: str = ""
    cta_external: bool = True
    cta_kind: str = "primary"           # primary / secondary（現行版への導線などは secondary）
    cta_track: str = ""
    details: list[tuple[str, str]] = field(default_factory=list)  # (項目名, 値)
    details_summary: str = "詳しく見る"
    deadline_iso: str = ""              # カウントダウン用（時刻が公表されているときだけ）
    deadline_prefix: str = "締切まで"
    attrs: dict[str, str] = field(default_factory=dict)

    # いつも見せる情報の上限（DESIGN_SYSTEM.md 6章）
    MAX_PRIMARY_FIELDS = 6

    def primary_field_count(self) -> int:
        return sum(1 for v in (self.title, self.subtitle, self.status, self.primary_metric,
                               self.secondary_metric, self.cta_label) if v)

    def render(self) -> str:
        extra = "".join(f' data-{esc(k)}="{esc(v)}"' for k, v in self.attrs.items())
        parts = [f'<article class="nu-card"{extra}>']
        head = f'<h3 class="nu-card__title">{esc(self.title)}</h3>'
        if self.status:
            head += badge(self.status)
        parts.append(f'<div class="nu-card__head">{head}</div>')
        if self.subtitle:
            parts.append(f'<p class="nu-card__sub">{esc(self.subtitle)}</p>')
        if self.primary_metric:
            parts.append(f'<p class="nu-card__metric">{esc(self.primary_metric)}</p>')
        if self.secondary_metric:
            cd = ""
            if self.deadline_iso:
                cd = (f' data-nu-deadline="{esc(self.deadline_iso)}"'
                      f' data-nu-prefix="{esc(self.deadline_prefix)}"')
            parts.append(f'<p class="nu-card__meta"{cd}>{esc(self.secondary_metric)}</p>')
        if self.cta_label and safe_href(self.cta_href):
            parts.append(button(self.cta_label, self.cta_href, kind=self.cta_kind,
                                external=self.cta_external, track=self.cta_track))
        if self.details:
            rows = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in self.details if v)
            if rows:
                parts.append(f'<details class="nu-details"><summary>{esc(self.details_summary)}'
                             f'</summary><dl>{rows}</dl></details>')
        parts.append("</article>")
        return "".join(parts)


# 空状態の種類。NO_DATA（情報そのものが無い）と NO_ACTIVE（情報はあるが今は対象が無い）を分ける
EMPTY_KINDS = ("NO_DATA", "NO_ACTIVE", "SOURCE_BLOCKED", "COLLECTOR_ERROR")


def empty_state(kind: str, message: str, hint: str = "") -> str:
    """空状態。「無い理由」と「次に起きること／代わりにできること」を1組で出す。"""
    if kind not in EMPTY_KINDS:
        kind = "NO_DATA"
    hint_html = f'<p class="nu-empty__hint">{esc(hint)}</p>' if hint else ""
    return (f'<div class="nu-empty" data-empty="{esc(kind)}" role="status">'
            f'<p class="nu-empty__msg">{esc(message)}</p>{hint_html}</div>')


def notice(message: str, *, href: str = "", link_label: str = "詳しく") -> str:
    """一般ユーザー向けの1行の注意。内部の件数・エラー内容は出さない。"""
    link = f' <a href="{esc(href)}">{esc(link_label)}</a>' if href else ""
    return f'<p class="nu-notice" role="note">ⓘ {esc(message)}{link}</p>'
