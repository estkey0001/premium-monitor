"""📢 投稿キュー管理"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df, execute_sql

st.set_page_config(page_title="投稿キュー", page_icon="📢", layout="wide")
check_db()
st.title("📢 投稿キュー管理")

col1, col2 = st.columns(2)
with col1:
    ch = st.selectbox("チャネル", ["全て", "x", "threads", "line", "discord", "note"], key="pq_ch")
with col2:
    status = st.selectbox("ステータス", ["全て", "draft", "approved", "published", "rejected"], key="pq_st")

try:
    where_parts = ["1=1"]
    params = []
    if ch != "全て":
        where_parts.append("channel=?")
        params.append(ch)
    if status != "全て":
        where_parts.append("status=?")
        params.append(status)
    where = " AND ".join(where_parts)

    df = query_df(
        f"SELECT * FROM publish_queue WHERE {where} ORDER BY generated_at DESC LIMIT 50",
        tuple(params),
    )
except Exception:
    st.info("publish_queueテーブルが見つかりません。init-dbを再実行してください。")
    st.stop()

if df.empty:
    st.info("投稿キューが空です。`python -m src.cli generate-posts` を実行してください。")
    st.stop()

st.markdown(f"**{len(df)} 件**")

for _, row in df.iterrows():
    status_icon = {"draft": "📝", "approved": "✅", "published": "📤", "rejected": "❌"}.get(row["status"], "❓")
    rank_icon = {"S": "🔴", "A": "🟠"}.get(row.get("rank", ""), "")

    with st.expander(
        f"{status_icon} {rank_icon} [{row['channel']}] {row['title'][:60]}",
        expanded=False,
    ):
        # メタ情報
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            st.markdown(f"**チャネル:** {row['channel']}")
            st.markdown(f"**ランク:** {row.get('rank') or '---'}")
        with mc2:
            st.markdown(f"**ステータス:** {row['status']}")
            st.markdown(f"**種別:** {row['source_type']}")
        with mc3:
            st.markdown(f"**生成日時:** {row['generated_at'][:19]}")
            st.markdown(f"**ID:** `{row['id'][:16]}...`")

        # 本文プレビュー
        st.markdown("---")
        st.markdown("**本文:**")
        st.text_area("", value=row["body"], height=200, key=f"body_{row['id']}", disabled=True)

        if row.get("hashtags"):
            st.markdown(f"**ハッシュタグ:** {row['hashtags']}")

        # コピー用テキスト
        full_text = row["body"]
        if row.get("hashtags"):
            full_text += "\n\n" + row["hashtags"]
        st.code(full_text, language=None)

        # 操作ボタン
        if row["status"] == "draft":
            bc1, bc2 = st.columns(2)
            with bc1:
                if st.button("✅ 承認", key=f"approve_{row['id']}"):
                    execute_sql(
                        "UPDATE publish_queue SET status='approved', approved_at=datetime('now') WHERE id=?",
                        (row["id"],),
                    )
                    st.success("承認しました。")
                    st.rerun()
            with bc2:
                if st.button("❌ 却下", key=f"reject_{row['id']}"):
                    execute_sql(
                        "UPDATE publish_queue SET status='rejected' WHERE id=?",
                        (row["id"],),
                    )
                    st.warning("却下しました。")
                    st.rerun()

        elif row["status"] == "approved":
            if st.button("📤 公開済みにする", key=f"publish_{row['id']}"):
                execute_sql(
                    "UPDATE publish_queue SET status='published', published_at=datetime('now') WHERE id=?",
                    (row["id"],),
                )
                st.success("公開済みにしました。")
                st.rerun()
