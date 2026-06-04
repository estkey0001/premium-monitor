#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""海外市場価格を更新するスクリプト。

PHASE 1 実装:
  1. eBay completed listings (Playwright scraping - 公開ページ)
  2. 手動CSV補完 (manual_market_prices.csv)
  3. 為替レートのライブ取得 (open.er-api.com)

将来対応:
  - StockX公式API (現在ToS上スクレイピング禁止)
  - Chrono24 API (時計ジャンル)
  - Amazon SP-API

confidence 計算:
  high:   completed listings >=10件 かつ 価格ばらつき<30%
  medium: completed listings >=3件 かつ 価格ばらつき<60%
  low:    それ以外

stale 判定:
  fetched_at から 48h 超でstale=True

Usage:
  python scripts/update_overseas_prices.py [--skip-ebay] [--manual-only] [--verbose]
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

JST = timezone(timedelta(hours=9))


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="海外価格更新スクリプト")
    parser.add_argument("--skip-ebay", action="store_true", help="eBay収集をスキップ")
    parser.add_argument("--manual-only", action="store_true", help="手動CSVのみ使用")
    parser.add_argument("--verbose", action="store_true", help="詳細ログ")
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger("update_overseas_prices")

    now = datetime.now(tz=JST)
    logger.info("[update_overseas_prices] 開始: %s JST", now.strftime("%Y-%m-%d %H:%M"))

    # ── EBAY_APP_ID 未設定の強警告（Task 3）──
    # API未設定だと eBay は HTML フォールバック（不安定・stale 化しやすい）。
    import os as _os_ebay
    _ebay_app_id = _os_ebay.environ.get("EBAY_APP_ID") or _os_ebay.environ.get("EBAY_CLIENT_ID")
    if not _ebay_app_id and not args.skip_ebay and not args.manual_only:
        logger.warning("=" * 60)
        logger.warning("STRONG WARNING: EBAY_APP_ID 未設定（理由: api_not_configured）")
        logger.warning("  eBay Finding API が使えず HTML フォールバックのみ → 価格が stale 化しやすく、")
        logger.warning("  ランキング/Pro/せどりの主計算からは stale 海外価格を除外します。")
        logger.warning("  正確な海外相場には Settings→Secrets に EBAY_APP_ID を設定してください。")
        logger.warning("=" * 60)

    # DB接続 + 商品一覧取得
    try:
        from src.db.database import Database
        from src.db.repository import Repository
        db = Database()
        db.init_schema()
        repo = Repository(db)
        products = repo.list_products()
        logger.info("商品数: %d", len(products))
    except Exception as e:
        logger.error("DB接続失敗: %s", e)
        return 1

    # FXレート更新
    try:
        from src.collectors.overseas.fx_fetcher import get_usd_jpy, get_eur_jpy, update_fx_yaml
        usd_jpy, usd_src = get_usd_jpy(force_refresh=True)
        eur_jpy, eur_src = get_eur_jpy(force_refresh=True)
        logger.info("FX: USD/JPY=%.2f(%s) EUR/JPY=%.2f(%s)", usd_jpy, usd_src, eur_jpy, eur_src)
        if usd_src == "live":
            update_fx_yaml({"USD_JPY": round(usd_jpy, 2), "EUR_JPY": round(eur_jpy, 2)})
            logger.info("fx_rates.yaml 更新完了")
    except Exception as e:
        logger.warning("FX取得エラー (静的レート使用): %s", e)

    # オーケストレーター実行
    try:
        from src.collectors.overseas.orchestrator import OverseasPriceOrchestrator
        orch = OverseasPriceOrchestrator(
            skip_ebay=args.skip_ebay or args.manual_only,
            use_manual_only=args.manual_only,
        )
        best_results, all_results = orch.run_all(products)
    except Exception as e:
        logger.error("オーケストレーター実行エラー: %s", e)
        return 1

    # 統計集計 + JSON保存
    try:
        json_path = orch.save_json(best_results, all_results, products)
    except Exception as e:
        logger.error("JSON保存エラー: %s", e)
        return 1

    # 日次履歴保存 (exports/overseas_prices/history/ + data/overseas_price_history.csv)
    try:
        orch.save_history(best_results, products)
    except Exception as e:
        logger.warning("履歴保存エラー (続行): %s", e)

    # サマリー出力
    high = sum(1 for r in best_results.values() if r.confidence == "high")
    medium = sum(1 for r in best_results.values() if r.confidence == "medium")
    low = sum(1 for r in best_results.values() if r.confidence == "low")
    stale = sum(1 for r in best_results.values() if r.stale)

    logger.info(
        "overseas_prices/latest.json 保存完了 "
        "(商品数: %d, high=%d, medium=%d, low=%d, stale=%d)",
        len(best_results), high, medium, low, stale
    )

    # 品質警告
    if high == 0 and medium == 0:
        logger.warning("WARNING: 有効な海外価格データが0件 (全てlow confidence)")
    elif stale > len(best_results) // 2:
        logger.warning("WARNING: 海外価格の50%%以上がstale(48h超)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
