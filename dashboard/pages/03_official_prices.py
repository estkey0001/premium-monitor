"""💰 公式価格管理"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df, fmt_price, execute_sql

st.set_page_config(page_title="公式価格管理", page_icon="💰", layout="wide")
check_db()
st.title("💰 公式価格管理")

show_candidates_only = st.checkbox("定価更新候補のみ表示", value=False)

where = "WHERE retail_price_update_candidate=1" if show_candidates_only else ""
df = query_df(f"""
    SELECT id, name, brand, genre, retail_price, official_price,
           official_price_source, official_price_updated_at,
           official_stock_status, is_lottery, is_discontinued,
           retail_price_update_candidate
    FROM products {where}
    ORDER BY retail_price_update_candidate DESC, name
""")

if df.empty:
    st.info("該当商品なし。")
    st.stop()

# 差額計算
df["差額"] = df.apply(
    lambda r: (r["official_price"] - r["retail_price"])
    if r["official_price"] and r["retail_price"] and r["official_price"] > 0 and r["retail_price"] > 0
    else None, axis=1
)

display = df.copy()
display["DB定価"] = display["retail_price"].apply(fmt_price)
display["公式定価"] = display["official_price"].apply(fmt_price)
display["差額表示"] = display["差額"].apply(lambda x: f"+¥{int(x):,}" if x and x > 0 else (f"¥{int(x):,}" if x and x < 0 else ("±0" if x == 0 else "---")))
display["在庫"] = display["official_stock_status"].fillna("---")
display["抽選"] = display["is_lottery"].apply(lambda x: "🎰" if x else "")
display["候補"] = display["retail_price_update_candidate"].apply(lambda x: "⭐" if x else "")
display["取得元"] = display["official_price_source"].fillna("---")
display["取得日時"] = display["official_price_updated_at"].fillna("---")

st.dataframe(
    display[["候補", "name", "brand", "DB定価", "公式定価", "差額表示",
             "取得元", "取得日時", "在庫", "抽選"]].rename(columns={
        "name": "商品名", "brand": "ブランド",
    }),
    use_container_width=True, hide_index=True,
)

# 更新操作
candidates = df[df["retail_price_update_candidate"] == 1]
if not candidates.empty:
    st.markdown("---")
    st.subheader("⭐ 定価更新操作")
    for _, r in candidates.iterrows():
        with st.expander(f"{r['name']}: ¥{r['retail_price']:,} → ¥{r['official_price']:,}"):
            st.markdown(f"- 取得元: {r['official_price_source']}")
            st.markdown(f"- 取得日時: {r['official_price_updated_at']}")
            st.markdown(f"- 在庫: {r['official_stock_status']}")
            if st.button(f"✓ 公式価格で更新", key=f"off_upd_{r['id']}"):
                ok = execute_sql(
                    "UPDATE products SET retail_price=?, retail_price_update_candidate=0, updated_at=datetime('now') WHERE id=?",
                    (r["official_price"], r["id"]),
                )
                if ok:
                    st.success(f"✓ {r['name']} を ¥{r['official_price']:,} に更新しました。")
                    st.rerun()
