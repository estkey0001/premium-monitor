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

# ===== 12時更新ボタン（メイン操作） =====
st.subheader("🕐 12時更新（本番LP更新）")

st.info(
    "このボタンは毎日12:00 JST の本番更新用です。"
    "run-buyback-premium-check → generate-daily-lp → build-public-lp → deploy-check を一括実行します。"
)

if st.button("🚀 12時更新を実行（本番LP更新）", type="primary", use_container_width=True):
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
            st.success(f"✅ 12時更新完了！ docs/index.html を git push してください。")
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
