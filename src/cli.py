"""CLIエントリーポイント。

Phase 1: init-db / seed / list-products / list-sources / test-log-notifier
Phase 2: test-collector / latest-observations / price-history
Phase 3: score-latest / list-alerts / dispatch-alerts / test-discord / test-telegram
Phase 3.5: test-official / official-prices / update-retail-price / scan-new-products
           list-product-candidates / approve-product-candidate / reject-product-candidate
Phase 5: run-once / run-stock-check / run-price-check / run-product-scan
          dispatch-pending / start-scheduler / scheduler-status
Phase 6: generate-posts / list-publish-queue / show-publish-item
          approve-publish-item / reject-publish-item / generate-weekly-report
Phase 7A: scan-category / compare-market / list-market-snapshots
           list-premium-candidates / approve-premium-candidate
Phase 7B-2: list-beginner-candidates / list-advanced-candidates
             compare-market --user-level
Phase 8: validate-data / recalc-market-scores / validate-publish-text
Phase 9A: scan-beginner-deals / list-beginner-deals / compare-buyback
           refresh-buyback-prices / import-buyback-csv
Phase 10: generate-note-report / generate-lp-copy / generate-line-messages
           generate-community-messages / simulate-profit
"""

import importlib
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

from src.db.database import Database
from src.db.repository import Repository
from src.models.product import ProductModel
from src.models.source import SourceModel, ProductSourceConfigModel
from src.models.alert import AlertModel
from src.notifiers.log_notifier import LogNotifier
from src.notifiers.discord_notifier import DiscordNotifier
from src.notifiers.telegram_notifier import TelegramNotifier
from src.collectors.rate_limiter import RateLimiter

# プロジェクトルート
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("premium_monitor.cli")


# =========================================
# ヘルパー
# =========================================

def _load_yaml(filename: str) -> dict:
    path = PROJECT_ROOT / "config" / filename
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_db() -> Database:
    settings = _load_yaml("settings.yaml")
    return Database(db_path=settings["system"]["db_path"])


SOURCE_ALIASES = {
    "kakaku": "src_kakaku", "yodobashi": "src_yodobashi",
    "map_camera": "src_map_camera", "mapcamera": "src_map_camera",
    "biccamera": "src_biccamera", "sofmap": "src_sofmap",
    "janpara": "src_janpara", "iosys": "src_iosys",
    "ebay": "src_ebay", "mercari": "src_mercari", "kitamura": "src_kitamura",
    # 公式ストア
    "ricoh": "src_ricoh_imaging", "ricoh_imaging": "src_ricoh_imaging",
    "fujifilm": "src_fujifilm_official", "fuji": "src_fujifilm_official",
    "apple": "src_apple_jp", "apple_jp": "src_apple_jp",
    "sony": "src_sony_store", "nintendo": "src_nintendo_store",
    "playstation": "src_playstation_official", "ps": "src_playstation_official",
    "canon": "src_canon_official", "nikon": "src_nikon_direct",
}

PRODUCT_ALIASES = {
    # GR IV系（最新・優先）
    "gr4": "prod_gr4", "griv": "prod_gr4",
    "gr4_hdf": "prod_gr4_hdf", "griv_hdf": "prod_gr4_hdf",
    "gr4_mono": "prod_gr4_mono", "griv_mono": "prod_gr4_mono",
    # GR III系（旧モデル）
    "gr3x": "prod_gr3x", "gr3_hdf": "prod_gr3_hdf", "gr3": "prod_gr3",
    # FUJIFILM
    "x100vi": "prod_x100vi",
    # iPhone 17
    "iphone17pro256": "prod_iphone17pro_256", "iphone17pro": "prod_iphone17pro_256",
    "iphone17pro512": "prod_iphone17pro_512",
    "iphone17pm256": "prod_iphone17pm_256", "iphone17pm": "prod_iphone17pm_256",
    "iphone17pm512": "prod_iphone17pm_512",
    "iphone17_256": "prod_iphone17_256", "iphone17": "prod_iphone17_256",
    # iPhone 16
    "iphone16pro256": "prod_iphone16pro_256", "iphone16pro": "prod_iphone16pro_256",
    "iphone16pm": "prod_iphone16pm_256", "iphone16pm_256": "prod_iphone16pm_256",
    "iphone16pm_512": "prod_iphone16pm_512",
    # Mac
    "macbook_air_m4_13": "prod_macbook_air_m4_13", "mba_m4": "prod_macbook_air_m4_13",
    "macbook_air_m4_15": "prod_macbook_air_m4_15",
    "macbook_pro_m4_14": "prod_macbook_pro_m4_14", "mbp_m4": "prod_macbook_pro_m4_14",
    "mac_mini_m4": "prod_mac_mini_m4",
    # iPad
    "ipad_pro_m4_11": "prod_ipad_pro_m4_11", "ipad_pro_m4_13": "prod_ipad_pro_m4_13",
    "ipad_air_m3": "prod_ipad_air_m3",
    # Apple Watch
    "apple_watch_s11": "prod_apple_watch_s11", "apple_watch_ultra3": "prod_apple_watch_ultra3",
    # AirPods
    "airpods_pro3": "prod_airpods_pro3", "airpods_max": "prod_airpods_max",
    # ゲーム機
    "ps5_pro": "prod_ps5_pro", "switch2": "prod_switch2",
}

COLLECTOR_MAP = {
    "src_kakaku": "src.collectors.price.kakaku_com.KakakuComCollector",
    "src_yodobashi": "src.collectors.stock.yodobashi.YodobashiCollector",
    "src_map_camera": "src.collectors.price.map_camera.MapCameraCollector",
    # 公式ストア
    "src_ricoh_imaging": "src.collectors.official.ricoh.RicohOfficialCollector",
    "src_fujifilm_official": "src.collectors.official.fujifilm.FujifilmOfficialCollector",
    "src_apple_jp": "src.collectors.official.apple.AppleOfficialCollector",
    # 買取・中古
    "src_janpara": "src.collectors.buyback.janpara.JanparaCollector",
    "src_iosys": "src.collectors.buyback.iosys.IosysCollector",
    "src_sofmap": "src.collectors.buyback.sofmap.SofmapCollector",
    # 量販店
    "src_biccamera": "src.collectors.stock.biccamera.BiccameraCollector",
    # 海外・フリマ・中古専門
    "src_ebay": "src.collectors.price.ebay.EbayCollector",
    "src_mercari": "src.collectors.price.mercari.MercariCollector",
    "src_kitamura": "src.collectors.price.kitamura.KitamuraCollector",
}


def _resolve_source_id(alias: str) -> str:
    if alias.startswith("src_"):
        return alias
    return SOURCE_ALIASES.get(alias, f"src_{alias}")


def _resolve_product_id(alias: str) -> str:
    if alias.startswith("prod_"):
        return alias
    return PRODUCT_ALIASES.get(alias, f"prod_{alias}")


def _load_collector(source_id, source, repo):
    class_path = COLLECTOR_MAP.get(source_id)
    if not class_path:
        raise ValueError(f"No collector for {source_id}. Available: {list(COLLECTOR_MAP)}")
    mod_path, cls_name = class_path.rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    settings = _load_yaml("settings.yaml")
    return getattr(mod, cls_name)(
        source=source, repository=repo,
        user_agent=settings["http"]["user_agent"],
        timeout=settings["http"]["default_timeout_sec"],
    )


def _build_notifiers() -> list:
    """設定+環境変数からNotifier群を構築。未設定のものはskip。"""
    ncfg = _load_yaml("notifications.yaml").get("notifications", {})
    settings = _load_yaml("settings.yaml")
    notifiers = []

    # Log（常に有効）
    lc = ncfg.get("log", {})
    notifiers.append(LogNotifier(
        enabled=lc.get("enabled", True),
        send_ranks=lc.get("send_ranks", ["S", "A", "B", "C"]),
        log_dir=str(PROJECT_ROOT / settings["system"]["log_dir"]),
    ))

    # Discord
    dc = ncfg.get("discord", {})
    webhook = os.environ.get(dc.get("webhook_url_env", "DISCORD_WEBHOOK_URL"), "")
    notifiers.append(DiscordNotifier(
        webhook_url=webhook,
        enabled=dc.get("enabled", False) or bool(webhook),
        send_ranks=dc.get("send_ranks", ["S", "A"]),
    ))

    # Telegram
    tc = ncfg.get("telegram", {})
    bot_token = os.environ.get(tc.get("bot_token_env", "TELEGRAM_BOT_TOKEN"), "")
    chat_id = os.environ.get(tc.get("chat_id_env", "TELEGRAM_CHAT_ID"), "")
    notifiers.append(TelegramNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
        enabled=tc.get("enabled", False) or bool(bot_token and chat_id),
        send_ranks=tc.get("send_ranks", ["S"]),
    ))

    return notifiers


def _build_dispatcher(repo):
    from src.pipeline.scorer import Scorer
    from src.pipeline.dedup import DedupChecker
    from src.pipeline.alert_dispatcher import AlertDispatcher
    return AlertDispatcher(
        repository=repo,
        scorer=Scorer(repository=repo),
        dedup=DedupChecker(repository=repo),
        notifiers=_build_notifiers(),
    )


# =========================================
# CLI
# =========================================

@click.group()
def cli():
    """プレ値商品監視システム CLI"""
    pass


# ---- Phase 1 ----

@cli.command("init-db")
def init_db():
    """データベースを初期化する。"""
    click.echo("Initializing database...")
    db = _get_db()
    try:
        db.init_schema()
        click.echo(f"Database initialized: {db.db_path}")
    finally:
        db.close()


@cli.command("seed")
def seed():
    """config/のYAMLからシードデータを投入する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)

        for p in _load_yaml("products.yaml").get("products", []):
            repo.upsert_product(ProductModel(
                id=p["id"], genre=p["genre"], name=p["name"],
                brand=p.get("brand", ""), model_number=p.get("model_number", ""),
                retail_price=p.get("retail_price", 0), keywords=p.get("keywords", []),
            ))

        for s in _load_yaml("sources.yaml").get("sources", []):
            repo.upsert_source(SourceModel(
                id=s["id"], name=s["name"], source_type=s["source_type"],
                base_url=s["base_url"], collector_module=s["collector_module"],
                rate_limit_sec=s.get("rate_limit_sec", 60), requires_js=s.get("requires_js", False),
            ))

        for c in _load_yaml("product_source_configs.yaml").get("product_source_configs", []):
            repo.upsert_product_source_config(ProductSourceConfigModel(
                id=f"psc_{c['product_id']}_{c['source_id']}",
                product_id=c["product_id"], source_id=c["source_id"],
                target_url=c.get("target_url", ""),
            ))

        click.echo(f"Products: {repo.count_products()}, Sources: {repo.count_sources()}")
        click.echo("Seed complete!")
    finally:
        db.close()


@cli.command("list-products")
@click.option("--genre", "-g", default=None)
def list_products(genre):
    """商品一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        products = repo.list_products(genre=genre)
        if not products:
            click.echo("No products. Run 'seed' first.")
            return
        click.echo(f"\n{'='*70}\n 商品一覧 ({len(products)} 件)\n{'='*70}")
        cur = None
        for p in products:
            if p.genre != cur:
                cur = p.genre
                click.echo(f"\n  [{cur.upper()}]")
            price = f"¥{p.retail_price:,}" if p.retail_price else "---"
            click.echo(f"    {p.id:<28} {p.name:<30} {price:>12}")
        click.echo(f"\n{'='*70}\n")
    finally:
        db.close()


