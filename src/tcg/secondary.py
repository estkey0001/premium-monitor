# -*- coding: utf-8 -*-
"""Task9: 二次流通（未開封BOX）価格の取り込み。

取得元は ToS を遵守できる範囲に限定する。
  1. data/tcg_secondary_prices.csv … 手動・CSVインポート由来の実測値
  2. eBay Finding API … ENABLE_EBAY_API=true かつ dry-run でない場合のみ

価格が取れない場合は推定せず、insufficient_samples=True のままにする。
"""
from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Optional

from .models import SHRINK_UNKNOWN, SHRINK_STATUSES
from .shrink import detect_shrink_status
from .premium import build_premium, split_by_shrink

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECONDARY_CSV = PROJECT_ROOT / "data" / "tcg_secondary_prices.csv"

CSV_COLUMNS = (
    "product_id", "product_name", "tcg", "source", "price",
    "shrink_status", "condition", "observed_at", "url", "note",
)

# 許可する取得元（ToS 遵守できる範囲）
ALLOWED_SOURCES = ("mercari", "yahoo_auctions", "rakuma", "ebay",
                   "card_shop_sale", "card_shop_buyback", "manual")


def load_secondary_observations(path: Optional[Path] = None) -> list[dict]:
    """二次流通価格の観測を読み込む。ファイルが無ければ空リスト。"""
    path = path or SECONDARY_CSV
    if not path.exists():
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                price = float(str(row.get("price", "")).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            shrink = (row.get("shrink_status") or SHRINK_UNKNOWN).strip()
            if shrink not in SHRINK_STATUSES:
                shrink = SHRINK_UNKNOWN
            src = (row.get("source") or "manual").strip().lower()
            if src not in ALLOWED_SOURCES:
                logger.warning("未許可の取得元をスキップ: %s", src)
                continue
            out.append({
                "product_id": (row.get("product_id") or "").strip(),
                "product_name": (row.get("product_name") or "").strip(),
                "tcg": (row.get("tcg") or "").strip(),
                "source": src,
                "price": price,
                "shrink_status": shrink,
                "condition": (row.get("condition") or "").strip(),
                "observed_at": (row.get("observed_at") or "").strip(),
                "url": (row.get("url") or "").strip(),
            })
    return out


def buyback_of(observations: list[dict]) -> Optional[int]:
    """買取価格（card_shop_buyback）の中央値。

    売値と同じく外れ値を除いたうえでサンプルが足りなければ None を返す
    （異常値1件を買取相場として採用しない）。
    """
    from .premium import market_median
    vals = [o["price"] for o in observations if o["source"] == "card_shop_buyback"]
    return market_median(vals) if vals else None


def premium_for_product(product_id: str, retail_price: Optional[int],
                        observations: Optional[list[dict]] = None) -> dict:
    """商品IDに対するプレミア情報を組み立てる。"""
    obs = [o for o in (observations if observations is not None
                       else load_secondary_observations())
           if o["product_id"] == product_id]
    sale_obs = [o for o in obs if o["source"] != "card_shop_buyback"]
    sealed, unsealed = split_by_shrink(sale_obs)
    return build_premium(
        retail_price=retail_price,
        sealed_prices=sealed,
        unsealed_prices=unsealed,
        buyback_price=buyback_of(obs),
        sample_sources=sorted({o["source"] for o in sale_obs}),
    )


def ebay_enabled() -> bool:
    """eBay API 経由の取得が有効か（既定は無効・dry-run 優先）。"""
    if os.environ.get("ENABLE_EBAY_API", "false").lower() != "true":
        return False
    if os.environ.get("API_DRY_RUN", "true").lower() != "false":
        return False
    return bool(os.environ.get("EBAY_APP_ID") or os.environ.get("EBAY_CLIENT_ID"))


def fetch_ebay_observations(product_id: str, keyword: str,
                            fetcher=None, fx_loader=None) -> list[dict]:
    """eBay から未開封BOXの出品価格を取得して観測に変換する。

    kill-switch（ENABLE_EBAY_API）と dry-run（API_DRY_RUN）で無効な間は
    何も取得しない。為替レートが取れない場合も価格を作らない。
    """
    if not ebay_enabled() or not keyword:
        return []
    if fetcher is None or fx_loader is None:
        from src.collectors.api.market_apis import ebay_fetch_items, load_fx_rate
        fetcher = fetcher or ebay_fetch_items
        fx_loader = fx_loader or load_fx_rate

    items = fetcher(keyword)
    if not items:
        return []

    out: list[dict] = []
    fx_cache: dict[str, Optional[float]] = {}
    for it in items:
        price = it.get("listing_price_original")
        currency = (it.get("currency") or "").upper()
        if price is None or not currency:
            continue
        if currency == "JPY":
            jpy = float(price)
        else:
            if currency not in fx_cache:
                fx_cache[currency] = (fx_loader(currency) or {}).get("rate")
            rate = fx_cache[currency]
            if not rate:
                continue          # レート不明なら円換算しない（推測しない）
            jpy = float(price) * float(rate)
        title = it.get("title") or ""
        out.append({
            "product_id": product_id,
            "product_name": title,
            "tcg": "",
            "source": "ebay",
            "price": jpy,
            "shrink_status": detect_shrink_status(title),
            "condition": it.get("condition") or "",
            "observed_at": "",
            "url": it.get("url") or "",
        })
    return out
