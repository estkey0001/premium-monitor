"""新UIの外枠（シェル）。

- `render_head()` は <head> に入れる CSS と、?ui=new を判定する小さなスクリプト
- `render_root(...)` は <body> の先頭に入れる #new-ui-root と、ページ切り替えのスクリプト

?ui=new が無いときは #new-ui-root を CSS で隠すだけで、旧UIの DOM・見た目・JS は変わらない。
?ui=new のときは旧UIの要素を CSS で隠す（DOM は残す）。cookie / localStorage で
新UIを既定にすることはしない。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.content.ui import account, home, lottery, navigation, parity, product_search, profit
from src.content.ui import runtime as rt
from src.content.ui import design_tokens as t
from src.content.ui.components import esc

ROOT_ID = "new-ui-root"
# root の終わりの目印（deploy-check が新UIの範囲だけを調べるのに使う）
ROOT_END_MARK = "<!-- /new-ui-root -->"


@dataclass
class ShellContext:
    tcg_report: dict
    opportunities: dict
    profit_routes: dict
    legacy_lotteries: list
    updated_text: str = ""
    source_issue: bool = False
    site_title: str = "プレ値速報"
    old_ui_counts: dict | None = None   # 旧UIが実際に出力した件数（照合用）
    now: object = None                  # 生成時刻（JST）。閲覧時はブラウザで計算し直す


def _tone_css() -> str:
    return "".join(
        f".nu-tone-{tone}{{--t-fg:var(--tone-{tone}-fg);--t-bg:var(--tone-{tone}-bg);"
        f"--t-bd:var(--tone-{tone}-bd);}}"
        for tone in t.TONES)


def _css() -> str:
    m, d = t.BP_MOBILE, t.BP_DESKTOP
    return (
        # 表示の切り替え（旧UIは DOM を残したまま隠す）
        f"html:not(.ui-new) #{ROOT_ID}{{display:none!important}}"
        f"html.ui-new body>*:not(#{ROOT_ID}){{display:none!important}}"
        f"html.ui-new body{{background:{t.BASE_COLORS['bg']};margin:0}}"
        f"#{ROOT_ID}{{{t.css_variables()}"
        "font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Noto Sans JP',sans-serif;"
        "color:var(--color-text);background:var(--color-bg);font-size:var(--font-md);line-height:1.6;"
        "min-height:100vh;padding-bottom:calc(var(--bottom-nav-h) + env(safe-area-inset-bottom) + var(--space-4))}"
        f"#{ROOT_ID} *,#{ROOT_ID} *::before,#{ROOT_ID} *::after{{box-sizing:border-box}}"
        f"#{ROOT_ID} [hidden]{{display:none!important}}"
        + _tone_css() +
        # スキップリンク
        ".nu-skip{position:absolute;left:-9999px;top:0}"
        ".nu-skip:focus{left:var(--space-2);top:var(--space-2);z-index:50;background:var(--color-surface);"
        "padding:var(--space-2) var(--space-3);border-radius:var(--radius-sm)}"
        # ヘッダー
        ".nu-header{position:sticky;top:0;z-index:20;background:var(--color-surface);"
        "border-bottom:1px solid var(--color-border)}"
        ".nu-header__inner{max-width:var(--max-width);margin:0 auto;display:flex;align-items:center;"
        "gap:var(--space-3);padding:0 var(--space-4);min-height:48px}"
        ".nu-brand{display:inline-flex;align-items:center;min-height:44px;font-size:var(--font-md);"
        "font-weight:800;color:var(--color-text);text-decoration:none}"
        ".nu-header__meta{margin-left:auto;font-size:var(--font-xs);color:var(--color-muted);white-space:nowrap}"
        # 上部ナビ（640px 以上）
        ".nu-topnav{display:none}"
        ".nu-topnav__link{display:inline-flex;align-items:center;gap:var(--space-1);min-height:44px;"
        "padding:0 var(--space-3);border-radius:var(--radius-sm);color:var(--color-muted);"
        "text-decoration:none;font-size:var(--font-sm);font-weight:700;white-space:nowrap}"
        ".nu-topnav__link[aria-current=page]{background:var(--tone-info-bg);color:var(--color-primary)}"
        # ボトムナビ（640px 未満）
        ".nu-bottomnav{position:fixed;left:0;right:0;bottom:0;z-index:30;display:grid;"
        "grid-template-columns:repeat(5,minmax(0,1fr));background:var(--color-surface);"
        "border-top:1px solid var(--color-border);padding-bottom:env(safe-area-inset-bottom)}"
        ".nu-bottomnav__link{display:flex;flex-direction:column;align-items:center;justify-content:center;"
        "gap:var(--space-1);min-height:var(--bottom-nav-h);min-width:44px;font-size:var(--font-xs);"
        "color:var(--color-muted);text-decoration:none}"
        ".nu-bottomnav__link[aria-current=page]{color:var(--color-primary);font-weight:800}"
        ".nu-bottomnav__icon{font-size:var(--font-lg);line-height:1}"
        f"@media (min-width:{m}px){{.nu-topnav{{display:flex;gap:var(--space-1)}}.nu-bottomnav{{display:none}}"
        f"#{ROOT_ID}{{padding-bottom:var(--space-6)}}}}"
        # 本文
        ".nu-main{max-width:var(--max-width);margin:0 auto;padding:var(--space-3) var(--space-4)}"
        ".nu-main:focus{outline:none}"
        ".nu-hero{padding:var(--space-1) 0 var(--space-3)}"
        ".nu-hero__title,.nu-page__title{font-size:var(--font-lg);font-weight:800;margin:0;line-height:1.3}"
        ".nu-hero__meta{font-size:var(--font-xs);color:var(--color-muted);margin:var(--space-1) 0 0}"
        ".nu-h2{font-size:var(--font-md);font-weight:800;margin:var(--space-5) 0 var(--space-2)}"
        ".nu-lead{font-size:var(--font-sm);color:var(--color-muted);margin:var(--space-2) 0 var(--space-4)}"
        # タイル
        ".nu-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--space-2)}"
        f"@media (min-width:{d}px){{.nu-tiles{{grid-template-columns:repeat(6,minmax(0,1fr))}}}}"
        ".nu-tile{display:flex;flex-direction:column;justify-content:space-between;min-height:76px;"
        "padding:var(--space-2);border-radius:var(--radius-md);border:1px solid var(--t-bd);"
        "background:var(--t-bg);color:var(--t-fg);text-decoration:none;min-width:0}"
        ".nu-tile__label{font-size:var(--font-xs);font-weight:700;line-height:1.3}"
        ".nu-tile__count{font-size:var(--font-xl);font-weight:800;line-height:1.1;font-variant-numeric:tabular-nums}"
        ".nu-tile__note{font-size:var(--font-xs);line-height:1.3}"
        # カード
        ".nu-cards{display:grid;gap:var(--space-3)}"
        f"@media (min-width:{d}px){{.nu-cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}"
        ".nu-card{display:flex;flex-direction:column;gap:var(--space-2);min-width:0;padding:var(--space-4);"
        "background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-md);"
        "box-shadow:var(--shadow)}"
        ".nu-card__head{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-2)}"
        ".nu-card__title{font-size:var(--font-md);font-weight:700;margin:0;line-height:1.4;overflow-wrap:anywhere}"
        ".nu-card__sub{margin:0;font-size:var(--font-sm);color:var(--color-muted);overflow-wrap:anywhere}"
        ".nu-card__metric{margin:0;font-size:var(--font-lg);font-weight:800;font-variant-numeric:tabular-nums}"
        ".nu-card__meta{margin:0;font-size:var(--font-sm)}"
        ".nu-cd{display:block;font-size:var(--font-xs);color:var(--color-muted);font-variant-numeric:tabular-nums}"
        ".nu-badge{flex:none;display:inline-flex;align-items:center;gap:var(--space-1);padding:var(--space-1) var(--space-2);"
        "border-radius:var(--radius-pill);font-size:var(--font-xs);font-weight:700;line-height:1.2;"
        "color:var(--t-fg);background:var(--t-bg);border:1px solid var(--t-bd);white-space:nowrap}"
        # ボタン（強いボタンは1カードに1つ。高さ44px以上、モバイルは横幅いっぱい）
        ".nu-btn{display:flex;align-items:center;justify-content:center;width:100%;min-height:44px;"
        "padding:0 var(--space-4);border-radius:var(--radius-sm);font-size:var(--font-md);font-weight:700;"
        "text-align:center;text-decoration:none;line-height:1.3}"
        ".nu-btn--primary{background:var(--color-primary);color:var(--color-primary-contrast)}"
        ".nu-btn--secondary{background:var(--color-surface);color:var(--color-primary);border:1px solid var(--color-border)}"
        ".nu-btn--link{width:auto;justify-content:flex-start;padding:0;color:var(--color-primary);text-decoration:underline}"
        f"@media (min-width:{m}px){{.nu-btn{{display:inline-flex;width:auto}}}}"
        ".nu-page>.nu-btn{margin:0 var(--space-2) var(--space-2) 0}"
        f"#{ROOT_ID} a:focus-visible,#{ROOT_ID} summary:focus-visible,#{ROOT_ID} [tabindex]:focus-visible"
        "{outline:3px solid var(--color-focus);outline-offset:2px}"
        # 開閉
        ".nu-details summary{display:flex;align-items:center;min-height:44px;cursor:pointer;"
        "font-size:var(--font-sm);font-weight:700;color:var(--color-primary)}"
        ".nu-details dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:var(--space-1) var(--space-3);"
        "margin:0;font-size:var(--font-sm)}"
        ".nu-details dt{color:var(--color-muted)}.nu-details dd{margin:0;overflow-wrap:anywhere}"
        # 空状態・注意
        ".nu-empty{padding:var(--space-5) var(--space-4);text-align:center;background:var(--color-surface);"
        "border:1px dashed var(--color-border);border-radius:var(--radius-md)}"
        ".nu-empty__msg{margin:0;font-size:var(--font-md);font-weight:700}"
        ".nu-empty__hint{margin:var(--space-1) 0 0;font-size:var(--font-sm);color:var(--color-muted)}"
        ".nu-notice{margin:var(--space-3) 0 0;padding:var(--space-2) var(--space-3);border-radius:var(--radius-sm);"
        "background:var(--tone-neutral-bg);color:var(--color-muted);font-size:var(--font-sm)}"
        ".nu-disclaimer{margin:var(--space-5) 0 0;font-size:var(--font-xs);color:var(--color-subtle)}"
        # 一覧
        ".nu-sumlist,.nu-linklist{list-style:none;margin:0 0 var(--space-4);padding:0;display:grid;gap:var(--space-2)}"
        ".nu-sumrow{display:flex;align-items:center;justify-content:space-between;min-height:44px;"
        "padding:0 var(--space-3);background:var(--color-surface);border:1px solid var(--color-border);"
        "border-radius:var(--radius-sm)}"
        ".nu-sumrow__n{font-weight:800;font-variant-numeric:tabular-nums}"
        # 開発用の照合表（?debug=1 のときだけ表示。表は横スクロールの枠の中だけ）
        ".nu-debug{margin-top:var(--space-5);padding:var(--space-3);border:1px solid var(--color-border);"
        "border-radius:var(--radius-md);background:var(--color-surface);font-size:var(--font-xs)}"
        ".nu-debug__scroll{overflow-x:auto}.nu-debug table{border-collapse:collapse}"
        ".nu-debug th,.nu-debug td{border:1px solid var(--color-border);padding:var(--space-1) var(--space-2);text-align:left}"
        ".nu-debug tr[data-match='0'] td{background:var(--tone-warning-bg)}"
    )


# ?ui=new を最初に判定してクラスを付ける（旧UIが一瞬見えるのを防ぐ）
_HEAD_SCRIPT = (
    "<script>(function(){try{if(new URLSearchParams(location.search).get('ui')==='new'"
    # アーカイブ（過去のLP）では新UIを使わない（相対リンクが合わないため）
    "&&!/\\/archive\\//.test(location.pathname))"
    "{document.documentElement.classList.add('ui-new');}}catch(e){}})();</script>"
)


def render_head() -> str:
    return f"<style>{_css()}</style>{_HEAD_SCRIPT}"


def _router_script() -> str:
    return """<script>
