"""新UIの外枠（シェル）。

- `render_head()` は <head> に入れる CSS と、?ui=new を判定する小さなスクリプト
- `render_root(...)` は <body> の先頭に入れる #new-ui-root と、ページ切り替えのスクリプト

?ui=new が無いときは #new-ui-root を CSS で隠すだけで、旧UIの DOM・見た目・JS は変わらない。
?ui=new のときは旧UIの要素を CSS で隠す（DOM は残す）。cookie / localStorage で
新UIを既定にすることはしない。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.content.ui import account, home, lottery_page, navigation, opportunities_page, pages, parity
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
    root.querySelectorAll('[data-nu-lot-list] [data-nu-lot]').forEach(function(card){
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

  // ── 利益商品（UI Phase 2）: 並べ替え・絞り込み・検索・ページ切り替え。値は data-* の確定値だけを使う ──
  var OPP_SORTS = ['rec', 'profit', 'roi', 'updated'], OPP_SIZE = 20, OPP_MAX_AGE = 14 * 86400000;
  function oppHref(name, value) {
    var cur = new URLSearchParams(location.search), u = new URLSearchParams();
    u.set('ui', 'new'); u.set('page', 'opportunities');
    cur.forEach(function(v, k){ if (k !== 'ui' && k !== 'page') u.set(k, v); });
    if (value) u.set(name, value); else u.delete(name);
    if (name !== 'page_num') { u.delete('page_num'); u.delete('top'); }
    return '?' + u.toString();
  }
  var FMT = null;
  try { FMT = new Intl.DateTimeFormat('ja-JP', {timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit',
          day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}); } catch (e) { FMT = null; }
  function parts(ms) {
    var o = {};
    if (FMT) FMT.formatToParts(new Date(ms)).forEach(function(p){ o[p.type] = p.value; });
    return o;
  }
  // 確認時刻の表示（Phase 0.1 の表記: 3分前確認 / 本日 11:42確認 / 10/02 18:30確認 / 更新遅延）
  function relTime(iso, now) {
    var t = Date.parse(iso);
    if (isNaN(t) || !FMT) return null;
    var a = parts(t), b = parts(now), diff = now - t, hm = a.hour + ':' + a.minute;
    if (diff > OPP_MAX_AGE) return '更新遅延 最終確認 ' + a.month + '/' + a.day + ' ' + hm;
    if (diff >= 0 && diff < 3600000) return Math.max(1, Math.round(diff / 60000)) + '分前確認';
    if (a.year === b.year && a.month === b.month && a.day === b.day) return '本日 ' + hm + '確認';
    return a.month + '/' + a.day + ' ' + hm + '確認';
  }
  function renderTimes() {
    var now = Date.now();
    root.querySelectorAll('[data-nu-time]').forEach(function(el){
      var txt = relTime(el.getAttribute('data-nu-time'), now);
      if (txt) el.textContent = txt;
    });
  }
  function renderOpp(q, cat) {
    var sec = root.querySelector('[data-nu-page="opportunities"]');
    if (!sec) return;
    var top = q.get('top') === '10';
    var sort = top ? 'profit' : (OPP_SORTS.indexOf(q.get('sort')) >= 0 ? q.get('sort') : 'rec');
    var filter = q.get('filter') === 'instock' ? 'instock' : '';
    var term = (q.get('q') || '').trim().toLowerCase();
    var pageNum = Math.max(1, parseInt(q.get('page_num') || '1', 10) || 1);
    var rows = {}, cards = {};
    sec.querySelectorAll('tr.nu-orow').forEach(function(r){ rows[r.getAttribute('data-nu-oid')] = r; });
    sec.querySelectorAll('li.nu-ocard').forEach(function(c){ cards[c.getAttribute('data-nu-oid')] = c; });
    var items = Object.keys(rows).map(function(id){
      var r = rows[id];
      return {id: id, cat: r.getAttribute('data-nu-cat'), profit: +r.getAttribute('data-profit'),
              roi: +r.getAttribute('data-roi'), upd: +r.getAttribute('data-updated'), rec: +r.getAttribute('data-rec'),
              stock: r.getAttribute('data-stock'), text: r.getAttribute('data-search') || ''};
    });
    var inCat = items.filter(function(it){ return cat === 'all' || it.cat === cat; });
    var list = inCat.filter(function(it){
      // 「今すぐ狙う TOP10」は今買えないもの（在庫切れ・抽選・予約）を除く
      if (top && ['OUT_OF_STOCK', 'LOTTERY', 'RESERVATION'].indexOf(it.stock) >= 0) return false;
      return (!filter || it.stock === 'IN_STOCK') && (!term || it.text.indexOf(term) >= 0);
    });
    var by = {rec: function(a, b){ return a.rec - b.rec; },
              profit: function(a, b){ return b.profit - a.profit || a.rec - b.rec; },
              roi: function(a, b){ return b.roi - a.roi || a.rec - b.rec; },
              updated: function(a, b){ return b.upd - a.upd || a.rec - b.rec; }}[sort];
    list.sort(by);
    var total = list.length, pages = top ? 1 : Math.max(1, Math.ceil(total / OPP_SIZE));
    if (pageNum > pages) pageNum = pages;
    var start = top ? 0 : (pageNum - 1) * OPP_SIZE;
    var shown = list.slice(start, start + (top ? 10 : OPP_SIZE)), on = {};
    shown.forEach(function(it){ on[it.id] = true; });
    var tbody = sec.querySelector('[data-nu-opp-table] tbody'), ul = sec.querySelector('[data-nu-opp-cards]');
    list.concat(items.filter(function(it){ return list.indexOf(it) < 0; })).forEach(function(it){
      var r = rows[it.id], d = r.nextElementSibling;
      tbody.appendChild(r);
      if (d && d.getAttribute('data-nu-detail-of') === it.id) tbody.appendChild(d);
      r.hidden = !on[it.id];
      if (d && !on[it.id]) {
        d.hidden = true;
        var b = r.querySelector('[data-nu-toggle]');
        if (b) b.setAttribute('aria-expanded', 'false');
      }
      if (cards[it.id]) { ul.appendChild(cards[it.id]); cards[it.id].hidden = !on[it.id]; }
    });
    var res = sec.querySelector('[data-nu-oresult]');
    if (res) res.textContent = total === 0 ? '0件' : top ? '上位' + shown.length + '件（利益が高い順）'
      : total + '件中 ' + (start + 1) + '〜' + (start + shown.length) + '件';
    // 選んだジャンルに掲載が無いときは、空の表・並べ替え・絞り込みを出さず空状態だけにする
    sec.querySelectorAll('[data-nu-opp-hide-empty]').forEach(function(el){ el.hidden = inCat.length === 0; });
    sec.querySelectorAll('[data-nu-oempty]').forEach(function(el){
      var kind = el.getAttribute('data-nu-oempty');
      el.hidden = !(kind === 'none' ? inCat.length === 0 : (inCat.length > 0 && total === 0));
    });
    sec.querySelectorAll('[data-nu-oparam]').forEach(function(a){
      var name = a.getAttribute('data-nu-oparam'), val = a.getAttribute('data-nu-ovalue');
      var active = name === 'sort' ? val === sort : val === filter;
      setCurrent(a, active, 'true');
      a.setAttribute('href', oppHref(name, name === 'filter' && active ? '' : val));
    });
    // ジャンルの切り替えは、並べ替え・絞り込み・検索を保つ（ページ番号だけ1に戻す）
    sec.querySelectorAll('[data-nu-switch]').forEach(function(a){
      var k = a.getAttribute('data-nu-switch');
      a.setAttribute('href', oppHref('category', k === 'all' ? '' : k));
    });
    var pager = sec.querySelector('[data-nu-pager]');
    if (pager) {
      pager.hidden = pages <= 1;
      while (pager.firstChild) pager.removeChild(pager.firstChild);
      var link = function(n, label, cur){
        var a = document.createElement('a');
        a.className = 'nu-pager__link';
        a.setAttribute('href', oppHref('page_num', n > 1 ? String(n) : ''));
        a.setAttribute('data-nu-scrolltop', '');
        if (cur) a.setAttribute('aria-current', 'page');
        a.textContent = label;
        pager.appendChild(a);
      };
      if (pages > 1) {
        if (pageNum > 1) link(pageNum - 1, '前へ', false);
        for (var n = 1; n <= pages; n++) link(n, String(n), n === pageNum);
        if (pageNum < pages) link(pageNum + 1, '次へ', false);
      }
    }
    var form = sec.querySelector('[data-nu-search-form]'), input = sec.querySelector('[data-nu-search-input]');
    var tog = sec.querySelector('[data-nu-search-toggle]');
    if (term && form && form.hidden) { form.hidden = false; if (tog) tog.setAttribute('aria-expanded', 'true'); }
    if (input && document.activeElement !== input) input.value = q.get('q') || '';
    var note = sec.querySelector('[data-nu-topnote]');
    if (note) note.hidden = !top;
  }

  // ── 抽選・予約（UI Phase 3）: 状態の絞り込み・並べ替え・検索・ページ切り替え ──
  // 状態（data-nu-status / data-nu-bucket / data-nu-today）は NuLotteryRuntime が閲覧時の時刻で書き換えた値だけを使う
  var LOT_TABS = ['open', 'today', 'wait', 'result'], LOT_SORTS = ['rec', 'deadline', 'start', 'updated', 'profit'];
  var LOT_SIZE = 20;
  function lotHref(name, value) {
    var cur = new URLSearchParams(location.search), u = new URLSearchParams();
    u.set('ui', 'new'); u.set('page', 'lottery');
    cur.forEach(function(v, k){ if (k !== 'ui' && k !== 'page') u.set(k, v); });
    if (value) u.set(name, value); else u.delete(name);
    if (name !== 'page_num') u.delete('page_num');
    return '?' + u.toString();
  }
  function numAttr(el, name) { var v = el.getAttribute(name); return v === null || v === '' ? null : +v; }
  function renderLot(q, cat) {
    var sec = root.querySelector('[data-nu-page="lottery"]');
    if (!sec) return;
    var tab = LOT_TABS.indexOf(q.get('st')) >= 0 ? q.get('st') : '';
    var sort = LOT_SORTS.indexOf(q.get('sort')) >= 0 ? q.get('sort') : 'rec';
    var term = (q.get('q') || '').trim().toLowerCase();
    var pageNum = Math.max(1, parseInt(q.get('page_num') || '1', 10) || 1), now = Date.now();
    var box = sec.querySelector('[data-nu-lot-list]');
    var items = Array.prototype.slice.call(box.querySelectorAll(':scope > [data-nu-lot]')).map(function(el){
      return {el: el, cat: el.getAttribute('data-nu-cat'), kind: el.getAttribute('data-nu-kind'),
              status: el.getAttribute('data-nu-status'), bucket: +el.getAttribute('data-nu-bucket'),
              sort: +el.getAttribute('data-nu-sort'), idx: +el.getAttribute('data-nu-idx'),
              today: el.getAttribute('data-nu-today') === '1', unv: el.getAttribute('data-nu-unv') === '1',
              ae: numAttr(el, 'data-ae'), as: numAttr(el, 'data-as'),
              upd: +el.getAttribute('data-upd') || 0, profit: numAttr(el, 'data-profit'),
              text: el.getAttribute('data-search') || ''};
    });
    // 掲載中（bucket < 99。HOME の件数と同じ定義）
    var inCat = items.filter(function(it){ return it.bucket < 99 && (cat === 'all' || it.cat === cat); });
    var match = {
      '': function(){ return true; },
      // 抽選受付中: 抽選で受付中・締切間近（予約の受付は「予約・発売待ち」）
      // 人の確認待ちの告知は「抽選受付中」に入れない（HOME の「受付中」の件数と同じ）
      open: function(it){ return it.kind === 'lottery' && !it.unv && (it.status === 'OPEN' || it.status === 'ENDING_SOON'); },
      today: function(it){ return it.today; },
      wait: function(it){ return it.kind === 'preorder' || it.kind === 'release'; },
      result: function(it){ return ['RESULT_PENDING', 'WINNER_ANNOUNCED', 'WINNER_PURCHASE_PERIOD'].indexOf(it.status) >= 0; }
    }[tab];
    var list = inCat.filter(function(it){ return match(it) && (!term || it.text.indexOf(term) >= 0); });
    function rec(a, b){ return a.bucket - b.bucket || a.sort - b.sort || a.idx - b.idx; }
    // 値の無いもの（締切未公表・利益算出前など）は後ろに回す（上位に混ぜない）
    function nullsLast(key, dir){ return function(a, b){
      var x = a[key], y = b[key];
      if (x === null && y === null) return rec(a, b);
      if (x === null) return 1;
      if (y === null) return -1;
      return (dir * (x - y)) || rec(a, b);
    }; }
    var by = {rec: rec,
              deadline: function(a, b){ return nullsLast('ae', 1)(
                {ae: a.ae !== null && a.ae > now ? a.ae : null, bucket: a.bucket, sort: a.sort, idx: a.idx},
                {ae: b.ae !== null && b.ae > now ? b.ae : null, bucket: b.bucket, sort: b.sort, idx: b.idx}); },
              start: function(a, b){ return nullsLast('as', 1)(
                {as: a.as !== null && a.as > now ? a.as : null, bucket: a.bucket, sort: a.sort, idx: a.idx},
                {as: b.as !== null && b.as > now ? b.as : null, bucket: b.bucket, sort: b.sort, idx: b.idx}); },
              updated: function(a, b){ return b.upd - a.upd || rec(a, b); },
              profit: nullsLast('profit', -1)}[sort];
    list.sort(by);
    var total = list.length, pages = Math.max(1, Math.ceil(total / LOT_SIZE));
    if (pageNum > pages) pageNum = pages;
    var start = (pageNum - 1) * LOT_SIZE, shown = list.slice(start, start + LOT_SIZE), on = {};
    shown.forEach(function(it){ on[it.idx] = true; });
    // 並び順が変わったときだけ並べ直す（毎分の更新でキーボードのフォーカスを外さない）
    var order = list.concat(items.filter(function(it){ return list.indexOf(it) < 0; }));
    var same = order.every(function(it, i){ return box.children[i] === it.el; });
    order.forEach(function(it){
      if (!same) box.appendChild(it.el);
      it.el.hidden = !on[it.idx];
    });
    var res = sec.querySelector('[data-nu-lresult]');
    if (res) res.textContent = total === 0 ? '0件' : total + '件中 ' + (start + 1) + '〜' + (start + shown.length) + '件';
    sec.querySelectorAll('[data-nu-lot-hide-empty]').forEach(function(el){ el.hidden = inCat.length === 0; });
    sec.querySelectorAll('[data-nu-lempty]').forEach(function(el){
      var kind = el.getAttribute('data-nu-lempty');
      el.hidden = !(kind === 'none' ? inCat.length === 0 : (inCat.length > 0 && total === 0));
    });
    sec.querySelectorAll('[data-nu-lparam]').forEach(function(a){
      var name = a.getAttribute('data-nu-lparam'), val = a.getAttribute('data-nu-lvalue');
      setCurrent(a, name === 'sort' ? val === sort : val === tab, 'true');
      a.setAttribute('href', lotHref(name, name === 'sort' && val === 'rec' ? '' : val));
    });
    sec.querySelectorAll('[data-nu-switch]').forEach(function(a){
      var k = a.getAttribute('data-nu-switch');
      a.setAttribute('href', lotHref('category', k === 'all' ? '' : k));
    });
    var pager = sec.querySelector('[data-nu-lpager]');
    if (pager) {
      pager.hidden = pages <= 1;
      while (pager.firstChild) pager.removeChild(pager.firstChild);
      var link = function(n, label, cur){
        var a = document.createElement('a');
        a.className = 'nu-pager__link';
        a.setAttribute('href', lotHref('page_num', n > 1 ? String(n) : ''));
        a.setAttribute('data-nu-scrolltop', '');
        if (cur) a.setAttribute('aria-current', 'page');
        a.textContent = label;
        pager.appendChild(a);
      };
      if (pages > 1) {
        if (pageNum > 1) link(pageNum - 1, '前へ', false);
        for (var n = 1; n <= pages; n++) link(n, String(n), n === pageNum);
        if (pageNum < pages) link(pageNum + 1, '次へ', false);
      }
    }
    var form = sec.querySelector('[data-nu-search-form]'), input = sec.querySelector('[data-nu-search-input]');
    var tog = sec.querySelector('[data-nu-search-toggle]');
    if (term && form && form.hidden) { form.hidden = false; if (tog) tog.setAttribute('aria-expanded', 'true'); }
    if (input && document.activeElement !== input) input.value = q.get('q') || '';
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
      // ジャンルの件数: ほかの目的の一部（せどりルート）は重ねて数えない（catalog.OVERLAPPING と同じ）
      var k = el.getAttribute('data-nu-catcount'), n = 0, overlap = DATA.overlap || [];
      PURPOSES.forEach(function(p){ if (overlap.indexOf(p) < 0) n += count(p, k, lot); });
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
    renderOpp(q, cat);
    renderLot(q, cat);
    renderTimes();
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
    else if (a.hasAttribute('data-nu-scrolltop')) {
      var sec = root.querySelector('[data-nu-page="' + after + '"]');
      if (sec) sec.scrollIntoView({block: 'start'});
    }
  });
  // 詳細を1段だけ開く・閉じる（aria-expanded）
  root.addEventListener('click', function(e){
    var b = e.target.closest('[data-nu-toggle]');
    if (b) {
      var t = document.getElementById(b.getAttribute('aria-controls')), open = b.getAttribute('aria-expanded') !== 'true';
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (t) t.hidden = !open;
      return;
    }
    var s = e.target.closest('[data-nu-search-toggle]');
    if (s) {
      // 検索欄はページごとにある（利益商品・抽選・予約）。ボタンの aria-controls で開く欄を決める
      var f = document.getElementById(s.getAttribute('aria-controls')), show = s.getAttribute('aria-expanded') !== 'true';
      s.setAttribute('aria-expanded', show ? 'true' : 'false');
      if (f) { f.hidden = !show; if (show) { var i = f.querySelector('input'); if (i) i.focus(); } }
    }
  });
  // 一覧内の検索（商品名・型番。選んだジャンルの中）。入力のたびに URL の q= を更新する
  var searchTimer = null;
  root.addEventListener('input', function(e){
    if (!e.target.matches('[data-nu-search-input]')) return;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function(){
      var u = new URLSearchParams(location.search), v = e.target.value.trim();
      if (v) u.set('q', v); else u.delete('q');
      u.delete('page_num'); u.delete('top');
      history.replaceState(null, '', location.pathname + '?' + u.toString());
      render(false);
    }, 200);
  });
  root.addEventListener('submit', function(e){ if (e.target.matches('[data-nu-search-form]')) e.preventDefault(); });
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


def build_catalog(ctx: ShellContext):
    """HOME のモデルと掲載データ（件数・一覧）。画面と内部の診断（opportunity_diagnostics）が同じものを使う。"""
    model = home.build_home_model(
        tcg_report=ctx.tcg_report, opportunities=ctx.opportunities,
        profit_routes=ctx.profit_routes, legacy_lotteries=ctx.legacy_lotteries, now=ctx.now)
    catalog = cl.build(model=model, tcg_report=ctx.tcg_report, profit_routes=ctx.profit_routes,
                       legacy_lotteries=ctx.legacy_lotteries, profit_deals=ctx.profit_deals,
                       product_genres=ctx.product_genres)
    return model, catalog


def render_root(ctx: ShellContext) -> str:
    import json
    model, catalog = build_catalog(ctx)
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
        + opportunities_page.render(catalog, has_data=has_data)
        + lottery_page.render(catalog, model, has_data=has_data)
        + "".join(pages.render_purpose(p, catalog, model, has_data=has_data)
                  for p in cl.PURPOSES if p not in ("opportunities", "lottery"))
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
