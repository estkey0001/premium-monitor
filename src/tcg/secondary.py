# -*- coding: utf-8 -*-
"""Task9: 二次流通（未開封BOX）価格の取り込み。

取得元は ToS を遵守できる範囲に限定する。
  1. 人が確認した成約の台帳（既定 .private/tcg_sold_ledger.csv（gitignore 済み）。環境変数 TCG_SOLD_LEDGER_PATH で場所を変えられる）
     … 形式・検証は src/tcg/market_prices.py。成約（ACTUAL_SALE）だけが相場の中央値に入る
  2. eBay Browse API … ENABLE_EBAY_API=true かつ dry-run でない場合のみ。出品（LISTING）なので相場にも利益にも使わない

監査 H-1 の対応: 出品（LISTING）・種類不明（UNKNOWN）・発売前の取引（PREORDER_TRADE / EARLY_SALE）・
成約日（sold_at）が古い成約は、プレミア率（premium_percent → buy_now）の計算に入れない。
出品は「出品参考相場」（listing_reference）として別に持つだけ。
価格が取れない場合は推定せず、insufficient_samples=True のままにする。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import market_prices as mp
from .models import SHRINK_SEALED
from .shrink import detect_shrink_status
from .premium import build_premium, split_by_shrink

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECONDARY_CSV = PROJECT_ROOT / "data" / "tcg_secondary_prices.csv"

# 台帳の列（人が確認した成約）。正本は market_prices.LEDGER_COLUMNS
CSV_COLUMNS = mp.LEDGER_COLUMNS


def load_secondary_observations(path: Optional[Path] = None, *, now: Optional[datetime] = None,
                                units: Optional[dict] = None) -> list[dict]:
    """人が確認した成約の台帳を読み、検証を通った成約だけを観測にする。ファイルが無ければ空リスト。

    出品・入札・買取の行、sold_at の無い行、単位・状態が合わない行、旧形式（price_kind の無い）行は入らない。
    """
    cfg = mp.load_config()
    if path is None:
        path = mp.ledger_path(cfg)
    res = mp.load_ledger(path, cfg=cfg, units=units, now=now)
    if res.rejected:
        logger.warning("成約の台帳で使えない行: %d 件 %s", len(res.rejected), res.reason_counts())
    if res.conflicts:
        logger.warning("同じ商品ページで価格・成約日が食い違う行を捨てた: %d 組", len(res.conflicts))
    return [mp.record_to_observation(r) for r in res.records]


def buyback_of(observations: list[dict]) -> Optional[int]:
    """買取価格（card_shop_buyback）の中央値。

    売値と同じく外れ値を除いたうえでサンプルが足りなければ None を返す
    （異常値1件を買取相場として採用しない）。
    """
    from .premium import market_median
    vals = [o["price"] for o in observations if o["source"] == "card_shop_buyback"]
    return market_median(vals) if vals else None


def premium_for_product(product_id: str, retail_price: Optional[int],
                        observations: Optional[list[dict]] = None,
                        now: Optional[datetime] = None) -> dict:
    """商品IDに対するプレミア情報を組み立てる。

    相場（sealed / unsealed の中央値 → premium_percent）に入れるのは、検証済みの成約（ACTUAL_SALE）で
    成約日が鮮度内のものだけ。出品（LISTING）は listing_reference に分け、利益・buy_now に使わない。
    """
    cfg = mp.load_config()
    now = now or datetime.now(tz=mp.JST)
    fresh_days = int(cfg.get("fresh_days") or 14)
    obs = [o for o in (observations if observations is not None
                       else load_secondary_observations(now=now))
           if o["product_id"] == product_id]
    sold_obs = [o for o in obs
                if o.get("source") != "card_shop_buyback"
                and mp.is_eligible_sold_observation(o, now=now, fresh_days=fresh_days)]
    listing_obs = [o for o in obs if o.get("price_kind") == mp.OBS_LISTING]
    sealed, unsealed = split_by_shrink(sold_obs)
    result = build_premium(
        retail_price=retail_price,
        sealed_prices=sealed,
        unsealed_prices=unsealed,
        buyback_price=buyback_of(obs),
        sample_sources=(sorted({o["source"] for o in sold_obs}) if cfg.get("publish_market_names") else []),
    )
    result.update({
        "price_basis": mp.SOLD_MEDIAN,          # 中央値は確認済みの成約だけ（出品ではない）
        "sold_count_total": len(sold_obs),
        "excluded_not_sold": sum(1 for o in obs if o.get("price_kind") != mp.OBS_SOLD
                                 and o.get("source") != "card_shop_buyback"),
        "listing_reference": mp.listing_reference(listing_obs, product_id, condition=SHRINK_SEALED),
        "executable": False,                    # 二次流通の値は「想定」。実行可能な利益にしない
    })
    return result


def ebay_enabled() -> bool:
    """eBay API 経由の取得が有効か（既定は無効・dry-run 優先）。"""
    if os.environ.get("ENABLE_EBAY_API", "false").lower() != "true":
        return False
    if os.environ.get("API_DRY_RUN", "true").lower() != "false":
        return False
    return bool(os.environ.get("EBAY_APP_ID") or os.environ.get("EBAY_CLIENT_ID"))


def fetch_ebay_observations(product_id: str, keyword: str,
                            fetcher=None, fx_loader=None) -> list[dict]:
    """eBay から未開封BOXの出品価格を取得して観測に変換する（price_kind=LISTING。成約ではない）。

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
            "price_kind": mp.OBS_LISTING,          # 出品。相場（中央値）・buy_now に入れない
            "sale_phase": None,
        })
    return out
