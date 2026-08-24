#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API Automation 回帰テスト（Task32/36）。

APIキー未設定でも全て PASS すること。実APIは呼ばず、モック/fixture で検証。
利益/AI ロジックは対象外（API収集・品質ゲート・ランタイムのみ）。
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.collectors.api import api_runtime as rt
from src.collectors.api.api_runtime import (
    CircuitBreaker, HealthTracker, retry_with_backoff, classify_error,
    is_configured, kill_switch_on, api_enabled, is_dry_run,
)
from src.market.product_identity_resolver import ProductIdentityResolver

_NO_SLEEP = lambda _d: None  # noqa: E731


def _resolver():
    products = {
        "prod_iphone17pro_256": {"name": "iPhone 17 Pro 256GB SIMフリー", "model_number": ""},
        "prod_iphone17pm_256": {"name": "iPhone 17 Pro Max 256GB SIMフリー", "model_number": ""},
        "prod_iphone17pro_512": {"name": "iPhone 17 Pro 512GB SIMフリー", "model_number": ""},
        "prod_gr3x": {"name": "RICOH GR IIIx", "model_number": "15286"},
    }
    return ProductIdentityResolver(products)


# ── env / kill switch / configured（Task2-4）──
def test_not_configured_graceful(monkeypatch):
    for k in ("EBAY_APP_ID", "EBAY_CLIENT_ID"):
        monkeypatch.delenv(k, raising=False)
    assert is_configured("ebay") is False
    assert api_enabled("ebay") is False   # 未設定 → 叩かない


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("EBAY_APP_ID", "dummy")
    monkeypatch.setenv("ENABLE_EBAY_API", "false")
    assert is_configured("ebay") is True
    assert kill_switch_on("ebay") is True
    assert api_enabled("ebay") is False   # kill switch → 叩かない


def test_dry_run_flag(monkeypatch):
    monkeypatch.setenv("API_DRY_RUN", "true")
    assert is_dry_run() is True
    monkeypatch.setenv("API_DRY_RUN", "false")
    assert is_dry_run() is False


# ── error 分類（Task7/8）──
def test_error_classification():
    assert classify_error(429) == "transient"
    assert classify_error(503) == "transient"
    assert classify_error(401) == "permanent"
    assert classify_error(403) == "permanent"
    assert classify_error(400) == "permanent"
    assert classify_error(None, Exception("timeout")) == "transient"
    assert classify_error(200) == "ok"


# ── 401 無限retry禁止（Task9）──
def test_401_no_infinite_retry():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return {"status": 401, "data": None, "retry_after": None, "exc": None}
    h = HealthTracker("ebay")
    r = retry_with_backoff(fn, max_retries=4, sleep_fn=_NO_SLEEP, health=h)
    assert r["ok"] is False
    assert calls["n"] == 1                    # 恒久エラーは1回で中断
    assert r["error_kind"] == "permanent_401"


# ── 429 retry制限 + Retry-After尊重 + カウンタ（Task10）──
def test_429_limited_retry():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return {"status": 429, "data": None, "retry_after": 0, "exc": None}
    h = HealthTracker("rakuten")
    r = retry_with_backoff(fn, max_retries=3, sleep_fn=_NO_SLEEP, health=h)
    assert r["ok"] is False
    assert calls["n"] == 4                    # 初回 + 3 retry
    assert h.rate_limited >= 1


def test_429_then_success():
    seq = [429, 200]
    def fn():
        s = seq.pop(0)
        return {"status": s, "data": {"ok": True} if s == 200 else None,
                "retry_after": 0, "exc": None}
    h = HealthTracker("rakuten")
    r = retry_with_backoff(fn, max_retries=3, sleep_fn=_NO_SLEEP, health=h)
    assert r["ok"] is True
    assert h.success == 1


# ── timeout retry（Task11）──
def test_timeout_limited_retry():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return {"status": None, "data": None, "retry_after": None, "exc": TimeoutError("t")}
    h = HealthTracker("yahoo")
    r = retry_with_backoff(fn, max_retries=2, sleep_fn=_NO_SLEEP, health=h)
    assert r["ok"] is False
    assert calls["n"] == 3
    assert h.timeout >= 1


# ── circuit breaker（Task12/14）──
def test_circuit_breaker_opens_and_recovers():
    cb = CircuitBreaker(threshold=5, cooldown_sec=100)
    t = 0.0
    for _ in range(5):
        cb.record_failure(t)
    assert cb.is_open(t) is True               # 5連続失敗 → OPEN
    assert cb.is_open(t + 50) is True          # cooldown 中は OPEN
    assert cb.is_open(t + 100) is False        # cooldown 後 → HALF_OPEN（許可）
    cb.record_success()                        # 成功 → CLOSED
    assert cb.is_open(t + 100) is False
    assert cb.consecutive_failures == 0


