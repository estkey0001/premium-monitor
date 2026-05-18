"""🔔 アラート一覧"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df, fmt_price, execute_sql
from dashboard.components.filters import rank_filter, product_filter

st.set_page_config(page_title="アラート一覧", page_icon="🔔", layout="wide")
check_db()
st.title("🔔 アラート一覧")

col1, col2, col3 = st.columns(3)
with col1:
    rank = rank_filter("alert_rank")
with col2:
    product_id = product_filter("alert_product")
with col3:
    sent_filter = st.selectbox("送信状態", ["全て", "送信済み", "未送信"], key="sent")

where_parts = ["1=1"]
params = []
if rank:
    where_parts.append("a.alert_rank=?")
    params.append(rank)
if product_id:
    where_parts.append("a.product_id=?")
    params.append(product_id)
if sent_filter == "送信済み":
    where_parts.append("a.is_sent=1")
elif sent_filter == "未送信":
    where_parts.append("a.is_sent=0")

where = " AND ".join(where_parts)
df = query_df(f"""
    SELECT a.id, a.created_at, a.alert_rank, a.alert_type, a.title,
           a.estimated_profit, a.score, a.confidence,
           a.is_sent, a.sent_channels, a.is_false_positive, a.is_published,
           a.product_id, a.body
    FROM alerts a WHERE {where}
    ORDER BY a.created_at DESC LIMIT 100
""", tuple(params))

if df.empty:
    st.info("アラートが見つかりません。")
    st.stop()

st.markdown(f"**{len(df)} 件**")

# 表示用
display = df.copy()
rank_icons = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "⚪"}
display["Rank"] = display["alert_rank"].apply(lambda x: f"{rank_icons.get(x, '')} {x}")
display["利益"] = display["estimated_profit"].apply(fmt_price)
display["信頼度"] = display["confidence"].apply(lambda x: f"{x:.0%}" if x else "---")
display["送信先"] = display["sent_channels"].fillna("---")
display["誤報"] = display["is_false_positive"].apply(lambda x: "⚠️" if x else "")

st.dataframe(
    display[["created_at", "Rank", "alert_type", "title", "利益",
             "score", "信頼度", "送信先", "誤報"]].rename(columns={
        "created_at": "日時", "alert_type": "タイプ",
        "title": "タイトル", "score": "スコア",
    }),
    use_container_width=True, hide_index=True, height=500,
)

# 誤報マーク操作
st.markdown("---")
st.subheader("誤報フラグ操作")
alert_id = st.text_input("アラートIDを入力", key="fp_id")
if alert_id and st.button("誤報としてマーク"):
    ok = execute_sql("UPDATE alerts SET is_false_positive=1 WHERE id=?", (alert_id,))
    if ok:
        st.success(f"✓ {alert_id} を誤報マークしました。")
        st.rerun()
