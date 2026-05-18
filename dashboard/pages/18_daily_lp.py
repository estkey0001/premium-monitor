"""Phase 13+: Daily LP管理（データ鮮度・12時更新ボタン・タブUIプレビュー）"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from dashboard.components.db_helper import check_db, get_db_path

st.set_page_config(page_title="Daily LP", page_icon="🌐", layout="wide")
check_db()
st.title("🌐 Daily LP 管理")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LP_DIR = PROJECT_ROOT / "exports" / "lp" / "daily"
DOCS_DIR = PROJECT_ROOT / "docs"
JST = timezone(timedelta(hours=9))


def _get_repo():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from src.db.database import Database
    from src.db.repository import Repository
    db = Database.__new__(Database)
    db.db_path = get_db_path()
    db._connection = None
    db.init_schema()
    return Repository(db), db


def _jst_str(dt) -> str:
    if not dt:
        return "不明"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    else:
        dt = dt.astimezone(JST)
    return dt.strftime("%Y-%m-%d %H:%M JST")


def _hours_ago(dt) -> float:
    if not dt:
        return 999.0
    now = datetime.now(tz=JST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    else:
        dt = dt.astimezone(JST)
    return (now - dt).total_seconds() / 3600


def _freshness_badge(hours: float) -> str:
    if hours < 6:
        return "🟢 最新（6時間以内）"
    elif hours < 24:
        return "🟡 やや古い（24時間以内）"
    else:
        return "🔴 古いデータ（24時間超）"


# ===== データ鮮度ダッシュボード =====
st.subheader("📊 データ鮮度")

try:
    repo, db = _get_repo()
    latest_buyback_at  = repo.get_latest_buyback_observed_at()
    latest_deals_at    = repo.get_latest_beginner_deals_at()
    db.close()

    # LP生成時刻はファイルのmtime
    index_path = LP_DIR / "index.html"
    lp_mtime = None
    if index_path.exists():
        lp_mtime = datetime.fromtimestamp(os.stat(index_path).st_mtime, tz=JST)

    col1, col2, col3 = st.columns(3)

    buyback_h = _hours_ago(latest_buyback_at)
    deals_h   = _hours_ago(latest_deals_at)
    lp_h      = _hours_ago(lp_mtime)

    with col1:
        st.metric("📦 買取価格更新", _jst_str(latest_buyback_at))
        st.caption(_freshness_badge(buyback_h))

    with col2:
        st.metric("🔎 案件計算（beginner_deals）", _jst_str(latest_deals_at))
        st.caption(_freshness_badge(deals_h))

    with col3:
        st.metric("🌐 LP生成", _jst_str(lp_mtime))
        st.caption(_freshness_badge(lp_h))

    # 24時間超警告
    stale = []
    if buyback_h >= 24:
        stale.append(f"買取価格（{buyback_h:.0f}時間前）")
    if deals_h >= 24:
        stale.append(f"案件情報（{deals_h:.0f}時間前）")
    if lp_h >= 24:
        stale.append(f"LP（{lp_h:.0f}時間前）")
    if stale:
        st.warning(f"⚠️ 古いデータがあります: {' / '.join(stale)} — 更新を推奨します")
    else:
        st.success("✅ 全データが24時間以内です")

except Exception as e:
    st.warning(f"鮮度取得エラー: {e}")

st.markdown("---")

# ===== daily-lp-update（ワンコマンド更新） =====
st.subheader("🚀 daily-lp-update（ワンコマンド更新）")

st.info(
    "**毎日12時更新用ワンコマンド。** "
    "validate-price-links → import-buyback-csv → import-market-csv → "
    "run-buyback-premium-check → generate-daily-lp → build-public-lp → "
    "deploy-check → prelaunch-check を順番に実行します。\n\n"
    "⚠️ git push は自動では行いません。結果確認後に手動で push してください。"
)

col_var, col_btn = st.columns([2, 3])
with col_var:
    dl_variant = st.selectbox("バリアント", ["A", "B", "C"], index=0, key="dl_variant")
    skip_link = st.checkbox("リンク検証スキップ（高速化）", key="dl_skip_link")

with col_btn:
    st.write("")
    st.write("")
    run_daily = st.button("▶ daily-lp-update 実行", type="primary", use_container_width=True)

if run_daily:
    progress = st.progress(0, text="初期化中...")
    log_area = st.empty()
    logs: list[str] = []
    result_summary: dict = {}

    def _dlog(msg: str):
        logs.append(msg)
        log_area.code("\n".join(logs[-60:]))  # 最新60行を表示

    try:
        # ---- Step 1: validate-price-links ----
        progress.progress(5, text="Step 1/8: リンク検証...")
        if skip_link:
            _dlog("Step 1/8: リンク検証 → スキップ（--skip-link-check）")
        else:
            _dlog("Step 1/8: リンク検証中...")
            try:
                import requests as _req, csv as _csv
                _seen: set = set()
                _ok_c = _ng_c = 0
                _buyback_csv = PROJECT_ROOT / "data" / "manual_buyback_prices.csv"
                if _buyback_csv.exists():
                    with open(_buyback_csv, encoding="utf-8") as _f:
                        for _row in _csv.DictReader(_f):
                            _u = _row.get("url", "").strip()
                            if not _u or _u in _seen:
                                continue
                            _seen.add(_u)
                            try:
                                _r = _req.head(_u, timeout=6, allow_redirects=True,
                                               headers={"User-Agent": "Mozilla/5.0"})
                                if _r.status_code in (200, 301, 302, 403):
                                    _ok_c += 1
                                else:
                                    _ng_c += 1
                            except Exception:
                                _ng_c += 1
                _dlog(f"  ✅ リンク OK:{_ok_c} / NG:{_ng_c}")
                result_summary["link_ok"] = _ok_c
                result_summary["link_ng"] = _ng_c
            except ImportError:
                _dlog("  ⚠️ requests未インストール → スキップ")

        # ---- Step 2: import-buyback-csv ----
        progress.progress(15, text="Step 2/8: 買取CSVインポート...")
        _dlog("Step 2/8: 買取CSVインポート...")
        from src.db.database import Database
        from src.db.repository import Repository
        _db = Database.__new__(Database)
        _db.db_path = get_db_path()
        _db._connection = None
        _db.init_schema()
        _repo = Repository(_db)
        _buyback_file = PROJECT_ROOT / "data" / "manual_buyback_prices.csv"
        if _buyback_file.exists():
            from src.market.buyback_csv_importer import BuybackCSVImporter
            _br = BuybackCSVImporter(_repo).import_file(str(_buyback_file))
            result_summary["buyback_imported"] = _br["imported"]
            _dlog(f"  ✅ 買取CSV: {_br['imported']}件 (skip={_br['skipped']})")
            for _e in _br.get("errors", [])[:3]:
                _dlog(f"  ⚠️  {_e}")
        else:
            _dlog("  ⚠️ manual_buyback_prices.csv なし → スキップ")

        # ---- Step 3: import-market-csv ----
        progress.progress(25, text="Step 3/8: 市場CSVインポート...")
        _dlog("Step 3/8: 市場CSVインポート...")
        _market_file = PROJECT_ROOT / "data" / "manual_market_prices.csv"
        if _market_file.exists():
            try:
                from src.market.market_csv_importer import MarketCSVImporter
                _mr = MarketCSVImporter(_repo).import_file(str(_market_file))
                result_summary["market_imported"] = _mr.get("imported", 0)
                _dlog(f"  ✅ 市場CSV: {_mr.get('imported', 0)}件")
            except Exception as _e2:
                _dlog(f"  ⚠️ 市場CSVスキップ: {_e2}")
        else:
            _dlog("  ⚠️ manual_market_prices.csv なし → スキップ")

        # ---- Step 4: run-buyback-premium-check ----
        progress.progress(38, text="Step 4/8: 買取+プレ値統合ジョブ...")
        _dlog("Step 4/8: run-buyback-premium-check 実行中...")
        from src.jobs.buyback_premium_job import BuybackPremiumJob
        _job = BuybackPremiumJob(repository=_repo)
        _jr = _job.run()
        _dlog(f"  ✅ snapshots={_jr['snapshots_updated']} deals={_jr['beginner_deals']} errors={len(_jr['errors'])}")
        _db.close()

        # ---- Step 5: generate-daily-lp ----
        progress.progress(52, text="Step 5/8: LP生成中...")
        _dlog(f"Step 5/8: generate-daily-lp --variant {dl_variant}...")
        _db5 = Database.__new__(Database)
        _db5.db_path = get_db_path()
        _db5._connection = None
        _db5.init_schema()
        _repo5 = Repository(_db5)
        from src.content.daily_lp_generator import DailyLPGenerator
        _lp = DailyLPGenerator(repository=_repo5)
        _lr = _lp.generate(variant=dl_variant)
        result_summary["beginner_count"] = _lr["beginner_count"]
        result_summary["advanced_count"] = _lr["advanced_count"]
        _dlog(f"  ✅ beginner={_lr['beginner_count']} advanced={_lr['advanced_count']}")
        _db5.close()

        # ---- Step 6: build-public-lp ----
        progress.progress(65, text="Step 6/8: docs/ ビルド中...")
        _dlog("Step 6/8: build-public-lp...")
        if str(PROJECT_ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import importlib
        import build_public_lp as _bpl
        importlib.reload(_bpl)
        _bpl.build()
        _dlog("  ✅ docs/ ビルド完了")

        # ---- Step 7: deploy-check ----
        progress.progress(80, text="Step 7/8: デプロイチェック...")
        _dlog("Step 7/8: deploy-check-lp...")
        import deploy_check as _dc
        importlib.reload(_dc)
        _cr = _dc.check()
        _errs = [r for r in _cr if r["level"] == "error"]
        _warns = [r for r in _cr if r["level"] == "warning"]
        result_summary["deploy_errors"] = len(_errs)
        result_summary["deploy_warnings"] = len(_warns)
        _dlog(f"  {'✅' if not _errs else '❌'} deploy-check: errors={len(_errs)} warnings={len(_warns)} ok={len(_cr)-len(_errs)-len(_warns)}")
        for r in _errs:
            _dlog(f"    ❌ [{r['check']}] {r['message']}")
        for r in _warns:
            _dlog(f"    ⚠️  [{r['check']}] {r['message']}")

        # ---- Step 8: prelaunch-check ----
        progress.progress(92, text="Step 8/8: 本番前チェック...")
        _dlog("Step 8/8: prelaunch-check...")
        _db8 = Database.__new__(Database)
        _db8.db_path = get_db_path()
        _db8._connection = None
        _db8.init_schema()
        _repo8 = Repository(_db8)
        from src.pipeline.prelaunch_checker import run_prelaunch_check, summarize as _summ
        _ps = _summ(run_prelaunch_check(repo=_repo8))
        _db8.close()
        result_summary["prelaunch_errors"] = _ps["errors"]
        _dlog(f"  {'✅' if _ps['errors']==0 else '❌'} prelaunch: errors={_ps['errors']} warnings={_ps['warnings']}")

        progress.progress(100, text="完了！")

        # ---- サマリ表示 ----
        has_error = len(_errs) > 0 or _ps["errors"] > 0
        if has_error:
            st.error("❌ エラーあり — ログを確認してください")
        else:
            st.success("✅ daily-lp-update 完了！")
            st.info(
                f"**結果サマリ**\n"
                f"- 買取CSV: {result_summary.get('buyback_imported', '-')}件\n"
                f"- beginner_easy案件: {result_summary.get('beginner_count', '-')}件\n"
                f"- advanced候補: {result_summary.get('advanced_count', '-')}件\n"
                f"- deploy-check: ✅ {len(_cr)-len(_errs)-len(_warns)}/22 OK\n"
                f"- NGリンク: {result_summary.get('link_ng', '-')}件\n\n"
                f"📌 **次のステップ（手動でpush）:**\n"
                f"```\n"
                f"git add docs/ exports/lp/daily/\n"
                f"git commit -m \"Update daily LP\"\n"
                f"git push\n"
                f"```"
            )
        st.rerun()

    except Exception as e:
        import traceback as _tb
        _dlog(f"ERROR: {e}\n{_tb.format_exc()}")
        st.error(f"実行エラー: {e}")

st.markdown("---")

# ===== 12時更新ボタン（旧UI・詳細ステップ） =====
with st.expander("🔧 個別ステップ実行（旧UI）"):
    st.info(
        "個別ステップを手動実行したい場合はこちら。"
        "run-buyback-premium-check → generate-daily-lp → build-public-lp → deploy-check を一括実行します。"
    )

    if st.button("▶ 個別ステップ実行（旧12時更新）", use_container_width=True):
        progress = st.progress(0, text="処理中...")
        log_area = st.empty()
        logs = []

        def _log(msg: str):
            logs.append(msg)
            log_area.code("\n".join(logs))

        try:
            _log("Step 1/4: run-buyback-premium-check 実行中...")
            progress.progress(10, text="Step 1: 買取価格更新 & プレ値チェック...")
            from src.db.database import Database
            from src.db.repository import Repository
            from src.jobs.buyback_premium_job import BuybackPremiumJob
            _db = Database.__new__(Database)
            _db.db_path = get_db_path()
            _db._connection = None
            _db.init_schema()
            _repo = Repository(_db)
            job = BuybackPremiumJob(repository=_repo)
            job_result = job.run()
            _log(f"  ✅ snapshots={job_result['snapshots_updated']} deals={job_result['beginner_deals']} errors={len(job_result['errors'])}")

            progress.progress(40, text="Step 2: LP生成中...")
            _log("Step 2/4: generate-daily-lp --variant A 実行中...")
            from src.content.daily_lp_generator import DailyLPGenerator
            lp_gen = DailyLPGenerator(repository=_repo)
            lp_result = lp_gen.generate(variant="A")
            _log(f"  ✅ beginner={lp_result['beginner_count']} advanced={lp_result['advanced_count']}")
            _log(f"     買取価格更新: {lp_result['latest_buyback_at']}")
            _log(f"     LP生成: {lp_result['time']}")
            _db.close()

            progress.progress(65, text="Step 3: docs/ ビルド中...")
            _log("Step 3/4: build-public-lp 実行中...")
            if str(PROJECT_ROOT / "scripts") not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            import importlib
            import build_public_lp as _bpl
            importlib.reload(_bpl)
            _bpl.build()
            _log("  ✅ docs/ にビルド完了")

            progress.progress(85, text="Step 4: deploy-check 実行中...")
            _log("Step 4/4: deploy-check 実行中...")
            import deploy_check as _dc
            importlib.reload(_dc)
            check_results = _dc.check()
            errors   = [r for r in check_results if r["level"] == "error"]
            warnings = [r for r in check_results if r["level"] == "warning"]
            _log(f"  結果: errors={len(errors)} warnings={len(warnings)} ok={len([r for r in check_results if r['level']=='ok'])}")
            for r in errors:
                _log(f"  ❌ {r['check']}: {r['message']}")
            for r in warnings:
                _log(f"  ⚠️ {r['check']}: {r['message']}")

            progress.progress(100, text="完了！")

            if errors:
                st.error(f"❌ deploy-check に {len(errors)} errors があります。修正してください。")
            else:
                st.success(f"✅ 完了！ docs/index.html を git push してください。")
            st.rerun()

        except Exception as e:
            import traceback
            _log(f"ERROR: {e}\n{traceback.format_exc()}")
            st.error(f"実行エラー: {e}")

st.markdown("---")

# ===== 個別LP生成 =====
st.subheader("LP生成（バリアント選択）")

col_v, col_btn = st.columns([2, 1])
with col_v:
    variant = st.selectbox("バリアント", ["A", "B", "C"], index=0)
with col_btn:
    st.write("")
    st.write("")
    if st.button("📄 LP生成", use_container_width=True):
        try:
            repo, db = _get_repo()
            from src.content.daily_lp_generator import DailyLPGenerator
            gen = DailyLPGenerator(repository=repo)
            result = gen.generate(variant=variant)
            db.close()
            st.success(f"LP生成完了（バリアント {result['variant']}）: {result['date']} {result['time']}")
            st.markdown(f"- 初心者案件: **{result['beginner_count']}** 件")
            st.markdown(f"- 上級者候補: **{result['advanced_count']}** 件")
            st.markdown(f"- 急変アラート: **{result['alerts_count']}** 件")
            st.markdown(f"- 買取価格更新: `{result['latest_buyback_at']}`")
            if result["forbidden_found"]:
                st.warning(f"禁止表現を自動置換: {result['forbidden_found']}")
            st.rerun()
        except Exception as e:
            st.error(f"エラー: {e}")

st.markdown("---")

# ===== LP プレビュー =====
st.subheader("🖥 LP プレビュー（タブUI確認）")

preview_tabs = st.tabs(["exports/lp/daily/index.html", "docs/index.html"])

with preview_tabs[0]:
    index_path = LP_DIR / "index.html"
    if index_path.exists():
        stat = os.stat(index_path)
        updated = datetime.fromtimestamp(stat.st_mtime, tz=JST).strftime("%Y-%m-%d %H:%M JST")
        st.caption(f"最終更新: {updated} / サイズ: {stat.st_size:,} bytes")
        html_content = index_path.read_text(encoding="utf-8")
        st.components.v1.html(html_content, height=900, scrolling=True)
    else:
        st.info("LPが生成されるとここにプレビューが表示されます。")

with preview_tabs[1]:
    docs_index = DOCS_DIR / "index.html"
    if docs_index.exists():
        stat = os.stat(docs_index)
        updated = datetime.fromtimestamp(stat.st_mtime, tz=JST).strftime("%Y-%m-%d %H:%M JST")
        st.caption(f"最終更新: {updated} / サイズ: {stat.st_size:,} bytes")
        html_content = docs_index.read_text(encoding="utf-8")
        st.components.v1.html(html_content, height=900, scrolling=True)
    else:
        st.info("build-public-lp を実行すると docs/index.html が表示されます。")

st.markdown("---")

# ===== 公開ビルド & チェック =====
st.subheader("公開ビルド & デプロイチェック")

col1, col2 = st.columns(2)

with col1:
    if st.button("🔨 docs/ にビルド", use_container_width=True):
        try:
            if str(PROJECT_ROOT / "scripts") not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            import importlib, build_public_lp as _bpl
            importlib.reload(_bpl)
            _bpl.build()
            st.success("docs/ ビルド完了")
            st.rerun()
        except Exception as e:
            st.error(f"ビルドエラー: {e}")

with col2:
    if st.button("🔍 デプロイチェック", use_container_width=True):
        try:
            if str(PROJECT_ROOT / "scripts") not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            import importlib, deploy_check as _dc
            importlib.reload(_dc)
            results = _dc.check()
            errors   = [r for r in results if r["level"] == "error"]
            warnings = [r for r in results if r["level"] == "warning"]
            for r in results:
                icon = {"ok": "✅", "warning": "⚠️", "error": "❌"}[r["level"]]
                st.markdown(f"{icon} **{r['check']}**: {r['message']}")
            if errors:
                st.error(f"❌ {len(errors)} errors — 修正してからデプロイしてください")
            else:
                st.success(f"✅ Deploy check PASSED（warnings: {len(warnings)}）")
        except Exception as e:
            st.error(f"チェックエラー: {e}")

# docs/ ファイル一覧
if DOCS_DIR.exists():
    files = [f for f in DOCS_DIR.rglob("*") if f.is_file()]
    if files:
        with st.expander(f"docs/ ファイル一覧（{len(files)} files）"):
            for f in sorted(files)[:20]:
                rel = f.relative_to(DOCS_DIR)
                st.markdown(f"- `{rel}` ({f.stat().st_size:,} bytes)")

st.markdown("---")

# ===== LP設定 =====
st.subheader("⚙️ LP設定")

try:
    import yaml
    settings_path = PROJECT_ROOT / "config" / "lp_settings.yaml"
    with open(settings_path) as f:
        lp_cfg = yaml.safe_load(f) or {}

    c1, c2, c3 = st.columns(3)
    c1.metric("note CTA", "ON ✅" if lp_cfg.get("enable_note_cta") else "OFF")
    c2.metric("LINE CTA", "ON ✅" if lp_cfg.get("enable_line_cta") else "OFF")
    c3.metric("Telegram CTA", "ON ✅" if lp_cfg.get("enable_telegram_cta") else "OFF")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.markdown(f"**site_url:** `{lp_cfg.get('site_url', '未設定')}`")
        st.markdown(f"**note_url:** `{lp_cfg.get('note_url', '未設定')}`")
    with col_s2:
        analytics = lp_cfg.get("analytics", {})
        st.markdown(f"**GA ID:** `{analytics.get('google_analytics_id') or '未設定'}`")
        variant = lp_cfg.get("headline_variant", "A")
        variants = lp_cfg.get("variants", {})
        st.markdown(f"**A/Bバリアント:** {variant} — 「{variants.get(variant, {}).get('headline', '?')}」")

    st.caption("設定変更は `config/lp_settings.yaml` を直接編集してください。")
except Exception as e:
    st.warning(f"設定読み込みエラー: {e}")

st.markdown("---")

# ===== 生成済みファイル一覧 =====
with st.expander("📁 exports/lp/daily/ ファイル一覧"):
    if LP_DIR.exists():
        files = sorted(LP_DIR.glob("*.html"), reverse=True)
        st.markdown(f"**生成済みファイル:** {len(files)} 件")
        for f in files[:10]:
            stat = os.stat(f)
            updated = datetime.fromtimestamp(stat.st_mtime, tz=JST).strftime("%Y-%m-%d %H:%M")
            st.markdown(f"- `{f.name}` — {updated} — {stat.st_size:,} bytes")
    else:
        st.markdown("ファイルなし")
