"""統合ジョブ: 買取価格更新 + プレ値計算 (10工程一括)。

実行内容:
1. refresh-buyback-prices (Collector / CSV)
2. buyback_history 保存
3. compare-buyback (店舗別比較)
4. compare-market (市場横断比較 → market_snapshots)
5. beginner_deals 再計算
6. premium_candidates 再検出
7. detect-buyback-changes (急騰急落)
8. publish_queue 候補生成
9. LINE速報候補生成
10. S/A 通知候補生成

10:00 / 12:00 / 18:00 JST に実行される。
"""

import logging
from datetime import datetime

from src.db.repository import Repository
from src.models.buyback_price import BUYBACK_SHOPS

logger = logging.getLogger(__name__)

# LINE速報条件
LINE_ALERT_MIN_PROFIT = 10000
LINE_ALERT_MIN_BEGINNER_SCORE = 0.7
LINE_ALERT_MAX_DIFFICULTY = 0.35


class BuybackPremiumJob:
    """買取更新 + プレ値計算の統合ジョブ。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def run(self) -> dict:
        """10工程を一括実行する。"""
        started = datetime.now()
        results = {
            "started_at": started.isoformat(),
            "buyback_refreshed": 0,
            "history_saved": 0,
            "snapshots_updated": 0,
            "beginner_deals": 0,
            "premium_candidates": 0,
            "buyback_changes": 0,
            "publish_items": 0,
            "line_alerts": 0,
            "errors": [],
        }

        # === Step 1: buyback_prices 更新 ===
        # (Collectorでの自動取得。失敗してもCSVデータで続行)
        try:
            results["buyback_refreshed"] = self._refresh_buyback_prices()
        except Exception as e:
            results["errors"].append(f"Step1 refresh: {e}")
            logger.error("Step1 error: %s", e)

        # === Step 2: buyback_history 保存 ===
        try:
            results["history_saved"] = self._save_buyback_history()
        except Exception as e:
            results["errors"].append(f"Step2 history: {e}")

        # === Step 3-4: market比較 + snapshots更新 ===
        try:
            from src.market.comparator import MarketComparator
            comp = MarketComparator(repository=self.repo)
            snapshots = comp.compare_all_products()
            results["snapshots_updated"] = len(snapshots)
        except Exception as e:
            results["errors"].append(f"Step3-4 market: {e}")
            snapshots = []

        # === Step 5: beginner_deals 再計算 ===
        try:
            from src.market.beginner_deal_scanner import BeginnerDealScanner
            scanner = BeginnerDealScanner(repository=self.repo)
            deals = scanner.scan_all()
            results["beginner_deals"] = len(deals)
        except Exception as e:
            results["errors"].append(f"Step5 beginner: {e}")

        # === Step 6: premium_candidates 再検出 ===
        try:
            from src.market.premium_detector import PremiumDetector
            detector = PremiumDetector(repository=self.repo)
            detected = detector.detect_from_snapshots(snapshots)
            saved = detector.save_as_product_candidates(detected)
            results["premium_candidates"] = saved
        except Exception as e:
            results["errors"].append(f"Step6 premium: {e}")

        # === Step 7: 急騰急落検知 ===
        try:
            from src.market.buyback_change_detector import BuybackChangeDetector
            change_detector = BuybackChangeDetector(repository=self.repo)
            changes = change_detector.detect_all()
            results["buyback_changes"] = len(changes)
        except Exception as e:
            results["errors"].append(f"Step7 changes: {e}")

        # === Step 8: publish_queue 候補生成 ===
        try:
            from src.publish.template_generator import TemplateGenerator
            gen = TemplateGenerator(repository=self.repo)
            items = gen.generate_from_beginner_deals()
            for item in items:
                self.repo.insert_publish_item(item)
            results["publish_items"] = len(items)
        except Exception as e:
            results["errors"].append(f"Step8 publish: {e}")

        # === Step 9: 日次LP生成 ===
        try:
            from src.content.daily_lp_generator import DailyLPGenerator
            lp_gen = DailyLPGenerator(repository=self.repo)
            lp_result = lp_gen.generate()
            results["lp_generated"] = True
            results["lp_path"] = lp_result["index_path"]
            logger.info("LP generated: %s", lp_result["index_path"])
        except Exception as e:
            results["errors"].append(f"Step9 LP: {e}")
            results["lp_generated"] = False

        # === Step 10-11: LINE速報候補（初期運用ではOFF、構造のみ残す） ===
        try:
            results["line_alerts"] = self._generate_line_alerts()
        except Exception as e:
            results["errors"].append(f"Step10-11 notify: {e}")

        elapsed = (datetime.now() - started).total_seconds()
        results["elapsed_sec"] = round(elapsed, 1)
        results["completed_at"] = datetime.now().isoformat()

        logger.info(
            "BuybackPremiumJob: snapshots=%d deals=%d changes=%d publish=%d line=%d errors=%d (%.1fs)",
            results["snapshots_updated"], results["beginner_deals"],
            results["buyback_changes"], results["publish_items"],
            results["line_alerts"], len(results["errors"]), elapsed,
        )
        return results

    def _refresh_buyback_prices(self) -> int:
        """Collectorで買取価格を取得する（失敗はスキップ）。"""
        count = 0
        products = self.repo.list_products()

        try:
            from src.collectors.buyback.mobile_ichiban import MobileIchibanCollector
            from src.collectors.buyback.kaitori_shouten import KaitoriShoutenCollector
            from src.collectors.buyback.iosys_buyback import IosysBuybackCollector
            collectors = [MobileIchibanCollector(), KaitoriShoutenCollector(), IosysBuybackCollector()]
        except Exception:
            collectors = []

        for prod in products:
            for coll in collectors:
                try:
                    result = coll.collect(prod)
                    if result:
                        self.repo.insert_buyback_price(result)
                        count += 1
                except Exception:
                    pass
        return count

    def _save_buyback_history(self) -> int:
        """現在のbuyback_pricesをbuyback_historyに保存する。"""
        count = 0
        buybacks = self.repo.list_buyback_prices(limit=200)
        for bp in buybacks:
            self.repo.insert_buyback_history(
                product_id=bp.product_id,
                shop_id=bp.shop_id,
                shop_name=bp.shop_name,
                price=bp.buyback_price,
                condition=bp.condition,
                observed_at=bp.observed_at,
            )
            count += 1
        return count

    def _generate_line_alerts(self) -> int:
        """LINE速報条件を満たすbeginner_easyを候補に追加する。"""
        deals = self.repo.list_beginner_deals(user_level="beginner_easy", min_profit=0, limit=50)
        count = 0
        for d in deals:
            if (d.net_profit_jpy >= LINE_ALERT_MIN_PROFIT
                    and d.beginner_score >= LINE_ALERT_MIN_BEGINNER_SCORE
                    and d.difficulty_score <= LINE_ALERT_MAX_DIFFICULTY):
                # 速報候補としてログ記録（実際のLINE送信はNotifier経由）
                logger.info(
                    "LINE alert candidate: %s net=+¥%s score=%.2f",
                    d.product_name, f"{d.net_profit_jpy:,}", d.beginner_score,
                )
                count += 1
        return count