@cli.command("list-sources")
@click.option("--type", "-t", "source_type", default=None)
def list_sources(source_type):
    """情報源一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        sources = repo.list_sources(source_type=source_type)
        if not sources:
            click.echo("No sources. Run 'seed' first.")
            return
        click.echo(f"\n{'='*80}\n 情報源一覧 ({len(sources)} 件)\n{'='*80}")
        cur = None
        for s in sources:
            if s.source_type != cur:
                cur = s.source_type
                click.echo(f"\n  [{cur}]")
            flags = (" [JS]" if s.requires_js else "") + (" [collector]" if s.id in COLLECTOR_MAP else "")
            click.echo(f"    {s.id:<25} {s.name:<20} rate={s.rate_limit_sec:>3}s{flags}")
        click.echo(f"\n{'='*80}\n")
    finally:
        db.close()


@cli.command("test-log-notifier")
def test_log_notifier():
    """LogNotifierの動作テスト。"""
    settings = _load_yaml("settings.yaml")
    n = LogNotifier(enabled=True, send_ranks=["S", "A", "B", "C"],
                    log_dir=str(PROJECT_ROOT / settings["system"]["log_dir"]))
    click.echo(f"Connection: {'OK' if n.test_connection() else 'FAIL'}")
    dummy = AlertModel(
        id="test", observation_id="test", product_id="test",
        alert_rank="S", alert_type="price_premium",
        title="テスト通知", body="テスト本文",
        estimated_profit=45000, score=0.85, confidence=0.90,
    )
    n.send(dummy, product=ProductModel(id="test", genre="camera", name="テスト商品", retail_price=139700))
    click.echo("Test alert sent to log.")


# ---- Phase 2 ----

@cli.command("test-collector")
@click.option("--source", "-s", required=True)
@click.option("--product", "-p", required=True)
@click.option("--skip-rate-limit", is_flag=True)
def test_collector(source, product, skip_rate_limit):
    """実サイトからデータを取得するテスト。"""
    sid, pid = _resolve_source_id(source), _resolve_product_id(product)
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        prod = repo.get_product(pid)
        src = repo.get_source(sid)
        config = repo.get_product_source_config(pid, sid)
        if not all([prod, src, config]):
            click.echo(f"Not found: product={pid} source={sid}. Run 'seed'.")
            sys.exit(1)

        if skip_rate_limit:
            RateLimiter().reset()

        click.echo(f"\n{src.name} x {prod.name}")
        click.echo(f"URL: {config.target_url}")
        collector = _load_collector(sid, src, repo)
        obs = collector.collect(prod, config)

        if obs is None:
            click.echo("Result: FAILED")
            sys.exit(1)

        click.echo(f"  Price:    ¥{obs.price:,}" if obs.price else "  Price:    ---")
        click.echo(f"  Buyback:  ¥{obs.buyback_price:,}" if obs.buyback_price else "  Buyback:  ---")
        click.echo(f"  Stock:    {obs.is_in_stock}")
        click.echo(f"  Conf:     {obs.confidence:.0%}")
        click.echo(f"  ID:       {obs.id}\n")
    finally:
        db.close()


@cli.command("latest-observations")
@click.option("--product", "-p", default=None)
@click.option("--limit", "-n", default=20)
def latest_observations(product, limit):
    """最新の観測データ一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        pid = _resolve_product_id(product) if product else None
        obs_list = repo.list_observations(product_id=pid, limit=limit)
        if not obs_list:
            click.echo("No observations.")
            return
        click.echo(f"\n{'='*90}\n 観測データ ({len(obs_list)} 件)\n{'='*90}")
        click.echo(f"  {'日時':<18} {'商品':<22} {'情報源':<18} {'種別':<8} {'価格':>10} {'在庫':<4} {'信頼度':>5}")
        click.echo(f"  {'─'*84}")
        for o in obs_list:
            p = f"¥{o.price:,}" if o.price else "---"
            s = "○" if o.is_in_stock is True else ("×" if o.is_in_stock is False else "?")
            c = f"{o.confidence:.0%}" if o.confidence else "---"
            click.echo(f"  {o.observed_at.strftime('%Y-%m-%d %H:%M'):<18} {o.product_id:<22} {o.source_id:<18} {o.observation_type:<8} {p:>10} {s:<4} {c:>5}")
        click.echo(f"\n{'='*90}\n")
    finally:
        db.close()


@cli.command("price-history")
@click.option("--product", "-p", required=True)
@click.option("--type", "-t", "price_type", default=None)
@click.option("--limit", "-n", default=30)
def price_history(product, price_type, limit):
    """商品の価格推移を表示する。"""
    pid = _resolve_product_id(product)
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        prod = repo.get_product(pid)
        if not prod:
            click.echo(f"Product not found: {pid}")
            sys.exit(1)
        records = repo.list_price_history(product_id=pid, price_type=price_type, limit=limit)
        if not records:
            click.echo("No price history.")
            return
        click.echo(f"\n{'='*80}\n 価格推移: {prod.name} (定価: ¥{prod.retail_price:,})\n{'='*80}")
        click.echo(f"  {'日時':<18} {'情報源':<18} {'種別':<10} {'価格':>12} {'定価差':>12}")
        click.echo(f"  {'─'*72}")
        for r in records:
            diff = r.price - prod.retail_price if prod.retail_price else 0
            ds = f"+¥{diff:,}" if diff > 0 else f"¥{diff:,}" if diff < 0 else "±0"
            click.echo(f"  {r.recorded_at.strftime('%Y-%m-%d %H:%M'):<18} {r.source_id:<18} {r.price_type:<10} ¥{r.price:>10,} {ds:>12}")
        click.echo(f"\n{'='*80}\n")
    finally:
        db.close()


# ---- Phase 3 ----

@cli.command("score-latest")
def score_latest():
    """未処理のobservationsをスコアリングしてアラートを生成する（通知は送らない）。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        dispatcher = _build_dispatcher(repo)
        alerts = dispatcher.score_latest()

        if not alerts:
            click.echo("No unscored observations.")
            return

        click.echo(f"\n{'='*90}\n スコアリング結果 ({len(alerts)} 件)\n{'='*90}")
        for a in alerts:
            profit = f"¥{a.estimated_profit:,}" if a.estimated_profit is not None else "---"
            click.echo(
                f"  [{a.alert_rank}] {a.alert_type:<20} {a.title:<38} "
                f"profit={profit:>12} score={a.score:.2f}"
            )

        by_rank = {}
        for a in alerts:
            by_rank[a.alert_rank] = by_rank.get(a.alert_rank, 0) + 1
        click.echo(f"\n  Summary: {by_rank}")
        click.echo(f"{'='*90}\n")
    finally:
        db.close()


@cli.command("list-alerts")
@click.option("--rank", "-r", default=None, help="S/A/B/C")
@click.option("--limit", "-n", default=30)
def list_alerts(rank, limit):
    """生成済みアラート一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        alerts = repo.list_alerts(rank=rank, limit=limit)
        if not alerts:
            click.echo("No alerts. Run 'score-latest' first.")
            return

        click.echo(f"\n{'='*105}\n アラート一覧 ({len(alerts)} 件)\n{'='*105}")
        click.echo(
            f"  {'日時':<18} {'Rank':<5} {'Type':<20} {'タイトル':<35} "
            f"{'利益':>12} {'Score':>6} {'送信先':<10}"
        )
        click.echo(f"  {'─'*100}")
        for a in alerts:
            profit = f"¥{a.estimated_profit:,}" if a.estimated_profit is not None else "---"
            sent = ",".join(a.sent_channels) if a.sent_channels else "---"
            click.echo(
                f"  {a.created_at.strftime('%Y-%m-%d %H:%M'):<18} "
                f"[{a.alert_rank}]  {a.alert_type:<20} {a.title[:33]:<35} "
                f"{profit:>12} {a.score:>6.2f} {sent:<10}"
            )
        click.echo(f"\n{'='*105}\n")
    finally:
        db.close()


@cli.command("dispatch-alerts")
def dispatch_alerts():
    """未送信のS/Aアラートを通知送信する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        dispatcher = _build_dispatcher(repo)
        dispatched = dispatcher.dispatch_alerts()

        if not dispatched:
            click.echo("No alerts to dispatch (all sent, dedup, or B/C only).")
            return

        click.echo(f"\nDispatched {len(dispatched)} alerts:")
        for a in dispatched:
            click.echo(f"  [{a.alert_rank}] {a.title} → {a.sent_channels}")
    finally:
        db.close()


@cli.command("test-discord")
def test_discord():
    """Discord Webhook接続テスト。"""
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook:
        click.echo("DISCORD_WEBHOOK_URL not set in .env → skip")
        return
    n = DiscordNotifier(webhook_url=webhook, enabled=True)
    ok = n.test_connection()
    click.echo(f"Discord: {'OK' if ok else 'FAIL'}")


@cli.command("test-telegram")
def test_telegram():
    """Telegram Bot接続テスト。"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        click.echo("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set in .env → skip")
        return
    n = TelegramNotifier(bot_token=token, chat_id=chat_id, enabled=True)
    ok = n.test_connection()
    click.echo(f"Telegram: {'OK' if ok else 'FAIL'}")


# ---- Phase 3.5: 公式価格 ----

