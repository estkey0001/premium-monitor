#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Market API fetchers — eBay / 楽天 / Yahoo!ショッピング の公式APIから item を取得。

各 fetcher は list[item] を返す（未設定/無効/失敗時は None）。取得できない項目は
「取得できるふり」をせず null にする。通貨/ポイント/送料は分離保持し元値を上書きしない。
利益ロジックは変更しない（収集・正規化のみ）。
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Optional

from src.collectors.api.api_runtime import (
    is_configured, retry_with_backoff, HealthTracker, CircuitBreaker,
)

_UA = "PremiumMonitor/1.0 (+market-api)"
_TIMEOUT = 15

RAKUTEN_ENDPOINT = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"
YAHOO_SHOPPING_ENDPOINT = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"


def _http(url: str, headers: Optional[dict] = None) -> dict:
    """HTTP GET → {status, data(json), retry_after, exc}。retry_with_backoff 用の形。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, **(headers or {})})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            return {"status": resp.getcode(), "data": json.loads(body), "retry_after": None, "exc": None}
    except urllib.error.HTTPError as e:  # type: ignore
        # 秒数・HTTP-date のどちらも retry_with_backoff（api_runtime.parse_retry_after）が読む
        ra = e.headers.get("Retry-After") if e.headers else None
        return {"status": e.code, "data": None, "retry_after": ra, "exc": e}
    except Exception as e:  # noqa: BLE001
        return {"status": None, "data": None, "retry_after": None, "exc": e}


# ── FX（為替）: 元通貨価格を上書きせず JPY 換算を別保持（Task6）──
def load_fx_rate(currency: str) -> dict:
    """fx_rates.yaml から為替を取得。source/observed_at を保持。取得不能は stale/None。"""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent.parent
    try:
        import yaml
        y = yaml.safe_load((root / "config" / "fx_rates.yaml").read_text(encoding="utf-8")) or {}
        rates = y.get("rates", y) or {}
        rate = rates.get(currency) or rates.get(currency.upper())
        return {"rate": rate, "source": y.get("source", "fx_rates.yaml"),
                "observed_at": y.get("observed_at"), "currency": currency}
    except Exception:
        return {"rate": None, "source": None, "observed_at": None, "currency": currency}


# ─────────────────────────────────────────────────────────────
# eBay（出品の検索）: Finding API は 2025-02-05 に廃止された（Phase 13 で呼ぶコードを削除）
# ─────────────────────────────────────────────────────────────
def ebay_fetch_items(keyword: str, *, health: HealthTracker = None,
                     breaker: CircuitBreaker = None, sleep_fn=None) -> Optional[list]:
    """eBay の出品の候補（今は取得しない。常に None）。

    以前は Finding API（findItemsByKeywords）を呼んでいたが、2025-02-05 に廃止された。EBAY_CLIENT_ID
    （成約の Marketplace Insights API の資格情報）を登録しても、廃止された API へ client id を送らない。
    成約は src/collectors/api/ebay_insights.py（scripts/collect_ebay_sold.py）だけで取る。
    """
    return None


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────
# 楽天市場 API（Task10-12）
# ─────────────────────────────────────────────────────────────
def rakuten_fetch_items(keyword: str, *, health: HealthTracker = None,
                        breaker: CircuitBreaker = None, sleep_fn=None) -> Optional[list]:
    app_id = os.environ.get("RAKUTEN_APP_ID")
    if not app_id or not keyword:
        return None
    params = {"applicationId": app_id, "keyword": keyword, "hits": 30,
              "sort": "+itemPrice", "format": "json", "formatVersion": 2}
    if os.environ.get("RAKUTEN_AFFILIATE_ID"):
        params["affiliateId"] = os.environ["RAKUTEN_AFFILIATE_ID"]
    url = RAKUTEN_ENDPOINT + "?" + urllib.parse.urlencode(params)
    kw = {} if sleep_fn is None else {"sleep_fn": sleep_fn}
    res = retry_with_backoff(lambda: _http(url), health=health, breaker=breaker, **kw)
    if not res["ok"] or not res["data"]:
        return None
    items = []
    for it in (res["data"].get("Items") or []):
        d = it if isinstance(it, dict) else {}
        items.append({
            "title": d.get("itemName"),
            "listed_price": d.get("itemPrice"),
            "currency": "JPY",
            "shipping": (0 if d.get("postageFlag") == 0 else None),  # 0=送料込, 他=不明
            "points": d.get("pointRate"),
            "coupon": None,
            "shop": d.get("shopName"),
            "availability": d.get("availability"),
            "jan": d.get("janCode") or None,
            "url": d.get("itemUrl"),
        })
    if health:
        health.items_received += len(items)
    return items


# ─────────────────────────────────────────────────────────────
# Yahoo!ショッピング API（Task13-14）
# ─────────────────────────────────────────────────────────────
def yahoo_fetch_items(keyword: str, *, health: HealthTracker = None,
                      breaker: CircuitBreaker = None, sleep_fn=None) -> Optional[list]:
    app_id = os.environ.get("YAHOO_SHOPPING_APP_ID")
    if not app_id or not keyword:
        return None
    params = {"appid": app_id, "query": keyword, "results": 30, "sort": "+price"}
    url = YAHOO_SHOPPING_ENDPOINT + "?" + urllib.parse.urlencode(params)
    kw = {} if sleep_fn is None else {"sleep_fn": sleep_fn}
    res = retry_with_backoff(lambda: _http(url), health=health, breaker=breaker, **kw)
    if not res["ok"] or not res["data"]:
        return None
    items = []
    for h in (res["data"].get("hits") or []):
        d = h if isinstance(h, dict) else {}
        items.append({
            "title": d.get("name"),
            "listed_price": d.get("price"),
            "currency": "JPY",
            "shipping": (d.get("shipping") or {}).get("code") if isinstance(d.get("shipping"), dict) else None,
            "points": (d.get("point") or {}).get("amount") if isinstance(d.get("point"), dict) else None,
            "coupon": None,
            "shop": (d.get("seller") or {}).get("name") if isinstance(d.get("seller"), dict) else None,
            "availability": d.get("availability"),
            "jan": d.get("janCode") or None,
            "brand": (d.get("brand") or {}).get("name") if isinstance(d.get("brand"), dict) else None,
            "url": d.get("url"),
        })
    if health:
        health.items_received += len(items)
    return items


FETCHERS = {"ebay": ebay_fetch_items, "rakuten": rakuten_fetch_items, "yahoo": yahoo_fetch_items}
