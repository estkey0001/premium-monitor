"""旧ページ（TCG・iPhone・カメラ・collector_report 等の静的ページ）向けの共通 CSS と共通ナビ。

HOME（#new-ui-root）とは干渉しない。ここが出す :root の --color-* は旧ページだけに入る
（HOME は同じ値を design_tokens.css_variables() で #new-ui-root に定義する）。
値の正本は design_tokens.py。ここでは色を直書きしない。

使い方（各ページ）:
    <style>{legacy_css()}{ページ固有の CSS}</style> ... <body>{site_nav("tcg")}<main>...
legacy_css() の後にページ固有の CSS を置く（ページ固有の指定が優先される）。ページ側の :root から
--bg 等を消し、この別名層に任せる。JS は使わない。

色の意味（全ページ共通）:
  緑 = 購入候補・黒字だけ（.sbadge--buy / .sbadge--profit / .pos）
  橙 = 様子見・要確認（.sbadge--wait）   赤 = 赤字・危険（.sbadge--loss / .neg）
  様子見の黒字は緑にしない（親に .is-wait → .pos が中立色。バッジは .sbadge--profit-neutral）
  灰 = 終了・STALE・不明（.sbadge--off）  青 = 情報・受付中など（.sbadge--info）
"""

from __future__ import annotations

from html import escape

from src.content.ui import design_tokens as t

# サイト内ナビ: (キー, 文言, 相対 URL)。静的に並べるだけ（HOME のルーターには依存しない）
SITE_NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("home", "HOME", "./"),
    ("tcg", "TCG 抽選", "./tcg.html"),
    ("iphone", "iPhone 買取", "./iphone-buyback.html"),
    ("camera", "カメラ", "./camera-research.html"),
)

_VARIANTS = ("doc", "app")


_BRAND_MARK = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" '
               'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
               '<polyline points="3,17 9,11 13,15 21,7"/><polyline points="15,7 21,7 21,13"/></svg>')


def site_nav(current: str = "") -> str:
    """旧ページ先頭に置く静的な共通ヘッダ（ブランド＋ナビ）。h1 は含まない。現在地は aria-current="page"。

    ブランド（プレ値速報）は HOME へのリンクを兼ねる。JS なし。モバイル（640px 未満）では画面上部に固定される。
    """
    links = []
    for key, label, href in SITE_NAV_ITEMS:
        cur = ' aria-current="page"' if key == current else ""
        head, _, tail = label.partition(" ")
        # 375px で 1 行に収めるため、2 語目（抽選・買取）は 640px 未満で見た目だけ省く（文字列は残る）
        text = escape(head) + (f'<span class="site-nav__x"> {escape(tail)}</span>' if tail else "")
        links.append(f'<a href="{escape(href, quote=True)}"{cur}>{text}</a>')
    brand = (f'<a class="site-nav__brand" href="./"><span class="site-nav__mark">{_BRAND_MARK}</span>'
             '<span class="site-nav__name">プレ値速報</span></a>')
    return f'<nav class="site-nav" aria-label="サイト内">{brand}{"".join(links)}</nav>'