@cli.command("test-official")
@click.option("--source", "-s", required=True, help="公式サイト (例: ricoh, fujifilm, apple)")
@click.option("--product", "-p", required=True, help="商品 (例: gr3x, x100vi, iphone16pm)")
@click.option("--skip-rate-limit", is_flag=True)
def test_official(source, product, skip_rate_limit):
    """公式サイトから定価・在庫・抽選情報を取得するテスト。"""
    sid, pid = _resolve_source_id(source), _resolve_product_id(product)
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        prod = repo.get_product(pid)
        src = repo.get_source(sid)
        config = repo.get_product_source_config(pid, sid)
        if not all([prod, src, config]):
            click.echo(f"Not found: product={pid} source={sid}. Run 'seed'.")
            sys.exit(1)
        if skip_rate_limit:
            RateLimiter().reset()
        click.echo(f"\n[Official] {src.name} x {prod.name}")
        click.echo(f"URL: {config.target_url}")
        collector = _load_collector(sid, src, repo)
        obs = collector.collect(prod, config)
        if obs is None:
            click.echo("Result: FAILED")
            sys.exit(1)
        click.echo(f"  Official Price: ¥{obs.price:,}" if obs.price else "  Official Price: N/A (オープン価格等)")
        click.echo(f"  Stock:          {obs.is_in_stock}")
        click.echo(f"  Lottery:        {obs.lottery_status}" if obs.lottery_status else "  Lottery:        N/A")
        click.echo(f"  Confidence:     {obs.confidence:.0%}")
        if obs.raw_text:
            try:
                raw = json.loads(obs.raw_text)
                for k, v in raw.get("raw", raw).items():
                    if k not in ("url",) and v:
                        click.echo(f"  {k}: {v}")
            except Exception:
                pass
        # 定価更新候補チェック
        if obs.price and obs.price != prod.retail_price:
            click.echo(f"\n  ⚠ 定価更新候補: 現在DB=¥{prod.retail_price:,} → 公式=¥{obs.price:,}")
        click.echo("")
    finally:
        db.close()


@cli.command("official-prices")
def official_prices():
    """全商品の公式価格取得状況を一覧表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        products = repo.list_products()
        click.echo(f"\n{'='*90}\n 公式価格一覧\n{'='*90}")
        click.echo(
            f"  {'商品':<28} {'DB定価':>12} {'公式定価':>12} {'取得元':<18} {'在庫':<8} {'抽選':<6} {'更新候補'}"
        )
        click.echo(f"  {'─'*86}")
        for p in products:
            db_price = f"¥{p.retail_price:,}" if p.retail_price else "---"
            off_price = f"¥{p.official_price:,}" if p.official_price else "---"
            src = p.official_price_source or "---"
            stock = p.official_stock_status or "---"
            lottery = "抽選中" if p.is_lottery else "---"
            candidate = "★" if p.retail_price_update_candidate else ""
            click.echo(
                f"  {p.name[:26]:<28} {db_price:>12} {off_price:>12} {src:<18} {stock:<8} {lottery:<6} {candidate}"
            )
        click.echo(f"\n{'='*90}\n")
    finally:
        db.close()


@cli.command("update-retail-price")
@click.option("--product", "-p", required=True)
@click.option("--source", "-s", required=True, help="公式ソース (例: ricoh)")
@click.option("--confirm", is_flag=True, help="確認なしで更新する")
def update_retail_price(product, source, confirm):
    """公式価格でretail_priceを更新する。"""
    pid, sid = _resolve_product_id(product), _resolve_source_id(source)
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        prod = repo.get_product(pid)
        if not prod:
            click.echo(f"Product not found: {pid}")
            sys.exit(1)
        # 最新のofficial_price observationを取得
        obs_list = repo.list_observations(product_id=pid, source_id=sid, limit=5)
        official_obs = [o for o in obs_list if o.observation_type == "official_price" and o.price]
        if not official_obs:
            click.echo(f"No official price observation found for {pid} from {sid}")
            sys.exit(1)
        latest = official_obs[0]
        click.echo(f"\n  Product:       {prod.name}")
        click.echo(f"  Current price: ¥{prod.retail_price:,}" if prod.retail_price else "  Current price: 未設定")
        click.echo(f"  Official:      ¥{latest.price:,}")
        click.echo(f"  Source:        {sid}")
        click.echo(f"  Observed at:   {latest.observed_at}")
        if prod.retail_price == latest.price:
            click.echo("\n  Already up to date.")
            return
        if not confirm:
            click.echo(f"\n  ¥{prod.retail_price:,} → ¥{latest.price:,} に更新しますか？")
            click.echo("  --confirm フラグを付けて再実行してください。")
            return
        repo.update_product_official_price(
            pid, latest.price, sid, latest.observed_at
        )
        click.echo(f"\n  ✓ Updated: ¥{latest.price:,}")
    finally:
        db.close()


# ---- Phase 3.5+: 新製品候補 ----

@cli.command("scan-new-products")
@click.option("--source", "-s", default=None, help="ソース限定 (例: ricoh)")
@click.option("--skip-rate-limit", is_flag=True)
def scan_new_products(source, skip_rate_limit):
    """公式サイトをスキャンして新製品候補を検出する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.pipeline.product_scanner import ProductScanner
        scanner = ProductScanner(repository=repo)

        if skip_rate_limit:
            RateLimiter().reset()

        # RICOH公式スキャン（サンドボックスではモック不可なので手動トリガー前提）
        click.echo("Scanning for new product candidates...")

        # 既存observationsのraw_textから候補を検出
        observations = repo.list_observations(limit=50)
        total_found = 0
        for obs in observations:
            if obs.observation_type == "official_price" and obs.raw_text:
                candidates = scanner.scan_from_html(
                    obs.raw_text, obs.source_id, "", brand="RICOH"
                )
                saved = scanner.save_candidates(candidates)
                total_found += saved

        click.echo(f"Found {total_found} new candidates.")
        if total_found == 0:
            click.echo("(Run test-official first to collect data for scanning)")
    finally:
        db.close()


@cli.command("list-product-candidates")
@click.option("--status", "-s", default=None, help="pending / approved / rejected")
def list_product_candidates(status):
    """新製品候補一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        candidates = repo.list_product_candidates(status=status)
        if not candidates:
            click.echo("No product candidates found.")
            return
        click.echo(f"\n{'='*90}\n 新製品候補 ({len(candidates)} 件)\n{'='*90}")
        click.echo(f"  {'Status':<10} {'Brand':<10} {'Name':<35} {'Keyword':<15} {'Price':>10} {'Source':<15}")
        click.echo(f"  {'─'*86}")
        for c in candidates:
            price = f"¥{c.estimated_price:,}" if c.estimated_price else "---"
            click.echo(
                f"  {c.status:<10} {c.brand:<10} {c.product_name[:33]:<35} "
                f"{c.detected_keyword:<15} {price:>10} {c.source_id:<15}"
            )
            click.echo(f"    ID: {c.id}")
        click.echo(f"\n{'='*90}\n")
    finally:
        db.close()


@cli.command("approve-product-candidate")
@click.option("--candidate-id", required=True)
@click.option("--product-id", default=None, help="紐付けるproduct ID（新規作成する場合は省略）")
def approve_candidate(candidate_id, product_id):
    """新製品候補を承認する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        repo.update_product_candidate_status(candidate_id, "approved", product_id)
        click.echo(f"Approved: {candidate_id}")
        if product_id:
            click.echo(f"  Linked to: {product_id}")
        else:
            click.echo("  (No product linked. Add manually with products.yaml + seed)")
    finally:
        db.close()


@cli.command("reject-product-candidate")
@click.option("--candidate-id", required=True)
def reject_candidate(candidate_id):
    """新製品候補を却下する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        repo.update_product_candidate_status(candidate_id, "rejected")
        click.echo(f"Rejected: {candidate_id}")
    finally:
        db.close()


# ---- Phase 5: 自動巡回 ----

@cli.command("run-once")
def run_once():
    """全体を1回実行（official→stock→price→score→dispatch→scan）。"""
    from src.orchestrator import Orchestrator
    click.echo("=== run-once START ===")
    orch = Orchestrator()
    results = orch.run_once()
    orch.close()
    click.echo(f"\n=== run-once DONE ===")
    click.echo(f"  Official:    {results['official']} observations")
    click.echo(f"  Stock:       {results['stock']} observations")
    click.echo(f"  Price:       {results['price']} observations")
    click.echo(f"  Scored:      {results['scored']} alerts")
    click.echo(f"  Dispatched:  {results['dispatched']} alerts sent")
    click.echo(f"  Candidates:  {results['candidates']} new")
    click.echo(f"  Errors:      {results['errors']}")


@cli.command("run-stock-check")
def run_stock_check():
    """在庫・抽選系Collectorのみ実行。"""
    from src.orchestrator import Orchestrator
    click.echo("Running stock check...")
    orch = Orchestrator()
    r = orch.run_stock_check()
    orch.close()
    click.echo(f"  Success: {r['success']}, Errors: {r['errors']}, Skipped: {r['skipped']}")


@cli.command("run-price-check")
def run_price_check():
    """価格・相場系Collectorのみ実行。"""
    from src.orchestrator import Orchestrator
    click.echo("Running price check...")
    orch = Orchestrator()
    r = orch.run_price_check()
    orch.close()
    click.echo(f"  Success: {r['success']}, Errors: {r['errors']}, Skipped: {r['skipped']}")


@cli.command("run-product-scan")
def run_product_scan():
    """新製品候補スキャンのみ実行。"""
    from src.orchestrator import Orchestrator
    click.echo("Running product scan...")
    orch = Orchestrator()
    n = orch.run_product_scan()
    orch.close()
    click.echo(f"  New candidates: {n}")


@cli.command("dispatch-pending")
def dispatch_pending():
    """未送信S/Aアラートを通知送信。"""
    from src.orchestrator import Orchestrator
    click.echo("Dispatching pending alerts...")
    orch = Orchestrator()
    n = orch.run_dispatch()
    orch.close()
    click.echo(f"  Dispatched: {n} alerts")


@cli.command("start-scheduler")
def start_scheduler_cmd():
    """APSchedulerを起動して常駐する（Ctrl+Cで停止）。"""
    from src.scheduler import start_scheduler
    click.echo("Starting scheduler (Ctrl+C to stop)...")
    click.echo("Jobs: stock(15min), price(60min), score(15min), dispatch(5min), scan(3h)")
    start_scheduler()


@cli.command("scheduler-status")
def scheduler_status():
    """スケジューラの実行状態を表示する。"""
    from src.scheduler import get_scheduler_status
    status = get_scheduler_status()

    running = status.get("scheduler_running", False)
    click.echo(f"\n{'='*60}")
    click.echo(f" Scheduler: {'🟢 RUNNING' if running else '🔴 STOPPED'}")
    click.echo(f" Updated:   {status.get('updated_at', 'N/A')}")
    click.echo(f"{'='*60}")

    jobs = status.get("jobs", {})
    if jobs:
        click.echo(f"\n  {'Job':<20} {'Status':<10} {'Last Run':<25} Details")
        click.echo(f"  {'─'*70}")
        for name, info in jobs.items():
            if name.startswith("_"):
                continue
            s = info.get("status", "?")
            icon = "✅" if s == "success" else "❌" if s == "error" else "⏳"
            click.echo(
                f"  {name:<20} {icon} {s:<8} {info.get('last_run', 'N/A'):<25} "
                f"{info.get('details', '')}"
            )
    else:
        click.echo("\n  No job history. Run 'start-scheduler' or 'run-once' first.")

    # ヘルスチェック
    click.echo(f"\n  Source Health:")
    db = _get_db()
    try:
        db.init_schema()
        rows = db.connection.execute(
            """SELECT h.source_id, h.consecutive_errors, h.auto_disabled,
                      h.last_success_at, h.last_error_at
               FROM source_health h
               INNER JOIN sources s ON s.id = h.source_id
               ORDER BY h.source_id"""
        ).fetchall()
        if rows:
            for r in rows:
                icon = "⚠️" if r["auto_disabled"] else ("❌" if r["consecutive_errors"] >= 3 else "✅")
                click.echo(
                    f"    {icon} {r['source_id']:<25} errors={r['consecutive_errors']} "
                    f"disabled={'Yes' if r['auto_disabled'] else 'No'}"
                )
        else:
            click.echo("    No health data yet.")
    finally:
        db.close()

    click.echo(f"\n{'='*60}\n")


# ---- Phase 6: 速報コンテンツ ----

@cli.command("generate-posts")
def generate_posts():
    """S/Aアラートからチャネル別投稿テンプレートを生成する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.publish.template_generator import TemplateGenerator
        gen = TemplateGenerator(repository=repo)

        items = gen.generate_from_alerts()
        items += gen.generate_from_candidates()

        for item in items:
            repo.insert_publish_item(item)

        click.echo(f"Generated {len(items)} posts:")
        by_ch = {}
        for i in items:
            by_ch[i.channel] = by_ch.get(i.channel, 0) + 1
        for ch, n in sorted(by_ch.items()):
            click.echo(f"  {ch}: {n}")
    finally:
        db.close()


