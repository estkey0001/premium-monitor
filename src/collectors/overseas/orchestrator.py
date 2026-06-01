"""海外価格コレクターオーケストレーター。

全商品に対して各海外コレクターを実行し、結果を集約する。
優先順位: eBay(成約) > 手動CSV > その他
"""
from __future__ import annotations

import csv
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.overseas.base_overseas import OverseasPriceResult, is_stale
from src.collectors.overseas.ebay_completed import EbayCompletedCollector
from src.collectors.overseas.manual_fallback import ManualFallbackCollector
from src.collectors.overseas.fx_fetcher import get_usd_jpy, update_fx_yaml

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

EXPORT_DIR = PROJECT_ROOT / "exports" / "overseas_prices"
HISTORY_DIR = EXPORT_DIR / "history"
REPORT_DIR = PROJECT_ROOT / "exports" / "overseas_report"
HISTORY_CSV = PROJECT_ROOT / "data" / "overseas_price_history.csv"

HISTORY_CSV_COLUMNS = [
    "product_id", "product_alias", "source", "market",
    "currency", "price_local", "fx_rate",
    "price_jpy", "median_price_jpy", "max_price_jpy", "min_price_jpy",
    "listing_count", "confidence", "collector_method", "observed_at",
]

# 商品あたりの eBay リクエスト間隔（秒）
# レートリミット遵守 + eBay への過負荷防止
EBAY_REQUEST_INTERVAL = 5.0  # 5秒以上の間隔


