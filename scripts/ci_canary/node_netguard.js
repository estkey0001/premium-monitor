// CI canary 用の外部通信の遮断・記録（Node。標準モジュールだけ・Secrets を読まない）。
// NODE_OPTIONS=--require=<このファイル> で読み込む。ループバック・UNIX ソケット・パイプ以外への
// 接続（net.Socket#connect。http / https / fetch もここを通る）と名前解決（dns.lookup / dns.resolve*）を
// 実行前に止め（例外）、違反を 1 行の JSON で記録する（ホストだけ。ポート・パス・内容は書かない）。
// 記録先は環境変数 CANARY_NODE_LOG。未設定のときは何もしない。
'use strict';
const fs = require('fs');
const net = require('net');
const dns = require('dns');

const LOG = process.env.CANARY_NODE_LOG;

function write(rec) {
  try { fs.appendFileSync(LOG, JSON.stringify(rec) + '\n'); } catch (e) { /* 記録できなくても止める */ }
}

function isLoopback(host) {
  if (host === undefined || host === null || host === '') return true;
  const h = String(host).replace(/^\[|\]$/g, '').split('%')[0];
  if (h === 'localhost') return true;
  if (/^127\.\d+\.\d+\.\d+$/.test(h)) return true;
  if (h === '::1' || /^::ffff:127\.\d+\.\d+\.\d+$/i.test(h)) return true;
  return false;
}

function block(event, host) {
  write({ kind: 'violation', event, target: String(host).slice(0, 200), pid: process.pid });
  const err = new Error('canary: 外部通信を遮断した（' + event + ' → ' + String(host).slice(0, 80) + '）');
  err.code = 'ECANARYBLOCKED';
  throw err;
}

if (LOG) {
  write({ kind: 'installed', pid: process.pid });

  const origConnect = net.Socket.prototype.connect;
  net.Socket.prototype.connect = function (...args) {
    // net.connect(port, host) などは、内部で正規化された [options, cb] の配列を渡して connect を呼ぶ
    const a = Array.isArray(args[0]) ? args[0][0] : args[0];
    let host;
    if (a !== null && typeof a === 'object') {
      if (a.path) return origConnect.apply(this, args); // UNIX ソケット・パイプ
      host = a.host === undefined ? 'localhost' : a.host;
    } else if (typeof a === 'string' && Number.isNaN(Number(a))) {
      return origConnect.apply(this, args); // パスの指定
    } else {
      host = typeof args[1] === 'string' ? args[1] : 'localhost';
    }
    if (!isLoopback(host)) block('net.connect', host);
    return origConnect.apply(this, args);
  };

  const origLookup = dns.lookup;
  dns.lookup = function (host, ...rest) {
    if (!isLoopback(host)) block('dns.lookup', host);
    return origLookup.call(this, host, ...rest);
  };
  for (const fn of ['resolve', 'resolve4', 'resolve6', 'resolveAny', 'resolveTxt', 'resolveMx', 'resolveSrv', 'resolveCname']) {
    const orig = dns[fn];
    if (typeof orig !== 'function') continue;
    dns[fn] = function (host, ...rest) {
      if (!isLoopback(host)) block('dns.' + fn, host);
      return orig.call(this, host, ...rest);
    };
  }
  if (dns.promises && typeof dns.promises.lookup === 'function') {
    const origP = dns.promises.lookup;
    dns.promises.lookup = function (host, ...rest) {
      if (!isLoopback(host)) block('dns.promises.lookup', host);
      return origP.call(this, host, ...rest);
    };
  }
}