@cli.command("list-publish-queue")
@click.option("--channel", "-c", default=None, help="x/threads/line/discord/note")
@click.option("--status", "-s", default=None, help="draft/approved/published/rejected")
@click.option("--limit", "-n", default=20)
def list_publish_queue(channel, status, limit):
    """投稿キュー一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        items = repo.list_publish_queue(channel=channel, status=status, limit=limit)
        if not items:
            click.echo("No items in publish queue.")
            return
        click.echo(f"\n{'='*90}\n 投稿キュー ({len(items)} 件)\n{'='*90}")
        for i in items:
            icon = {"draft": "📝", "approved": "✅", "published": "📤", "rejected": "❌"}.get(i.status, "❓")
            click.echo(f"  {icon} [{i.channel:>8}] [{i.rank or '-'}] {i.title[:50]}")
            click.echo(f"    ID: {i.id}  status: {i.status}  {i.generated_at.strftime('%Y-%m-%d %H:%M')}")
        click.echo(f"\n{'='*90}\n")
    finally:
        db.close()


@cli.command("show-publish-item")
@click.option("--item-id", required=True)
def show_publish_item(item_id):
    """投稿アイテムの詳細を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        item = repo.get_publish_item(item_id)
        if not item:
            click.echo(f"Item not found: {item_id}")
            sys.exit(1)
        click.echo(f"\n{'='*60}")
        click.echo(f"ID:      {item.id}")
        click.echo(f"Channel: {item.channel}")
        click.echo(f"Rank:    {item.rank or '---'}")
        click.echo(f"Status:  {item.status}")
        click.echo(f"Title:   {item.title}")
        click.echo(f"Tags:    {item.hashtags}")
        click.echo(f"{'='*60}")
        click.echo(item.body)
        click.echo(f"{'='*60}\n")
    finally:
        db.close()


@cli.command("approve-publish-item")
@click.option("--item-id", required=True)
def approve_publish_item(item_id):
    """投稿アイテムを承認する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        repo.update_publish_item_status(item_id, "approved")
        click.echo(f"✅ Approved: {item_id}")
    finally:
        db.close()


@cli.command("reject-publish-item")
@click.option("--item-id", required=True)
def reject_publish_item(item_id):
    """投稿アイテムを却下する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        repo.update_publish_item_status(item_id, "rejected")
        click.echo(f"❌ Rejected: {item_id}")
    finally:
        db.close()


@cli.command("generate-weekly-report")
def generate_weekly_report():
    """過去7日間の週間レポートを生成する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.publish.report_generator import ReportGenerator
        gen = ReportGenerator(repository=repo)
        item = gen.generate_weekly_report()
        repo.insert_publish_item(item)
        click.echo(f"Weekly report generated:")
        click.echo(f"  ID: {item.id}")
        click.echo(f"  Title: {item.title}")
        click.echo(f"  Channel: {item.channel}")
        click.echo(f"\nPreview (first 500 chars):")
        click.echo(item.body[:500])
        click.echo("...")
    finally:
        db.close()


# ---- Phase 7A: 市場横断比較 ----

@cli.command("scan-category")
@click.option("--category", "-c", required=True, help="camera/apple/game/pc/all")
def scan_category(category):
    """カテゴリ内全商品の市場比較を実行し、プレ値候補を検出する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.market.category_scanner import CategoryScanner
        scanner = CategoryScanner(repository=repo)
        result = scanner.scan(category=category)

        click.echo(f"\n{'='*90}")
        click.echo(f" カテゴリスキャン: {category}")
        click.echo(f" 商品数: {result['total_products']} / プレ値候補: {result['premium_candidates']}")
        click.echo(f"{'='*90}")

        for snap in result["snapshots"]:
            prem = f"+{snap.premium_gap_percent}%" if snap.premium_gap_percent else "---"
            method = snap.sale_method or "---"
            click.echo(
                f"  {snap.product_name[:30]:<32} "
                f"official=¥{snap.official_price_jpy or 0:>8,} "
                f"used=¥{snap.domestic_used_price_jpy or 0:>8,} "
                f"buyback=¥{snap.domestic_buyback_price_jpy or 0:>8,} "
                f"prem={prem:>7} method={method:<10} "
                f"score={snap.overall_score:.2f}"
            )

        if result["detected"]:
            click.echo(f"\n  {'─'*80}")
            click.echo(f"  プレ値候補:")
            for d in result["detected"]:
                snap = d["snapshot"]
                click.echo(f"    ★ {snap.product_name} (score={snap.overall_score:.2f})")
                for r in d["reasons"]:
                    click.echo(f"      - {r}")

        click.echo(f"\n{'='*90}\n")
    finally:
        db.close()


@cli.command("compare-market")
@click.option("--product", "-p", default=None, help="商品 (例: gr4)")
@click.option("--candidate-id", default=None, help="候補ID")
@click.option("--user-level", "-u", default=None, help="beginner/advanced")
def compare_market(product, candidate_id, user_level):
    """商品の市場横断比較を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.market.comparator import MarketComparator
        comp = MarketComparator(repository=repo)

        if product:
            pid = _resolve_product_id(product)
            prod = repo.get_product(pid)
            if not prod:
                click.echo(f"Product not found: {pid}")
                sys.exit(1)
            snap = comp.compare_product(prod)
        elif user_level:
            # user_levelのみ指定 → 該当レベルの全snapshots表示
            snaps = repo.list_market_snapshots(user_level=user_level, limit=30)
            if not snaps:
                click.echo(f"No snapshots for user_level={user_level}. Run 'scan-category --category all' first.")
                return
            level_label = "初心者向け" if user_level == "beginner" else "上級者向け"
            click.echo(f"\n{'='*110}")
            click.echo(f" 市場比較 [{level_label}] ({len(snaps)} 件)")
            click.echo(f"{'='*110}")
            click.echo(
                f"  {'商品':<30} {'定価':>10} {'買取':>10} {'中古':>10} {'利益':>10} "
                f"{'難易度':>6} {'初心者':>6} {'Level':<20} {'Action':<15}"
            )
            click.echo(f"  {'─'*105}")
            for s in snaps:
                profit = ""
                if s.official_price_jpy and s.domestic_buyback_price_jpy and s.domestic_buyback_price_jpy > s.official_price_jpy:
                    profit = f"+¥{s.domestic_buyback_price_jpy - s.official_price_jpy:,}"
                elif s.premium_gap_jpy:
                    profit = f"+¥{s.premium_gap_jpy:,}"
                click.echo(
                    f"  {s.product_name[:28]:<30} "
                    f"¥{s.official_price_jpy or 0:>8,} "
                    f"¥{s.domestic_buyback_price_jpy or 0:>8,} "
                    f"¥{s.domestic_used_price_jpy or 0:>8,} "
                    f"{profit:>10} "
                    f"{s.difficulty_score:>6.2f} "
                    f"{s.beginner_score:>6.2f} "
                    f"{s.user_level:<20} "
                    f"{s.recommended_action:<15}"
                )
            click.echo(f"\n{'='*110}\n")
            return
        else:
            click.echo("--product or --user-level required")
            sys.exit(1)

        click.echo(f"\n{'='*60}")
        click.echo(f" 市場比較: {snap.product_name}")
        click.echo(f"{'='*60}")
        click.echo(f"  カテゴリ:     {snap.category}")
        click.echo(f"  ブランド:     {snap.brand}")
        click.echo(f"  公式定価:     ¥{snap.official_price_jpy:,}" if snap.official_price_jpy else "  公式定価:     不明")
        click.echo(f"  国内中古:     ¥{snap.domestic_used_price_jpy:,}" if snap.domestic_used_price_jpy else "  国内中古:     データなし")
        click.echo(f"  国内買取:     ¥{snap.domestic_buyback_price_jpy:,}" if snap.domestic_buyback_price_jpy else "  国内買取:     データなし")
        click.echo(f"  海外(JPY):    ¥{snap.overseas_price_jpy:,}" if snap.overseas_price_jpy else "  海外:         データなし")
        click.echo(f"  プレ値差額:   +¥{snap.premium_gap_jpy:,} (+{snap.premium_gap_percent}%)" if snap.premium_gap_jpy else "  プレ値差額:   なし")
        click.echo(f"  在庫:         {snap.stock_status or '不明'}")
        click.echo(f"  販売方式:     {snap.sale_method}")
        click.echo(f"\n  --- スコア ---")
        click.echo(f"  premium:     {snap.premium_score:.2f}")
        click.echo(f"  scarcity:    {snap.scarcity_score:.2f}")
        click.echo(f"  liquidity:   {snap.liquidity_score:.2f}")
        click.echo(f"  overseas:    {snap.overseas_gap_score:.2f}")
        click.echo(f"  confidence:  {snap.source_confidence:.2f}")
        click.echo(f"  OVERALL:     {snap.overall_score:.2f}")
        click.echo(f"\n  --- 初心者/上級者評価 ---")
        click.echo(f"  beginner:    {snap.beginner_score:.2f}")
        click.echo(f"  difficulty:  {snap.difficulty_score:.2f}")
        click.echo(f"  beg_profit:  {snap.beginner_profit_score:.2f}")
        click.echo(f"  user_level:  {snap.user_level or '未分類'}")
        click.echo(f"  action:      {snap.recommended_action or '---'}")
        click.echo(f"\n{'='*60}\n")
    finally:
        db.close()


@cli.command("list-market-snapshots")
@click.option("--category", "-c", default=None)
@click.option("--limit", "-n", default=30)
def list_market_snapshots(category, limit):
    """市場比較スナップショット一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        snaps = repo.list_market_snapshots(category=category, limit=limit)
        if not snaps:
            click.echo("No snapshots. Run 'scan-category' first.")
            return
        click.echo(f"\n{'='*100}")
        click.echo(f"  {'Product':<30} {'Official':>10} {'Used':>10} {'Buyback':>10} {'Prem%':>7} {'Method':<10} {'Score':>6}")
        click.echo(f"  {'─'*95}")
        for s in snaps:
            prem = f"+{s.premium_gap_percent}%" if s.premium_gap_percent else "---"
            click.echo(
                f"  {s.product_name[:28]:<30} "
                f"¥{s.official_price_jpy or 0:>8,} "
                f"¥{s.domestic_used_price_jpy or 0:>8,} "
                f"¥{s.domestic_buyback_price_jpy or 0:>8,} "
                f"{prem:>7} {s.sale_method:<10} {s.overall_score:>6.2f}"
            )
        click.echo(f"\n{'='*100}\n")
    finally:
        db.close()