class OverseasPriceOrchestrator:
    """全海外コレクターを統合して実行する。"""

    def __init__(self, skip_ebay: bool = False, use_manual_only: bool = False):
        self.skip_ebay = skip_ebay
        self.use_manual_only = use_manual_only
        self.ebay = EbayCompletedCollector()
        self.manual = ManualFallbackCollector()
        self._last_ebay_request = 0.0

    def run_all(self, products: list) -> tuple[dict[str, OverseasPriceResult], dict[str, list[OverseasPriceResult]]]:
        """全商品の海外価格を収集する。

        Args:
            products: ProductModel のリスト

        Returns:
            ({product_id: best_OverseasPriceResult}, {product_id: [all_results]}) のタプル
        """
        results: dict[str, OverseasPriceResult] = {}
        all_results: dict[str, list[OverseasPriceResult]] = {}

        logger.info("OverseasPriceOrchestrator: %d products", len(products))

        for product in products:
            pid = product.id
            alias = pid.replace("prod_", "")
            keywords = getattr(product, "keywords", []) or [product.name]
            genre = getattr(product, "genre", "") or ""

            product_results: list[OverseasPriceResult] = []

            # 1. eBay completed listings
            if not self.skip_ebay and not self.use_manual_only:
                self._ebay_rate_limit()
                try:
                    ebay_result = self.ebay.collect(
                        product_id=pid,
                        product_alias=alias,
                        keywords=keywords,
                        condition_filter="new",
                    )
                    if ebay_result:
                        product_results.append(ebay_result)
                        logger.info(
                            "[%s] eBay: ¥%s conf=%s count=%d",
                            alias, f"{ebay_result.price_jpy:,}",
                            ebay_result.confidence, ebay_result.listing_count
                        )
                except Exception as e:
                    logger.warning("[%s] eBay collection error: %s", alias, e)
                    product_results.append(self._make_error_result(pid, alias, "ebay_completed", str(e)))

            # 2. 手動CSV補完
            manual_results = self.manual.collect_all(alias, pid)
            product_results.extend(manual_results)

            all_results[pid] = product_results

            # 最良結果を選択 (有効な中で最高価格)
            best = self._select_best(product_results)
            if best:
                results[pid] = best

        return results, all_results

    def _select_best(self, results: list[OverseasPriceResult]) -> Optional[OverseasPriceResult]:
        """最良の海外価格を選択する。

        優先順位:
        1. confidence=high かつ stale=False
        2. confidence=medium かつ stale=False
        3. confidence=high (stale OK)
        4. confidence=medium (stale OK)
        5. その他
        """
        if not results:
            return None

        valid = [r for r in results if r.price_jpy > 0]
        if not valid:
            return None

        def priority(r: OverseasPriceResult) -> tuple:
            conf_score = {"high": 3, "medium": 2, "low": 1}.get(r.confidence, 0)
            stale_score = 0 if r.stale else 1
            return (stale_score, conf_score, r.price_jpy)

        return max(valid, key=priority)

    def _ebay_rate_limit(self) -> None:
        """eBayリクエストの間隔を守る。"""
        now = time.monotonic()
        elapsed = now - self._last_ebay_request
        if elapsed < EBAY_REQUEST_INTERVAL:
            time.sleep(EBAY_REQUEST_INTERVAL - elapsed)
        self._last_ebay_request = time.monotonic()

    def _make_error_result(
        self, product_id: str, alias: str, source: str, error: str
    ) -> OverseasPriceResult:
        usd_jpy, _ = get_usd_jpy()
        now_str = datetime.now(tz=JST).isoformat()
        return OverseasPriceResult(
            source=source, market=source,
            product_id=product_id, product_alias=alias,
            country="US", currency="USD",
            price_local=0.0, fx_rate=usd_jpy, price_jpy=0,
            confidence="low", listing_count=0,
            median_price_jpy=0, min_price_jpy=0, max_price_jpy=0,
            fetched_at=datetime.now(tz=JST).isoformat(), stale=False,
            failure_reason=error[:200], url="", raw_prices_json="[]",
        )

    def save_json(self, best_results: dict, all_results: dict, products: list) -> Path:
        """結果をJSONとして保存する。"""
        now = datetime.now(tz=JST)
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

        # --- latest.json ---
        prod_map = {p.id: p for p in products}

        by_product = {}
        prices_list = []

        for pid, result in best_results.items():
            prod = prod_map.get(pid)
            alias = pid.replace("prod_", "")
            entry = result.to_dict()
            entry["product_name"] = prod.name if prod else alias
            by_product[alias] = entry
            prices_list.append(entry)

        # 全結果（best以外も含む）
        all_entries = []
        for pid, results_list in all_results.items():
            prod = prod_map.get(pid)
            for r in results_list:
                e = r.to_dict()
                e["product_name"] = prod.name if prod else pid.replace("prod_", "")
                all_entries.append(e)

        # 統計
        high_conf = sum(1 for r in best_results.values() if r.confidence == "high")
        medium_conf = sum(1 for r in best_results.values() if r.confidence == "medium")
        low_conf = sum(1 for r in best_results.values() if r.confidence == "low")
        stale_count = sum(1 for r in best_results.values() if r.stale)

        # 取得モード集計（api / html / html_blocked / manual / unknown）を明記（Task 1）
        import os as _os_mode
        _ebay_app_id_set = bool(_os_mode.environ.get("EBAY_APP_ID")
                                or _os_mode.environ.get("EBAY_CLIENT_ID"))
        _method_counts: dict = {}
        for r in best_results.values():
            _m = getattr(r, "collector_method", "") or "unknown"
            # manual CSV 由来は failure_reason=stale_manual 等で判別
            _fr = getattr(r, "failure_reason", "") or ""
            if "manual" in str(_fr).lower():
                _m = "manual"
            _method_counts[_m] = _method_counts.get(_m, 0) + 1
        # overseas 全体の主モード判定
        if _method_counts.get("api", 0) > 0:
            _source_mode = "api"
        elif _method_counts.get("html", 0) > 0:
            _source_mode = "html"
        elif _method_counts.get("html_blocked", 0) > 0:
            _source_mode = "html_blocked"
        elif _method_counts.get("manual", 0) > 0:
            _source_mode = "manual"
        else:
            _source_mode = "none"

        report = {
            "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
            "total_prices": len(prices_list),
            "products_with_overseas": len(best_results),
            "confidence_summary": {
                "high": high_conf,
                "medium": medium_conf,
                "low": low_conf,
            },
            "stale_count": stale_count,
            # Task 1: EBAY_APP_ID 設定状況と取得モードを明記
            "ebay_app_id_configured": _ebay_app_id_set,
            "source_mode": _source_mode,
            "method_counts": _method_counts,
            "prices": prices_list,
            "by_product": by_product,
            "all_results": all_entries,
        }

        json_path = EXPORT_DIR / "latest.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # --- overseas_report/latest.json (詳細レポート) ---
        report2 = dict(report)
        report2["by_product_detailed"] = {}
        for pid, results_list in all_results.items():
            alias = pid.replace("prod_", "")
            report2["by_product_detailed"][alias] = [r.to_dict() for r in results_list]

        json_path2 = REPORT_DIR / "latest.json"
        with open(json_path2, "w", encoding="utf-8") as f:
            json.dump(report2, f, ensure_ascii=False, indent=2)

        # --- overseas_report/latest.md ---
        md_lines = [
            "# 海外価格レポート",
            f"\n生成日時: {now.strftime('%Y-%m-%d %H:%M JST')}",
            f"\n## サマリー\n",
            f"- 取得商品数: {len(best_results)}",
            f"- confidence high: {high_conf}件",
            f"- confidence medium: {medium_conf}件",
            f"- confidence low: {low_conf}件",
            f"- stale (48h超): {stale_count}件",
            "\n## 商品別海外価格\n",
            "| 商品 | 市場 | 価格(JPY) | 件数 | confidence | stale | 取得時刻 |",
            "|------|------|-----------|------|------------|-------|---------|",
        ]
        for alias, entry in sorted(by_product.items()):
            stale_mark = "stale" if entry.get("stale") else "ok"
            md_lines.append(
                f"| {entry.get('product_name', alias)} | {entry.get('market','')} "
                f"| ¥{entry.get('price_jpy',0):,} | {entry.get('listing_count',0)}件 "
                f"| {entry.get('confidence','')} | {stale_mark} | {entry.get('fetched_at','')[:16]} |"
            )

        md_path = REPORT_DIR / "latest.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))

        logger.info(
            "overseas saved: latest.json(%d products), overseas_report/latest.json, latest.md",
            len(best_results)
        )
        return json_path

    def save_history(self, best_results: dict, products: list) -> None:
        """海外価格の日次履歴を保存する。

        保存先:
          exports/overseas_prices/history/YYYY-MM-DD.json  — 当日分の全データ
          data/overseas_price_history.csv                  — 時系列 CSV (追記)
        """
        now = datetime.now(tz=JST)
        date_str = now.strftime("%Y-%m-%d")
        prod_map = {p.id: p for p in products}

        # ── JSON 保存 ──────────────────────────────────────────────
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        json_entries = []
        for pid, result in best_results.items():
            prod = prod_map.get(pid)
            entry = result.to_dict()
            entry["product_name"] = prod.name if prod else pid.replace("prod_", "")
            json_entries.append(entry)

        history_json = {
            "date": date_str,
            "generated_at": now.isoformat(),
            "total": len(json_entries),
            "prices": json_entries,
        }
        json_path = HISTORY_DIR / f"{date_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(history_json, f, ensure_ascii=False, indent=2)
        logger.info("overseas history JSON saved: %s (%d entries)", json_path, len(json_entries))

        # ── CSV 追記 ───────────────────────────────────────────────
        HISTORY_CSV.parent.mkdir(parents=True, exist_ok=True)
        write_header = not HISTORY_CSV.exists()
        with open(HISTORY_CSV, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HISTORY_CSV_COLUMNS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            for pid, result in best_results.items():
                # confidence=low / stale / html_blocked は除外
                if result.confidence == "low" or result.stale or result.collector_method == "html_blocked":
                    continue
                if result.price_jpy <= 0:
                    continue
                row = {
                    "product_id": result.product_id,
                    "product_alias": result.product_alias,
                    "source": result.source,
                    "market": result.market,
                    "currency": result.currency,
                    "price_local": result.price_local,
                    "fx_rate": result.fx_rate,
                    "price_jpy": result.price_jpy,
                    "median_price_jpy": result.median_price_jpy,
                    "max_price_jpy": result.max_price_jpy,
                    "min_price_jpy": result.min_price_jpy,
                    "listing_count": result.listing_count,
                    "confidence": result.confidence,
                    "collector_method": result.collector_method,
                    "observed_at": result.fetched_at,
                }
                writer.writerow(row)

        logger.info("overseas history CSV appended: %s", HISTORY_CSV)

    @staticmethod
    def load_previous_history(exclude_date: str | None = None) -> dict[str, dict]:
        """最新の履歴 JSON から前回価格を読み込む。

        Args:
            exclude_date: 除外する日付 (通常は今日の日付 "YYYY-MM-DD")

        Returns:
            {product_alias: entry_dict} の辞書 (前回取得データ)
        """
        if not HISTORY_DIR.exists():
            return {}

        history_files = sorted(HISTORY_DIR.glob("????-??-??.json"), reverse=True)
        for hf in history_files:
            date_part = hf.stem  # "2026-05-27"
            if exclude_date and date_part == exclude_date:
                continue
            try:
                with open(hf, encoding="utf-8") as f:
                    data = json.load(f)
                prev = {}
                for entry in data.get("prices", []):
                    alias = entry.get("product_alias", "")
                    if alias:
                        prev[alias] = entry
                logger.debug("overseas history loaded: %s (%d entries)", hf.name, len(prev))
                return prev
            except Exception as e:
                logger.warning("overseas history load failed %s: %s", hf, e)
                continue

        return {}
