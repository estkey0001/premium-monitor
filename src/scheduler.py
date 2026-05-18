"""APScheduler ベースの定期実行スケジューラ（Phase 10修正版）。

ジョブ構成:
  1. buyback_premium_check: 10:00/12:00/18:00 JST — 買取更新+プレ値計算（統合ジョブ）
  2. stock_check: 60分間隔 — 在庫監視（公式/量販店）
  3. dispatch: 10分間隔 — 通知再送チェック
  4. product_scan: 180分間隔 — 新製品候補スキャン

起動: python -m src.cli start-scheduler
"""

import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = PROJECT_ROOT / "data" / "scheduler_status.yaml"


def _load_settings() -> dict:
    with open(PROJECT_ROOT / "config" / "settings.yaml", "r") as f:
        return yaml.safe_load(f)


def _save_status(job_name: str, status: str, details: str = ""):
    """スケジューラの実行状態をファイルに保存する。"""
    data = {}
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, "r") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

    if "jobs" not in data:
        data["jobs"] = {}

    data["jobs"][job_name] = {
        "last_run": datetime.now().isoformat(),
        "status": status,
        "details": details,
    }
    data["scheduler_running"] = True
    data["updated_at"] = datetime.now().isoformat()

    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATUS_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


# ===== ジョブ定義 =====

def _get_db_and_repo():
    """DB+Repository生成ヘルパー。"""
    from src.db.database import Database
    from src.db.repository import Repository
    settings = _load_settings()
    db = Database(db_path=settings["system"]["db_path"])
    db.init_schema()
    return db, Repository(db)


def _job_buyback_premium_check():
    """統合ジョブ: 買取更新 + プレ値計算 (10工程一括)。"""
    logger.info("[scheduler] buyback_premium_check START")
    try:
        db, repo = _get_db_and_repo()
        from src.jobs.buyback_premium_job import BuybackPremiumJob
        job = BuybackPremiumJob(repository=repo)
        results = job.run()
        db.close()
        _save_status("buyback_premium_check", "success",
                      f"snaps={results['snapshots_updated']} deals={results['beginner_deals']} "
                      f"changes={results['buyback_changes']} line={results['line_alerts']} "
                      f"errors={len(results['errors'])} ({results['elapsed_sec']}s)")
        logger.info("[scheduler] buyback_premium_check DONE: %s", results)
    except Exception as e:
        logger.error("[scheduler] buyback_premium_check ERROR: %s", e)
        _save_status("buyback_premium_check", "error", str(e))


def _job_stock_check():
    """在庫監視ジョブ（60分間隔）。"""
    logger.info("[scheduler] stock_check START")
    try:
        from src.orchestrator import Orchestrator
        orch = Orchestrator()
        r = orch.run_stock_check()
        orch.close()
        _save_status("stock_check", "success", str(r))
        logger.info("[scheduler] stock_check DONE: %s", r)
    except Exception as e:
        logger.error("[scheduler] stock_check ERROR: %s", e)
        _save_status("stock_check", "error", str(e))


def _job_dispatch():
    """通知再送チェック（10分間隔）。"""
    logger.info("[scheduler] dispatch START")
    try:
        from src.orchestrator import Orchestrator
        orch = Orchestrator()
        n = orch.run_dispatch()
        orch.close()
        _save_status("dispatch", "success", f"dispatched={n}")
    except Exception as e:
        logger.error("[scheduler] dispatch ERROR: %s", e)
        _save_status("dispatch", "error", str(e))


def _job_product_scan():
    """新製品候補スキャン（09:00 / 12:30 / 18:30 JST）。NewProductScannerを使用。"""
    logger.info("[scheduler] new_product_scan START")
    try:
        db, repo = _get_db_and_repo()
        from src.market.new_product_scanner import NewProductScanner
        scanner = NewProductScanner(repository=repo)
        result = scanner.scan()
        db.close()
        _save_status("new_product_scan", "success",
                     f"new={result['new']} updated={result['updated']} errors={len(result['errors'])}")
        logger.info("[scheduler] new_product_scan DONE: %s", result)
    except Exception as e:
        logger.error("[scheduler] new_product_scan ERROR: %s", e)
        _save_status("new_product_scan", "error", str(e))


# ===== スケジューラ本体 =====

def start_scheduler():
    """APSchedulerを起動して常駐する。"""
    config = _load_settings().get("scheduler", {})

    if not config.get("enabled", True):
        logger.warning("Scheduler is disabled in settings.yaml")
        return

    tz = config.get("timezone", "Asia/Tokyo")
    scheduler = BlockingScheduler(timezone=tz)

    # === 買取+プレ値統合ジョブ (10:00/12:00/18:00 JST) ===
    buyback_times = config.get("buyback_and_premium_times", ["10:00", "12:00", "18:00"])
    for time_str in buyback_times:
        hour, minute = time_str.split(":")
        job_id = f"buyback_premium_{hour}{minute}"
        scheduler.add_job(
            _job_buyback_premium_check,
            CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
            id=job_id, name=f"買取+プレ値計算 ({time_str})",
            max_instances=1, replace_existing=True,
        )

    # === 在庫監視 (60分間隔) ===
    stock_interval = config.get("stock_interval_minutes", 60)
    scheduler.add_job(
        _job_stock_check,
        IntervalTrigger(minutes=stock_interval, timezone=tz),
        id="stock_check", name=f"在庫監視 ({stock_interval}分)",
        max_instances=1, replace_existing=True,
    )

    # === 通知再送 (10分間隔) ===
    dispatch_interval = config.get("dispatch_interval_minutes", 10)
    scheduler.add_job(
        _job_dispatch,
        IntervalTrigger(minutes=dispatch_interval, timezone=tz),
        id="dispatch", name=f"通知再送 ({dispatch_interval}分)",
        max_instances=1, replace_existing=True,
    )

    # === 新商品スキャン (09:00 / 12:30 / 18:30 JST) ===
    for scan_time in ["9:0", "12:30", "18:30"]:
        hour, minute = scan_time.split(":")
        scheduler.add_job(
            _job_product_scan,
            CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
            id=f"new_product_scan_{hour}_{minute}",
            name=f"新商品スキャン ({scan_time} JST)",
            max_instances=1, replace_existing=True,
        )

    _save_status("_scheduler", "started", f"jobs={len(scheduler.get_jobs())}")

    def _shutdown(signum, frame):
        logger.info("Scheduler shutting down...")
        _save_status("_scheduler", "stopped", "signal")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Scheduler started with %d jobs (tz=%s)", len(scheduler.get_jobs()), tz)
    for job in scheduler.get_jobs():
        logger.info("  %s: next=%s", job.name, job.next_run_time)

    scheduler.start()


def get_scheduler_status() -> dict:
    """スケジューラの状態を返す。"""
    if not STATUS_FILE.exists():
        return {"scheduler_running": False, "jobs": {}, "updated_at": None}
    try:
        with open(STATUS_FILE, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {"scheduler_running": False, "jobs": {}, "updated_at": None}
