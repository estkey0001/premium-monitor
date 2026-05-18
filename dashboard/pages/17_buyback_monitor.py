"""Phase 10修正: 買取価格モニター"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df, fmt_price

st.set_page_config(page_title="買取価格モニター", page_icon="📊", layout="wide")
check_db()
st.title("📊 買取価格モニター")

# ===== 急騰急落アラート =====
st.subheader("買取価格 急騰・急落アラート")
try:
    alerts_df = query_df("SELECT * FROM buyback_alerts ORDER BY detected_at DESC LIMIT 20")
    if alerts_df.empty:
        st.info("急変アラートなし（閾値: ±¥5,000）")
    else:
        for _, row in alerts_df.iterrows():
            icon = "📈" if row["alert_type"] == "buyback_surge" else "📉"
            color = "green" if row["alert_type"] == "buyback_surge" else "red"
            st.markdown(
                f"{icon} **{row['product_name']}** @ {row['shop_name']}: "
                f"¥{row['previous_price']:,} → ¥{row['current_price']:,} "
                f"(:{color}[{row['price_change']:+,}])"
            )
except Exception:
    st.info("buyback_alertsテーブルなし。`run-buyback-premium-check` を実行してください。")

st.markdown("---")

# ===== 買取価格推移 =====
st.subheader("買取価格推移")
try:
    history_df = query_df("""
        SELECT product_id, shop_name, price, condition, observed_at
        FROM buyback_history ORDER BY observed_at DESC LIMIT 200
    """)
    if history_df.empty:
        st.info("買取履歴なし。")
    else:
        products = sorted(history_df["product_id"].unique().tolist())
        selected = st.selectbox("商品", products)
        filtered = history_df[history_df["product_id"] == selected]

        if not filtered.empty:
            # 店舗別比較テーブル
            latest = filtered.drop_duplicates(subset=["shop_name"], keep="first")
            latest_sorted = latest.sort_values("price", ascending=False)
            display = latest_sorted.copy()
            display["買取価格"] = display["price"].apply(lambda x: f"¥{x:,}")
            st.dataframe(
                display[["shop_name", "買取価格", "condition", "observed_at"]].rename(columns={
                    "shop_name": "店舗", "condition": "条件", "observed_at": "取得日時",
                }),
                use_container_width=True, hide_index=True,
            )

            # チャート
            if len(filtered) > 1:
                import pandas as pd
                filtered = filtered.copy()
                filtered["observed_at"] = pd.to_datetime(filtered["observed_at"])
                chart_data = filtered.pivot_table(
                    index="observed_at", columns="shop_name", values="price", aggfunc="last"
                )
                st.line_chart(chart_data)
except Exception as e:
    st.info(f"buyback_historyテーブルなし: {e}")

st.markdown("---")

# ===== 実質利益ランキング =====
st.subheader("実質利益ランキング")
try:
    deals_df = query_df("""
        SELECT product_name, brand, official_price_jpy, best_buyback_price,
               best_buyback_shop, net_profit_jpy, net_profit_rate, user_level,
               difficulty_score, buyback_condition
        FROM beginner_deals
        WHERE is_active = 1 AND net_profit_jpy > 0
        ORDER BY net_profit_jpy DESC LIMIT 20
    """)
    if deals_df.empty:
        st.info("案件なし。")
    else:
        display = deals_df.copy()
        display["公式価格"] = display["official_price_jpy"].apply(fmt_price)
        display["買取価格"] = display["best_buyback_price"].apply(fmt_price)
        display["実質利益"] = display["net_profit_jpy"].apply(lambda x: f"+¥{x:,}")
        display["利益率"] = display["net_profit_rate"].apply(lambda x: f"{x:.1%}" if x else "---")
        LEVEL_LABELS = {
            "beginner_easy": "🟢", "beginner_watch": "🟡",
            "advanced_high_profit": "🟠", "expert_only": "🔴",
        }
        display["Lv"] = display["user_level"].map(LEVEL_LABELS).fillna("")
        st.dataframe(
            display[["Lv", "product_name", "公式価格", "買取価格", "best_buyback_shop",
                      "実質利益", "利益率", "buyback_condition"]].rename(columns={
                "product_name": "商品", "best_buyback_shop": "買取店",
                "buyback_condition": "条件",
            }),
            use_container_width=True, hide_index=True, height=400,
        )
except Exception as e:
    st.info(f"beginner_dealsテーブルなし: {e}")

st.markdown("---")

# ===== スケジューラ状態 =====
st.subheader("スケジューラ状態")
st.markdown("""
**統合ジョブ (買取+プレ値):** 10:00 / 12:00 / 18:00 JST
**在庫監視:** 60分間隔
**通知再送:** 10分間隔
**新製品スキャン:** 180分間隔
""")
st.code("python -m src.cli run-buyback-premium-check  # 手動実行", language="bash")