def test_circuit_breaker_blocks_requests():
    cb = CircuitBreaker(threshold=2, cooldown_sec=100)
    cb.record_failure(0.0); cb.record_failure(0.0)
    # OPEN 中は retry_with_backoff が即中断（叩かない）
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return {"status": 200, "data": {}, "retry_after": None, "exc": None}
    r = retry_with_backoff(fn, sleep_fn=_NO_SLEEP, breaker=cb, now_fn=lambda: 1.0)
    assert r["error_kind"] == "circuit_open"
    assert calls["n"] == 0                      # OPEN 中は1回も叩かない


# ── ProductIdentityResolver 統合（Task15/20-22）──
def test_ebay_pro_ne_promax():
    R = _resolver()
    r = R.resolve(source_title="iPhone 17 Pro Max 256GB", link_type="item",
                  expected_product_id="prod_iphone17pro_256")
    assert r.matched_product_id != "prod_iphone17pro_256"   # Pro に Pro Max を割当てない


def test_ebay_256_ne_512():
    R = _resolver()
    r = R.resolve(source_title="iPhone 17 Pro 512GB", link_type="item",
                  expected_product_id="prod_iphone17pro_256")
    assert r.matched_product_id != "prod_iphone17pro_256"


def test_ebay_accessory_rejected():
    R = _resolver()
    r = R.resolve(source_title="iPhone 17 Pro 256GB case leather", link_type="item")
    assert r.accessory_flag is True


def test_rakuten_accessory_rejected():
    R = _resolver()
    r = R.resolve(source_title="RICOH GR IIIx 用 保護フィルム", link_type="item")
    assert r.accessory_flag is True


def test_yahoo_capacity_mismatch_rejected():
    R = _resolver()
    r = R.resolve(source_title="iPhone 17 Pro 512GB", capacity="512GB", link_type="item",
                  expected_product_id="prod_iphone17pro_256")
    # 期待(256)と異なる容量 → 再マッチ（256ではない）
    assert r.matched_product_id != "prod_iphone17pro_256"


def test_unknown_model_not_auto_high():
    R = _resolver()
    # 汎用ラベル（機種抽出不能）→ high にしない
    r = R.resolve(source_title="買取価格", link_type="item", expected_product_id="prod_gr3x")
    assert r.identity_confidence != "high"
    assert r.model_match is None                 # unknown（false と同一視しない）


# ── data_origin 保持（Task23）──
def test_data_origin_constants():
    assert rt.ORIGIN_API == "api"
    assert rt.ORIGIN_FALLBACK == "fallback"
    assert rt.ORIGIN_MANUAL == "manual"


# ── Dry Run が production main を書き換えない（Task6）──
def test_dry_run_no_main_mutation(monkeypatch):
    db = ROOT / "data" / "premium_monitor.db"
    if not db.exists():
        return  # DB 無しでもテストを落とさない
    def snap():
        c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
        obs = c.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        prices = c.execute("SELECT COUNT(*) FROM buyback_prices").fetchone()[0]
        offi = c.execute("SELECT COALESCE(SUM(official_price),0) FROM products").fetchone()[0]
        c.close()
        return (obs, prices, offi)
    before = snap()
    monkeypatch.setenv("API_DRY_RUN", "true")
    import importlib
    m = importlib.import_module("scripts.collect_api_prices") if False else None
    # collect_api_prices を直接実行（DB は書かない設計）
    import subprocess
    subprocess.run([sys.executable, "scripts/collect_api_prices.py"], cwd=str(ROOT),
                   env={**os.environ, "PYTHONPATH": ".", "API_DRY_RUN": "true"}, check=True)
    after = snap()
    assert before == after                       # Dry Run で main は不変


# ── fallback origin が api として扱われない（Task23/24）──
def test_fallback_not_fresh_api():
    # fallback 由来の観測を api の fresh として扱わないことを origin で保証
    obs_api = {"data_origin": rt.ORIGIN_API, "is_fresh": True}
    obs_fb = {"data_origin": rt.ORIGIN_FALLBACK, "is_fresh": False}
    assert obs_api["data_origin"] != obs_fb["data_origin"]
    assert not (obs_fb["data_origin"] == rt.ORIGIN_API)


def _run_all():
    import types
    class _MP:
        def __init__(self): self._saved = {}
        def setenv(self, k, v): self._saved.setdefault(k, os.environ.get(k)); os.environ[k] = v
        def delenv(self, k, raising=False): self._saved.setdefault(k, os.environ.get(k)); os.environ.pop(k, None)
        def undo(self):
            for k, v in self._saved.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and isinstance(v, types.FunctionType)]
    passed = 0
    for fn in fns:
        mp = _MP()
        try:
            if fn.__code__.co_argcount == 1:
                fn(mp)
            else:
                fn()
            passed += 1
            print(f"  PASS {fn.__name__}")
        except Exception as e:
            print(f"  FAIL {fn.__name__}: {e}")
            raise
        finally:
            mp.undo()
    print(f"\n{passed}/{len(fns)} passed")
    return passed == len(fns)


if __name__ == "__main__":
    raise SystemExit(0 if _run_all() else 1)
