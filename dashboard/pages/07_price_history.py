"""📉 価格推移グラフ"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df
from dashboard.components.filters import product_filter, source_filter
from dashboard.components.charts import price_history_chart

st.set_page_config(page_title="価格推移", page_icon="📉", layout="wide")
check_db()
st.title("📉 価格推移グラフ")

col1, col2 = st.columns(2)
with col1:
    product_id = product_filter("ph_product")
with col2:
    source_id = source_filter("ph_source")

if not product_id:
    st.info("商品を選択してください。")
    st.stop()

# 商品情報
product = query_df("SELECT * FROM products WHERE id=?", (product_id,))
if product.empty:
    st.error("商品が見つかりません。")
    st.stop()

p = product.iloc[0]
retail = int(p["official_price"] or p["retail_price"] or 0)

st.markdown(f"**{p['name']}** (定価: ¥{retail:,})" if retail else f"**{p['name']}** (定価: 未設定)")

# 価格履歴
where = "WHERE product_id=?"
params = [product_id]
if source_id:
    where += " AND source_id=?"
    params.append(source_id)

df = query_df(f"""
    SELECT recorded_at, price, price_type, source_id
    FROM price_history {where}
    ORDER BY recorded_at ASC
""", tuple(params))

if df.empty:
    st.info("価格履歴データなし。Collectorを実行してください。")
    st.stop()

fig = price_history_chart(df, retail_price=retail, product_name=p["name"])
st.plotly_chart(fig, use_container_width=True)

# データテーブル
st.subheader("データ一覧")
display = df.copy()
display["price"] = display["price"].apply(lambda x: f"¥{int(x):,}")
st.dataframe(
    display.rename(columns={
        "recorded_at": "日時", "price": "価格",
        "price_type": "種別", "source_id": "情報源",
    }),
    use_container_width=True, hide_index=True,
)
