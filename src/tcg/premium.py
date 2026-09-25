# -*- coding: utf-8 -*-
"""Task9: 未開封BOXのプレミア計算 / Task10: シュリンクプレミア。

原則:
  - 二次流通の異常値1件を市場価格に採用しない（中央値 + 外れ値除外）。
  - サンプルが少なすぎる場合は market_median を出さず None のままにする。
  - 商品状態を正確に分類できない場合は shrink premium を推定しない。
"""
from __future__ import annotations

import statistics
from typing import Optional, Sequence

from .models import SHRINK_SEALED, SHRINK_REMOVED, SHRINK_TAPE_CUT, SHRINK_OPENED_BOX

# 中央値を採用するための最小サンプル数（1件では市場価格としない）
MIN_SAMPLES_FOR_MEDIAN = 3
# 外れ値判定: 中央値の ±X 倍を超えるものは除外
OUTLIER_LOW_RATIO = 0.4
OUTLIER_HIGH_RATIO = 3.0


def filter_outliers(prices: Sequence[float]) -> list[float]:
    """中央値から大きく外れた価格を除外する（異常値1件の混入を防ぐ）。"""
    vals = [float(p) for p in prices if p is not None and float(p) > 0]
    if len(vals) < 3:
        return sorted(vals)
    med = statistics.median(vals)
    if med <= 0:
        return sorted(vals)
    return sorted(v for v in vals
                  if med * OUTLIER_LOW_RATIO <= v <= med * OUTLIER_HIGH_RATIO)


def market_median(prices: Sequence[float],
                  min_samples: int = MIN_SAMPLES_FOR_MEDIAN) -> Optional[int]:
    """外れ値を除いた中央値。サンプル不足なら None（推測しない）。"""
    cleaned = filter_outliers(prices)
    if len(cleaned) < min_samples:
        return None
    return int(round(statistics.median(cleaned)))


def compute_premium(retail_price: Optional[int],
                    sealed_market_price: Optional[int]) -> dict:
    """premium_yen / premium_percent を計算する。

    定価不明・市場価格不明なら計算せず None を返す。
    """
    out: dict = {
        "retail_price": retail_price,
        "sealed_market_price": sealed_market_price,
        "premium_yen": None,
        "premium_percent": None,
    }
    if not retail_price or retail_price <= 0 or not sealed_market_price:
        return out
    out["premium_yen"] = int(sealed_market_price - retail_price)
    out["premium_percent"] = round(
        (sealed_market_price / retail_price - 1) * 100, 1)
    return out


def build_premium(retail_price: Optional[int],
                  sealed_prices: Sequence[float] = (),
                  unsealed_prices: Sequence[float] = (),
                  buyback_price: Optional[int] = None,
                  sample_sources: Optional[list[str]] = None) -> dict:
    """Task9/Task10: BOX のプレミア情報一式を構築する。

    sealed / unsealed を分離できない場合、shrink premium は None のまま。
    """
    sealed_median = market_median(sealed_prices)
    unsealed_median = market_median(unsealed_prices)

    result = compute_premium(retail_price, sealed_median)
    result.update({
        "buyback_price": buyback_price,
        "market_median": sealed_median,
        "sealed_price": sealed_median,
        "unsealed_price": unsealed_median,
        "shrink_premium_yen": None,
        "shrink_premium_percent": None,
        "sealed_sample_count": len(filter_outliers(sealed_prices)),
        "unsealed_sample_count": len(filter_outliers(unsealed_prices)),
        "sample_sources": sample_sources or [],
        "insufficient_samples": sealed_median is None,
    })

    # Task10: 状態を分離できたときだけシュリンク差を出す
    if sealed_median and unsealed_median and unsealed_median > 0:
        result["shrink_premium_yen"] = int(sealed_median - unsealed_median)
        result["shrink_premium_percent"] = round(
            (sealed_median / unsealed_median - 1) * 100, 1)
    return result


def split_by_shrink(observations: Sequence[dict]) -> tuple[list[float], list[float]]:
    """二次流通の観測を「シュリンク付き」「シュリンクなし」に分離する。

    状態が判別できない観測はどちらにも入れない（推定しない）。
    """
    sealed: list[float] = []
    unsealed: list[float] = []
    for obs in observations:
        price = obs.get("price")
        if not price:
            continue
        st = obs.get("shrink_status")
        if st == SHRINK_SEALED:
            sealed.append(float(price))
        elif st in (SHRINK_REMOVED, SHRINK_TAPE_CUT, SHRINK_OPENED_BOX):
            unsealed.append(float(price))
    return sealed, unsealed