(function(){
  'use strict';
  var params = new URLSearchParams(location.search);
  // 新UIの仮ページから現行版へ来たときだけ、ハッシュのタブを開く（通常の URL では何もしない）
  if (params.get('ui') !== 'new') {
    if (params.get('from') !== 'new' || !location.hash) return;
    var go = function(){
      var id = location.hash.slice(1), btn = null, el = document.getElementById(id);
      if (/^tab-/.test(id)) btn = document.querySelector('[data-tab="' + id.slice(4) + '"]');
      if (!btn && el) {
        var panel = el.closest('[id^="tab-"]');
        if (panel) btn = document.querySelector('[data-tab="' + panel.id.slice(4) + '"]');
      }
      if (btn) btn.click();
      if (el) setTimeout(function(){ el.scrollIntoView({block: 'start'}); }, 150);
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();
    return;
  }
  var root = document.getElementById('""" + ROOT_ID + """');
  if (!root || !document.documentElement.classList.contains('ui-new')) return;
  root.hidden = false;
  var MAP = JSON.parse(root.getAttribute('data-nu-map') || '{}');
  var PAGES = MAP.pages || ['home'];
  var TITLES = {home: 'HOME', lottery: '抽選・販売', profit: '利益商品', search: '商品検索', account: 'マイページ'};
  var SITE = root.getAttribute('data-nu-site') || '';

  function resolveHash(h) {
    var key = (h || '').replace(/^#/, '');
    if (!key) return null;
    if (MAP.exact && MAP.exact[key]) return MAP.exact[key];
    for (var i = 0; i < (MAP.prefix || []).length; i++) {
      if (key.indexOf(MAP.prefix[i][0]) === 0) return MAP.prefix[i][1];
    }
    return null;
  }
  function applyLegacyHash() {
    var target = resolveHash(location.hash);
    if (!target) return false;
    var q = new URLSearchParams(location.search);
    q.set('ui', 'new');
    q.set('page', target.page);
    ['mode', 'focus'].forEach(function(k){ if (target[k]) q.set(k, target[k]); else q.delete(k); });
    history.replaceState(null, '', location.pathname + '?' + q.toString());
    return true;
  }
  function currentPage() {
    var p = new URLSearchParams(location.search).get('page');
    return PAGES.indexOf(p) >= 0 ? p : 'home';
  }
  function render(moveFocus) {
    var q = new URLSearchParams(location.search), page = currentPage();
    root.querySelectorAll('[data-nu-page]').forEach(function(el){
      el.hidden = el.getAttribute('data-nu-page') !== page;
    });
    root.querySelectorAll('[data-nu-nav]').forEach(function(a){
      if (a.getAttribute('data-nu-nav') === page) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    var dbg = root.querySelector('[data-nu-debug]');
    if (dbg) dbg.hidden = q.get('debug') !== '1';
    var mode = q.get('mode') === 'pro' ? '詳細' : 'かんたん';
    root.querySelectorAll('[data-nu-mode-label]').forEach(function(el){ el.textContent = mode; });
    document.title = (TITLES[page] || '') + ' | ' + SITE;
    var focusId = q.get('focus') === 'operator' ? 'nu-operator' : '';
    var target = focusId ? document.getElementById(focusId)
               : root.querySelector('[data-nu-page="' + page + '"] h1');
    if (moveFocus && target) {
      if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
      target.focus({preventScroll: true});
    }
    if (focusId && target) target.scrollIntoView({block: 'start'});
  }
  root.addEventListener('click', function(e){
    var a = e.target.closest('a[href^="?ui=new"]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    var next = new URLSearchParams(a.getAttribute('href').slice(1));
    var cur = new URLSearchParams(location.search);
    if (cur.get('debug') === '1') next.set('debug', '1');
    if (cur.get('mode') && !next.get('mode')) next.set('mode', cur.get('mode'));
    var url = location.pathname + '?' + next.toString();
    if (url !== location.pathname + location.search) history.pushState(null, '', url);
    render(true);
    window.scrollTo(0, 0);
  });
  window.addEventListener('popstate', function(){ render(true); });
  window.addEventListener('hashchange', function(){ if (applyLegacyHash()) render(true); });

  // 抽選の閲覧時の状態（状態・残り時間・ボタン・件数・並び順）。判定は NuLotteryRuntime だけ。
  // 残り時間は分単位なので毎分の頭に更新し、状態が変わる時刻（締切など）にはその時刻ちょうどに更新する
  var timer = null;
  function refresh() {
    var res = null;
    try { res = NuLotteryRuntime.apply(root, Date.now()); } catch (e) { /* 失敗しても生成時点の表示のまま */ }
    if (timer) clearTimeout(timer);
    var now = Date.now(), wait = 60000 - (now % 60000) + 50;
    if (res && res.next !== null && res.next - now + 20 < wait) wait = Math.max(res.next - now + 20, 20);
    timer = setTimeout(refresh, wait);
  }
  // 戻る・タブの切り替えで戻ってきたときも判定し直す
  window.addEventListener('pageshow', refresh);
  document.addEventListener('visibilitychange', function(){ if (!document.hidden) refresh(); });
  // 「応募する」を押した瞬間にもう一度判定し、締切を過ぎていたら開かない
  function guardApply(e){
    var a = e.target.closest('a[data-nu-cta="apply"]');
    if (!a) return;
    refresh();
    if (!a.isConnected || a.getAttribute('data-nu-cta') !== 'apply') e.preventDefault();
  }
  root.addEventListener('click', guardApply, true);
  root.addEventListener('auxclick', guardApply, true);   // 中クリック（新しいタブで開く）
  applyLegacyHash();
  render(false);
  refresh();
})();
</script>"""


def _brand(title: str) -> str:
    """サイト名の短い形（「プレ値速報 — 説明」の説明部分を落とす）。"""
    for sep in (" — ", " - ", "｜", " | "):
        if sep in title:
            return title.split(sep, 1)[0].strip() or title
    return title


def render_root(ctx: ShellContext) -> str:
    model = home.build_home_model(
        tcg_report=ctx.tcg_report, opportunities=ctx.opportunities,
        profit_routes=ctx.profit_routes, legacy_lotteries=ctx.legacy_lotteries, now=ctx.now)
    rows = (parity.build(model, ctx.tcg_report, ctx.old_ui_counts)
            if ctx.old_ui_counts is not None else [])
    updated = f'<span class="nu-header__meta">情報確認 {esc(ctx.updated_text)}</span>' if ctx.updated_text else ""
    pages = (
        home.render_home(model, source_issue=ctx.source_issue)
        + parity.render(rows, hidden_prices=model.hidden_prices)
        + lottery.render(model.vms, model.states, has_data=bool(ctx.tcg_report or model.vms))
        + profit.render(ctx.profit_routes)
        + product_search.render()
        + account.render()
    )
    return (
        # hidden: CSS を使わない読み手にも、旧UIより先に新UIの本文を見せない（?ui=new のとき JS で外す）
        f'<div id="{ROOT_ID}" hidden data-nu-site="{esc(_brand(ctx.site_title))}" '
        f"data-nu-map='{esc(navigation.legacy_map_json())}'>"
        '<a class="nu-skip" href="#nu-main">本文へ移動</a>'
        '<header class="nu-header"><div class="nu-header__inner">'
        f'<a class="nu-brand" href="{esc(navigation.page_href("home"))}" data-nu-nav-brand>{esc(_brand(ctx.site_title))}</a>'
        f'{navigation.top_nav()}{updated}</div></header>'
        f'<main id="nu-main" class="nu-main" tabindex="-1">{pages}</main>'
        f'{navigation.bottom_nav()}'
        f'<script type="application/json" id="nu-lot-data">{rt.data_json(model.vms)}</script>'
        f'<script>{rt.runtime_js()}</script>'
        f'{_router_script()}'
        f'</div>{ROOT_END_MARK}'
    )
