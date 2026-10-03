"""新UIの外枠（シェル）。

- `render_head()` は <head> に入れる CSS と、?ui=new を判定する小さなスクリプト
- `render_root(...)` は <body> の先頭に入れる #new-ui-root と、ページ切り替えのスクリプト

?ui=new が無いときは #new-ui-root を CSS で隠すだけで、旧UIの DOM・見た目・JS は変わらない。
?ui=new のときは旧UIの要素を CSS で隠す（DOM は残す）。cookie / localStorage で
新UIを既定にすることはしない。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.content.ui import account, home, navigation, pages, parity
from src.content.ui import catalog as cl
from src.content.ui import categories as cats
from src.content.ui import runtime as rt
from src.content.ui.components import esc
from src.content.ui.icons import icon

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
    # 利益商品（定価を確認済みで、定価で買って買取店に売る案件。daily_lp_generator が絞り込む）
    profit_deals: list | None = None
    product_genres: dict | None = None  # product_id → products.genre（ジャンルの判定に使う）


def _css() -> str:
    from src.content.ui import styles
    return styles.css()


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
  function jsonAttr(name) { try { return JSON.parse(root.getAttribute(name) || '{}'); } catch (e) { return {}; } }
  var MAP = jsonAttr('data-nu-map'), CATS = jsonAttr('data-nu-cats'), TITLES = jsonAttr('data-nu-titles');
  var PAGES = MAP.pages || ['home'], ALIASES = MAP.aliases || {};
  var PURPOSES = ['opportunities', 'lottery', 'restock', 'routes'];
  // 「その他」から開くページでは、ボトムナビの「その他」を現在地にする
  var MORE_PAGES = ['more', 'routes', 'search', 'account'];
  var SITE = root.getAttribute('data-nu-site') || '';
  var DATA = {};
  try { DATA = JSON.parse((document.getElementById('nu-catalog') || {}).textContent || '{}'); } catch (e) { DATA = {}; }

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
    ['mode', 'focus', 'category'].forEach(function(k){ if (target[k]) q.set(k, target[k]); else q.delete(k); });
    history.replaceState(null, '', location.pathname + '?' + q.toString());
    return true;
  }
  function currentPage() {
    var p = new URLSearchParams(location.search).get('page') || 'home';
    p = ALIASES[p] || p;
    return PAGES.indexOf(p) >= 0 ? p : 'home';
  }
  function currentCat() {
    var c = (new URLSearchParams(location.search).get('category') || '').toLowerCase();
    return Object.prototype.hasOwnProperty.call(CATS, c) ? c : 'all';
  }
  function withCat(href, cat) {
    var i = href.indexOf('#'), hash = i >= 0 ? href.slice(i) : '', base = i >= 0 ? href.slice(0, i) : href;
    var u = new URLSearchParams(base.slice(1));
    if (cat !== 'all') u.set('category', cat); else u.delete('category');
    return '?' + u.toString() + hash;
  }
  function sum(o) { var n = 0; Object.keys(o || {}).forEach(function(k){ n += +o[k] || 0; }); return n; }
  // 抽選はカードの閲覧時の状態（data-nu-bucket。runtime が書き換える）から数える
  function lotteryCounts() {
    var out = {};
    root.querySelectorAll('[data-nu-list="lottery"] [data-nu-lot]').forEach(function(card){
      var cat = (DATA.lot || {})[card.getAttribute('data-nu-lot')];
      if (cat && +card.getAttribute('data-nu-bucket') < 99) out[cat] = (out[cat] || 0) + 1;
    });
    return out;
  }
  function count(p, cat, lot) {
    var src = p === 'lottery' ? lot : ((DATA['static'] || {})[p] || {});
    return cat === 'all' ? sum(src) : (+src[cat] || 0);
  }
  function setCurrent(el, on, value) {
    if (on) el.setAttribute('aria-current', value || 'page'); else el.removeAttribute('aria-current');
  }
  function render(moveFocus) {
    var page = currentPage(), cat = currentCat(), lot = lotteryCounts();
    var q = new URLSearchParams(location.search);
    root.querySelectorAll('[data-nu-page]').forEach(function(el){
      el.hidden = el.getAttribute('data-nu-page') !== page;
    });
    root.querySelectorAll('[data-nu-nav]').forEach(function(a){
      var key = a.getAttribute('data-nu-nav');
      setCurrent(a, key === page || (key === 'more' && MORE_PAGES.indexOf(page) >= 0 && a.closest('.nu-bottomnav')));
    });
    // ジャンルを保つリンク（目的・上部ナビ・ボトムナビ）
    root.querySelectorAll('a[data-nu-keepcat]').forEach(function(a){
      if (!a.hasAttribute('data-nu-base')) a.setAttribute('data-nu-base', a.getAttribute('href'));
      a.setAttribute('href', withCat(a.getAttribute('data-nu-base'), cat));
    });
    // HOME のジャンル: 選んでいるジャンルをもう一度押すと「すべて」に戻る
    root.querySelectorAll('a[data-nu-cat-link]').forEach(function(a){
      var k = a.getAttribute('data-nu-cat-link'), on = k === cat;
      setCurrent(a, on, 'true');
      a.setAttribute('href', withCat('?ui=new', on ? 'all' : k));
    });
    root.querySelectorAll('[data-nu-switch]').forEach(function(a){
      setCurrent(a, a.getAttribute('data-nu-switch') === cat, 'true');
    });
    root.querySelectorAll('[data-nu-count]').forEach(function(el){
      var n = count(el.getAttribute('data-nu-count'), cat, lot);
      el.textContent = n + '件';
      if (n) el.removeAttribute('data-zero'); else el.setAttribute('data-zero', '');
    });
    root.querySelectorAll('[data-nu-catcount]').forEach(function(el){
      var k = el.getAttribute('data-nu-catcount'), n = 0;
      PURPOSES.forEach(function(p){ n += count(p, k, lot); });
      el.textContent = n + '件';
      var a = el.closest('a');
      if (a) {
        a.setAttribute('aria-label', (CATS[k] || '') + ' ' + n + '件');
        if (n) a.removeAttribute('data-zero'); else a.setAttribute('data-zero', '');
      }
    });
    root.querySelectorAll('[data-nu-catlabel]').forEach(function(el){ el.textContent = CATS[cat] || ''; });
    root.querySelectorAll('[data-nu-home-ctx],[data-nu-crumb-cat]').forEach(function(el){ el.hidden = cat === 'all'; });
    root.querySelectorAll('a[data-nu-crumb-catlink]').forEach(function(a){ a.setAttribute('href', withCat('?ui=new', cat)); });
    // 一覧: ジャンルで絞り込み、抽選は閲覧時に掲載中のもの（bucket < 99）だけを出す
    var top = page === 'opportunities' && q.get('top') === '10' ? 10 : 0;
    root.querySelectorAll('[data-nu-topnote]').forEach(function(el){ el.hidden = !top; });
    root.querySelectorAll('[data-nu-list]').forEach(function(list){
      var p = list.getAttribute('data-nu-list'), shown = 0;
      // 抽選は閲覧時の状態の順（締切間近 → 受付中 → まもなく開始 → 日程要確認）に並べ直す
      if (p === 'lottery') {
        var key = function(li){ var a = li.querySelector('[data-nu-bucket]') || li;
          return [+a.getAttribute('data-nu-bucket') || 0, +a.getAttribute('data-nu-sort') || 0, +a.getAttribute('data-nu-idx') || 0]; };
        Array.prototype.slice.call(list.children).sort(function(x, y){
          var a = key(x), b = key(y);
          return a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
        }).forEach(function(li){ list.appendChild(li); });
      }
      list.querySelectorAll(':scope > [data-nu-item]').forEach(function(li){
        var ok = cat === 'all' || li.getAttribute('data-nu-cat') === cat;
        if (ok && p === 'lottery') {
          var card = li.querySelector('[data-nu-bucket]');
          ok = !!card && +card.getAttribute('data-nu-bucket') < 99;
        }
        // 「今すぐ狙う TOP10」: 利益が大きい順（生成時の並び）の上位10件だけ
        if (ok && p === 'opportunities' && top && shown >= top) ok = false;
        li.hidden = !ok;
        if (ok) shown++;
      });
      var empty = root.querySelector('[data-nu-empty-for="' + p + '"]');
      if (empty) empty.hidden = shown > 0;
    });
    var dbg = root.querySelector('[data-nu-debug]');
    if (dbg) dbg.hidden = q.get('debug') !== '1';
    var mode = q.get('mode') === 'pro' ? '詳細' : 'かんたん';
    root.querySelectorAll('[data-nu-mode-label]').forEach(function(el){ el.textContent = mode; });
    var label = page === 'home' ? (cat === 'all' ? (TITLES.home || 'HOME') : (CATS[cat] || ''))
              : (cat === 'all' ? '' : (CATS[cat] || '') + 'の') + (TITLES[page] || '');
    document.title = label + ' | ' + SITE;
    var focusId = q.get('focus') === 'operator' ? 'nu-operator' : '';
    var target = focusId ? document.getElementById(focusId)
               : root.querySelector('[data-nu-page="' + page + '"] h1');
    if (moveFocus && target) {
      if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
      target.focus({preventScroll: true});
    }
    if (moveFocus && focusId && target) target.scrollIntoView({block: 'start'});
    return page;
  }
  function scrollToHash() {
    var id = location.hash.slice(1), el = id ? document.getElementById(id) : null;
    if (el) el.scrollIntoView({block: 'start'});
  }
  root.addEventListener('click', function(e){
    var a = e.target.closest('a[href^="?ui=new"]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    var href = a.getAttribute('href'), i = href.indexOf('#');
    var next = new URLSearchParams((i >= 0 ? href.slice(0, i) : href).slice(1));
    var cur = new URLSearchParams(location.search);
    if (cur.get('debug') === '1') next.set('debug', '1');
    if (cur.get('mode') && !next.get('mode')) next.set('mode', cur.get('mode'));
    var before = currentPage();
    var url = location.pathname + '?' + next.toString() + (i >= 0 ? href.slice(i) : '');
    if (url !== location.pathname + location.search + location.hash) history.pushState(null, '', url);
    var after = render(before !== currentPage());
    if (i >= 0) scrollToHash();
    else if (before !== after) window.scrollTo(0, 0);
  });
  window.addEventListener('popstate', function(){ render(true); });
  window.addEventListener('hashchange', function(){ if (applyLegacyHash()) render(true); });

  // 抽選の閲覧時の状態（状態・残り時間・ボタン）。判定は NuLotteryRuntime だけ。
  // 残り時間は分単位なので毎分の頭に更新し、状態が変わる時刻（締切など）にはその時刻ちょうどに更新する。
  // 状態が変わったら、件数と一覧の表示も数え直す
  var timer = null;
  function refresh() {
    var res = null;
    try { res = NuLotteryRuntime.apply(root, Date.now()); } catch (e) { /* 失敗しても生成時点の表示のまま */ }
    render(false);
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
    var a = e.target.closest('a[data-nu-cta]');
    if (!a || a.getAttribute('data-nu-cta') !== 'apply') return;
    refresh();
    if (!a.isConnected || a.getAttribute('data-nu-cta') !== 'apply') e.preventDefault();
  }
  root.addEventListener('click', guardApply, true);
  root.addEventListener('auxclick', guardApply, true);   // 中クリック（新しいタブで開く）
  applyLegacyHash();
  render(false);
  refresh();
  if (location.hash) scrollToHash();
})();
</script>"""