@cli.command("list-premium-candidates")
@click.option("--limit", "-n", default=30)
def list_premium_candidates(limit):
    """プレ値候補一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        snaps = repo.list_premium_candidates_with_snapshots(limit=limit)
        if not snaps:
            click.echo("No premium candidates. Run 'scan-category --category all' first.")
            return
        click.echo(f"\n{'='*100}")
        click.echo(f" プレ値候補 ({len(snaps)} 件)")
        click.echo(f"{'='*100}")
        for s in snaps:
            prem = f"+{s.premium_gap_percent}%" if s.premium_gap_percent else "---"
            click.echo(
                f"  ★ {s.product_name[:30]:<32} official=¥{s.official_price_jpy or 0:>8,} "
                f"prem={prem:>7} method={s.sale_method:<10} overall={s.overall_score:.2f}"
            )
        click.echo(f"\n{'='*100}\n")
    finally:
        db.close()


@cli.command("approve-premium-candidate")
@click.option("--candidate-id", required=True)
def approve_premium_candidate(candidate_id):
    """プレ値候補を承認する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        repo.update_product_candidate_status(candidate_id, "approved")
        click.echo(f"✅ Approved: {candidate_id}")
    finally:
        db.close()


# ---- Phase 7B-2: 初心者向け/上級者向け候補 ----

@cli.command("list-beginner-candidates")
@click.option("--limit", "-n", default=30)
def list_beginner_candidates(limit):
    """初心者向けプレ値候補一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        snaps = repo.list_premium_candidates_with_snapshots(limit=limit, user_level="beginner")
        if not snaps:
            click.echo("初心者向け候補なし。'scan-category --category all' を実行してください。")
            return

        click.echo(f"\n{'='*110}")
        click.echo(f" 初心者向けプレ値候補 ({len(snaps)} 件)")
        click.echo(f"{'='*110}")
        click.echo(
            f"  {'商品':<30} {'定価':>10} {'買取':>10} {'想定利益':>10} "
            f"{'難易度':>6} {'初心者':>6} {'Level':<16} {'Action':<15}"
        )
        click.echo(f"  {'─'*105}")
        for s in snaps:
            profit = ""
            if s.official_price_jpy and s.domestic_buyback_price_jpy and s.domestic_buyback_price_jpy > s.official_price_jpy:
                profit = f"+¥{s.domestic_buyback_price_jpy - s.official_price_jpy:,}"
            icon = "🟢" if s.user_level == "beginner_easy" else "🟡"
            click.echo(
                f"  {icon} {s.product_name[:28]:<28} "
                f"¥{s.official_price_jpy or 0:>8,} "
                f"¥{s.domestic_buyback_price_jpy or 0:>8,} "
                f"{profit:>10} "
                f"{s.difficulty_score:>6.2f} "
                f"{s.beginner_score:>6.2f} "
                f"{s.user_level:<16} "
                f"{s.recommended_action:<15}"
            )
        click.echo(f"\n{'='*110}\n")
    finally:
        db.close()


@cli.command("list-advanced-candidates")
@click.option("--limit", "-n", default=30)
def list_advanced_candidates(limit):
    """上級者向けプレ値候補一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        snaps = repo.list_premium_candidates_with_snapshots(limit=limit, user_level="advanced")
        if not snaps:
            click.echo("上級者向け候補なし。'scan-category --category all' を実行してください。")
            return

        click.echo(f"\n{'='*110}")
        click.echo(f" 上級者向けプレ値候補 ({len(snaps)} 件)")
        click.echo(f"{'='*110}")
        click.echo(
            f"  {'商品':<30} {'定価':>10} {'中古':>10} {'プレ値差':>10} "
            f"{'難易度':>6} {'方式':<10} {'Level':<22} {'Action':<15}"
        )
        click.echo(f"  {'─'*105}")
        for s in snaps:
            prem = f"+¥{s.premium_gap_jpy:,}" if s.premium_gap_jpy else "---"
            method = s.sale_method or "---"
            icon = "🔴" if s.user_level == "expert_only" else "🟠"
            click.echo(
                f"  {icon} {s.product_name[:28]:<28} "
                f"¥{s.official_price_jpy or 0:>8,} "
                f"¥{s.domestic_used_price_jpy or 0:>8,} "
                f"{prem:>10} "
                f"{s.difficulty_score:>6.2f} "
                f"{method:<10} "
                f"{s.user_level:<22} "
                f"{s.recommended_action:<15}"
            )
        click.echo(f"\n{'='*110}\n")
    finally:
        db.close()


# ---- Phase 7B: CSVインポート・海外/フリマ表示 ----

@cli.command("import-market-csv")
@click.option("--file", "-f", "filepath", required=True, help="CSVファイルパス")
def import_market_csv(filepath):
    """市場価格CSVをインポートする。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.market.csv_importer import CSVImporter
        imp = CSVImporter(repository=repo)
        result = imp.import_file(str(PROJECT_ROOT / filepath) if not filepath.startswith("/") else filepath)
        click.echo(f"\nCSV Import Results:")
        click.echo(f"  Imported: {result['imported']}")
        click.echo(f"  Skipped:  {result['skipped']}")
        if result["errors"]:
            click.echo(f"  Errors:")
            for e in result["errors"]:
                click.echo(f"    {e}")
    finally:
        db.close()


@cli.command("list-overseas-prices")
@click.option("--limit", "-n", default=20)
def list_overseas_prices(limit):
    """海外価格一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        records = repo.list_price_history(price_type="overseas", limit=limit)
        if not records:
            click.echo("No overseas prices. Import via CSV or run eBay collector.")
            return
        click.echo(f"\n{'='*70}\n 海外価格 ({len(records)} 件)\n{'='*70}")
        for r in records:
            click.echo(f"  {r.recorded_at.strftime('%Y-%m-%d %H:%M'):<18} {r.product_id:<22} {r.source_id:<15} ¥{r.price:>10,}")
        click.echo(f"\n{'='*70}\n")
    finally:
        db.close()


@cli.command("list-flea-market-prices")
@click.option("--limit", "-n", default=20)
def list_flea_market_prices(limit):
    """フリマ/中古価格一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        records = repo.list_price_history(price_type="used", limit=limit)
        if not records:
            click.echo("No used prices.")
            return
        click.echo(f"\n{'='*70}\n 中古/フリマ価格 ({len(records)} 件)\n{'='*70}")
        for r in records:
            click.echo(f"  {r.recorded_at.strftime('%Y-%m-%d %H:%M'):<18} {r.product_id:<22} {r.source_id:<15} ¥{r.price:>10,}")
        click.echo(f"\n{'='*70}\n")
    finally:
        db.close()


# ---- Phase 8: 品質チェック・整備 ----

@cli.command("validate-data")
def validate_data_cmd():
    """データ整合性チェックを実行する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.pipeline.quality_checker import QualityChecker
        checker = QualityChecker(repository=repo)
        results = checker.validate_data()

        errors = [r for r in results if r["level"] == "error"]
        warnings = [r for r in results if r["level"] == "warning"]
        oks = [r for r in results if r["level"] == "ok"]

        click.echo(f"\n{'='*90}")
        click.echo(f" データ整合性チェック")
        click.echo(f"{'='*90}")

        if errors:
            click.echo(f"\n  ❌ ERRORS ({len(errors)} 件):")
            for r in errors:
                click.echo(f"    [{r['category']}] {r['message']}")

        if warnings:
            click.echo(f"\n  ⚠️  WARNINGS ({len(warnings)} 件):")
            for r in warnings:
                click.echo(f"    [{r['category']}] {r['message']}")

        if not errors and not warnings:
            click.echo(f"\n  ✅ データ整合性に問題なし")

        click.echo(f"\n  --- サマリ ---")
        click.echo(f"  Errors:   {len(errors)}")
        click.echo(f"  Warnings: {len(warnings)}")
        click.echo(f"  OK:       {len(oks)}")

        # beginner / advanced 品質チェックも実行
        beginner_results = checker.check_beginner_quality()
        advanced_results = checker.check_advanced_quality()

        b_issues = [r for r in beginner_results if r["level"] != "ok"]
        a_issues = [r for r in advanced_results if r["level"] != "ok"]

        if b_issues:
            click.echo(f"\n  ⚠️  初心者向け品質問題 ({len(b_issues)} 件):")
            for r in b_issues:
                click.echo(f"    {r['message']}")
                if r.get("should_downgrade"):
                    click.echo(f"      → beginner_watch への降格推奨")

        if a_issues:
            click.echo(f"\n  ⚠️  上級者向け品質問題 ({len(a_issues)} 件):")
            for r in a_issues:
                click.echo(f"    {r['message']}")

        b_ok = [r for r in beginner_results if r["level"] == "ok"]
        a_ok = [r for r in advanced_results if r["level"] == "ok"]
        if b_ok:
            click.echo(f"\n  ✅ 初心者向け品質OK: {len(b_ok)} 件")
        if a_ok:
            click.echo(f"  ✅ 上級者向け品質OK: {len(a_ok)} 件")

        click.echo(f"\n{'='*90}\n")
    finally:
        db.close()


