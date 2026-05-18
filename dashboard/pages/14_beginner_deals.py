"""Phase 9A: 初心者向け案件ダッシュボード"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df, fmt_price

st.set_page_config(page_title="初心者向け案件", page_icon="🟢", layout="wide")
check_db()
st.title("🟢 初心者向け案件（Beginner Deals）")

try:
    df = query_df("SELECT * FROM beginner_deals WHERE is_active = 1 ORDER BY net_profit_jpy DESC LIMIT 100")
except Exception:
    st.info("beginner_dealsテーブルなし。以下を実行してください:")
    st.code("python -m src.cli import-buyback-csv --file data/manual_buyback_prices.csv\npython -m src.cli scan-beginner-deals", language="bash")
    st.stop()

if df.empty:
    st.info("案件なし。買取データをインポートしてスキャンしてください。")
    st.code("python -m src.cli import-buyback-csv --file data/manual_buyback_prices.csv\npython -m src.cli scan-beginner-deals", language="bash")
    st.stop()

# ===== フィルタ =====
st.sidebar.markdown("### フィルタ")

# カテゴリ
categories = ["すべて"] + sorted(df["category"].dropna().unique().tolist())
cat_filter = st.sidebar.selectbox("カテゴリ", categories)
if cat_filter != "すべて":
    df = df[df["category"] == cat_filter]

# 利益フィルタ
profit_filter = st.sidebar.radio(
    "最低利益額",
    ["すべて", "¥5,000以上", "¥10,000以上", "¥20,000以上"],
)
if profit_filter == "¥5,000以上":
    df = df[df["net_profit_jpy"] >= 5000]
elif profit_filter == "¥10,000以上":
    df = df[df["net_profit_jpy"] >= 10000]
elif profit_filter == "¥20,000以上":
    df = df[df["net_profit_jpy"] >= 20000]

# user_level
level_filter = st.sidebar.radio("レベル", ["すべて", "beginner_easy", "beginner_watch"])
if level_filter != "すべて":
    df = df[df["user_level"] == level_filter]

# 買取店フィルタ
shops = ["すべて"] + sorted(df["best_buyback_shop"].dropna().unique().tolist())
shop_filter = st.sidebar.selectbox("買取店", shops)
if shop_filter != "すべて":
    df = df[df["best_buyback_shop"] == shop_filter]

# ブランドフィルタ
st.sidebar.markdown("### ショートカット")
if st.sidebar.button("Apple製品のみ"):
    df = df[df["brand"] == "Apple"]
if st.sidebar.button("ゲーム機のみ"):
    df = df[df["category"] == "game_console"]

# ソート
sort_option = st.sidebar.selectbox(
    "ソート",
    ["実質利益順", "利益率順", "更新日順", "公式価格順"],
)
if sort_option == "利益率順":
    df = df.sort_values("net_profit_rate", ascending=False)
elif sort_option == "更新日順":
    df = df.sort_values("scanned_at", ascending=False)
elif sort_option == "公式価格順":
    df = df.sort_values("official_price_jpy", ascending=True)
else:
    df = df.sort_values("net_profit_jpy", ascending=False)

if df.empty:
    st.info("条件に合う案件がありません。")
    st.stop()

# ===== サマリ =====
col1, col2, col3, col4 = st.columns(4)
with col1:
    easy = df[df["user_level"] == "beginner_easy"]
    st.metric("🟢 beginner_easy", f"{len(easy)} 件")
with col2:
    watch = df[df["user_level"] == "beginner_watch"]
    st.metric("🟡 beginner_watch", f"{len(watch)} 件")
with col3:
    avg_profit = int(df["net_profit_jpy"].mean()) if not df.empty else 0
    st.metric("平均実質利益", f"¥{avg_profit:,}")
with col4:
    max_profit = int(df["net_profit_jpy"].max()) if not df.empty else 0
    st.metric("最大実質利益", f"¥{max_profit:,}")

st.markdown("---")

# ===== テーブル =====
display = df.copy()
display["公式価格"] = display["official_price_jpy"].apply(fmt_price)
display["買取価格"] = display["best_buyback_price"].apply(fmt_price)
display["粗利"] = display["gross_profit_jpy"].apply(lambda x: f"+¥{x:,}" if x > 0 else "---")
display["コスト"] = display["estimated_costs_jpy"].apply(lambda x: f"-¥{x:,}" if x > 0 else "---")
display["実質利益"] = display["net_profit_jpy"].apply(lambda x: f"+¥{x:,}" if x > 0 else "---")
display["利益率"] = display["net_profit_rate"].apply(lambda x: f"{x:.1%}" if x > 0 else "---")

LEVEL_LABELS = {
    "beginner_easy": "🟢 beginner_easy",
    "beginner_watch": "🟡 beginner_watch",
    "advanced_high_profit": "🟠 advanced",
    "expert_only": "🔴 expert",
}
display["レベル"] = display["user_level"].map(LEVEL_LABELS).fillna("---")

ACTION_LABELS = {
    "check_official": "公式確認",
    "check_buyback": "買取確認",
    "watch_price": "価格監視",
    "lottery_only": "抽選のみ",
}
display["推奨"] = display["recommended_action"].map(ACTION_LABELS).fillna("---")
display["難易度"] = display["difficulty_score"].apply(lambda x: f"{x:.2f}")

st.dataframe(
    display[["product_name", "category", "brand", "レベル", "公式価格",
             "買取価格", "best_buyback_shop", "粗利", "コスト", "実質利益",
             "利益率", "buyback_condition", "難易度", "推奨"]].rename(columns={
        "product_name": "商品", "category": "カテゴリ", "brand": "ブランド",
        "best_buyback_shop": "買取店", "buyback_condition": "買取条件",
    }),
    use_container_width=True, hide_index=True, height=500,
)

# ===== 詳細カード =====
st.markdown("---")
st.subheader("案件詳細")

for _, row in df.head(10).iterrows():
    level = LEVEL_LABELS.get(row.get("user_level", ""), "---")
    with st.expander(f"{level} {row['product_name']} — 実質利益: +¥{row['net_profit_jpy']:,}"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("公式価格", fmt_price(row.get("official_price_jpy")))
        c2.metric("買取価格", fmt_price(row.get("best_buyback_price")))
        c3.metric("実質利益", f"+¥{row['net_profit_jpy']:,}")
        c4.metric("利益率", f"{row['net_profit_rate']:.1%}" if row.get("net_profit_rate") else "---")

        st.markdown(f"- **買取店**: {row.get('best_buyback_shop', '---')}")
        st.markdown(f"- **買取条件**: {row.get('buyback_condition', '---')}")
        st.markdown(f"- **販売方式**: {row.get('sale_method', '---')}")
        st.markdown(f"- **在庫**: {row.get('stock_status', '---') or '確認中'}")
        st.markdown(f"- **難易度**: {row.get('difficulty_score', 0):.2f}")
        st.markdown(f"- **推奨**: {ACTION_LABELS.get(row.get('recommended_action', ''), '---')}")

        if row.get("official_url"):
            st.markdown(f"- **公式購入URL**: {row['official_url']}")
        if row.get("best_buyback_url"):
            st.markdown(f"- **買取店URL**: {row['best_buyback_url']}")

        # コスト内訳
        st.markdown(f"- **コスト内訳**: 送料¥1,000 + 振込手数料¥300 + 移動¥500 = ¥{row.get('estimated_costs_jpy', 0):,}")
