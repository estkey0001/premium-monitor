"""Phase 10: コンテンツ生成ダッシュボード"""

import streamlit as st
from pathlib import Path
from dashboard.components.db_helper import check_db, get_db_path

st.set_page_config(page_title="コンテンツ生成", page_icon="📝", layout="wide")
check_db()
st.title("📝 コンテンツ生成")

def _get_repo():
    import sys
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
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

tab1, tab2, tab3, tab4 = st.tabs(["📓 note記事", "🖥️ LPコピー", "💬 LINE配信", "🎮 Community"])

# ===== note記事 =====
with tab1:
    st.subheader("note記事生成")
    report_type = st.selectbox("記事タイプ", ["beginner", "advanced", "weekly"])
    if st.button("生成", key="note_gen"):
        with st.spinner("生成中..."):
            try:
                from src.content.note_generator import NoteGenerator
                gen = NoteGenerator(repository=repo)
                result = gen.generate(report_type=report_type)
                st.success(f"生成完了: {result['char_count']:,}文字")
                if result["forbidden_found"]:
                    st.warning(f"禁止表現を自動置換: {result['forbidden_found']}")
                st.markdown(f"**保存先:** `{result['md_path']}`")
                with st.expander("プレビュー", expanded=True):
                    st.markdown(result["content"][:3000])
                    if len(result["content"]) > 3000:
                        st.info("（3000文字以降は省略）")
            except Exception as e:
                st.error(f"エラー: {e}")

# ===== LPコピー =====
with tab2:
    st.subheader("LPコピー素材生成")
    if st.button("生成", key="lp_gen"):
        with st.spinner("生成中..."):
            try:
                from src.content.lp_generator import LPGenerator
                gen = LPGenerator(repository=repo)
                result = gen.generate()
                st.success(f"生成完了: {result['char_count']:,}文字")
                st.markdown(f"**保存先:** `{result['path']}`")
                for name, section in result["sections"].items():
                    with st.expander(f"セクション: {name}"):
                        st.markdown(section)
            except Exception as e:
                st.error(f"エラー: {e}")

# ===== LINE配信 =====
with tab3:
    st.subheader("LINE配信文生成")
    if st.button("全テンプレート生成", key="line_gen"):
        with st.spinner("生成中..."):
            try:
                from src.content.line_message_generator import LINEMessageGenerator
                gen = LINEMessageGenerator(repository=repo)
                result = gen.generate_all()
                st.success(f"生成完了: {result['count']}件")
                for key, msg in result["messages"].items():
                    with st.expander(f"テンプレート: {key}"):
                        st.text(msg)
            except Exception as e:
                st.error(f"エラー: {e}")

# ===== Community =====
with tab4:
    st.subheader("Discord / Telegram 配信文生成")
    if st.button("全テンプレート生成", key="comm_gen"):
        with st.spinner("生成中..."):
            try:
                from src.content.community_message_generator import CommunityMessageGenerator
                gen = CommunityMessageGenerator(repository=repo)
                result = gen.generate_all()
                st.success(f"生成完了: {result['count']}件")
                for key, msg in result["messages"].items():
                    with st.expander(f"テンプレート: {key}"):
                        st.text(msg)
            except Exception as e:
                st.error(f"エラー: {e}")

try:
    db.close()
except Exception:
    pass
