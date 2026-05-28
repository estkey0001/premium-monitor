"""海外価格コレクター基底クラスと共通データ型。"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
JST = timezone(timedelta(hours=9))
STALE_HOURS = 48  # 48h超でstale=True

@dataclass
class OverseasPriceResult:
    """海外価格収集結果の標準データ型。"""
    source: str               # "ebay_completed", "stockx", "chrono24", "manual"
    market: str               # "eBay (Sold)", "StockX", "Chrono24"
    product_id: str           # "prod_gr4"
    product_alias: str        # "gr4"
    country: str              # "US", "EU", "global"
    currency: str             # "USD", "EUR", "JPY"
    price_local: float        # 現地通貨での中央値価格
    fx_rate: float            # 例: 155.0 (USD→JPY)
    price_jpy: int            # round(price_local * fx_rate)
    confidence: str           # "high", "medium", "low"
    listing_count: int        # 取得できた成約件数
    median_price_jpy: int     # 中央値(JPY)
    min_price_jpy: int        # 最安値(JPY)
    max_price_jpy: int        # 最高値(JPY)
    fetched_at: str           # ISO8601 JST
    stale: bool               # True if > STALE_HOURS
    failure_reason: str       # "" or エラー理由
    url: str                  # 参照URL
    raw_prices_json: str      # デバッグ用生価格JSON

    @property
    def is_valid(self) -> bool:
        """利益計算に使用できる有効な価格かどうか。"""
        return (
            self.price_jpy > 0
            and not self.failure_reason
            and self.confidence in ("high", "medium")
            and not self.stale
        )

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "market": self.market,
            "product_id": self.product_id,
            "product_alias": self.product_alias,
            "country": self.country,
            "currency": self.currency,
            "price_local": self.price_local,
            "fx_rate": self.fx_rate,
            "price_jpy": self.price_jpy,
            "confidence": self.confidence,
            "listing_count": self.listing_count,
            "median_price_jpy": self.median_price_jpy,
            "min_price_jpy": self.min_price_jpy,
            "max_price_jpy": self.max_price_jpy,
            "fetched_at": self.fetched_at,
            "stale": self.stale,
            "failure_reason": self.failure_reason,
            "url": self.url,
        }


def calc_confidence(listing_count: int, min_jpy: int, max_jpy: int, median_jpy: int) -> str:
    """件数と価格ばらつきから信頼度(high/medium/low)を計算する。"""
    if listing_count == 0 or median_jpy == 0:
        return "low"
    spread = (max_jpy - min_jpy) / median_jpy if median_jpy > 0 else 1.0
    if listing_count >= 10 and spread < 0.30:
        return "high"
    elif listing_count >= 3 and spread < 0.60:
        return "medium"
    else:
        return "low"


def is_stale(fetched_at_iso: str) -> bool:
    """取得時刻が STALE_HOURS を超えているか判定する。"""
    try:
        dt = datetime.fromisoformat(fetched_at_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        now = datetime.now(tz=timezone.utc).astimezone(JST)
        return (now - dt).total_seconds() > STALE_HOURS * 3600
    except Exception:
        return True


def load_fx_rates() -> dict:
    """fx_rates.yaml から為替レートを読み込む。フォールバック値あり。"""
    try:
        with open(PROJECT_ROOT / "config" / "fx_rates.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("fx_rates", {})
    except Exception:
        return {"USD_JPY": 155, "EUR_JPY": 170, "GBP_JPY": 195}
