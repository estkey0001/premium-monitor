# -*- coding: utf-8 -*-
"""TCG 取得の「同一 run のキャッシュ」「ドメインごとの直列化」「全体の並列上限」（Coverage Wave 6 Stage H / I）。

- 同一 run のキャッシュ: 同じ URL（正規化した形）を同じ run で 2 回取得しない。成功も失敗（403・robots・通信失敗）も覚える
  （ブロックされた URL を取り直さない = 回避しない）。**保持はメモリだけ・この run の間だけ**。前回の run の応答を新しい証拠として使わない
  （ファイルに書かない・取得時刻を新しくしない）。有効にするのは `activate()` の中だけ（テストや他の呼び出しには影響しない）。
- 同時に 1 つ（single-flight）: 同じ URL を 2 つのスレッドが同時に要求したら、1 つだけ取得し、もう 1 つはその結果を待つ。
- ドメインごとの直列化: 同じドメインへの取得は同時に 1 つだけ（polite の間隔 60 秒以上は RateLimiter が別に守る）。
- 全体の並列上限: 同時に通信する数に上限（GLOBAL_CAP）を置く（間隔の待ちの間は枠を使わない）。上限なしの並列にしない。
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit

JST = timezone(timedelta(hours=9))
GLOBAL_CAP = 12                # 同時に動かす取得元（スレッド）の数の上限。ドメインごとは 1 つずつ・60 秒以上の間隔なので全体でも毎分 12 件程度

_ACTIVE: Optional["TcgRunCache"] = None
_STATE_LOCK = threading.Lock()
_DOMAIN_LOCKS: dict[str, threading.Lock] = {}
MAX_TASK_THREADS = 64          # 取得元のスレッドの数の上限（間隔の待ちで眠っているだけのものを含む）
_GLOBAL_SLOTS = threading.BoundedSemaphore(GLOBAL_CAP)


def normalize_url(url: str) -> str:
    """キャッシュの鍵（スキーム・ホストは小文字、末尾のスラッシュ・フラグメントを除く。クエリは残す）。"""
    if not url:
        return ""
    sp = urlsplit(url.strip())
    path = sp.path.rstrip("/") or "/"
    return urlunsplit((sp.scheme.lower(), sp.netloc.lower(), path, sp.query, ""))


def domain_of(url: str) -> str:
    return urlsplit(url or "").netloc.lower()


def domain_lock(url: str) -> threading.Lock:
    """そのドメインへの取得を同時に 1 つにするためのロック。"""
    d = domain_of(url)
    with _STATE_LOCK:
        lock = _DOMAIN_LOCKS.get(d)
        if lock is None:
            lock = _DOMAIN_LOCKS[d] = threading.Lock()
        return lock


@contextmanager
def global_slot():
    """全体の並列上限の枠を 1 つ使う。"""
    _GLOBAL_SLOTS.acquire()
    try:
        yield
    finally:
        _GLOBAL_SLOTS.release()


class TcgRunCache:
    """1 回の run の間だけ有効な、取得結果のメモリキャッシュ。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        self._inflight: dict[str, threading.Event] = {}
        self.fetches = 0            # 実際に取得した回数
        self.hits = 0               # キャッシュで省いた回数
        self.by_domain: dict[str, int] = {}

    def fetch(self, url: str, do_fetch: Callable[[], dict], variant: str = "") -> tuple[dict, bool]:
        """(entry, hit)。entry は {"html": str|None, "error": str|None, "blocked": bool, "status": int|None, "final_url": str|None,
        "fetched_at": ISO 日時（実際に取得した時刻。キャッシュで受け取った側も、この時刻を使う）}。
        do_fetch は実際の取得（成功も失敗も entry を返す。例外にしない）。variant: 取得の方法（JS 描画 = "js"）。違う方法の応答を混ぜない。"""
        key = normalize_url(url) + ("#" + variant if variant else "")
        while True:
            with self._lock:
                if key in self._entries:
                    self.hits += 1
                    return self._entries[key], True
                ev = self._inflight.get(key)
                if ev is None:
                    ev = self._inflight[key] = threading.Event()
                    break
            ev.wait(timeout=1800)                      # 同じ URL を取得中のスレッドの結果を待つ（取得は 1 つだけ）
        entry = None
        try:
            try:
                entry = do_fetch()
            except Exception as exc:  # noqa: BLE001 - 取得の例外もキャッシュして取り直さない
                entry = {"html": None, "error": f"{type(exc).__name__}", "blocked": False, "status": None, "final_url": None}
            entry.setdefault("fetched_at", datetime.now(timezone.utc).astimezone(JST).isoformat())
        finally:
            with self._lock:                           # 中断（KeyboardInterrupt など）でも待機側を必ず解放する
                if entry is not None:
                    self._entries[key] = entry
                    self.fetches += 1
                    d = domain_of(url)
                    self.by_domain[d] = self.by_domain.get(d, 0) + 1
                self._inflight.pop(key).set()
        return entry, False

    def stats(self) -> dict:
        with self._lock:
            return {"fetches": self.fetches, "cache_hits": self.hits, "domains": len(self.by_domain),
                    "max_per_domain": max(self.by_domain.values()) if self.by_domain else 0}


def active() -> Optional[TcgRunCache]:
    return _ACTIVE


@contextmanager
def activate():
    """この run の間だけキャッシュを有効にする。抜けたら捨てる（次の run に持ち越さない）。"""
    global _ACTIVE
    cache = TcgRunCache()
    prev, _ACTIVE = _ACTIVE, cache
    try:
        yield cache
    finally:
        _ACTIVE = prev


def run_parallel(tasks: list[tuple[str, Callable[[], object]]], max_workers: int | None = None) -> dict[str, dict]:
    """tasks（名前, 関数）を並列に実行する。戻りは {名前: {"result": ..., "error": 型名|None, "seconds": 秒}}。

    スレッドは取得元の数だけ作る（多くは間隔の待ちで眠っている）。**同時に通信する数の上限は global_slot（通信の間だけ確保）**。
    1 つの失敗で他を止めない。ドメインごとの間隔は取得の側（RateLimiter・domain_lock）が守る。
    """
    from concurrent.futures import ThreadPoolExecutor
    out: dict[str, dict] = {}

    def _run(name: str, fn: Callable[[], object]) -> dict:
        t0 = time.monotonic()
        try:
            return {"result": fn(), "error": None, "seconds": round(time.monotonic() - t0, 1)}
        except Exception as exc:  # noqa: BLE001
            return {"result": None, "error": f"{type(exc).__name__}: {exc}"[:200], "seconds": round(time.monotonic() - t0, 1)}
    n = max(1, min(int(max_workers or len(tasks) or 1), MAX_TASK_THREADS))
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = [(name, ex.submit(_run, name, fn)) for name, fn in tasks]
        for name, f in futs:
            out[name] = f.result()
    return out
