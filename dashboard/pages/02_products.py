"""📦 商品管理"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df, fmt_price, execute_sql
from dashboard.components.filters import genre_filter, brand_filter

st.set_page_config(page_title="商品管理", page_icon="📦", layout="wide")
check_db()
st.title("📦 商品管理")

col1, col2 = st.columns(2)
with col1:
    genre = genre_filter("prod_genre")
with col2:
    brand = brand_filter("prod_brand")

where = "WHERE is_active=1"
params = []
if genre:
    where += " AND genre=?"
    params.append(genre)
if brand:
    where += " AND brand=?"
    params.append(brand)

df = query_df(f"""
    SELECT id, genre, brand, name, retail_price, official_price,
           official_price_source, official_stock_status, is_lottery,
           is_discontinued, retail_price_update_candidate, memo
    FROM products {where}
    ORDER BY
        CASE WHEN name LIKE '%GR IV%' THEN 0
             WHEN name LIKE '%GR III%' THEN 1
             ELSE 2 END,
        genre, name
""", tuple(params))

if df.empty:
    st.info("商品が見つかりません。")
    st.stop()

st.markdown(f"**{len(df)} 件**")

# 表示用加工
display = df.copy()
display["定価"] = display["retail_price"].apply(fmt_price)
display["公式定価"] = display["official_price"].apply(fmt_price)
display["在庫"] = display["official_stock_status"].fillna("---")
display["抽選"] = display["is_lottery"].apply(lambda x: "🎰 抽選中" if x else "")
display["終了"] = display["is_discontinued"].apply(lambda x: "⛔ 終了" if x else "")
display["更新候補"] = display["retail_price_update_candidate"].apply(lambda x: "⭐" if x else "")

st.dataframe(
    display[["id", "genre", "brand", "name", "定価", "公式定価",
             "在庫", "抽選", "終了", "更新候補", "memo"]].rename(columns={
        "id": "商品ID", "genre": "ジャンル", "brand": "ブランド",
        "name": "商品名", "memo": "メモ",
    }),
    use_container_width=True, hide_index=True, height=500,
)

# 定価更新候補の一括表示
candidates = df[df["retail_price_update_candidate"] == 1]
if not candidates.empty:
    st.markdown("---")
    st.subheader("⭐ 定価更新候補")
    for _, r in candidates.iterrows():
        st.markdown(
            f"**{r['name']}**: DB=¥{r['retail_price']:,} → 公式=¥{r['official_price']:,} "
            f"(取得元: {r['official_price_source']})"
        )
        if st.button(f"¥{r['official_price']:,} に更新", key=f"upd_{r['id']}"):
            ok = execute_sql(
                "UPDATE products SET retail_price=?, official_price=?, retail_price_update_candidate=0, updated_at=datetime('now') WHERE id=?",
                (r["official_price"], r["official_price"], r["id"]),
            )
            if ok:
                st.success(f"✓ {r['name']} の定価を ¥{r['official_price']:,} に更新しました。")
                st.rerun()