@cli.command("recalc-market-scores")
@click.option("--fix-downgrade", is_flag=True, help="beginner_easy品質不足をbeginner_watchに降格する")
def recalc_market_scores(fix_downgrade):
    """既存market_snapshotsのスコアを再計算する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.market.comparator import MarketComparator
        comp = MarketComparator(repository=repo)

        snapshots = repo.list_all_market_snapshots_raw(limit=500)
        if not snapshots:
            click.echo("market_snapshotsなし。scan-category を実行してください。")
            return

        click.echo(f"\n{'='*90}")
        click.echo(f" スコア再計算: {len(snapshots)} 件")
        click.echo(f"{'='*90}")

        updated = 0
        for snap in snapshots:
            # product情報を取得してスコア再計算
            product = repo.get_product(snap.product_id) if snap.product_id else None
            if not product:
                continue

            new_snap = comp.compare_product(product)
            # 既存snapshotのスコアを更新
            repo.update_market_snapshot_scores(
                snap.id,
                premium_score=new_snap.premium_score,
                scarcity_score=new_snap.scarcity_score,
                liquidity_score=new_snap.liquidity_score,
                overseas_gap_score=new_snap.overseas_gap_score,
                source_confidence=new_snap.source_confidence,
                overall_score=new_snap.overall_score,
                beginner_score=new_snap.beginner_score,
                difficulty_score=new_snap.difficulty_score,
                beginner_profit_score=new_snap.beginner_profit_score,
                user_level=new_snap.user_level,
                recommended_action=new_snap.recommended_action,
            )
            updated += 1

            old_level = snap.user_level or "---"
            new_level = new_snap.user_level or "---"
            changed = " ← CHANGED" if old_level != new_level else ""
            click.echo(
                f"  {product.name[:30]:<32} "
                f"overall={new_snap.overall_score:.2f} "
                f"level={new_level:<22} "
                f"action={new_snap.recommended_action:<15}{changed}"
            )

        # beginner品質チェック & 降格
        if fix_downgrade:
            from src.pipeline.quality_checker import QualityChecker
            checker = QualityChecker(repository=repo)
            beginner_results = checker.check_beginner_quality()
            downgraded = 0
            for r in beginner_results:
                if r.get("should_downgrade"):
                    repo.update_market_snapshot_scores(
                        r["snapshot_id"],
                        user_level="beginner_watch",
                        recommended_action="check_buyback",
                    )
                    click.echo(f"  ↓ {r['product_name']}: beginner_easy → beginner_watch (降格)")
                    downgraded += 1
            if downgraded:
                click.echo(f"\n  降格: {downgraded} 件")

        click.echo(f"\n  再計算完了: {updated} 件更新")
        click.echo(f"{'='*90}\n")
    finally:
        db.close()


@cli.command("validate-publish-text")
def validate_publish_text_cmd():
    """投稿テンプレートの禁止表現チェック。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.pipeline.quality_checker import QualityChecker
        checker = QualityChecker(repository=repo)
        results = checker.validate_publish_text()

        errors = [r for r in results if r["level"] == "error"]
        oks = [r for r in results if r["level"] == "ok"]

        click.echo(f"\n{'='*90}")
        click.echo(f" 投稿テンプレート安全チェック")
        click.echo(f"{'='*90}")

        if errors:
            click.echo(f"\n  ❌ 禁止表現検出 ({len(errors)} 件):")
            for r in errors:
                click.echo(f"    item_id:  {r['item_id']}")
                click.echo(f"    channel:  {r['channel']}")
                click.echo(f"    phrase:   {r['forbidden_phrase']}")
                click.echo(f"    抜粋:     ...{r['excerpt']}...")
                click.echo("")
        else:
            for r in oks:
                click.echo(f"\n  ✅ {r['message']}")

        click.echo(f"\n{'='*90}\n")
    finally:
        db.close()


# ---- Phase 9A: 初心者向け案件・買取比較 ----

@cli.command("import-buyback-csv")
@click.option("--file", "-f", "filepath", required=True, help="買取価格CSVファイルパス")
def import_buyback_csv(filepath):
    """買取価格CSVをインポートする。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.market.buyback_csv_importer import BuybackCSVImporter
        imp = BuybackCSVImporter(repository=repo)
        path = str(PROJECT_ROOT / filepath) if not filepath.startswith("/") else filepath
        result = imp.import_file(path)
        click.echo(f"\nBuyback CSV Import:")
        click.echo(f"  Imported: {result['imported']}")
        click.echo(f"  Skipped:  {result['skipped']}")
        if result["errors"]:
            for e in result["errors"][:5]:
                click.echo(f"    {e}")
    finally:
        db.close()


@cli.command("scan-beginner-deals")
@click.option("--category", "-c", default=None, help="カテゴリ (iphone/game_console/camera/all)")
def scan_beginner_deals(category):
    """初心者向け案件をスキャンする。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.market.beginner_deal_scanner import BeginnerDealScanner
        scanner = BeginnerDealScanner(repository=repo)
        deals = scanner.scan_all(category=category if category != "all" else None)

        click.echo(f"\n{'='*110}")
        click.echo(f" 初心者向け案件スキャン ({len(deals)} 件)")
        click.echo(f"{'='*110}")

        if not deals:
            click.echo("  案件なし。買取価格データをインポートしてください。")
            click.echo("  python -m src.cli import-buyback-csv --file data/manual_buyback_prices.csv")
        else:
            click.echo(
                f"  {'商品':<32} {'定価':>10} {'最高買取':>10} {'粗利':>10} "
                f"{'コスト':>8} {'実質利益':>10} {'利益率':>6} {'Level':<16} {'買取店':<14}"
            )
            click.echo(f"  {'─'*108}")
            for d in deals:
                rate = f"{d.net_profit_rate:.1%}" if d.net_profit_rate else "---"
                click.echo(
                    f"  {d.product_name[:30]:<32} "
                    f"¥{d.official_price_jpy or 0:>8,} "
                    f"¥{d.best_buyback_price or 0:>8,} "
                    f"+¥{d.gross_profit_jpy:>7,} "
                    f"-¥{d.estimated_costs_jpy:>5,} "
                    f"+¥{d.net_profit_jpy:>7,} "
                    f"{rate:>6} "
                    f"{d.user_level:<16} "
                    f"{d.best_buyback_shop:<14}"
                )

        beginner = [d for d in deals if d.user_level in ("beginner_easy", "beginner_watch")]
        advanced = [d for d in deals if d.user_level in ("advanced_high_profit", "expert_only")]
        click.echo(f"\n  beginner: {len(beginner)} | advanced: {len(advanced)}")
        click.echo(f"{'='*110}\n")
    finally:
        db.close()


@cli.command("list-beginner-deals")
@click.option("--min-profit", "-m", default=0, help="最低利益額")
@click.option("--category", "-c", default=None)
@click.option("--limit", "-n", default=30)
def list_beginner_deals(min_profit, category, limit):
    """初心者向け案件一覧を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        deals = repo.list_beginner_deals(
            user_level="beginner", category=category,
            min_profit=min_profit, limit=limit,
        )
        if not deals:
            click.echo("初心者向け案件なし。'scan-beginner-deals' を実行してください。")
            return

        click.echo(f"\n{'='*120}")
        click.echo(f" 初心者向け案件 ({len(deals)} 件)")
        click.echo(f"{'='*120}")
        click.echo(
            f"  {'商品':<32} {'定価':>10} {'買取':>10} {'実質利益':>10} {'利益率':>6} "
            f"{'Level':<16} {'Action':<15} {'買取店':<14} {'条件':<16}"
        )
        click.echo(f"  {'─'*118}")
        for d in deals:
            icon = "🟢" if d.user_level == "beginner_easy" else "🟡"
            rate = f"{d.net_profit_rate:.1%}" if d.net_profit_rate else "---"
            click.echo(
                f"  {icon} {d.product_name[:29]:<30} "
                f"¥{d.official_price_jpy or 0:>8,} "
                f"¥{d.best_buyback_price or 0:>8,} "
                f"+¥{d.net_profit_jpy:>7,} "
                f"{rate:>6} "
                f"{d.user_level:<16} "
                f"{d.recommended_action:<15} "
                f"{d.best_buyback_shop:<14} "
                f"{d.buyback_condition:<16}"
            )
        click.echo(f"\n{'='*120}\n")
    finally:
        db.close()


@cli.command("compare-buyback")
@click.option("--product", "-p", default=None, help="商品 (例: iphone17pro256)")
@click.option("--category", "-c", default=None, help="カテゴリ (例: iphone)")
def compare_buyback(product, category):
    """買取価格を複数店舗で比較する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.market.beginner_deal_scanner import BeginnerDealScanner
        scanner = BeginnerDealScanner(repository=repo)

        if product:
            pid = _resolve_product_id(product)
            prod = repo.get_product(pid)
            if not prod:
                click.echo(f"Product not found: {pid}")
                sys.exit(1)
            products = [prod]
        elif category:
            products = [p for p in repo.list_products() if p.genre == category]
        else:
            click.echo("--product or --category required")
            sys.exit(1)

        for prod in products:
            official = prod.official_price or prod.retail_price or 0
            results = scanner.compare_buyback(prod)

            if not results:
                click.echo(f"\n  {prod.name}: 買取データなし")
                continue

            click.echo(f"\n{'='*90}")
            click.echo(f" 買取比較: {prod.name} (公式: ¥{official:,})")
            click.echo(f"{'='*90}")
            click.echo(
                f"  {'買取店':<18} {'買取価格':>10} {'条件':<18} {'粗利':>10} "
                f"{'実質利益':>10} {'利益率':>6}"
            )
            click.echo(f"  {'─'*85}")
            for r in results:
                rate = f"{r['net_rate']:.1%}" if r['net_rate'] > 0 else "---"
                gross = f"+¥{r['gross_profit']:,}" if r['gross_profit'] > 0 else "---"
                net = f"+¥{r['net_profit']:,}" if r['net_profit'] > 0 else "---"
                click.echo(
                    f"  {r['shop_name']:<18} "
                    f"¥{r['buyback_price']:>8,} "
                    f"{r['condition']:<18} "
                    f"{gross:>10} "
                    f"{net:>10} "
                    f"{rate:>6}"
                )
            click.echo(f"{'='*90}")

    finally:
        db.close()


@cli.command("refresh-buyback-prices")
@click.option("--product", "-p", default=None)
def refresh_buyback_prices(product):
    """買取価格を再取得する（Collector経由）。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)

        products = repo.list_products()
        if product:
            pid = _resolve_product_id(product)
            products = [p for p in products if p.id == pid]

        # Collectorで取得を試みる
        from src.collectors.buyback.mobile_ichiban import MobileIchibanCollector
        from src.collectors.buyback.kaitori_shouten import KaitoriShoutenCollector
        from src.collectors.buyback.iosys_buyback import IosysBuybackCollector

        collectors = [
            MobileIchibanCollector(),
            KaitoriShoutenCollector(),
            IosysBuybackCollector(),
        ]

        total = 0
        for prod in products:
            for coll in collectors:
                try:
                    result = coll.collect(prod)
                    if result:
                        repo.insert_buyback_price(result)
                        total += 1
                        click.echo(f"  {coll.SHOP_NAME} x {prod.name}: ¥{result.buyback_price:,}")
                except Exception as e:
                    logger.debug("Collector error: %s", e)

        click.echo(f"\n  取得完了: {total} 件")
        if total == 0:
            click.echo("  (Collectorでの自動取得はサイト構造に依存します)")
            click.echo("  CSVインポートを推奨: python -m src.cli import-buyback-csv --file data/manual_buyback_prices.csv")
    finally:
        db.close()


# ---- Phase 10: 販売導線コンテンツ生成 ----

@cli.command("generate-note-report")
@click.option("--type", "-t", "report_type", default="beginner", help="beginner/advanced/weekly")
def generate_note_report(report_type):
    """note販売用Markdown記事を生成する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.content.note_generator import NoteGenerator
        gen = NoteGenerator(repository=repo)
        result = gen.generate(report_type=report_type)

        click.echo(f"\n{'='*60}")
        click.echo(f" note記事生成: {report_type}")
        click.echo(f"{'='*60}")
        click.echo(f"  MD:   {result['md_path']}")
        click.echo(f"  TXT:  {result['txt_path']}")
        click.echo(f"  文字数: {result['char_count']:,}")
        if result["forbidden_found"]:
            click.echo(f"  ⚠️ 禁止表現を自動置換: {result['forbidden_found']}")
        else:
            click.echo(f"  ✅ 禁止表現なし")
        click.echo(f"\n--- プレビュー (先頭500文字) ---")
        click.echo(result["content"][:500])
        click.echo(f"...\n{'='*60}\n")
    finally:
        db.close()


