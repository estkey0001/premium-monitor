"""公式API 統合（env-gated・準備レイヤ）。

正規の公式APIで価格を取得するための薄い抽象。**APIキーが環境変数に設定された時のみ
有効化**され、未設定なら None を返す（既存のHTMLフォールバックがそのまま働く）。
これにより「キーをSecretに入れるだけで自動API取得が起動する」状態を用意する。

対応（すべて公式・ログイン不要・ToS準拠の正規API）:
  - 楽天市場 Ichiba Item Search API   env: RAKUTEN_APP_ID
  - Yahoo!ショッピング itemSearch API  env: YAHOO_SHOPPING_APP_ID

注意（正直な範囲）:
  - Yahoo!ショッピングAPIは「新品ショッピング価格」であり、ヤフオクの
    「落札(sold)相場」とは別種のデータ。sold コレクターには混在させない。
  - Mercari / ラクマ には公式の価格APIが無く、規約でスクレイピングも禁止のため
    本モジュールでは扱わない（手動キュレーションが正しい設計）。

決定論/安全性: タイムアウト付き・例外は握りつぶして None を返す（CIを止めない）。
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_TIMEOUT = 15
_UA = "PremiumMonitor/1.0 (+official-api; contact via repo)"

RAKUTEN_ENDPOINT = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"
YAHOO_SHOPPING_ENDPOINT = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"


def _http_json(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.info("[official_api] HTTP/JSON エラー: %s", e)
        return None


def _stats(prices: list[int]) -> Optional[dict]:
    prices = [p for p in prices if isinstance(p, int) and p > 0]
    if not prices:
        return None
    return {
        "price_jpy": int(statistics.median(prices)),
        "listing_count": len(prices),
        "min": min(prices),
        "max": max(prices),
    }


def rakuten_available() -> bool:
    return bool(os.environ.get("RAKUTEN_APP_ID"))


def yahoo_shopping_available() -> bool:
    return bool(os.environ.get("YAHOO_SHOPPING_APP_ID"))


def rakuten_ichiba_search(keyword: str, hits: int = 20, min_price: int = 5000) -> Optional[dict]:
    """楽天Ichiba公式APIで新品価格の中央値を取得。未設定/失敗時 None。

    Returns: {price_jpy, listing_count, url, collector_method='rakuten_api'} or None
    """
    app_id = os.environ.get("RAKUTEN_APP_ID")
    if not app_id:
        return None
    if not keyword:
        return None
    params = {
        "applicationId": app_id,
        "keyword": keyword,
        "hits": max(1, min(hits, 30)),
        "minPrice": min_price,
        "sort": "+itemPrice",
        "format": "json",
        "formatVersion": 2,
    }
    aff = os.environ.get("RAKUTEN_AFFILIATE_ID")
    if aff:
        params["affiliateId"] = aff
    url = RAKUTEN_ENDPOINT + "?" + urllib.parse.urlencode(params)
    data = _http_json(url)
    if not data:
        return None
    items = data.get("Items") or []
    prices = []
    for it in items:
        # formatVersion=2 では item は dict 直下
        price = it.get("itemPrice") if isinstance(it, dict) else None
        if isinstance(price, int):
            prices.append(price)
    st = _stats(prices)
    if not st:
        logger.info("[Rakuten API:%s] ヒットなし", keyword)
        return None
    logger.info("[Rakuten API:%s] ¥%s (median of %d)", keyword, f"{st['price_jpy']:,}", st["listing_count"])
    return {
        "price_jpy": st["price_jpy"],
        "listing_count": st["listing_count"],
        "url": f"https://search.rakuten.co.jp/search/mall/{urllib.parse.quote(keyword)}/",
        "collector_method": "rakuten_api",
    }


def yahoo_shopping_search(keyword: str, hits: int = 20, condition: str = "new") -> Optional[dict]:
    """Yahoo!ショッピング公式APIで新品ショッピング価格の中央値を取得。未設定/失敗時 None。

    注意: これは「ショッピング新品価格」であり、ヤフオク落札(sold)相場ではない。
    Returns: {price_jpy, listing_count, url, collector_method='yahoo_shopping_api'} or None
    """
    app_id = os.environ.get("YAHOO_SHOPPING_APP_ID")
    if not app_id:
        return None
    if not keyword:
        return None
    params = {
        "appid": app_id,
        "query": keyword,
        "results": max(1, min(hits, 50)),
        "sort": "+price",
        "condition": condition,      # new / used
    }
    url = YAHOO_SHOPPING_ENDPOINT + "?" + urllib.parse.urlencode(params)
    data = _http_json(url)
    if not data:
        return None
    hits_list = data.get("hits") or []
    prices = []
    for h in hits_list:
        price = (h.get("price") if isinstance(h, dict) else None)
        if isinstance(price, (int, float)) and price > 0:
            prices.append(int(price))
    st = _stats(prices)
    if not st:
        logger.info("[Yahoo Shopping API:%s] ヒットなし", keyword)
        return None
    logger.info("[Yahoo Shopping API:%s] ¥%s (median of %d)", keyword, f"{st['price_jpy']:,}", st["listing_count"])
    return {
        "price_jpy": st["price_jpy"],
        "listing_count": st["listing_count"],
        "url": f"https://shopping.yahoo.co.jp/search?p={urllib.parse.quote(keyword)}",
        "collector_method": "yahoo_shopping_api",
    }
