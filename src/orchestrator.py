"""Orchestrator - 全体制御。

Collector実行 → Score → Dispatch → Scan を統括する。
1つのCollectorが失敗しても全体を止めない。
同一ドメインへの同時アクセスはRateLimiterが防ぐ。
"""

import importlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml

from src.db.database import Database
from src.db.repository import Repository
from src.collectors.rate_limiter import RateLimiter
from src.pipeline.scorer import Scorer
from src.pipeline.dedup import DedupChecker
from src.pipeline.alert_dispatcher import AlertDispatcher

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# source_id → Collectorクラスパス
COLLECTOR_MAP = {
    "src_kakaku": "src.collectors.price.kakaku_com.KakakuComCollector",
    "src_yodobashi": "src.collectors.stock.yodobashi.YodobashiCollector",
    "src_map_camera": "src.collectors.price.map_camera.MapCameraCollector",
    "src_ricoh_imaging": "src.collectors.official.ricoh.RicohOfficialCollector",
    "src_fujifilm_official": "src.collectors.official.fujifilm.FujifilmOfficialCollector",
    "src_apple_jp": "src.collectors.official.apple.AppleOfficialCollector",
    "src_janpara": "src.collectors.buyback.janpara.JanparaCollector",
    "src_iosys": "src.collectors.buyback.iosys.IosysCollector",
    "src_sofmap": "src.collectors.buyback.sofmap.SofmapCollector",
    "src_biccamera": "src.collectors.stock.biccamera.BiccameraCollector",
}

# ソースをカテゴリ分類
STOCK_SOURCES = {
    "src_yodobashi", "src_biccamera", "src_ricoh_imaging",
    "src_apple_jp", "src_fujifilm_official", "src_canon_official",
    "src_nikon_direct", "src_sony_store", "src_nintendo_store",
    "src_playstation_official",
}

PRICE_SOURCES = {
    "src_kakaku", "src_map_camera", "src_sofmap", "src_janpara",
    "src_iosys", "src_mercari", "src_yahoo_auction", "src_ebay",
    "src_stockx",
}

OFFICIAL_SOURCES = {
    "src_ricoh_imaging", "src_fujifilm_official", "src_apple_jp",
    "src_canon_official", "src_nikon_direct", "src_sony_store",
    "src_nintendo_store", "src_playstation_official",
}


class HealthChecker:
    """Collectorの稼働状態を管理する。"""

    def __init__(self, repository: Repository, threshold: int = 5):
        self.repository = repository
        self.threshold = threshold

    def _source_exists(self, source_id: str) -> bool:
        """sourcesテーブルにsource_idが存在するか確認する。"""
        row = self.repository.db.connection.execute(
            "SELECT id FROM sources WHERE id=?", (source_id,)
        ).fetchone()
        return row is not None

    def record_success(self, source_id: str, duration_ms: int) -> None:
        if not self._source_exists(source_id):
            logger.warning("Unknown source skipped (health): %s", source_id)
            return
        now = datetime.now().isoformat()
        self.repository.db.connection.execute("""
            INSERT INTO source_health (source_id, last_success_at, consecutive_errors,
                                        avg_duration_ms, auto_disabled, updated_at)
            VALUES (?, ?, 0, ?, 0, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                last_success_at = ?,
                consecutive_errors = 0,
                avg_duration_ms = (avg_duration_ms + ?) / 2,
                updated_at = ?
        """, (source_id, now, duration_ms, now, now, duration_ms, now))
        self.repository.db.connection.commit()

    def record_error(self, source_id: str) -> bool:
        """エラーを記録。auto_disabled候補になったらTrue。"""
        if not self._source_exists(source_id):
            logger.warning("Unknown source skipped (health): %s", source_id)
            return False
        now = datetime.now().isoformat()
        self.repository.db.connection.execute("""
            INSERT INTO source_health (source_id, last_error_at, consecutive_errors,
                                        auto_disabled, updated_at)
            VALUES (?, ?, 1, 0, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                last_error_at = ?,
                consecutive_errors = consecutive_errors + 1,
                auto_disabled = CASE
                    WHEN consecutive_errors + 1 >= ? THEN 1 ELSE auto_disabled END,
                updated_at = ?
        """, (source_id, now, now, now, self.threshold, now))
        self.repository.db.connection.commit()

        row = self.repository.db.connection.execute(
            "SELECT consecutive_errors, auto_disabled FROM source_health WHERE source_id=?",
            (source_id,),
        ).fetchone()
        if row and row["auto_disabled"]:
            logger.warning("Source %s auto-disabled after %d consecutive errors",
                           source_id, row["consecutive_errors"])
            return True
        return False

    def is_disabled(self, source_id: str) -> bool:
        row = self.repository.db.connection.execute(
            "SELECT auto_disabled FROM source_health WHERE source_id=?",
            (source_id,),
        ).fetchone()
        return bool(row and row["auto_disabled"])

    def get_all_health(self):
        """sourcesテーブルに存在するsource_idのhealthのみ返す。"""
        return self.repository.db.connection.execute(
            """SELECT h.* FROM source_health h
               INNER JOIN sources s ON s.id = h.source_id
               ORDER BY h.source_id"""
        ).fetchall()