@cli.command("generate-lp-copy")
def generate_lp_copy():
    """LP用コピー素材を生成する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.content.lp_generator import LPGenerator
        gen = LPGenerator(repository=repo)
        result = gen.generate()

        click.echo(f"\n{'='*60}")
        click.echo(f" LPコピー生成")
        click.echo(f"{'='*60}")
        click.echo(f"  出力: {result['path']}")
        click.echo(f"  文字数: {result['char_count']:,}")
        click.echo(f"  セクション: {list(result['sections'].keys())}")
        if result["forbidden_found"]:
            click.echo(f"  ⚠️ 禁止表現を自動置換: {result['forbidden_found']}")
        else:
            click.echo(f"  ✅ 禁止表現なし")
        click.echo(f"\n--- ヘッドライン ---")
        click.echo(result["sections"]["headline"])
        click.echo(f"\n{'='*60}\n")
    finally:
        db.close()


@cli.command("generate-line-messages")
def generate_line_messages():
    """LINE配信用テンプレートを生成する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.content.line_message_generator import LINEMessageGenerator
        gen = LINEMessageGenerator(repository=repo)
        result = gen.generate_all()

        click.echo(f"\n{'='*60}")
        click.echo(f" LINE配信文生成: {result['count']} 件")
        click.echo(f"{'='*60}")
        click.echo(f"  出力先: {result['exports_dir']}")
        if result["forbidden_found"]:
            click.echo(f"  ⚠️ 禁止表現を自動置換: {result['forbidden_found']}")
        else:
            click.echo(f"  ✅ 禁止表現なし")
        for key, msg in result["messages"].items():
            click.echo(f"\n  --- {key} ---")
            click.echo("  " + msg[:200].replace("\n", "\n  "))
            if len(msg) > 200:
                click.echo("  ...")
        click.echo(f"\n{'='*60}\n")
    finally:
        db.close()


@cli.command("generate-community-messages")
def generate_community_messages():
    """Discord/Telegram向けテンプレートを生成する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.content.community_message_generator import CommunityMessageGenerator
        gen = CommunityMessageGenerator(repository=repo)
        result = gen.generate_all()

        click.echo(f"\n{'='*60}")
        click.echo(f" Community配信文生成: {result['count']} 件")
        click.echo(f"{'='*60}")
        click.echo(f"  出力先: {result['exports_dir']}")
        if result["forbidden_found"]:
            click.echo(f"  ⚠️ 禁止表現を自動置換: {result['forbidden_found']}")
        else:
            click.echo(f"  ✅ 禁止表現なし")
        for key, msg in result["messages"].items():
            click.echo(f"\n  --- {key} ---")
            click.echo("  " + msg[:200].replace("\n", "\n  "))
            if len(msg) > 200:
                click.echo("  ...")
        click.echo(f"\n{'='*60}\n")
    finally:
        db.close()


@cli.command("simulate-profit")
@click.option("--product", "-p", required=True, help="商品 (例: iphone17pro256)")
@click.option("--buyback-shop", "-b", default=None, help="買取店 (例: mobile_ichiban)")
@click.option("--shipping", default=1000, help="送料 (デフォルト: 1000)")
@click.option("--transfer-fee", default=300, help="振込手数料 (デフォルト: 300)")
@click.option("--transport", default=500, help="移動コスト (デフォルト: 500)")
@click.option("--cc-fee-rate", default=0.0, help="クレカ手数料率 (デフォルト: 0.0)")
@click.option("--other-costs", default=0, help="その他コスト")
def simulate_profit(product, buyback_shop, shipping, transfer_fee, transport, cc_fee_rate, other_costs):
    """利益シミュレーションを実行する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.market.profit_simulator import ProfitSimulator

        pid = _resolve_product_id(product)
        shop_id = f"src_{buyback_shop}" if buyback_shop and not buyback_shop.startswith("src_") else buyback_shop

        sim = ProfitSimulator(repository=repo)
        result = sim.simulate(
            product_id=pid, shop_id=shop_id,
            shipping=shipping, transfer_fee=transfer_fee,
            transport=transport, cc_fee_rate=cc_fee_rate,
            other_costs=other_costs,
        )

        if not result:
            click.echo("商品が見つかりません。")
            sys.exit(1)
        if "error" in result:
            click.echo(f"  エラー: {result['error']}")
            sys.exit(1)

        # 保存
        path = sim.save_simulation(result)

        click.echo(f"\n{'='*70}")
        click.echo(f" 利益シミュレーション: {result['product_name']}")
        click.echo(f"{'='*70}")
        click.echo(f"  公式価格: ¥{result['official_price']:,}")
        click.echo(f"")
        click.echo(f"  --- コスト ---")
        cb = result["cost_breakdown"]
        click.echo(f"  送料:       ¥{cb['shipping']:,}")
        click.echo(f"  振込手数料: ¥{cb['transfer_fee']:,}")
        click.echo(f"  移動コスト: ¥{cb['transport']:,}")
        click.echo(f"  クレカ手数料: ¥{cb['cc_fee']:,}")
        click.echo(f"  その他:     ¥{cb['other']:,}")
        click.echo(f"  合計:       ¥{cb['total']:,}")
        click.echo(f"")
        click.echo(f"  --- 買取店別 ---")
        for s in result["shops"]:
            icon = "✅" if s["profitable"] else "❌"
            click.echo(
                f"  {icon} {s['shop_name']:<14} "
                f"買取¥{s['buyback_price']:>8,} "
                f"粗利{s['gross_profit']:>+8,} "
                f"実質{s['net_profit']:>+8,} "
                f"({s['net_profit_rate']:.1%})"
            )
        click.echo(f"")
        click.echo(f"  最適: {result['best_shop']} → 実質+¥{result['best_net_profit']:,} ({result['best_rate']:.1%})")
        click.echo(f"  保存: {path}")
        click.echo(f"{'='*70}\n")
    finally:
        db.close()


# ---- Phase 10修正: 統合ジョブ・買取監視 ----

@cli.command("run-buyback-premium-check")
def run_buyback_premium_check():
    """買取更新+プレ値計算を一括実行する（10工程統合ジョブ）。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.jobs.buyback_premium_job import BuybackPremiumJob
        job = BuybackPremiumJob(repository=repo)
        results = job.run()

        click.echo(f"\n{'='*70}")
        click.echo(f" 買取+プレ値統合ジョブ結果")
        click.echo(f"{'='*70}")
        click.echo(f"  買取更新:      {results['buyback_refreshed']} 件")
        click.echo(f"  履歴保存:      {results['history_saved']} 件")
        click.echo(f"  Snapshots:     {results['snapshots_updated']} 件")
        click.echo(f"  Beginner deals: {results['beginner_deals']} 件")
        click.echo(f"  Premium候補:   {results['premium_candidates']} 件")
        click.echo(f"  買取変動:      {results['buyback_changes']} 件")
        click.echo(f"  投稿候補:      {results['publish_items']} 件")
        click.echo(f"  LINE速報:      {results['line_alerts']} 件")
        click.echo(f"  実行時間:      {results['elapsed_sec']}秒")
        if results['errors']:
            click.echo(f"\n  ⚠️ エラー ({len(results['errors'])} 件):")
            for e in results['errors']:
                click.echo(f"    {e}")
        else:
            click.echo(f"\n  ✅ エラーなし")
        click.echo(f"{'='*70}\n")
    finally:
        db.close()


@cli.command("detect-buyback-changes")
def detect_buyback_changes():
    """買取価格の急騰・急落を検知する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.market.buyback_change_detector import BuybackChangeDetector
        detector = BuybackChangeDetector(repository=repo)
        changes = detector.detect_all()

        click.echo(f"\n{'='*70}")
        click.echo(f" 買取価格変動検知: {len(changes)} 件")
        click.echo(f"{'='*70}")
        if not changes:
            click.echo("  変動なし（閾値: ±¥5,000）")
        else:
            for c in changes:
                icon = "📈" if c["alert_type"] == "buyback_surge" else "📉"
                click.echo(
                    f"  {icon} {c['product_name']} @ {c['shop_name']}: "
                    f"¥{c['previous_price']:,} → ¥{c['current_price']:,} "
                    f"({c['price_change']:+,})"
                )
        click.echo(f"{'='*70}\n")
    finally:
        db.close()


@cli.command("recalc-beginner-deals")
def recalc_beginner_deals():
    """beginner_dealsを再計算する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.market.beginner_deal_scanner import BeginnerDealScanner
        scanner = BeginnerDealScanner(repository=repo)
        deals = scanner.scan_all()
        click.echo(f"\n  Beginner deals再計算: {len(deals)} 件")
        beginner = [d for d in deals if d.user_level in ("beginner_easy", "beginner_watch")]
        click.echo(f"  beginner_easy/watch: {len(beginner)} 件")
        for d in deals:
            if d.user_level in ("beginner_easy", "beginner_watch"):
                icon = "🟢" if d.user_level == "beginner_easy" else "🟡"
                click.echo(
                    f"    {icon} {d.product_name[:30]:<32} "
                    f"net=+¥{d.net_profit_jpy:>7,} ({d.net_profit_rate:.1%}) "
                    f"level={d.user_level}"
                )
    finally:
        db.close()


@cli.command("list-buyback-history")
@click.option("--product", "-p", default=None)
@click.option("--shop", "-s", default=None)
@click.option("--limit", "-n", default=30)
def list_buyback_history_cmd(product, shop, limit):
    """買取価格履歴を表示する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        pid = _resolve_product_id(product) if product else None
        sid = f"src_{shop}" if shop and not shop.startswith("src_") else shop
        records = repo.list_buyback_history(product_id=pid, shop_id=sid, limit=limit)
        if not records:
            click.echo("買取履歴なし。")
            return
        click.echo(f"\n{'='*80}")
        click.echo(f" 買取価格履歴 ({len(records)} 件)")
        click.echo(f"{'='*80}")
        click.echo(f"  {'日時':<20} {'商品':<22} {'店舗':<14} {'価格':>10} {'条件':<16}")
        click.echo(f"  {'─'*78}")
        for r in records:
            click.echo(
                f"  {r['observed_at'][:19]:<20} {r['product_id']:<22} "
                f"{r['shop_name']:<14} ¥{r['price']:>8,} {r.get('condition',''):<16}"
            )
        click.echo(f"{'='*80}\n")
    finally:
        db.close()


