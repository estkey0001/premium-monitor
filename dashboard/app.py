"""プレ値商品監視システム - Streamlit管理画面。

起動: streamlit run dashboard/app.py
"""

import streamlit as st

st.set_page_config(
    page_title="プレ値商品監視システム",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.title("📊 プレ値商品監視")
st.sidebar.markdown("---")
st.sidebar.markdown("""
**メニュー**
- 📈 ダッシュボード
- 📦 商品管理
- 💰 公式価格管理
- 🔔 アラート一覧
- 🏆 利益ランキング
- 🆕 新製品候補
- 📉 価格推移グラフ
- 📋 実行ログ
""")
st.sidebar.markdown("---")
st.sidebar.caption("← 左メニューからページを選択")

st.title("📊 プレ値商品監視システム")
st.markdown("左のサイドバーからページを選択してください。")

from dashboard.components.db_helper import check_db, query_df, fmt_price
check_db()

# トップページにサマリKPIを表示
col1, col2, col3, col4 = st.columns(4)
with col1:
    n = query_df("SELECT COUNT(*) as c FROM products WHERE is_active=1")
    st.metric("監視商品", f"{n['c'].iloc[0]} 件" if not n.empty else "0")
with col2:
    n = query_df("SELECT COUNT(*) as c FROM sources WHERE is_active=1")
    st.metric("情報源", f"{n['c'].iloc[0]} 件" if not n.empty else "0")
with col3:
    n = query_df("SELECT COUNT(*) as c FROM alerts WHERE alert_rank IN ('S','A')")
    st.metric("S/Aアラート", f"{n['c'].iloc[0]} 件" if not n.empty else "0")
with col4:
    n = query_df("SELECT COUNT(*) as c FROM products WHERE retail_price_update_candidate=1")
    st.metric("定価更新候補", f"{n['c'].iloc[0]} 件" if not n.empty else "0")

st.markdown("---")
st.subheader("直近S/Aアラート")
alerts = query_df("""
    SELECT a.created_at, a.alert_rank, a.alert_type, a.title,
           a.estimated_profit, a.confidence, a.sent_channels
    FROM alerts a WHERE a.alert_rank IN ('S','A')
    ORDER BY a.created_at DESC LIMIT 10
""")
if not alerts.empty:
    for _, row in alerts.iterrows():
        rank_icon = "🔴" if row["alert_rank"] == "S" else "🟠"
        profit = fmt_price(row["estimated_profit"]) if row["estimated_profit"] else "---"
        sent = row["sent_channels"] or "---"
        st.markdown(
            f"{rank_icon} **[{row['alert_rank']}]** {row['title']}　"
            f"利益: {profit}　信頼度: {row['confidence']:.0%}　"
            f"送信: {sent}　_{row['created_at']}_"
        )
else:
    st.info("S/Aアラートはまだありません。")