class Orchestrator:
    """全体制御。"""

    def __init__(self, db: Optional[Database] = None):
        self.config = self._load_config()
        self.db = db or Database(db_path=self.config["system"]["db_path"])
        self.db.init_schema()
        self.repo = Repository(self.db)
        self.health = HealthChecker(
            self.repo,
            threshold=self.config["scheduler"].get("consecutive_error_threshold", 5),
        )
        self.max_workers = self.config["scheduler"].get("max_workers", 3)

    def _load_config(self) -> dict:
        path = PROJECT_ROOT / "config" / "settings.yaml"
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _build_notifiers(self) -> list:
        """CLI._build_notifiersと同等。"""
        import os
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")

        ncfg_path = PROJECT_ROOT / "config" / "notifications.yaml"
        with open(ncfg_path, "r", encoding="utf-8") as f:
            ncfg = yaml.safe_load(f).get("notifications", {})

        from src.notifiers.log_notifier import LogNotifier
        from src.notifiers.discord_notifier import DiscordNotifier
        from src.notifiers.telegram_notifier import TelegramNotifier

        notifiers = [LogNotifier(
            enabled=True,
            send_ranks=["S", "A", "B", "C"],
            log_dir=str(PROJECT_ROOT / self.config["system"]["log_dir"]),
        )]

        dc = ncfg.get("discord", {})
        wh = os.environ.get(dc.get("webhook_url_env", "DISCORD_WEBHOOK_URL"), "")
        notifiers.append(DiscordNotifier(webhook_url=wh, enabled=bool(wh),
                                          send_ranks=dc.get("send_ranks", ["S", "A"])))

        tc = ncfg.get("telegram", {})
        bt = os.environ.get(tc.get("bot_token_env", "TELEGRAM_BOT_TOKEN"), "")
        ci = os.environ.get(tc.get("chat_id_env", "TELEGRAM_CHAT_ID"), "")
        notifiers.append(TelegramNotifier(bot_token=bt, chat_id=ci,
                                           enabled=bool(bt and ci),
                                           send_ranks=tc.get("send_ranks", ["S"])))
        return notifiers

    def _load_collector(self, source_id: str, source, repo):
        class_path = COLLECTOR_MAP.get(source_id)
        if not class_path:
            return None
        mod_path, cls_name = class_path.rsplit(".", 1)
        mod = importlib.import_module(mod_path)
        return getattr(mod, cls_name)(
            source=source, repository=repo,
            user_agent=self.config["http"]["user_agent"],
            timeout=self.config["http"]["default_timeout_sec"],
        )

    # ===== 実行メソッド =====

    def run_once(self) -> dict:
        """全体を1回実行する。"""
        logger.info("=== run-once START ===")
        results = {"official": 0, "stock": 0, "price": 0, "scored": 0,
                   "dispatched": 0, "candidates": 0, "errors": 0}

        # 1. Official price check
        r = self.run_collectors(OFFICIAL_SOURCES & set(COLLECTOR_MAP.keys()))
        results["official"] = r["success"]
        results["errors"] += r["errors"]

        # 2. Stock check
        r = self.run_collectors(STOCK_SOURCES & set(COLLECTOR_MAP.keys()))
        results["stock"] = r["success"]
        results["errors"] += r["errors"]

        # 3. Price check
        r = self.run_collectors(PRICE_SOURCES & set(COLLECTOR_MAP.keys()))
        results["price"] = r["success"]
        results["errors"] += r["errors"]

        # 4. Score
        results["scored"] = self.run_scoring()

        # 5. Dispatch
        results["dispatched"] = self.run_dispatch()

        # 6. Product scan
        results["candidates"] = self.run_product_scan()

        logger.info("=== run-once DONE: %s ===", results)
        return results

    def run_stock_check(self) -> dict:
        """在庫・抽選系のみ実行。"""
        return self.run_collectors(STOCK_SOURCES & set(COLLECTOR_MAP.keys()))

    def run_price_check(self) -> dict:
        """価格・相場系のみ実行。"""
        return self.run_collectors(PRICE_SOURCES & set(COLLECTOR_MAP.keys()))

    def run_collectors(self, source_ids: set) -> dict:
        """指定されたsource群のCollectorを実行する。"""
        results = {"success": 0, "errors": 0, "skipped": 0}
        tasks = []

        products = self.repo.list_products()
        for product in products:
            for sid in source_ids:
                if self.health.is_disabled(sid):
                    results["skipped"] += 1
                    continue
                config = self.repo.get_product_source_config(product.id, sid)
                if not config or not config.target_url:
                    continue
                source = self.repo.get_source(sid)
                if not source:
                    continue
                tasks.append((product, source, config))

        if not tasks:
            return results

        # 並列実行（max_workers制限、RateLimiterでドメイン重複防止）
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}
            for product, source, config in tasks:
                f = pool.submit(self._run_single, product, source, config)
                futures[f] = (product.id, source.id)

            for f in as_completed(futures):
                pid, sid = futures[f]
                try:
                    ok = f.result()
                    if ok:
                        results["success"] += 1
                    else:
                        results["errors"] += 1
                except Exception as e:
                    logger.error("Collector %s x %s exception: %s", sid, pid, e)
                    results["errors"] += 1

        return results

    def _run_single(self, product, source, config) -> bool:
        """1つの商品×ソースのCollector実行。"""
        started = datetime.now()
        try:
            collector = self._load_collector(source.id, source, self.repo)
            if not collector:
                return False

            obs = collector.collect(product, config)
            duration = int((datetime.now() - started).total_seconds() * 1000)

            if obs:
                self.health.record_success(source.id, duration)
                return True
            else:
                self.health.record_error(source.id)
                return False

        except Exception as e:
            logger.error("Collector error %s x %s: %s", source.id, product.id, e)
            self.health.record_error(source.id)
            return False

    def run_scoring(self) -> int:
        """未処理observationsをスコアリング。"""
        dispatcher = AlertDispatcher(
            repository=self.repo,
            scorer=Scorer(repository=self.repo),
            dedup=DedupChecker(repository=self.repo),
            notifiers=[],  # score_latestは通知しない
        )
        alerts = dispatcher.score_latest()
        logger.info("Scored %d observations → %d alerts", len(alerts), len(alerts))
        return len(alerts)

    def run_dispatch(self) -> int:
        """未送信S/Aアラートを通知送信。"""
        dispatcher = AlertDispatcher(
            repository=self.repo,
            scorer=Scorer(repository=self.repo),
            dedup=DedupChecker(repository=self.repo),
            notifiers=self._build_notifiers(),
        )
        dispatched = dispatcher.dispatch_alerts()
        logger.info("Dispatched %d alerts", len(dispatched))
        return len(dispatched)

    def run_product_scan(self) -> int:
        """新製品候補スキャン。"""
        from src.pipeline.product_scanner import ProductScanner
        scanner = ProductScanner(repository=self.repo)
        observations = self.repo.list_observations(limit=50)
        total = 0
        for obs in observations:
            if obs.observation_type == "official_price" and obs.raw_text:
                candidates = scanner.scan_from_html(
                    obs.raw_text, obs.source_id, "", brand="RICOH"
                )
                total += scanner.save_candidates(candidates)
        return total

    def close(self):
        self.db.close()