# ---- Phase 10.5: LP日次自動更新 ----

@cli.command("generate-daily-lp")
@click.option("--date", "date_str", default=None, help="日付 (YYYY-MM-DD, デフォルト=今日)")
@click.option("--variant", "-v", default=None, help="A/Bテストバリアント (A/B/C)")
@click.option("--open", "open_file", is_flag=True, help="生成後にブラウザで開く")
def generate_daily_lp(date_str, variant, open_file):
    """日次LP HTMLを生成する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.content.daily_lp_generator import DailyLPGenerator
        gen = DailyLPGenerator(repository=repo)

        if date_str == "today":
            date_str = None

        result = gen.generate(date_str=date_str, variant=variant)

        click.echo(f"\n{'='*60}")
        click.echo(f" 日次LP生成完了")
        click.echo(f"{'='*60}")
        click.echo(f"  日付:       {result['date']}")
        click.echo(f"  更新時刻:   {result['time']}")
        click.echo(f"  初心者案件: {result['beginner_count']} 件")
        click.echo(f"  上級者候補: {result['advanced_count']} 件")
        click.echo(f"  急変アラート: {result['alerts_count']} 件")
        click.echo(f"  文字数:     {result['char_count']:,}")
        if result["forbidden_found"]:
            click.echo(f"  ⚠️ 禁止表現を自動置換: {result['forbidden_found']}")
        else:
            click.echo(f"  ✅ 禁止表現なし")
        click.echo(f"")
        click.echo(f"  index.html: {result['index_path']}")
        click.echo(f"  日付HTML:   {result['dated_path']}")
        click.echo(f"  Markdown:   {result['md_path']}")
        click.echo(f"{'='*60}\n")

        if open_file:
            import webbrowser
            webbrowser.open(f"file://{result['index_path']}")
    finally:
        db.close()


@cli.command("preview-daily-lp")
def preview_daily_lp():
    """最新のLP HTMLのパスと概要を表示する。"""
    lp_dir = PROJECT_ROOT / "exports" / "lp" / "daily"
    index = lp_dir / "index.html"
    if not index.exists():
        click.echo("LP未生成。'generate-daily-lp' を実行してください。")
        return

    import os
    stat = os.stat(index)
    click.echo(f"\n  最新LP: {index}")
    click.echo(f"  サイズ: {stat.st_size:,} bytes")
    click.echo(f"  更新:   {datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")

    # HTML内から日付を抽出
    content = index.read_text(encoding="utf-8")
    click.echo(f"  文字数: {len(content):,}")
    click.echo(f"\n  ブラウザで開く: file://{index}\n")


# ---- Phase 11: LP公開・デプロイ ----

@cli.command("build-public-lp")
def build_public_lp():
    """docs/ にLP公開ファイルをビルドする。"""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_public_lp import build
    click.echo("\n  Building public LP...")
    build()


@cli.command("deploy-check-lp")
def deploy_check_lp():
    """LP公開前のデプロイチェックを実行する。"""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from deploy_check import check
    results = check()
    errors = [r for r in results if r["level"] == "error"]
    warnings = [r for r in results if r["level"] == "warning"]
    oks = [r for r in results if r["level"] == "ok"]

    click.echo(f"\n{'='*60}")
    click.echo(f" Deploy Check ({len(results)} items)")
    click.echo(f"{'='*60}")
    for r in results:
        icon = {"ok": "✅", "warning": "⚠️", "error": "❌"}[r["level"]]
        click.echo(f"  {icon} [{r['check']}] {r['message']}")
    click.echo(f"\n  Errors: {len(errors)} | Warnings: {len(warnings)} | OK: {len(oks)}")
    if errors:
        click.echo(f"\n  ❌ Deploy check FAILED")
    else:
        click.echo(f"\n  ✅ Deploy check PASSED")
    click.echo(f"{'='*60}\n")


# ---- Phase 12: 計測テスト ----

@cli.command("test-analytics-tag")
def test_analytics_tag():
    """GA/Meta Pixel タグの出力状態をテストする。"""
    import re as _re
    settings = _load_yaml("lp_settings.yaml") if (PROJECT_ROOT / "config" / "lp_settings.yaml").exists() else {}
    ga_id = (settings.get("analytics", {}).get("google_analytics_id") or "").strip()
    meta_pixel = (settings.get("analytics", {}).get("meta_pixel_id") or "").strip()

    click.echo(f"\n{'='*50}")
    click.echo(f" Analytics Tag テスト")
    click.echo(f"{'='*50}")
    click.echo(f"  GA ID:      '{ga_id}' → {'設定済み' if ga_id else '未設定'}")
    click.echo(f"  Meta Pixel: '{meta_pixel}' → {'設定済み' if meta_pixel else '未設定'}")

    # LP HTMLを確認
    lp_path = PROJECT_ROOT / "exports" / "lp" / "daily" / "index.html"
    if not lp_path.exists():
        click.echo(f"\n  LP未生成。generate-daily-lp を先に実行してください。")
        return

    html = lp_path.read_text(encoding="utf-8")
    has_ga_snippet = "googletagmanager.com/gtag" in html
    has_ga_config = f'gtag("config"' in html
    has_meta = "fbevents.js" in html
    has_data_track = "data-track" in html
    has_click_js = "addEventListener" in html

    click.echo(f"\n  LP内タグ状況:")
    if ga_id:
        click.echo(f"  {'✅' if has_ga_snippet else '❌'} GAスニペット出力: {has_ga_snippet}")
    else:
        click.echo(f"  {'✅' if not has_ga_snippet else '❌'} GAスニペット非出力: {not has_ga_snippet} (未設定→正常)")
    if meta_pixel:
        click.echo(f"  {'✅' if has_meta else '❌'} Meta Pixel出力: {has_meta}")
    else:
        click.echo(f"  {'✅' if not has_meta else '❌'} Meta Pixel非出力: {not has_meta} (未設定→正常)")

    click.echo(f"  {'✅' if has_data_track else '❌'} data-track属性: {has_data_track}")
    click.echo(f"  {'✅' if has_click_js else '❌'} クリック計測JS: {has_click_js}")

    # イベント名確認
    note_ev = settings.get("analytics", {}).get("note_click_event_name", "note_click")
    prod_ev = settings.get("analytics", {}).get("product_click_event_name", "product_click")
    click.echo(f"\n  イベント名:")
    click.echo(f"    note_click → '{note_ev}' ({'検出' if f'data-track=\"{note_ev}\"' in html or 'note_click' in html else '未検出'})")
    click.echo(f"    product_click → '{prod_ev}' ({'検出' if 'data-track=\"product_click\"' in html else '未検出'})")
    click.echo(f"{'='*50}\n")


@cli.command("test-note-cta")
def test_note_cta():
    """note CTA の表示状態をテストする。"""
    settings = _load_yaml("lp_settings.yaml") if (PROJECT_ROOT / "config" / "lp_settings.yaml").exists() else {}
    note_url = (settings.get("note_url") or "").strip()
    enabled = settings.get("enable_note_cta", False)

    click.echo(f"\n{'='*50}")
    click.echo(f" note CTA テスト")
    click.echo(f"{'='*50}")
    click.echo(f"  enable_note_cta: {enabled}")
    click.echo(f"  note_url:        '{note_url}' → {'設定済み' if note_url else '未設定'}")

    lp_path = PROJECT_ROOT / "exports" / "lp" / "daily" / "index.html"
    if not lp_path.exists():
        click.echo(f"\n  LP未生成。generate-daily-lp を先に実行してください。")
        return

    html = lp_path.read_text(encoding="utf-8")
    has_note_btn = f'data-track="note_click"' in html
    has_preparing = "準備中" in html or "公開予定" in html
    has_empty_link = 'href="#"' in html and 'note_click' in html

    click.echo(f"\n  LP内CTA状況:")
    if enabled and note_url:
        click.echo(f"  {'✅' if has_note_btn else '❌'} noteボタン（リンク付き）: {has_note_btn}")
        click.echo(f"  {'✅' if not has_preparing else '⚠️'} 「準備中」非表示: {not has_preparing}")
    elif enabled and not note_url:
        click.echo(f"  {'✅' if not has_note_btn else '❌'} noteボタン非表示: {not has_note_btn} (URL未設定→正常)")
        click.echo(f"  {'✅' if has_preparing else '❌'} 「準備中」表示: {has_preparing}")
    else:
        click.echo(f"  note CTA無効 → 表示なし（正常）")

    click.echo(f"  {'✅' if not has_empty_link else '❌'} 空リンクなし: {not has_empty_link}")
    click.echo(f"{'='*50}\n")


# ---- Phase 13: 本番前チェック ----

@cli.command("prelaunch-check")
def prelaunch_check():
    """本番公開前の最終チェックリストを実行する。"""
    db = _get_db()
    try:
        db.init_schema()
        repo = Repository(db)
        from src.pipeline.prelaunch_checker import run_prelaunch_check, summarize
        results = run_prelaunch_check(repo=repo)
        s = summarize(results)

        click.echo(f"\n{'='*70}")
        click.echo(f" 本番前チェックリスト ({s['total']} 項目)")
        click.echo(f"{'='*70}")

        for r in results:
            icon = {"ok": "✅", "warning": "⚠️", "error": "❌"}[r["level"]]
            click.echo(f"  {icon} [{r['check']}] {r['message']}")

        click.echo(f"\n  --- サマリ ---")
        click.echo(f"  Errors:   {s['errors']}")
        click.echo(f"  Warnings: {s['warnings']}")
        click.echo(f"  OK:       {s['ok']}")

        if s["ready"]:
            click.echo(f"\n  ✅ 公開準備完了！")
            click.echo(f"  次のステップ:")
            click.echo(f"    git add . && git commit -m 'Launch LP' && git push")
            click.echo(f"    → GitHub Pages URL を確認")
        else:
            click.echo(f"\n  ❌ 修正が必要な項目があります:")
            for step in s["next_steps"]:
                click.echo(f"    {step}")

        if s["warnings"] > 0 and s["errors"] == 0:
            click.echo(f"\n  ℹ️ Warningは公開を妨げませんが、設定すると運用が改善します。")

        click.echo(f"{'='*70}\n")
    finally:
        db.close()


# =========================================
if __name__ == "__main__":
    cli()
