"""📊 市場比較"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df, fmt_price
from dashboard.components.filters import product_filter

st.set_page_config(page_title="市場比較", page_icon="📊", layout="wide")
check_db()
st.title("📊 市場比較")

product_id = product_filter("mc_product")
if not product_id:
    st.info("商品を選択してください。")
    st.stop()

prod = query_df("SELECT * FROM products WHERE id=?", (product_id,))
if prod.empty:
    st.error("商品が見つかりません。")
    st.stop()
p = prod.iloc[0]

try:
    snaps = query_df(
        "SELECT * FROM market_snapshots WHERE product_id=? ORDER BY captured_at DESC LIMIT 5",
        (product_id,),
    )
except Exception:
    snaps = None

st.subheader(f"{p['name']}")
st.markdown(f"カテゴリ: {p['genre']} / ブランド: {p['brand']}")

# 価格比較カード
col1, col2, col3, col4 = st.columns(4)
with col1:
    official = p.get("official_price") or p.get("retail_price") or 0
    st.metric("公式定価", fmt_price(official))
with col2:
    if snaps is not None and not snaps.empty:
        st.metric("国内中古", fmt_price(snaps.iloc[0].get("domestic_used_price_jpy")))
    else:
        st.metric("国内中古", "---")
with col3:
    if snaps is not None and not snaps.empty:
        st.metric("国内買取", fmt_price(snaps.iloc[0].get("domestic_buyback_price_jpy")))
    else:
        st.metric("国内買取", "---")
with col4:
    if snaps is not None and not snaps.empty:
        st.metric("海外(JPY)", fmt_price(snaps.iloc[0].get("overseas_price_jpy")))
    else:
        st.metric("海外", "---")

if snaps is not None and not snaps.empty:
    s = snaps.iloc[0]
    st.markdown("---")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### 価格差")
        if s.get("premium_gap_jpy"):
            st.markdown(f"プレ値差額: **+¥{int(s['premium_gap_jpy']):,}** (+{s['premium_gap_percent']}%)")
        else:
            st.markdown("プレ値差額: なし")
        if s.get("overseas_gap_jpy"):
            st.markdown(f"海外差額: +¥{int(s['overseas_gap_jpy']):,} (+{s['overseas_gap_percent']}%)")

        st.markdown(f"在庫: {s.get('stock_status') or '不明'}")
        st.markdown(f"販売方式: {s.get('sale_method') or '不明'}")

    with col_b:
        st.markdown("### スコア")
        scores = {
            "価格差 (premium)": s.get("premium_score", 0),
            "希少性 (scarcity)": s.get("scarcity_score", 0),
            "流動性 (liquidity)": s.get("liquidity_score", 0),
            "海外差 (overseas)": s.get("overseas_gap_score", 0),
            "信頼度 (confidence)": s.get("source_confidence", 0),
        }
        for name, val in scores.items():
            bar = "█" * int(val * 10) + "░" * (10 - int(val * 10))
            st.markdown(f"`{bar}` {val:.1f} {name}")
        st.markdown(f"**OVERALL: {s.get('overall_score', 0):.2f}**")

# 情報源別価格履歴
st.markdown("---")
st.subheader("情報源別価格")
ph = query_df(
    "SELECT source_id, price_type, price, recorded_at FROM price_history WHERE product_id=? ORDER BY recorded_at DESC LIMIT 30",
    (product_id,),
)
if not ph.empty:
    ph["price"] = ph["price"].apply(lambda x: f"¥{int(x):,}")
    st.dataframe(
        ph.rename(columns={"source_id": "情報源", "price_type": "種別", "price": "価格", "recorded_at": "日時"}),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("価格履歴なし。")
