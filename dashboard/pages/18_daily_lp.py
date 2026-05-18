"""Phase 10.5: Daily LP管理"""

import streamlit as st
from pathlib import Path
from datetime import datetime
from dashboard.components.db_helper import check_db, get_db_path

st.set_page_config(page_title="Daily LP", page_icon="🌐", layout="wide")
check_db()
st.title("🌐 Daily LP 管理")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LP_DIR = PROJECT_ROOT / "exports" / "lp" / "daily"

def _get_repo():
    import sys
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from src.db.database import Database
    from src.db.repository import Repository
    db = Database.__new__(Database)
    db.db_path = get_db_path()
    db._connection = None
    db.init_schema()
    return Repository(db), db

# ===== 状態表示 =====
index_path = LP_DIR / "index.html"
col1, col2 = st.columns(2)

with col1:
    if index_path.exists():
        import os
        stat = os.stat(index_path)
        updated = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        st.metric("LP状態", "✅ 生成済み")
        st.markdown(f"**最終更新:** {updated}")
        st.markdown(f"**サイズ:** {stat.st_size:,} bytes")
    else:
        st.metric("LP状態", "❌ 未生成")
        st.info("「LP生成」ボタンを押すか、CLIで `generate-daily-lp` を実行してください。")

with col2:
    # 生成済みファイル一覧
    if LP_DIR.exists():
        files = sorted(LP_DIR.glob("*.html"), reverse=True)
        st.markdown(f"**生成済みファイル:** {len(files)} 件")
        for f in files[:5]:
            st.markdown(f"- `{f.name}`")
    else:
        st.markdown("生成済みファイルなし")

st.markdown("---")

# ===== LP生成ボタン =====
st.subheader("LP生成")
if st.button("📄 今日のLPを生成する", type="primary"):
    try:
        repo, db = _get_repo()
        from src.content.daily_lp_generator import DailyLPGenerator
        gen = DailyLPGenerator(repository=repo)
        result = gen.generate()
        db.close()
        st.success(f"LP生成完了: {result['date']} {result['time']}")
        st.markdown(f"- 初心者案件: {result['beginner_count']} 件")
        st.markdown(f"- 上級者候補: {result['advanced_count']} 件")
        st.markdown(f"- 急変アラート: {result['alerts_count']} 件")
        if result["forbidden_found"]:
            st.warning(f"禁止表現を自動置換: {result['forbidden_found']}")
        st.rerun()
    except Exception as e:
        st.error(f"エラー: {e}")

st.markdown("---")

# ===== HTMLプレビュー =====
st.subheader("LP プレビュー")
if index_path.exists():
    html_content = index_path.read_text(encoding="utf-8")
    st.components.v1.html(html_content, height=800, scrolling=True)
else:
    st.info("LPが生成されるとここにプレビューが表示されます。")

st.markdown("---")

# ===== 設定 =====
st.subheader("LP設定")
try:
    import yaml
    settings_path = PROJECT_ROOT / "config" / "lp_settings.yaml"
    with open(settings_path) as f:
        lp_cfg = yaml.safe_load(f) or {}

    st.markdown("**CTA表示設定:**")
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"- note CTA: {'✅ ON' if lp_cfg.get('enable_note_cta') else '❌ OFF'}")
    c2.markdown(f"- LINE CTA: {'✅ ON' if lp_cfg.get('enable_line_cta') else '❌ OFF'}")
    c3.markdown(f"- Telegram CTA: {'✅ ON' if lp_cfg.get('enable_telegram_cta') else '❌ OFF'}")

    st.markdown("**URL設定:**")
    st.markdown(f"- note: `{lp_cfg.get('note_url', '未設定')}`")
    st.markdown(f"- LINE: `{lp_cfg.get('line_url', '未設定')}`")

    st.markdown("**A/Bテスト:**")
    variant = lp_cfg.get("headline_variant", "A")
    variants = lp_cfg.get("variants", {})
    st.markdown(f"- 現在のバリアント: **{variant}** — 「{variants.get(variant, {}).get('headline', '?')}」")

    st.markdown("**Analytics:**")
    analytics = lp_cfg.get("analytics", {})
    st.markdown(f"- GA: `{analytics.get('google_analytics_id') or '未設定'}`")
    st.markdown(f"- Meta Pixel: `{analytics.get('meta_pixel_id') or '未設定'}`")

    st.markdown("")
    st.caption("設定変更は `config/lp_settings.yaml` を直接編集してください。")
except Exception as e:
    st.warning(f"設定読み込みエラー: {e}")

st.markdown("---")

# ===== 公開ビルド =====
st.subheader("公開ビルド & デプロイチェック")

PUBLIC_DIR = PROJECT_ROOT / "public"
pub_index = PUBLIC_DIR / "index.html"

c1, c2 = st.columns(2)
with c1:
    if st.button("🔨 public/ にビルド"):
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from build_public_lp import build
            build()
            st.success("public/ ビルド完了")
            st.rerun()
        except Exception as e:
            st.error(f"ビルドエラー: {e}")

with c2:
    if st.button("🔍 デプロイチェック"):
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from deploy_check import check
            results = check()
            errors = [r for r in results if r["level"] == "error"]
            warnings = [r for r in results if r["level"] == "warning"]
            for r in results:
                icon = {"ok": "✅", "warning": "⚠️", "error": "❌"}[r["level"]]
                st.markdown(f"{icon} **{r['check']}**: {r['message']}")
            if errors:
                st.error(f"❌ {len(errors)} errors — 修正してからデプロイしてください")
            else:
                st.success("✅ Deploy check PASSED")
        except Exception as e:
            st.error(f"チェックエラー: {e}")

# 公開ファイル一覧
if PUBLIC_DIR.exists():
    files = sorted(PUBLIC_DIR.rglob("*"), key=lambda f: f.name)
    file_list = [f for f in files if f.is_file()]
    if file_list:
        st.markdown(f"**public/ ファイル一覧 ({len(file_list)} files):**")
        for f in file_list[:15]:
            rel = f.relative_to(PUBLIC_DIR)
            st.markdown(f"- `{rel}` ({f.stat().st_size:,} bytes)")
