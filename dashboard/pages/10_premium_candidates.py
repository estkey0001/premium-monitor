"""★ プレ値候補一覧（Phase 7B-2: 初心者/上級者分類対応）"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df, fmt_price

st.set_page_config(page_title="プレ値候補", page_icon="★", layout="wide")
check_db()
st.title("★ プレ値候補一覧")

try:
    df = query_df("""
        SELECT * FROM market_snapshots
        WHERE premium_score > 0.2 OR scarcity_score > 0.4
              OR (user_level = 'beginner_easy' AND beginner_profit_score > 0)
        ORDER BY overall_score DESC LIMIT 100
    """)
except Exception:
    st.info("market_snapshotsテーブルなし。`scan-category --category all` を実行してください。")
    st.stop()

if df.empty:
    st.info("プレ値候補なし。`scan-category --category all` を実行してください。")
    st.stop()

# ===== フィルタ =====
st.sidebar.markdown("### フィルタ")

# user_levelフィルタ
level_filter = st.sidebar.radio(
    "ユーザーレベル",
    ["すべて", "初心者向け", "上級者向け"],
    index=0,
)

if level_filter == "初心者向け":
    df = df[df["user_level"].isin(["beginner_easy", "beginner_watch"])]
elif level_filter == "上級者向け":
    df = df[df["user_level"].isin(["advanced_high_profit", "expert_only"])]

# カテゴリフィルタ
categories = ["すべて"] + sorted(df["category"].dropna().unique().tolist())
cat_filter = st.sidebar.selectbox("カテゴリ", categories)
if cat_filter != "すべて":
    df = df[df["category"] == cat_filter]

# ソート
sort_option = st.sidebar.selectbox(
    "ソート",
    ["総合スコア順", "利益額順", "入手難易度順（低→高）", "初心者スコア順", "プレ値%順"],
)

if sort_option == "利益額順":
    df["_profit"] = df.apply(
        lambda r: (r["domestic_buyback_price_jpy"] or 0) - (r["official_price_jpy"] or 0)
        if (r["domestic_buyback_price_jpy"] or 0) > (r["official_price_jpy"] or 0)
        else (r["premium_gap_jpy"] or 0),
        axis=1,
    )
    df = df.sort_values("_profit", ascending=False)
elif sort_option == "入手難易度順（低→高）":
    df = df.sort_values("difficulty_score", ascending=True)
elif sort_option == "初心者スコア順":
    df = df.sort_values("beginner_score", ascending=False)
elif sort_option == "プレ値%順":
    df = df.sort_values("premium_gap_percent", ascending=False, na_position="last")
else:
    df = df.sort_values("overall_score", ascending=False)

if df.empty:
    st.info("条件に合う候補がありません。")
    st.stop()

st.markdown(f"**{len(df)} 件のプレ値候補**")

# ===== サマリ =====
col1, col2, col3, col4 = st.columns(4)
with col1:
    beginner_easy = df[df["user_level"] == "beginner_easy"]
    st.metric("🟢 初心者向け", f"{len(beginner_easy)} 件")
with col2:
    beginner_watch = df[df["user_level"] == "beginner_watch"]
    st.metric("🟡 要ウォッチ", f"{len(beginner_watch)} 件")
with col3:
    advanced = df[df["user_level"] == "advanced_high_profit"]
    st.metric("🟠 上級者向け", f"{len(advanced)} 件")
with col4:
    expert = df[df["user_level"] == "expert_only"]
    st.metric("🔴 エキスパート", f"{len(expert)} 件")

st.markdown("---")

# ===== テーブル =====
display = df.copy()
display["公式定価"] = display["official_price_jpy"].apply(fmt_price)
display["中古価格"] = display["domestic_used_price_jpy"].apply(fmt_price)
display["買取価格"] = display["domestic_buyback_price_jpy"].apply(fmt_price)
display["海外(JPY)"] = display["overseas_price_jpy"].apply(fmt_price)
display["プレ値%"] = display["premium_gap_percent"].apply(
    lambda x: f"+{x}%" if x and x > 0 else "---"
)

# 想定利益（買取-定価）
def calc_profit(row):
    official = row.get("official_price_jpy") or 0
    buyback = row.get("domestic_buyback_price_jpy") or 0
    if buyback > official and official > 0:
        return f"+¥{buyback - official:,}"
    prem = row.get("premium_gap_jpy") or 0
    if prem > 0:
        return f"+¥{prem:,}"
    return "---"

display["想定利益"] = display.apply(calc_profit, axis=1)
display["方式"] = display["sale_method"].fillna("---")
display["Overall"] = display["overall_score"].apply(lambda x: f"{x:.2f}")

# user_levelラベル
LEVEL_LABELS = {
    "beginner_easy": "🟢 初心者向け",
    "beginner_watch": "🟡 要ウォッチ",
    "advanced_high_profit": "🟠 上級者向け",
    "expert_only": "🔴 エキスパート",
}
display["レベル"] = display["user_level"].map(LEVEL_LABELS).fillna("---")

ACTION_LABELS = {
    "check_official": "公式確認",
    "check_buyback": "買取確認",
    "watch_price": "価格監視",
    "lottery_only": "抽選のみ",
    "avoid": "非推奨",
}
display["推奨"] = display["recommended_action"].map(ACTION_LABELS).fillna("---")

display["難易度"] = display["difficulty_score"].apply(lambda x: f"{x:.2f}")
display["初心者"] = display["beginner_score"].apply(lambda x: f"{x:.2f}")

st.dataframe(
    display[["product_name", "category", "brand", "レベル", "公式定価",
             "買取価格", "中古価格", "想定利益", "プレ値%", "方式",
             "難易度", "初心者", "推奨", "Overall"]].rename(columns={
        "product_name": "商品", "category": "カテゴリ", "brand": "ブランド",
    }),
    use_container_width=True, hide_index=True, height=600,
)

# ===== 初心者向け詳細セクション =====
if level_filter == "初心者向け" or level_filter == "すべて":
    beginner_df = df[df["user_level"].isin(["beginner_easy", "beginner_watch"])]
    if not beginner_df.empty:
        st.markdown("---")
        st.subheader("🟢 初心者向け候補の詳細")
        for _, row in beginner_df.iterrows():
            official = row.get("official_price_jpy") or 0
            buyback = row.get("domestic_buyback_price_jpy") or 0
            profit = buyback - official if buyback > official else 0
            level = LEVEL_LABELS.get(row.get("user_level", ""), "---")

            with st.expander(f"{level} {row['product_name']} — 想定利益: +¥{profit:,}" if profit > 0 else f"{level} {row['product_name']}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("公式定価", f"¥{official:,}" if official else "不明")
                c2.metric("買取価格", f"¥{buyback:,}" if buyback else "データなし")
                c3.metric("想定利益", f"+¥{profit:,}" if profit > 0 else "---")

                st.markdown(f"- **販売方式**: {row.get('sale_method', '---')}")
                st.markdown(f"- **難易度スコア**: {row.get('difficulty_score', 0):.2f}")
                st.markdown(f"- **初心者スコア**: {row.get('beginner_score', 0):.2f}")
                st.markdown(f"- **推奨アクション**: {ACTION_LABELS.get(row.get('recommended_action', ''), '---')}")