def site_nav_css() -> str:
    """共通ヘッダ（site_nav）の CSS。旧ページ（legacy_css）と HOME（styles.py）が同じものを使う。

    4 ページで高さ・見た目・項目を揃える。375px でも 1 行（約 53px）。767px 以下は画面上部に固定。
    """
    return (
        ".site-nav a{display:inline-flex;align-items:center;justify-content:center;"
        f"min-height:{t.TAP_MIN}px;min-width:{t.TAP_MIN}px;padding:0 var(--space-3);"
        "border:1px solid var(--color-border-strong);border-radius:var(--radius-sm);"
        "background:var(--color-surface);color:var(--tone-info-fg);font-size:var(--font-sm);font-weight:700;"
        "text-decoration:none;line-height:1.3;white-space:nowrap}"
        ".site-nav a:hover{background:var(--color-primary-soft)}"
        ".site-nav{display:flex;flex-wrap:nowrap;align-items:center;gap:var(--space-1) var(--space-2);"
        "padding:var(--space-1) max(var(--space-4),calc((100% - 1240px)/2 + var(--space-4)));background:var(--color-surface);"
        "border-bottom:1px solid var(--color-border);z-index:20;min-height:53px}"
        ".site-nav a[aria-current=page]{background:var(--color-primary);border-color:var(--color-primary);"
        "color:var(--color-primary-contrast)}"
        ".site-nav a.site-nav__brand{gap:var(--space-2);margin-right:auto;padding:0;border:0;"
        "background:none;color:var(--color-text);font-size:var(--font-md);font-weight:800}"
        ".site-nav__mark{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;"
        "border-radius:var(--radius-sm);background:var(--color-primary);color:var(--color-primary-contrast)}"
        "@media (max-width:767px){.site-nav{position:sticky;top:0;padding-left:var(--space-3);"
        "padding-right:var(--space-3);gap:0 var(--space-1)}"
        ".site-nav a:not(.site-nav__brand){padding:0 6px;min-width:var(--tap-min,44px);font-size:var(--font-xs)}"
        "html{scroll-padding-top:64px}}"
        "@media (max-width:639px){.site-nav__x{display:none}}"
        "@media (max-width:359px){.site-nav__name{display:none}}"
    )


def _aliases(variant: str) -> tuple[str, str]:
    """旧ページの変数（--bg 等）→ 新トークン。(ライト, ダークだけの上書き) を返す。

    doc（iPhone・カメラ）: 地は白（surface）、カード・メモは薄い灰（bg）。ダークは地が最も暗く、カードが少し明るい。
    app（TCG）: 地は bg、カードは surface（ライト・ダークとも）。
    """
    common = ("--fg:var(--color-text);--mut:var(--color-muted);--line:var(--color-border);"
              "--ok:var(--tone-success-fg);--ng:var(--tone-danger-fg);--bad:var(--tone-danger-fg);"
              "--ref:var(--tone-warning-fg);--warn:var(--tone-warning-fg);"
              "--link:var(--tone-info-fg);--acc:var(--tone-info-fg);")
    # 4 ページ（HOME・TCG・iPhone・カメラ）で地・カードを同じトークンにする（variant に依らない）
    return common + "--bg:var(--color-bg);--card:var(--color-surface);", ""


