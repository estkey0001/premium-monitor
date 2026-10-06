"""新UIの外枠（シェル）。

- `render_head()` は <head> に入れる CSS と、表示（新UI / 旧UI）を URL で判定する小さなスクリプト
- `render_root(...)` は <body> の先頭に入れる #new-ui-root と、ページ切り替えのスクリプト

UI Phase 8 から新UIが正式の表示（クエリなし・?ui=new・?ui=それ以外 は新UI）。旧UIは ?ui=legacy のときだけ
（監査・比較用に1フェーズ残す。DOM は同じ HTML の中にあり、新UIのときは CSS の display:none で隠す）。
どちらを出すかは URL だけで決める（cookie・localStorage・過去の設定では切り替えない）。
アーカイブ（過去の LP）は旧UIのまま。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.content.ui import (account, admin, home, lottery_page, mypage, navigation, opportunities_page, pages, parity,
                            restock_page, routes_page)
from src.content.ui import product_detail, product_page
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
    stock_history: dict | None = None   # 在庫の状態の履歴（exports/stock_history/latest.json）
    price_observations: list | None = None  # 正規化した価格の観測（出品価格の参考に使う）
    products: list | None = None        # 商品の一覧（商品詳細。product_id・名前・ジャンル・メーカー・型番・公式の URL）
    price_history: dict | None = None   # 実際に観測した価格の履歴（exports/price_history/latest.json）
    notifications: list | None = None   # 通知のイベント（exports/notifications の latest と直近の history。マイページの履歴）
    admin_data: dict | None = None      # 運営者向けの生成物（表示する項目だけ。admin.build が読む。秘密の値は入れない）


def _css() -> str:
    from src.content.ui import styles
    return styles.css()


# 新UIが正式の表示（UI Phase 8）。旧UIは ?ui=legacy のときだけ（監査・比較用の退避）。
# 判定は URL だけ（cookie・localStorage・過去の設定では切り替えない）。最初に判定してクラスを付ける（旧UIが一瞬見えるのを防ぐ）
_HEAD_SCRIPT = (
    "<script>(function(){try{var d=document.documentElement;"
    "if(new URLSearchParams(location.search).get('ui')==='legacy'){d.classList.add('ui-legacy');}"
    # アーカイブ（過去のLP）では新UIを使わない（相対リンクが合わないため）
    "else if(!/\\/archive\\//.test(location.pathname)){d.classList.add('ui-new');"
    # 新UIのルーター（本文を表示する）が動かなかったときは、読み込みの終わりに旧UIへ戻す（白い画面にしない）
    "window.addEventListener('load',function(){var r=document.getElementById('new-ui-root');"
    "if(!r||r.hidden){d.classList.remove('ui-new');}});}"
    "}catch(e){}})();</script>"
)


def render_head() -> str:
    return f"<style>{_css()}</style>{_HEAD_SCRIPT}"


def _router_script() -> str:
    return """<script>
