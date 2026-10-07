/* 新UIの抽選の閲覧時の状態。
 * deriveLotteryRuntimeState は src/content/ui/runtime.py の derive_runtime_state と同じ結果を返す
 * （状態の判定は src/tcg/lottery/schema.py の compute_lottery_status を移したもの）。
 * tests/test_new_ui_runtime.py が node で実行し、固定時刻で Python 側と一致することを確かめている。
 * ここでは状態を推測で作らない。日付だけ（時刻未公表）の値に時刻を足さない。
 */
var NuLotteryRuntime = (function () {
  'use strict';
  var MIN = 60000, HOUR = 3600000, DAY = 86400000, JST = 9 * HOUR;
  var WEEK = '日月火水木金土';
  var OPEN = { OPEN: 1, ENDING_SOON: 1 };

  function exact(v) { if (!v) return null; var t = Date.parse(v); return isNaN(t) ? null : t; }
  function day(v) {
    if (!v || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
    var t = Date.parse(v + 'T00:00:00+09:00'); return isNaN(t) ? null : t;
  }
  // (確実に過ぎたと言える時刻, まだ来ていないと言える時刻)。schema._bound と同じ
  function bound(vm, k, kd) {
    var e = exact(vm[k]); if (e !== null) return [e, e];
    var d = day(vm[kd]); if (d !== null) return [d + DAY, d];
    return [null, null];
  }
  // schema.compute_lottery_status と同じ判定
  function computeStatus(vm, now, C) {
    var s = bound(vm, 'as', 'asd'), e = bound(vm, 'ae', 'aed'), r = bound(vm, 'wa', 'wad');
    var ps = bound(vm, 'ps', 'psd'), pe = bound(vm, 'pe', 'ped');
    var sp = s[0], ep = e[0], enot = e[1], rp = r[0], rnot = r[1], psp = ps[0], pep = pe[0], penot = pe[1];
    if (sp === null && ep === null) return 'UNKNOWN';
    var ended = ep !== null && now >= ep;
    if (!ended && sp !== null && now < sp) return 'UPCOMING';
    if (ep === null) return (sp !== null && now - sp <= C.start_only_ms) ? 'UNKNOWN' : 'ENDED';
    if (now < enot) return (enot - now) <= C.ending_soon_ms ? 'ENDING_SOON' : 'OPEN';
    if (now < ep) return 'ENDING_SOON';
    if (pep !== null && now >= pep) return 'ENDED';
    if (psp !== null && penot !== null && psp <= now) return 'WINNER_PURCHASE_PERIOD';
    if (rnot !== null && now < rnot) return 'RESULT_PENDING';
    if (rp !== null && now < rp) return 'RESULT_PENDING';
    if (rp !== null && now >= rp) return (pep === null && now - rp > C.closed_ms) ? 'ENDED' : 'WINNER_ANNOUNCED';
    return (now - ep <= C.closed_ms) ? 'CLOSED' : 'ENDED';
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function jst(t) { return new Date(t + JST); }
  function ymd(t) { return jst(t).toISOString().slice(0, 10); }
  function fmtExact(iso) {
    var d = jst(exact(iso));
    return (d.getUTCMonth() + 1) + '/' + d.getUTCDate() + '(' + WEEK[d.getUTCDay()] + ') ' +
      pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes());
  }
  function fmtDay(v) {
    var d = jst(day(v));
    return (d.getUTCMonth() + 1) + '/' + d.getUTCDate() + '(' + WEEK[d.getUTCDay()] + ')';
  }
  function when(vm, k, kd, suffix) {
    if (vm[k]) return fmtExact(vm[k]) + ' ' + suffix;
    if (vm[kd]) return fmtDay(vm[kd]) + ' ' + suffix + '・時刻未公表';
    return '';
  }
  function countdownText(target, now) {
    var diff = target - now;
    if (diff <= 0) return '';
    if (diff >= DAY) return Math.floor(diff / DAY) + '日';
    if (diff >= HOUR) return Math.floor(diff / HOUR) + '時間';
    return Math.max(Math.floor(diff / MIN), 1) + '分';
  }
  function infoCta(vm, style) {
    if (!vm.info) return null;
    return { kind: 'info', label: vm.info_official ? '公式情報を見る' : '情報元を見る',
      url: vm.info, style: style || 'secondary', track: 'lottery_info_click' };
  }

  // 発売待ち（runtime._release_state と同じ）。発売日の 0 時を過ぎたら一覧から外す
  function releaseState(vm, now, C) {
    var d0 = day(vm.rd), waiting = d0 !== null && now < d0;
    var status = waiting ? 'RELEASE_WAIT' : (d0 !== null ? 'ENDED' : 'UNKNOWN');
    var meta = C.statuses[status] || C.statuses.UNKNOWN;
    var rest = waiting ? countdownText(d0, now) : '';
    return {
      status: status, label: meta.label, icon: meta.icon, tone: meta.tone,
      when: waiting ? fmtDay(vm.rd) + ' 発売予定' : (d0 !== null ? '発売日を過ぎました' : '日程は未公表です'),
      cd_text: rest ? '発売まで あと' + rest : '', cta: infoCta(vm),
      bucket: waiting ? 5 : 99, sort: waiting ? d0 : 0,
      open: false, ending_today: false, starting_24h: false, upcoming: false
    };
  }

  function deriveLotteryRuntimeState(vm, now, C) {
    if (vm.k === 'release') return releaseState(vm, now, C);
    var preorder = vm.k === 'preorder';
    var base = computeStatus(vm, now, C);
    // 予約には当選発表・当選者の購入期間が無い。受付期間の後は「予約受付終了」（runtime.py と同じ）
    if (preorder && (base === 'RESULT_PENDING' || base === 'WINNER_ANNOUNCED' || base === 'WINNER_PURCHASE_PERIOD')) {
      base = 'CLOSED';
    }
    var status = vm.conflict ? 'SOURCE_CONFLICT' : base;
    var s = bound(vm, 'as', 'asd'), e = bound(vm, 'ae', 'aed');
    var isOpen = !!OPEN[status], cta = null;
    if (isOpen) {
      if (vm.apply && !vm.unv && s[0] !== null && now >= s[0] && e[1] !== null && now < e[1]) {
        cta = { kind: 'apply', label: preorder ? '予約する' : '応募する', url: vm.apply, style: 'primary', track: 'lottery_apply_click' };
      } else {
        cta = infoCta(vm, vm.unv ? 'secondary' : 'primary');
      }
    } else if (status === 'WINNER_PURCHASE_PERIOD') {
      if (vm.purchase) cta = { kind: 'purchase', label: '購入ページ（当選者のみ）', url: vm.purchase, style: 'primary', track: 'lottery_purchase_click' };
      else if (vm.result) cta = { kind: 'result', label: '結果を確認', url: vm.result, style: 'primary', track: 'lottery_result_click' };
      else cta = infoCta(vm);
    } else if ((status === 'RESULT_PENDING' || status === 'WINNER_ANNOUNCED') && vm.result) {
      cta = { kind: 'result', label: '結果を確認', url: vm.result, style: 'secondary', track: 'lottery_result_click' };
    } else {
      cta = infoCta(vm);
    }

    var w, prefix = '', key = '';
    if (isOpen) { w = when(vm, 'ae', 'aed', '締切'); prefix = '締切まで'; key = 'ae'; }
    else if (status === 'UPCOMING') { w = when(vm, 'as', 'asd', '開始'); prefix = '開始まで'; key = 'as'; }
    else if (status === 'WINNER_PURCHASE_PERIOD') { w = when(vm, 'pe', 'ped', '購入期限'); prefix = '購入期限まで'; key = 'pe'; }
    else if (status === 'RESULT_PENDING') w = when(vm, 'wa', 'wad', '当選発表') || '当選発表待ち';
    else if (status === 'WINNER_ANNOUNCED') w = '当選発表済み';
    else if (status === 'CLOSED') w = when(vm, 'ae', 'aed', '受付終了') || '受付終了';
    else if (status === 'ENDED') w = '終了しました';
    else if (status === 'SOURCE_CONFLICT') w = '日程は公式情報でご確認ください';
    else w = '日程は未公表です';
    var cd = '';
    if (key && vm[key]) { var rest = countdownText(exact(vm[key]), now); cd = rest ? prefix + ' あと' + rest : ''; }

    var today = ymd(now);
    var aeDay = vm.ae ? ymd(exact(vm.ae)) : vm.aed;
    var asMs = vm.as ? exact(vm.as) : null;
    var counted = !vm.ann;
    var bucket = 99, sort = 0;
    if (counted && status === 'ENDING_SOON') { bucket = 0; sort = e[0] || 0; }
    else if (counted && status === 'OPEN') { bucket = 1; sort = e[0] || 0; }
    else if (counted && status === 'UPCOMING') { bucket = 3; sort = s[1] || 0; }
    else if (counted && status === 'SOURCE_CONFLICT') { bucket = 4; sort = 0; }
    else if (counted && status === 'WINNER_PURCHASE_PERIOD') { bucket = 2; sort = bound(vm, 'pe', 'ped')[0] || 0; }
    else if (counted && (status === 'RESULT_PENDING' || status === 'WINNER_ANNOUNCED')) { bucket = 5; sort = e[0] || 0; }
    var meta = C.statuses[status] || C.statuses.UNKNOWN;
    var label = preorder && (C.preorder_labels || {})[status] ? C.preorder_labels[status] : meta.label;
    var tone = meta.tone, unconfirmed = !!vm.unv && isOpen;
    if (unconfirmed) { label = label + '（確認待ち）'; tone = 'warning'; }
    return {
      status: status, label: label, icon: meta.icon, tone: tone,
      when: w, cd_text: cd, cta: cta, bucket: bucket, sort: sort,
      open: counted && isOpen && !preorder && !unconfirmed,
      ending_today: counted && isOpen && aeDay === today,
      starting_24h: counted && !preorder && status === 'UPCOMING' &&
        ((asMs !== null && asMs - now <= DAY) || (asMs === null && vm.asd === today)),
      upcoming: counted && !preorder && status === 'UPCOMING'
    };
  }

  // 次に状態が変わりうる時刻（日時・日付の境目と、締切の24時間前）。無ければ null
  function nextChange(vms, now, C) {
    var best = null;
    vms.forEach(function (vm) {
      [['as', 'asd'], ['ae', 'aed'], ['wa', 'wad'], ['ps', 'psd'], ['pe', 'ped'], ['', 'rd']].forEach(function (k) {
        var e = exact(vm[k[0]]), d = day(vm[k[1]]);
        [e, e === null ? null : e - C.ending_soon_ms, d, d === null ? null : d + DAY,
         d === null ? null : d - C.ending_soon_ms].forEach(function (t) {
          if (t !== null && t > now && (best === null || t < best)) best = t;
        });
      });
    });
    return best;
  }

  function nextStartNote(vms, states) {
    var best = null;
    vms.forEach(function (v) {
      var s = states[v.id];
      if (!s.upcoming) return;
      if (!best || s.sort < states[best.id].sort || (s.sort === states[best.id].sort && v.id < best.id)) best = v;
    });
    if (!best) return '';
    if (best.as) return '次: ' + fmtExact(best.as) + ' 開始';
    if (best.asd) return '次: ' + fmtDay(best.asd) + ' 開始';
    return '';
  }

  // ── DOM への反映（すべて derive の結果だけを使う） ──
  function setBadge(badge, st, status) {
    badge.className = 'nu-badge nu-tone-' + st.tone;
    badge.setAttribute('data-status', status);
    badge.textContent = '';
    var icon = document.createElement('span');
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = st.icon;
    badge.appendChild(icon);
    badge.appendChild(document.createTextNode(' ' + st.label));
  }
  function setCta(card, cta) {
    var a = card.querySelector('a[data-nu-cta]');
    if (!cta || !/^https:\/\//.test(cta.url)) { if (a) a.remove(); return; }
    if (!a) {
      a = document.createElement('a');
      // 一覧の行（抽選・予約のページ）はボタンの置き場所が決まっている
      var slot = card.querySelector('[data-nu-cta-slot]'), det = card.querySelector('details');
      if (slot) slot.appendChild(a);
      else if (det) card.insertBefore(a, det); else card.appendChild(a);
    }
    a.className = 'nu-btn nu-btn--' + cta.style;
    a.href = cta.url;
    a.target = '_blank';
    a.rel = 'noopener nofollow';
    a.setAttribute('data-track', cta.track);
    a.setAttribute('data-nu-cta', cta.kind);
    a.textContent = cta.label;
  }
  function updateCard(card, st) {
    card.setAttribute('data-nu-status', st.status);
    card.setAttribute('data-nu-bucket', String(st.bucket));
    card.setAttribute('data-nu-sort', String(st.sort));
    // 抽選・予約のページの絞り込み（今日締切）に使う
    card.setAttribute('data-nu-today', st.ending_today ? '1' : '0');
    var badge = card.querySelector('.nu-badge');
    if (badge) setBadge(badge, st, st.status);
    var w = card.querySelector('.nu-when');
    if (w) w.textContent = st.when;
    var cd = card.querySelector('.nu-cd');
    if (cd) cd.textContent = st.cd_text;
    setCta(card, st.cta);
  }
  function setTile(tile, n, note) {
    var cnt = tile.querySelector('.nu-tile__count');
    if (cnt) cnt.textContent = String(n);
    tile.setAttribute('data-count', String(n));
    var tone = n > 0 ? (tile.getAttribute('data-nu-tone') || 'neutral') : 'neutral';
    tile.className = tile.className.replace(/nu-tone-\w+/, 'nu-tone-' + tone);
    var label = tile.querySelector('.nu-tile__label');
    tile.setAttribute('aria-label', (label ? label.textContent.trim() : '') + ' ' + n + '件');
    if (note !== undefined) {
      var el = tile.querySelector('.nu-tile__note');
      if (note && !el) { el = document.createElement('span'); el.className = 'nu-tile__note'; tile.appendChild(el); }
      if (el) { if (note) el.textContent = note; else el.remove(); }
    }
  }
  function reorder(container, limit) {
    var cards = Array.prototype.slice.call(container.querySelectorAll(':scope > [data-nu-bucket]'));
    cards.sort(function (a, b) {
      var ka = [+a.getAttribute('data-nu-bucket'), +a.getAttribute('data-nu-sort'), +a.getAttribute('data-nu-idx')];
      var kb = [+b.getAttribute('data-nu-bucket'), +b.getAttribute('data-nu-sort'), +b.getAttribute('data-nu-idx')];
      for (var i = 0; i < 3; i++) if (ka[i] !== kb[i]) return ka[i] - kb[i];
      return 0;
    });
    var shown = 0;
    cards.forEach(function (c) {
      var ok = +c.getAttribute('data-nu-bucket') < 99 && shown < limit;
      c.hidden = !ok;
      if (ok) shown++;
      container.appendChild(c);
    });
    var empty = container.querySelector('[data-nu-empty-home]');
    if (empty) { empty.hidden = shown > 0; container.appendChild(empty); }
    container.setAttribute('data-nu-actions', String(shown));
    return shown;
  }

  function apply(root, now) {
    var el = root.querySelector('#nu-lot-data');
    if (!el) return null;
    var data = JSON.parse(el.textContent || '{}'), C = data.cfg, vms = data.vms || [];
    var states = {}, counts = { lottery_open: 0, ending_today: 0, starting_24h: 0 }, sums = {};
    vms.forEach(function (vm) {
      var st = deriveLotteryRuntimeState(vm, now, C);
      states[vm.id] = st;
      if (st.open) counts.lottery_open++;
      if (st.ending_today) counts.ending_today++;
      if (st.starting_24h) counts.starting_24h++;
      if (!vm.ann) sums[st.status] = (sums[st.status] || 0) + 1;
    });
    root.querySelectorAll('[data-nu-lot]').forEach(function (card) {
      var st = states[card.getAttribute('data-nu-lot')];
      if (st) updateCard(card, st);
    });
    var note = counts.lottery_open ? '' : nextStartNote(vms, states);
    Object.keys(counts).forEach(function (k) {
      var t = root.querySelector('[data-tile="' + k + '"]');
      if (t) setTile(t, counts[k], k === 'lottery_open' ? note : undefined);
    });
    root.querySelectorAll('[data-nu-sum]').forEach(function (row) {
      var n = row.querySelector('.nu-sumrow__n');
      if (n) n.textContent = (sums[row.getAttribute('data-nu-sum')] || 0) + '件';
    });
    var box = root.querySelector('[data-nu-actions]');
    var shown = box ? reorder(box, +(box.getAttribute('data-nu-limit') || 5)) : 0;
    return { states: states, counts: counts, shown: shown, next: nextChange(vms, now, C) };
  }

  return { computeStatus: computeStatus, deriveLotteryRuntimeState: deriveLotteryRuntimeState,
    countdownText: countdownText, nextStartNote: nextStartNote, nextChange: nextChange, apply: apply };
})();
if (typeof module !== 'undefined') module.exports = NuLotteryRuntime;