def _brand(title: str) -> str:
    """サイト名の短い形（「プレ値速報 — 説明」の説明部分を落とす）。"""
    for sep in (" — ", " - ", "｜", " | "):
        if sep in title:
            return title.split(sep, 1)[0].strip() or title
    return title


PAGE_TITLES = {"home": "HOME", "opportunities": "利益商品", "lottery": "抽選・予約", "restock": "在庫再開",
               "routes": "せどりルート", "more": "メニュー", "search": "商品を検索", "account": "運営者向け"}


def render_root(ctx: ShellContext) -> str:
    import json
    model = home.build_home_model(
        tcg_report=ctx.tcg_report, opportunities=ctx.opportunities,
        profit_routes=ctx.profit_routes, legacy_lotteries=ctx.legacy_lotteries, now=ctx.now)
    catalog = cl.build(model=model, tcg_report=ctx.tcg_report, profit_routes=ctx.profit_routes,
                       legacy_lotteries=ctx.legacy_lotteries, profit_deals=ctx.profit_deals,
                       product_genres=ctx.product_genres)
    # 情報そのものがあるか（無ければ「まだ情報がありません」。あるが対象が無ければ「今はありません」）
    has_data = bool(model.has_data or ctx.profit_deals)
    rows = (parity.build(model, ctx.tcg_report, ctx.old_ui_counts)
            if ctx.old_ui_counts is not None else [])
    updated = (f'<span class="nu-header__meta" title="取得に成功した最新の時刻">'
               f'<span class="nu-header__metalabel">情報確認 </span>{esc(ctx.updated_text)}</span>'
               if ctx.updated_text else "")
    body = (
        pages.render_home(catalog, source_issue=ctx.source_issue,
                          debug_html=parity.render(rows, hidden_prices=model.hidden_prices))
        + "".join(pages.render_purpose(p, catalog, model, has_data=has_data) for p in cl.PURPOSES)
        + pages.render_more(catalog)
        + pages.render_search()
        + account.render()
    )
    brand = esc(_brand(ctx.site_title))
    cats_json = json.dumps({c.key: c.label for c in cats.CATEGORIES}, ensure_ascii=False)
    return (
        # hidden: CSS を使わない読み手にも、旧UIより先に新UIの本文を見せない（?ui=new のとき JS で外す）
        f'<div id="{ROOT_ID}" hidden data-nu-site="{brand}" '
        f"data-nu-map='{esc(navigation.legacy_map_json())}' "
        f"data-nu-cats='{esc(cats_json)}' data-nu-titles='{esc(json.dumps(PAGE_TITLES, ensure_ascii=False))}'>"
        '<a class="nu-skip" href="#nu-main">本文へ移動</a>'
        '<header class="nu-header"><div class="nu-header__inner">'
        f'<a class="nu-brand" href="{esc(navigation.page_href("home"))}" data-nu-nav-brand aria-label="{brand} HOME">'
        f'<span class="nu-brand__mark">{icon("trend", size=18)}</span>'
        f'<span class="nu-brand__name">{brand}</span><span class="nu-brand__en">Premium Monitor</span></a>'
        f'{navigation.top_nav()}'
        f'<div class="nu-header__tools">{updated}'
        f'<a class="nu-iconbtn" href="{esc(navigation.page_href("search"))}" data-nu-nav="search" aria-label="商品を検索">'
        f'{icon("search", size=20)}</a></div></div></header>'
        f'<main id="nu-main" class="nu-main" tabindex="-1">{body}</main>'
        f'{pages.render_footer(_brand(ctx.site_title))}'
        f'{navigation.bottom_nav()}'
        f'<script type="application/json" id="nu-lot-data">{rt.data_json(model.vms)}</script>'
        f'<script type="application/json" id="nu-catalog">{esc_json(catalog.data_json())}</script>'
        f'<script>{rt.runtime_js()}</script>'
        f'{_router_script()}'
        f'</div>{ROOT_END_MARK}'
    )


def esc_json(text: str) -> str:
    """<script type="application/json"> の中に入れる JSON（</script> で閉じられないようにする）。"""
    return text.replace("</", "<\\/")