def _components() -> str:
    return (
        # 共通の土台
        "html{color-scheme:light dark}"
        # 4 ページ共通の地・本文色・フォント（ページ固有の body{...} より詳細度を上げて固定）
        f"html body{{background:var(--color-bg);color:var(--color-text);font-family:{t.FONT_STACK}}}"
        # フォーカス（旧ページには無かった）
        ":where(a,button,summary,select,input,textarea,[tabindex]):focus-visible"
        "{outline:3px solid var(--color-focus);outline-offset:2px}"
        "@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}"
        "*,*::before,*::after{transition:none!important;animation:none!important}}"
        ".nu-linkbtn{display:inline-flex;align-items:center;justify-content:center;"
        f"min-height:{t.TAP_MIN}px;min-width:{t.TAP_MIN}px;padding:0 var(--space-3);"
        "border:1px solid var(--color-border-strong);border-radius:var(--radius-sm);"
        "background:var(--color-surface);color:var(--tone-info-fg);font-size:var(--font-sm);font-weight:700;"
        "text-decoration:none;line-height:1.3}"
        ".nu-linkbtn:hover{background:var(--color-primary-soft)}"
        # リスト内リンクを 44px にする（出典リンク等。クラスを付けるだけ）
        ".hit44{display:inline-flex;align-items:center;min-height:44px}"
        + site_nav_css() +
        # アンカー（#lottery 等）で見出しが固定ヘッダに隠れない
        ".nu-anchor,main :is(h2,h3,h4)[id],main [id]:target{scroll-margin-top:var(--space-4)}"
        "@media (max-width:639px){.nu-anchor,main :is(h2,h3,h4)[id],main [id]:target{scroll-margin-top:64px}}"
        # 開閉（summary）は 44px。マーカーは自前（flex にするとブラウザの三角が消えるため）
        "main summary{display:flex;align-items:center;gap:var(--space-2);"
        f"min-height:{t.TAP_MIN}px;min-width:{t.TAP_MIN}px;cursor:pointer}}"
        "main summary::-webkit-details-marker{display:none}"
        "main summary::before{content:'\\25B8';flex:none}"
        "main details[open]>summary::before{content:'\\25BE'}"
        # 鮮度（控えめだが読める）
        ".nu-fresh{font-size:var(--font-xs);color:var(--color-subtle);font-variant-numeric:tabular-nums}"
        ".nu-fresh--stale{display:inline-block;padding:0 var(--space-2);border-radius:var(--radius-sm);"
        "color:var(--tone-neutral-fg);background:var(--tone-neutral-bg);border:1px solid var(--tone-neutral-bd)}"
        # 状態バッジ（文字で伝える。色の点を添える）
        ".sbadge{display:inline-flex;align-items:center;gap:6px;padding:2px var(--space-2);"
        "border-radius:var(--radius-sm);font-size:var(--font-xs);font-weight:700;line-height:1.5;"
        "color:var(--t-fg);background:var(--t-bg);border:1px solid var(--t-bd);white-space:nowrap}"
        ".sbadge::before{content:'';width:6px;height:6px;border-radius:50%;background:currentColor;flex:none}"
        + "".join(
            f".sbadge--{name}{{--t-fg:var(--tone-{tone}-fg);--t-bg:var(--tone-{tone}-bg);--t-bd:var(--tone-{tone}-bd)}}"
            for name, tone in (("buy", "success"), ("profit", "success"), ("wait", "warning"),
                               ("loss", "danger"), ("off", "neutral"), ("info", "info"))) +
        ".pos{color:var(--tone-success-fg)}.neg{color:var(--tone-danger-fg)}"
        # 様子見（WAIT）のとき利益額は緑にしない: 親に .is-wait（または .pos--neutral）を付けると .pos は中立色。
        # 黒字の事実は文字（「黒字」「+¥…」）で伝える。バッジは .sbadge--profit-neutral（灰）
        ".is-wait .pos,.pos--neutral{color:inherit}"
        ".sbadge--profit-neutral{--t-fg:var(--tone-neutral-fg);--t-bg:var(--tone-neutral-bg);--t-bd:var(--tone-neutral-bd)}"
        # 表: 640px 未満はカード風に積む（td に data-label を付ける）。広い画面は普通の表
        ".nu-table--stack{width:100%;border-collapse:collapse}"
        "@media (max-width:639px){"
        ".nu-table--stack,.nu-table--stack tbody{display:block;min-width:0}"
        ".nu-table--stack thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}"
        ".nu-table--stack tr{display:block;margin:0 0 var(--space-3);padding:var(--space-3);"
        "background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-md)}"
        ".nu-table--stack th,.nu-table--stack td{display:flex;justify-content:space-between;gap:var(--space-3);"
        "padding:var(--space-1) 0;border:0;text-align:right;overflow-wrap:anywhere}"
        ".nu-table--stack td::before,.nu-table--stack th[scope=row]::before{content:attr(data-label);"
        "color:var(--color-muted);text-align:left;flex:none}"
        ".nu-table--stack .num{white-space:normal}}"
    )


def legacy_css(variant: str = "doc") -> str:
    """旧ページ用 CSS。自己完結（:root に --color-* / --tone-* を含む）。

    variant: "doc"（iPhone・カメラ。既定）/ "app"（TCG。地が bg・カードが surface）。
    """
    if variant not in _VARIANTS:
        raise ValueError(f"variant は {_VARIANTS} のどちらか: {variant!r}")
    light, dark_extra = _aliases(variant)
    root = f":root{{{t.css_variables()}{light}}}"
    dark = t.dark_css(":root:not([data-theme=\"light\"])")
    if dark_extra:
        dark += ("@media (prefers-color-scheme:dark){"
                 f":root:not([data-theme=\"light\"]){{{dark_extra}}}}}")
    # 旧ページは tone クラス（.nu-tone-*）を使わない。.sbadge--* が直接トークンを参照する
    return root + dark + "*,*::before,*::after{box-sizing:border-box}" + _components()
