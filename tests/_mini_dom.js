// テスト用の小さな DOM（jsdom などの追加の依存を入れずに、抽選ページの絞り込みの JS を node で動かすため）。
// 対応する範囲は、抽選ページの JS が使うものだけ: 子孫結合のセレクタ（タグ・#id・.class・[属性]・[属性=値]・[属性^=値]・:not(単純)）、
// hidden・open・dataset・classList・textContent・closest・querySelector(All)・イベント・フォームの elements と select の value。
'use strict';

class Ev {
  constructor(type) { this.type = type; this.defaultPrevented = false; }
  preventDefault() { this.defaultPrevented = true; }
}

function kebab(k) { return k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase()); }

class El {
  constructor(tag, attrs) {
    this.tagName = tag.toUpperCase(); this.attrs = new Map(attrs || []); this.children = []; this.parentElement = null;
    this.listeners = {};
    const self = this;
    this.dataset = new Proxy({}, { get: (_, k) => self.getAttribute('data-' + kebab(String(k))) ?? undefined,
      set: (_, k, v) => { self.setAttribute('data-' + kebab(String(k)), v); return true; } });
    this.classList = {
      contains: (c) => self._cls().includes(c),
      add: (c) => { if (!self._cls().includes(c)) self.setAttribute('class', self._cls().concat([c]).join(' ')); },
      remove: (c) => self.setAttribute('class', self._cls().filter((x) => x !== c).join(' ')),
      toggle: (c, on) => { const has = self._cls().includes(c); const want = on === undefined ? !has : !!on;
        if (want && !has) self.classList.add(c); if (!want && has) self.classList.remove(c); return want; },
    };
  }
  _cls() { return (this.getAttribute('class') || '').split(/\s+/).filter(Boolean); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  removeAttribute(k) { this.attrs.delete(k); }
  hasAttribute(k) { return this.attrs.has(k); }
  get hidden() { return this.attrs.has('hidden'); }
  set hidden(v) { if (v) this.attrs.set('hidden', ''); else this.attrs.delete('hidden'); }
  get open() { return this.attrs.has('open'); }
  set open(v) { if (v) this.attrs.set('open', ''); else this.attrs.delete('open'); }
  get id() { return this.getAttribute('id') || ''; }
  get textContent() { return this.children.map((c) => (typeof c === 'string' ? c : c.textContent)).join(''); }
  set textContent(v) { this.children = [String(v)]; }
  get innerText() { return this.textContent; }
  get elements() {
    const out = {};
    this.querySelectorAll('select,input').forEach((e) => { if (e.getAttribute('name')) out[e.getAttribute('name')] = e; });
    return out;
  }
  get value() {
    if (this._value !== undefined) return this._value;
    const o = this.querySelector('option');
    return o ? (o.getAttribute('value') ?? o.textContent) : (this.getAttribute('value') || '');
  }
  set value(v) { this._value = String(v); }
  *_desc() { for (const c of this.children) if (typeof c !== 'string') { yield c; yield* c._desc(); } }
  querySelectorAll(sel) { const m = parse(sel); return [...this._desc()].filter((e) => m.some((s) => matches(e, s))); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  matches(sel) { return parse(sel).some((s) => matches(this, s)); }
  closest(sel) { let e = this; while (e) { if (e.matches(sel)) return e; e = e.parentElement; } return null; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  dispatchEvent(ev) { ev.target = ev.target || this; (this.listeners[ev.type] || []).forEach((f) => f(ev)); return !ev.defaultPrevented; }
  click() { return this.dispatchEvent(new Ev('click')); }
  scrollIntoView() {}
}

// セレクタ: カンマ区切り → 空白区切りの複合 → 単純セレクタの並び
function parse(sel) {
  return sel.split(',').map((one) => one.trim().split(/\s+/).map(compound));
}
function compound(s) {
  const out = []; let i = 0;
  const tag = /^[a-zA-Z][a-zA-Z0-9]*/.exec(s); if (tag) { out.push({ t: 'tag', v: tag[0].toUpperCase() }); i = tag[0].length; }
  while (i < s.length) {
    const r = s.slice(i); let m;
    if ((m = /^#([\w-]+)/.exec(r))) out.push({ t: 'id', v: m[1] });
    else if ((m = /^\.([\w-]+)/.exec(r))) out.push({ t: 'cls', v: m[1] });
    else if ((m = /^\[([\w-]+)(?:(\^?=)["']?([^"'\]]*)["']?)?\]/.exec(r))) out.push({ t: 'attr', k: m[1], op: m[2], v: m[3] });
    else if ((m = /^:not\(([^)]*)\)/.exec(r))) out.push({ t: 'not', v: compound(m[1]) });
    else throw new Error('未対応のセレクタ: ' + s);
    i += m[0].length;
  }
  return out;
}
function simple(e, p) {
  if (p.t === 'tag') return e.tagName === p.v;
  if (p.t === 'id') return e.getAttribute('id') === p.v;
  if (p.t === 'cls') return e._cls().includes(p.v);
  if (p.t === 'attr') { const a = e.getAttribute(p.k); if (a === null) return false;
    return !p.op || (p.op === '=' ? a === p.v : a.startsWith(p.v)); }
  if (p.t === 'not') return !p.v.every((q) => simple(e, q));
  return false;
}
function matches(e, chain) {
  if (!chain[chain.length - 1].every((p) => simple(e, p))) return false;
  let k = chain.length - 2, a = e.parentElement;
  while (k >= 0 && a) { if (chain[k].every((p) => simple(a, p))) k--; a = a.parentElement; }
  return k < 0;
}

function build(node, parent) {
  if (typeof node === 'string') return node;
  const e = new El(node.tag, node.attrs); e.parentElement = parent || null;
  e.children = node.children.map((c) => build(c, e));
  return e;
}

function makeEnv(tree, nowMs) {
  const root = build(tree, null);
  const doc = new El('#document');
  doc.children = [root]; root.parentElement = null;
  doc.getElementById = (id) => (root.getAttribute('id') === id ? root : root.querySelector('#' + id));
  doc.querySelectorAll = (s) => [root].filter((e) => e.matches(s)).concat(root.querySelectorAll(s));
  doc.querySelector = (s) => doc.querySelectorAll(s)[0] || null;
  const win = { listeners: {}, addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); } };
  const g = { document: doc, window: win, location: { hash: '' }, history: { replaceState() {} }, Event: Ev,
    setInterval() {}, now: nowMs };
  return g;
}

function run(tree, scripts, nowMs, steps) {
  const g = makeEnv(tree, nowMs);
  const RealDate = Date;
  const FakeDate = class extends RealDate { constructor(...a) { if (a.length) super(...a); else super(g.now); } static now() { return g.now; } };
  const fn = new Function('document', 'window', 'location', 'history', 'Event', 'setInterval', 'Date', scripts);
  fn(g.document, g.window, g.location, g.history, g.Event, g.setInterval, FakeDate);
  return steps(g);
}

module.exports = { run, Ev };