(function(){
  'use strict';
  var params = new URLSearchParams(location.search);
  // 旧UI（?ui=legacy・アーカイブ）: 新UIから来たときだけ、ハッシュのタブを開く。新UIのルーターは動かさない
  if (params.get('ui') === 'legacy' || /\\/archive\\//.test(location.pathname)) {
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
  var MORE_PAGES = ['more', 'routes', 'search', 'account', 'mypage', 'admin'];
  var SITE = root.getAttribute('data-nu-site') || '';
  var PD_ALIAS = jsonAttr('data-nu-pd-alias'), PD_TABS = ['buy', 'history', 'changes'];
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
    q.delete('ui');
    q.set('page', target.page);
    ['mode', 'focus', 'category'].forEach(function(k){ if (target[k]) q.set(k, target[k]); else q.delete(k); });
    // 旧UIの商品カード（#product-<別名>）は商品詳細へ。詳細の無い商品は、その別名で検索する
    var key = location.hash.replace(/^#/, '');
    if (key.indexOf('product-') === 0) {
      var alias = key.slice('product-'.length);
      try { alias = decodeURIComponent(alias); } catch (e) { /* 読めない別名はそのまま */ }
      q.delete('q'); q.delete('product_id');            // 元の URL の検索語・商品を持ち越さない
      if (PD_ALIAS[alias]) { q.set('page', 'product'); q.set('product_id', PD_ALIAS[alias]); }
      else if (alias) { q.set('page', 'search'); q.set('q', alias.replace(/_/g, ' ')); }
    }
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
    var u = new URLSearchParams(base.replace(/^\\.\\//, '').replace(/^\\?/, ''));
    if (cat !== 'all') u.set('category', cat); else u.delete('category');
    var qs = u.toString();
    return (qs ? '?' + qs : './') + hash;
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
  function count(p, cat, lot, rs) {
    // 抽選・予約と在庫再開は、閲覧時の状態（runtime）から数える
    var src = p === 'lottery' ? lot : p === 'restock' ? (rs || {}) : ((DATA['static'] || {})[p] || {});
    return cat === 'all' ? sum(src) : (+src[cat] || 0);
  }
  function setCurrent(el, on, value) {
    if (on) el.setAttribute('aria-current', value || 'page'); else el.removeAttribute('aria-current');
  }

  // ── 利益商品（UI Phase 2）: 並べ替え・絞り込み・検索・ページ切り替え。値は data-* の確定値だけを使う ──
  var OPP_SORTS = ['rec', 'profit', 'roi', 'updated'], OPP_SIZE = 20, OPP_MAX_AGE = 14 * 86400000;
  function oppHref(name, value) {
    var cur = new URLSearchParams(location.search), u = new URLSearchParams();
    u.set('page', 'opportunities');
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
      // 商品詳細は相対の時刻に絶対の時刻を添える（例: 21分前確認（本日 13:32））
      if (txt && el.hasAttribute('data-nu-time-both') && /分前確認$/.test(txt)) {
        var p = parts(Date.parse(el.getAttribute('data-nu-time'))), n = parts(now);
        var same = p.year === n.year && p.month === n.month && p.day === n.day;
        txt += '（' + (same ? '本日 ' : p.month + '/' + p.day + ' ') + p.hour + ':' + p.minute + '）';
      }
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
    u.set('page', 'lottery');
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

  // ── 在庫再開（UI Phase 4）: 購入可能の判定（閲覧時の時刻）・タブ・絞り込み・並べ替え・検索・ページ ──
  // 購入可能 = 在庫あり（data-state=IN_STOCK）・確認の期限前（data-fresh-until）・販売ページあり（data-has-url）。
  // restock_view.RestockView.available と同じ条件。期限を過ぎた在庫ありは「在庫未確認（更新待ち）」に落とす
  var RS_VIEWS = ['history'], RS_WHENS = ['today', '24h'], RS_SORTS = ['rec', 'checked', 'profit', 'price'], RS_SIZE = 20;
  function rsRows() { return Array.prototype.slice.call(root.querySelectorAll('[data-nu-rs-list] > [data-nu-rs]')); }
  function stockRuntime(now) {
    var next = null;
    rsRows().forEach(function(el){
      var until = numAttr(el, 'data-fresh-until'), url = el.getAttribute('data-has-url') === '1';
      var inStock = el.getAttribute('data-state') === 'IN_STOCK';
      var avail = inStock && until !== null && now < until && url;
      if (inStock && until !== null && until > now && (next === null || until < next)) next = until;
      el.setAttribute('data-avail', avail ? '1' : '0');
      var fresh = until !== null && now < until;
      if (inStock) {
        // 期限を過ぎたら販売ページの有無に関係なく「更新待ち」（restock_view.RestockView.label と同じ）
        var label = avail ? '購入可能' : (!fresh ? '在庫未確認（更新待ち）' : '在庫あり（販売ページ未確認）');
        var badge = el.querySelector('[data-nu-rbadge]'), detail = el.querySelector('[data-nu-rstate]');
        if (badge) { badge.textContent = label; badge.className = 'nu-badge nu-tone-' + (avail ? 'success' : 'neutral'); }
        if (detail) detail.textContent = label;
      }
      var a = el.querySelector('a[data-nu-rcta]');
      if (a) {
        a.textContent = avail ? '購入する' : '販売ページを見る';
        a.className = 'nu-btn nu-btn--' + (avail ? 'primary' : 'secondary');
        a.setAttribute('data-nu-rcta', avail ? 'buy' : 'page');
      }
    });
    return next;
  }
  function restockCounts() {
    var out = {};
    rsRows().forEach(function(el){
      if (el.getAttribute('data-avail') === '1') { var c = el.getAttribute('data-nu-cat'); out[c] = (out[c] || 0) + 1; }
    });
    return out;
  }
  function rsHref(name, value) {
    var cur = new URLSearchParams(location.search), u = new URLSearchParams();
    u.set('page', 'restock');
    cur.forEach(function(v, k){ if (k !== 'ui' && k !== 'page') u.set(k, v); });
    if (value) u.set(name, value); else u.delete(name);
    if (name !== 'page_num') u.delete('page_num');
    return '?' + u.toString();
  }
  function renderRTimes(now) {
    root.querySelectorAll('[data-nu-rtime]').forEach(function(el){
      var iso = el.getAttribute('data-nu-rtime'), suffix = el.getAttribute('data-nu-suffix') || '';
      if (suffix === '確認') { var t = relTime(iso, now); if (t) el.textContent = t; return; }
      var ms = Date.parse(iso);
      if (isNaN(ms) || !FMT) return;
      var a = parts(ms), b = parts(now), hm = a.hour + ':' + a.minute;
      var same = a.year === b.year && a.month === b.month && a.day === b.day;
      el.textContent = (same ? '本日 ' + hm : a.month + '/' + a.day + ' ' + hm) + ' ' + suffix;
    });
  }
  function renderRestock(q, cat) {
    var sec = root.querySelector('[data-nu-page="restock"]');
    if (!sec) return;
    var view = RS_VIEWS.indexOf(q.get('view')) >= 0 ? q.get('view') : '';
    var when = RS_WHENS.indexOf(q.get('when')) >= 0 ? q.get('when') : '';
    var sort = RS_SORTS.indexOf(q.get('sort')) >= 0 ? q.get('sort') : 'rec';
    var term = (q.get('q') || '').trim().toLowerCase(), now = Date.now();
    var pageNum = Math.max(1, parseInt(q.get('page_num') || '1', 10) || 1);
    var box = sec.querySelector('[data-nu-rs-list]');
    var items = rsRows().map(function(el){
      // r: 再入荷の時刻（在庫切れ → 在庫あり）。t: 並べ替え用（再入荷、無ければ初めての在庫確認）
      var r = numAttr(el, 'data-restock'), t = r !== null ? r : numAttr(el, 'data-first');
      return {el: el, cat: el.getAttribute('data-nu-cat'), avail: el.getAttribute('data-avail') === '1', t: t, r: r,
              checked: numAttr(el, 'data-checked') || 0, profit: numAttr(el, 'data-profit'),
              price: numAttr(el, 'data-price'), idx: +el.getAttribute('data-idx'), text: el.getAttribute('data-search') || ''};
    });
    // 購入可能タブは今買えるものだけ。履歴タブは再入荷・在庫確認の時刻があるもの（今の在庫は状態の欄で示す）
    var universe = items.filter(function(it){
      return (cat === 'all' || it.cat === cat) && (view === 'history' ? it.t !== null : it.avail);
    });
    var b = parts(now);
    var list = universe.filter(function(it){
      if (term && it.text.indexOf(term) < 0) return false;
      if (!when) return true;
      // 「本日再開」「24時間以内に再開」は再入荷だけ（初めての在庫確認は再開ではない）
      if (it.r === null) return false;
      if (when === '24h') return now - it.r <= 86400000 && it.r <= now;
      var a = parts(it.r);
      return a.year === b.year && a.month === b.month && a.day === b.day;
    });
    function nl(key, dir){ return function(x, y){
      var p = x[key], r = y[key];
      if (p === null && r === null) return x.idx - y.idx;
      if (p === null) return 1;
      if (r === null) return -1;
      return dir * (p - r) || x.idx - y.idx;
    }; }
    var by = {rec: function(x, y){ return nl('t', -1)(x, y) || y.checked - x.checked; },
              checked: function(x, y){ return y.checked - x.checked || x.idx - y.idx; },
              profit: nl('profit', -1), price: nl('price', 1)}[sort];
    list.sort(by);
    var total = list.length, pages = Math.max(1, Math.ceil(total / RS_SIZE));
    if (pageNum > pages) pageNum = pages;
    var start = (pageNum - 1) * RS_SIZE, shown = list.slice(start, start + RS_SIZE), on = {};
    shown.forEach(function(it){ on[it.idx] = true; });
    var order = list.concat(items.filter(function(it){ return list.indexOf(it) < 0; }));
    var same = order.every(function(it, i){ return box.children[i] === it.el; });
    order.forEach(function(it){ if (!same) box.appendChild(it.el); it.el.hidden = !on[it.idx]; });
    var res = sec.querySelector('[data-nu-rresult]');
    if (res) res.textContent = total === 0 ? '0件' : total + '件中 ' + (start + 1) + '〜' + (start + shown.length) + '件';
    var head = sec.querySelector('[data-nu-rs-head]');
    if (head) head.hidden = total === 0;
    // 表示するものが無いときは、絞り込み・並べ替え・検索を出さない（タブだけ残す）
    sec.querySelectorAll('[data-nu-rs-hide-empty]').forEach(function(el){ el.hidden = universe.length === 0; });
    // 履歴も0件なら、空状態のリンクは「抽選・予約」へ（行き止まりにしない）
    var anyHistory = items.some(function(it){ return it.t !== null && (cat === 'all' || it.cat === cat); });
    var toHist = sec.querySelector('[data-nu-rs-tohist]'), toLot = sec.querySelector('[data-nu-rs-tolot]');
    if (toHist) toHist.hidden = !anyHistory;
    if (toLot) toLot.hidden = anyHistory;
    sec.querySelectorAll('[data-nu-rempty]').forEach(function(el){
      var k = el.getAttribute('data-nu-rempty');
      el.hidden = !(universe.length === 0 ? k === (view === 'history' ? 'history' : 'avail') : (total === 0 && k === 'nomatch'));
    });
    sec.querySelectorAll('[data-nu-rparam]').forEach(function(a){
      var name = a.getAttribute('data-nu-rparam'), val = a.getAttribute('data-nu-rvalue');
      var cur = {view: view, when: when, sort: sort}[name];
      setCurrent(a, val === cur || (name === 'sort' && val === 'rec' && cur === 'rec'), 'true');
      a.setAttribute('href', rsHref(name, name === 'sort' && val === 'rec' ? '' : val));
    });
    sec.querySelectorAll('[data-nu-switch]').forEach(function(a){
      var k = a.getAttribute('data-nu-switch');
      a.setAttribute('href', rsHref('category', k === 'all' ? '' : k));
    });
    var pager = sec.querySelector('[data-nu-rpager]');
    if (pager) {
      pager.hidden = pages <= 1;
      while (pager.firstChild) pager.removeChild(pager.firstChild);
      for (var n = 1; pages > 1 && n <= pages; n++) {
        var a = document.createElement('a');
        a.className = 'nu-pager__link';
        a.setAttribute('href', rsHref('page_num', n > 1 ? String(n) : ''));
        a.setAttribute('data-nu-scrolltop', '');
        if (n === pageNum) a.setAttribute('aria-current', 'page');
        a.textContent = String(n);
        pager.appendChild(a);
      }
    }
    var form = sec.querySelector('[data-nu-search-form]'), input = sec.querySelector('[data-nu-search-input]');
    var tog = sec.querySelector('[data-nu-search-toggle]');
    if (term && form && form.hidden) { form.hidden = false; if (tog) tog.setAttribute('aria-expanded', 'true'); }
    if (input && document.activeElement !== input) input.value = q.get('q') || '';
  }

  // ── せどりルート（UI Phase 5）: ルートの種類・絞り込み・並べ替え・検索・ページ（値は data-* の確定値だけ） ──
  var RT_TABS = ['retail', 'secondary', 'other'], RT_FILTERS = ['highroi'];
  var RT_SORTS = ['profit', 'roi', 'updated', 'samples'], RT_SIZE = 20, RT_HIGH_ROI = 0.2;
  function rtHref(name, value) {
    var cur = new URLSearchParams(location.search), u = new URLSearchParams();
    u.set('page', 'routes');
    cur.forEach(function(v, k){ if (k !== 'ui' && k !== 'page') u.set(k, v); });
    if (value) u.set(name, value); else u.delete(name);
    if (name !== 'page_num') u.delete('page_num');
    return '?' + u.toString();
  }
  function renderRoutes(q, cat) {
    var sec = root.querySelector('[data-nu-page="routes"]');
    if (!sec) return;
    var tab = RT_TABS.indexOf(q.get('tab')) >= 0 ? q.get('tab') : '';
    var filter = RT_FILTERS.indexOf(q.get('filter')) >= 0 ? q.get('filter') : '';
    var sort = RT_SORTS.indexOf(q.get('sort')) >= 0 ? q.get('sort') : 'profit';
    var term = (q.get('q') || '').trim().toLowerCase();
    var pageNum = Math.max(1, parseInt(q.get('page_num') || '1', 10) || 1);
    var box = sec.querySelector('[data-nu-route-list]');
    var items = Array.prototype.slice.call(box.querySelectorAll(':scope > [data-nu-route]')).map(function(el){
      return {el: el, cat: el.getAttribute('data-nu-cat'), tab: el.getAttribute('data-rt-tab'),
              profit: +el.getAttribute('data-profit'), roi: +el.getAttribute('data-roi'), upd: +el.getAttribute('data-upd'),
              samples: +el.getAttribute('data-samples'), stock: el.getAttribute('data-stock'),
              idx: +el.getAttribute('data-idx'), text: el.getAttribute('data-search') || ''};
    });
    var inCat = items.filter(function(it){ return cat === 'all' || it.cat === cat; });
    var list = inCat.filter(function(it){
      if (tab && it.tab !== tab) return false;
      if (filter === 'highroi' && !(it.roi >= RT_HIGH_ROI)) return false;
      return !term || it.text.indexOf(term) >= 0;
    });
    var by = {profit: function(a, b){ return b.profit - a.profit || a.idx - b.idx; },
              roi: function(a, b){ return b.roi - a.roi || a.idx - b.idx; },
              updated: function(a, b){ return b.upd - a.upd || a.idx - b.idx; },
              samples: function(a, b){ return b.samples - a.samples || a.idx - b.idx; }}[sort];
    list.sort(by);
    var total = list.length, pages = Math.max(1, Math.ceil(total / RT_SIZE));
    if (pageNum > pages) pageNum = pages;
    var start = (pageNum - 1) * RT_SIZE, shown = list.slice(start, start + RT_SIZE), on = {};
    shown.forEach(function(it){ on[it.idx] = true; });
    var order = list.concat(items.filter(function(it){ return list.indexOf(it) < 0; }));
    var same = order.every(function(it, i){ return box.children[i] === it.el; });
    order.forEach(function(it){ if (!same) box.appendChild(it.el); it.el.hidden = !on[it.idx]; });
    var res = sec.querySelector('[data-nu-tresult]');
    if (res) res.textContent = total === 0 ? '0件' : total + '件中 ' + (start + 1) + '〜' + (start + shown.length) + '件';
    sec.querySelectorAll('[data-nu-rt-hide-empty]').forEach(function(el){ el.hidden = inCat.length === 0; });
    sec.querySelectorAll('[data-nu-tempty]').forEach(function(el){
      var k = el.getAttribute('data-nu-tempty');
      el.hidden = !(k === 'none' ? inCat.length === 0 : (inCat.length > 0 && total === 0));
    });
    sec.querySelectorAll('[data-nu-tparam]').forEach(function(a){
      var name = a.getAttribute('data-nu-tparam'), val = a.getAttribute('data-nu-tvalue');
      var cur = {tab: tab, filter: filter, sort: sort}[name], on2 = val === cur;
      setCurrent(a, on2, 'true');
      a.setAttribute('href', rtHref(name, (name === 'filter' && on2) || (name === 'sort' && val === 'profit') ? '' : val));
    });
    sec.querySelectorAll('[data-nu-switch]').forEach(function(a){
      var k = a.getAttribute('data-nu-switch');
      a.setAttribute('href', rtHref('category', k === 'all' ? '' : k));
    });
    // 出品価格の参考もジャンルで絞る（件数・利益には使わない）
    var refShown = 0;
    sec.querySelectorAll('[data-nu-ref]').forEach(function(li){
      var ok = cat === 'all' || li.getAttribute('data-nu-cat') === cat;
      li.hidden = !ok; if (ok) refShown++;
    });
    var refEmpty = sec.querySelector('[data-nu-ref-empty]');
    if (refEmpty) refEmpty.hidden = refShown > 0;
    var pager = sec.querySelector('[data-nu-tpager]');
    if (pager) {
      pager.hidden = pages <= 1;
      while (pager.firstChild) pager.removeChild(pager.firstChild);
      for (var n = 1; pages > 1 && n <= pages; n++) {
        var a = document.createElement('a');
        a.className = 'nu-pager__link';
        a.setAttribute('href', rtHref('page_num', n > 1 ? String(n) : ''));
        a.setAttribute('data-nu-scrolltop', '');
        if (n === pageNum) a.setAttribute('aria-current', 'page');
        a.textContent = String(n);
        pager.appendChild(a);
      }
    }
    var form = sec.querySelector('[data-nu-search-form]'), input = sec.querySelector('[data-nu-search-input]');
    var tog = sec.querySelector('[data-nu-search-toggle]');
    if (term && form && form.hidden) { form.hidden = false; if (tog) tog.setAttribute('aria-expanded', 'true'); }
    if (input && document.activeElement !== input) input.value = q.get('q') || '';
  }
  // 商品詳細: URL の product_id（旧来の別名 ps5_pro なども受け付ける）の1件だけを出す。タブは URL の tab
  function productId(q) {
    var p = (q.get('product_id') || '').trim();
    return PD_ALIAS[p] || PD_ALIAS[p.replace(/^prod_/, '')] || p;
  }
  function renderProduct(q) {
    var sec = root.querySelector('[data-nu-page="product"]');
    if (!sec) return null;
    var pid = productId(q), found = null, now = Date.now();
    sec.querySelectorAll('[data-nu-pd]').forEach(function(a){
      var on = !!pid && a.getAttribute('data-nu-pd') === pid;
      a.hidden = !on;
      if (on) found = a;
    });
    var miss = sec.querySelector('[data-nu-pd-missing]');
    if (miss) miss.hidden = !!found;
    if (!found) return null;
    var tab = PD_TABS.indexOf(q.get('tab')) >= 0 ? q.get('tab') : 'buy';
    found.querySelectorAll('[data-nu-pdtab]').forEach(function(b){
      var on = b.getAttribute('data-nu-pdtab') === tab, panel = document.getElementById(b.getAttribute('aria-controls'));
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
      if (panel) panel.hidden = !on;
    });
    // 在庫ありと言える期限（確認から一定時間）を過ぎたら、「購入可能」「購入する」と言わない
    found.querySelectorAll('[data-nu-pd-until]').forEach(function(el){
      if (now < +el.getAttribute('data-nu-pd-until')) return;
      el.textContent = el.getAttribute('data-nu-pd-stale-text') || '';
      var cls = el.getAttribute('data-nu-pd-stale-class');
      if (cls) el.className = cls;
      if (el.hasAttribute('data-nu-pd-status')) {
        el.setAttribute('data-nu-pd-status', 'STOCK_UNKNOWN');
        el.className = 'nu-badge nu-tone-neutral';
      }
      el.removeAttribute('data-nu-pd-until');
    });
    // 今の状態: 購入可能でなければ、受付中などの抽選・予約（閲覧時の判定 NuLotteryRuntime）を出す
    var st = found.querySelector('[data-nu-pd-status]');
    if (st && st.getAttribute('data-nu-pd-status') !== 'AVAILABLE') {
      var lots = Array.prototype.slice.call(found.querySelectorAll('[data-nu-lot]')).filter(function(c){
        return +c.getAttribute('data-nu-bucket') < 99; });
      lots.sort(function(a, b){ return +a.getAttribute('data-nu-bucket') - +b.getAttribute('data-nu-bucket')
        || +a.getAttribute('data-nu-sort') - +b.getAttribute('data-nu-sort'); });
      if (lots.length) {
        if (!st.hasAttribute('data-nu-pd-base')) st.setAttribute('data-nu-pd-base', st.textContent);
        var badge = lots[0].querySelector('.nu-badge');
        st.textContent = badge ? badge.textContent.trim() : st.textContent;
        st.className = badge ? badge.className : st.className;
      } else {
        // 受付中などの抽選・予約が無い（締め切られた）ときは、在庫などから決めた状態に戻す
        st.textContent = st.getAttribute('data-nu-pd-fallback') || st.textContent;
        st.className = 'nu-badge nu-tone-' + (st.getAttribute('data-nu-pd-fallback-tone') || 'neutral');
      }
    }
    return found;
  }
  // 商品を検索: キーワード（q）とジャンル（category）で商品の一覧を絞り込む
  function renderSearch(q, cat) {
    var sec = root.querySelector('[data-nu-page="search"]');
    if (!sec) return;
    var term = (q.get('q') || '').trim().toLowerCase(), shown = 0;
    var inp = sec.querySelector('[data-nu-search-input]');
    if (inp && document.activeElement !== inp) inp.value = q.get('q') || '';
    sec.querySelectorAll('[data-nu-srow]').forEach(function(li){
      var ok = (cat === 'all' || li.getAttribute('data-nu-cat') === cat)
        && (!term || (li.getAttribute('data-search') || '').indexOf(term) >= 0);
      li.hidden = !ok;
      if (ok) shown++;
    });
    var res = sec.querySelector('[data-nu-sresult]');
    if (res) res.textContent = shown + '件';
    var empty = sec.querySelector('[data-nu-sempty]');
    if (empty) empty.hidden = shown > 0;
    // ジャンルを切り替えても検索語を保つ
    sec.querySelectorAll('a[data-nu-switch]').forEach(function(a){
      if (!a.hasAttribute('data-nu-sbase')) a.setAttribute('data-nu-sbase', a.getAttribute('href'));
      var base = a.getAttribute('data-nu-sbase'), raw = (q.get('q') || '').trim();
      a.setAttribute('href', raw ? base + (base.indexOf('?') >= 0 ? '&' : '?') + 'q=' + encodeURIComponent(raw) : base);
    });
  }
  function render(moveFocus) {
    var stockNext = stockRuntime(Date.now());
    var page = currentPage(), cat = currentCat(), lot = lotteryCounts(), rs = restockCounts();
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
      a.setAttribute('href', withCat('./', on ? 'all' : k));
    });
    root.querySelectorAll('[data-nu-switch]').forEach(function(a){
      setCurrent(a, a.getAttribute('data-nu-switch') === cat, 'true');
    });
    root.querySelectorAll('[data-nu-count]').forEach(function(el){
      var n = count(el.getAttribute('data-nu-count'), cat, lot, rs);
      el.textContent = n + '件';
      if (n) el.removeAttribute('data-zero'); else el.setAttribute('data-zero', '');
    });
    root.querySelectorAll('[data-nu-catcount]').forEach(function(el){
      // ジャンルの件数: ほかの目的の一部（せどりルート）は重ねて数えない（catalog.OVERLAPPING と同じ）
      var k = el.getAttribute('data-nu-catcount'), n = 0, overlap = DATA.overlap || [];
      PURPOSES.forEach(function(p){ if (overlap.indexOf(p) < 0) n += count(p, k, lot, rs); });
      el.textContent = n + '件';
      var a = el.closest('a');
      if (a) {
        a.setAttribute('aria-label', (CATS[k] || '') + ' ' + n + '件');
        if (n) a.removeAttribute('data-zero'); else a.setAttribute('data-zero', '');
      }
    });
    root.querySelectorAll('[data-nu-catlabel]').forEach(function(el){ el.textContent = CATS[cat] || ''; });
    root.querySelectorAll('[data-nu-home-ctx],[data-nu-crumb-cat]').forEach(function(el){ el.hidden = cat === 'all'; });
    root.querySelectorAll('a[data-nu-crumb-catlink]').forEach(function(a){ a.setAttribute('href', withCat('./', cat)); });
    // 一覧: ジャンルで絞り込み、抽選は閲覧時に掲載中のもの（bucket < 99）だけを出す
    renderOpp(q, cat);
    renderLot(q, cat);
    renderRestock(q, cat);
    renderRoutes(q, cat);
    var pdShown = renderProduct(q);
    renderSearch(q, cat);
    renderTimes();
    renderRTimes(Date.now());
    STOCK_NEXT = stockNext;
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
              : page === 'product' ? (pdShown ? pdShown.getAttribute('data-nu-pd-name') : '商品が見つかりません')
              : page === 'mypage' ? (TITLES.mypage || '')
              : (cat === 'all' ? '' : (CATS[cat] || '') + 'の') + (TITLES[page] || '');
    document.title = label + ' | ' + SITE;
    var focusId = q.get('focus') === 'operator' ? 'nu-operator' : '';
    var target = focusId ? document.getElementById(focusId)
               : page === 'product' ? (pdShown ? pdShown.querySelector('h1')
                                       : root.querySelector('[data-nu-pd-missing] h1'))
               : root.querySelector('[data-nu-page="' + page + '"] h1');
    if (moveFocus && target) {
      if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
      target.focus({preventScroll: true});
    }
    if (moveFocus && focusId && target) target.scrollIntoView({block: 'start'});
    // マイページ・ウォッチのボタン（mypage.py のスクリプト）に、表示が変わったことを知らせる
    root.dispatchEvent(new CustomEvent('nu:render', {detail: {page: page}}));
    return page;
  }
  function scrollToHash() {
    var id = location.hash.slice(1), el = id ? document.getElementById(id) : null;
    if (el) el.scrollIntoView({block: 'start'});
  }
  root.addEventListener('click', function(e){
    var a = e.target.closest('a[href^="?"], a[href="./"], a[href^="./#"]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    // 商品詳細の「戻る」: 一覧から来たときは履歴を戻る（ジャンル・絞り込み・並べ替え・ページを URL ごと戻す）
    if (a.hasAttribute('data-nu-back') && history.state && history.state.nuFrom) { history.back(); return; }
    var href = a.getAttribute('href').replace(/^\\.\\//, ''), i = href.indexOf('#');
    var next = new URLSearchParams((i >= 0 ? href.slice(0, i) : href).replace(/^\\?/, ''));
    next.delete('ui');                                   // 新UIが既定。旧UIへはこのルーターでは行かない
    var cur = new URLSearchParams(location.search);
    if (cur.get('debug') === '1') next.set('debug', '1');
    if (cur.get('mode') && !next.get('mode')) next.set('mode', cur.get('mode'));
    var before = currentPage();
    var nq = next.toString();
    var url = location.pathname + (nq ? '?' + nq : '') + (i >= 0 ? href.slice(i) : '');
    // 商品詳細へ入るときは、戻り先があることを履歴に残す（「戻る」で一覧の状態に戻すため）
    var state = (next.get('page') === 'product' && before !== 'product') ? {nuFrom: before} : null;
    if (url !== location.pathname + location.search + location.hash) history.pushState(state, '', url);
    var after = render(before !== currentPage());
    if (i >= 0) scrollToHash();
    else if (before !== after) window.scrollTo(0, 0);
    else if (a.hasAttribute('data-nu-scrolltop')) {
      var sec = root.querySelector('[data-nu-page="' + after + '"]');
      if (sec) sec.scrollIntoView({block: 'start'});
    }
  });
  // 商品詳細のタブ（URL の tab を書き換える。履歴は増やさない）。左右の矢印キーで隣のタブへ
  function selectPdTab(btn, focus) {
    var u = new URLSearchParams(location.search), k = btn.getAttribute('data-nu-pdtab');
    if (k === 'buy') u.delete('tab'); else u.set('tab', k);
    history.replaceState(history.state, '', location.pathname + '?' + u.toString());
    render(false);
    if (focus) btn.focus();
  }
  root.addEventListener('click', function(e){
    var b = e.target.closest('[data-nu-pdtab]');
    if (b) selectPdTab(b, false);
  });
  root.addEventListener('keydown', function(e){
    var b = e.target.closest('[data-nu-pdtab]');
    if (!b || ['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(e.key) < 0) return;
    var tabs = Array.prototype.slice.call(b.parentNode.querySelectorAll('[data-nu-pdtab]')), i = tabs.indexOf(b);
    var j = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1
          : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    e.preventDefault();
    selectPdTab(tabs[j], true);
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
  var timer = null, STOCK_NEXT = null;
  function refresh() {
    var res = null;
    try { res = NuLotteryRuntime.apply(root, Date.now()); } catch (e) { /* 失敗しても生成時点の表示のまま */ }
    render(false);
    if (timer) clearTimeout(timer);
    var now = Date.now(), wait = 60000 - (now % 60000) + 50;
    if (res && res.next !== null && res.next - now + 20 < wait) wait = Math.max(res.next - now + 20, 20);
    // 在庫ありの確認の期限（購入可能 → 更新待ち）にもちょうど更新する
    if (STOCK_NEXT !== null && STOCK_NEXT - now + 20 < wait) wait = Math.max(STOCK_NEXT - now + 20, 20);
    timer = setTimeout(refresh, wait);
  }
  // 戻る・タブの切り替えで戻ってきたときも判定し直す
  window.addEventListener('pageshow', refresh);
  document.addEventListener('visibilitychange', function(){ if (!document.hidden) refresh(); });
  // 「応募する」を押した瞬間にもう一度判定し、締切を過ぎていたら開かない
  function guardApply(e){
    // 「購入する」も押した瞬間に在庫の確認の期限を判定し直し、期限切れなら開かない
    var b = e.target.closest('a[data-nu-rcta]');
    if (b && b.getAttribute('data-nu-rcta') === 'buy') {
      refresh();
      if (!b.isConnected || b.getAttribute('data-nu-rcta') !== 'buy') {
        e.preventDefault();
        // 開かなかった理由を、ページの通知欄に出す（読み上げにも伝える。行は購入可能から外れて隠れるため）
        var row = b.closest('[data-nu-rs]'), notice = root.querySelector('[data-nu-rnotice]');
        if (notice) {
          var name = row ? (row.querySelector('h3') || {}).textContent || '' : '';
          notice.textContent = (name ? '「' + name + '」は' : '') + '在庫の確認から時間が経ったため、購入可能から外しました。'
            + '販売ページで在庫をご確認ください（「再開履歴すべて」に残っています）。';
          notice.hidden = false;
        }
      }
      return;
    }
    var a = e.target.closest('a[data-nu-cta]');
    if (!a || a.getAttribute('data-nu-cta') !== 'apply') return;
    refresh();
    if (!a.isConnected || a.getAttribute('data-nu-cta') !== 'apply') e.preventDefault();
  }
  root.addEventListener('click', guardApply, true);
  // 商品詳細の「購入する」も、押した瞬間に在庫ありと言える期限を確かめ直す（過ぎていれば開かずに表示を落とす）
  function guardPdBuy(e){
    var a = e.target.closest('a[data-nu-pd-until]');
    if (!a || Date.now() < +a.getAttribute('data-nu-pd-until')) return;
    e.preventDefault();
    render(false);
  }
  root.addEventListener('click', guardPdBuy, true);
  // 主要な数値から利益の根拠へ（同じページの中。URL は変えない。買う・売るのタブに切り替えてから移る）
  root.addEventListener('click', function(e){
    var j = e.target.closest('[data-nu-pd-jump]');
    if (!j) return;
    e.preventDefault();
    var art = j.closest('[data-nu-pd]'), b = art && art.querySelector('[data-nu-pdtab="buy"]');
    if (b && b.getAttribute('aria-selected') !== 'true') selectPdTab(b, false);
    var t = document.getElementById(j.getAttribute('data-nu-pd-jump'));
    if (t) { t.scrollIntoView({block: 'start'}); t.focus({preventScroll: true}); }
  });
  root.addEventListener('auxclick', guardPdBuy, true);
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
               "routes": "せどりルート", "more": "メニュー", "search": "商品を検索", "account": "運営者向け",
               "product": "商品詳細", "mypage": "マイページ", "admin": "運営"}


def build_catalog(ctx: ShellContext):
    """HOME のモデルと掲載データ（件数・一覧）。画面と内部の診断（opportunity_diagnostics）が同じものを使う。"""
    model = home.build_home_model(
        tcg_report=ctx.tcg_report, opportunities=ctx.opportunities,
        profit_routes=ctx.profit_routes, legacy_lotteries=ctx.legacy_lotteries, now=ctx.now)
    catalog = cl.build(model=model, tcg_report=ctx.tcg_report, profit_routes=ctx.profit_routes,
                       legacy_lotteries=ctx.legacy_lotteries, profit_deals=ctx.profit_deals,
                       product_genres=ctx.product_genres, stock_history=ctx.stock_history,
                       price_observations=ctx.price_observations)
    return model, catalog


def render_root(ctx: ShellContext) -> str:
    import json
    model, catalog = build_catalog(ctx)
    # 商品詳細（product_id ごと）。一覧からのリンクは、詳細のある商品にだけ付ける
    details = product_detail.build(products=ctx.products, catalog=catalog, observations=ctx.price_observations,
                                   price_history=ctx.price_history, stock_history=ctx.stock_history, now=model.now)
    catalog.product_ids = set(details)
    pd_alias = {v.alias: pid for pid, v in details.items()}
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
        + restock_page.render(catalog, now=model.now)
        + routes_page.render(catalog)
        + pages.render_more(catalog)
        + pages.render_search(details)
        + account.render()
        + product_page.render(details)
        # 運営者向け（UI Phase 9）。マイページより前に置く（マイページは本文の最後のページとして検査している）
        + admin.render(admin.build(dict(ctx.admin_data or {}, notifications=ctx.notifications), catalog=catalog,
                                   details=details, profit_routes=ctx.profit_routes, tcg_report=ctx.tcg_report,
                                   now=model.now, lp_generated=ctx.updated_text or ""))
        + mypage.render(details, mypage.build_events(details, ctx.notifications, ctx.profit_routes, model.now),
                        model.now)
    )
    brand = esc(_brand(ctx.site_title))
    cats_json = json.dumps({c.key: c.label for c in cats.CATEGORIES}, ensure_ascii=False)
    return (
        # hidden: CSS を使わない読み手にも、JS が表示を決めるまで新UIの本文を見せない（新UIのとき JS で外す）
        # 旧UI（?ui=legacy）のときだけ見える小さな案内（新UIのときは body 直下の要素なので CSS で隠れる）
        '<div class="nu-legacy-note" role="note">旧表示（確認・比較用に残しています）・'
        '<a href="./">新しい表示に戻る</a></div>'
        f'<div id="{ROOT_ID}" hidden data-nu-site="{brand}" '
        f"data-nu-map='{esc(navigation.legacy_map_json())}' "
        f"data-nu-cats='{esc(cats_json)}' data-nu-titles='{esc(json.dumps(PAGE_TITLES, ensure_ascii=False))}' "
        f"data-nu-pd-alias='{esc(json.dumps(pd_alias, ensure_ascii=False))}'>"
        '<a class="nu-skip" href="#nu-main">本文へ移動</a>'
        '<header class="nu-header"><div class="nu-header__inner">'
        f'<a class="nu-brand" href="{esc(navigation.page_href("home"))}" data-nu-nav-brand aria-label="{brand} HOME">'
        f'<span class="nu-brand__mark">{icon("trend", size=18)}</span>'
        f'<span class="nu-brand__name">{brand}</span><span class="nu-brand__en">Premium Monitor</span></a>'
        f'{navigation.top_nav()}'
        f'<div class="nu-header__tools">{updated}'
        f'<a class="nu-iconbtn" href="{esc(navigation.page_href("search"))}" data-nu-nav="search" aria-label="商品を検索">'
        f'{icon("search", size=20)}</a>'
        f'<a class="nu-iconbtn" href="{esc(navigation.page_href("mypage"))}" data-nu-nav="mypage" aria-label="マイページ">'
        f'{icon("star", size=20)}</a></div></div></header>'
        f'<main id="nu-main" class="nu-main" tabindex="-1">{body}</main>'
        f'{pages.render_footer(_brand(ctx.site_title))}'
        f'{navigation.bottom_nav()}'
        f'<script type="application/json" id="nu-lot-data">{rt.data_json(model.vms)}</script>'
        f'<script type="application/json" id="nu-catalog">{esc_json(catalog.data_json())}</script>'
        f'<script>{rt.runtime_js()}</script>'
        f'{mypage.script(details)}{admin.script()}'
        f'{_router_script()}'
        f'</div>{ROOT_END_MARK}'
    )


def esc_json(text: str) -> str:
    """<script type="application/json"> の中に入れる JSON（</script> で閉じられないようにする）。"""
    return text.replace("</", "<\\/")
