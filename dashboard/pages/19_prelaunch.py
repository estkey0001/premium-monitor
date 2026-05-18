"""Phase 13: 本番前チェック"""

import streamlit as st
from pathlib import Path
from dashboard.components.db_helper import check_db, get_db_path

st.set_page_config(page_title="本番前チェック", page_icon="🚀", layout="wide")
check_db()
st.title("🚀 本番前チェックリスト")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

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

try:
    repo, db = _get_repo()
except Exception as e:
    st.error(f"初期化エラー: {e}")
    st.stop()

# ===== チェック実行 =====
try:
    import sys
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from src.pipeline.prelaunch_checker import run_prelaunch_check, summarize
    results = run_prelaunch_check(repo=repo)
    s = summarize(results)
except Exception as e:
    st.error(f"チェック実行エラー: {e}")
    st.stop()

# ===== サマリ =====
col1, col2, col3, col4 = st.columns(4)
with col1:
    status = "✅ 公開準備完了" if s["ready"] else "❌ 修正が必要"
    st.metric("ステータス", status)
with col2:
    st.metric("❌ Errors", s["errors"])
with col3:
    st.metric("⚠️ Warnings", s["warnings"])
with col4:
    st.metric("✅ OK", s["ok"])

st.markdown("---")

# ===== チェック結果 =====
st.subheader("チェック結果")
for r in results:
    icon = {"ok": "✅", "warning": "⚠️", "error": "❌"}[r["level"]]
    st.markdown(f"{icon} **{r['check']}** — {r['message']}")

st.markdown("---")

# ===== 設定状態 =====
st.subheader("設定状態")
try:
    import yaml
    with open(PROJECT_ROOT / "config" / "lp_settings.yaml") as f:
        cfg = yaml.safe_load(f) or {}

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**CTA設定:**")
        st.markdown(f"- note CTA: {'✅ ON' if cfg.get('enable_note_cta') else '❌ OFF'}")
        st.markdown(f"- LINE CTA: {'❌ OFF' if not cfg.get('enable_line_cta') else '⚠️ ON'}")
        st.markdown(f"- Telegram CTA: {'❌ OFF' if not cfg.get('enable_telegram_cta') else '⚠️ ON'}")

        st.markdown("**URLs:**")
        st.markdown(f"- note: `{cfg.get('note_url') or '未設定'}`")
        st.markdown(f"- site: `{cfg.get('site_url') or '未設定'}`")

    with c2:
        st.markdown("**Analytics:**")
        ga = cfg.get("analytics", {}).get("google_analytics_id") or ""
        st.markdown(f"- GA ID: `{ga or '未設定'}`")
        st.markdown(f"- Meta Pixel: `{cfg.get('analytics', {}).get('meta_pixel_id') or '未設定'}`")

        st.markdown("**A/Bテスト:**")
        variant = cfg.get("headline_variant", "A")
        st.markdown(f"- 現在: **Variant {variant}**")
        exports_dir = PROJECT_ROOT / "exports" / "lp" / "daily"
        for v in ["A", "B", "C"]:
            exists = (exports_dir / f"index_{v}.html").exists()
            st.markdown(f"- Variant {v}: {'✅ 生成済み' if exists else '❌ 未生成'}")
except Exception as e:
    st.warning(f"設定読み込みエラー: {e}")

st.markdown("---")

# ===== 次にやるべきこと =====
st.subheader("次にやるべきこと")
if s["ready"] and s["warnings"] == 0:
    st.success("全項目クリア。公開準備完了です。")
    st.code("git add . && git commit -m 'Launch LP' && git push", language="bash")
elif s["ready"]:
    st.info("公開可能ですが、以下を設定するとさらに良くなります:")
    for step in s["next_steps"]:
        st.markdown(f"- {step}")
else:
    st.error("以下を修正してから公開してください:")
    for step in s["next_steps"]:
        st.markdown(f"- {step}")

st.markdown("---")

# ===== 公開手順 =====
st.subheader("LP公開手順")
st.code("""# 1. LP生成
python -m src.cli generate-daily-lp --variant A

# 2. publicにビルド
python -m src.cli build-public-lp

# 3. デプロイチェック
python -m src.cli deploy-check-lp

# 4. 本番前チェック
python -m src.cli prelaunch-check

# 5. GitHubにpush
git add . && git commit -m 'Launch LP' && git push

# 6. GitHub Pages URLを開いて確認""", language="bash")

# ===== 公開ファイル =====
st.subheader("公開ファイル一覧")
public_dir = PROJECT_ROOT / "public"
if public_dir.exists():
    files = sorted(public_dir.rglob("*"), key=lambda f: f.name)
    file_list = [f for f in files if f.is_file()]
    if file_list:
        for f in file_list[:20]:
            rel = f.relative_to(public_dir)
            st.markdown(f"- `{rel}` ({f.stat().st_size:,} bytes)")
else:
    st.info("public/ 未生成")

try:
    db.close()
except Exception:
    pass
