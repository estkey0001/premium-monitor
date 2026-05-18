"""🏆 利益ランキング"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df, fmt_price

st.set_page_config(page_title="利益ランキング", page_icon="🏆", layout="wide")
check_db()
st.title("🏆 利益ランキング")

df = query_df("""
    SELECT a.alert_rank, a.alert_type, a.title, a.estimated_profit,
           a.confidence, a.score, a.body, a.created_at, a.product_id,
           p.name as product_name, p.retail_price, p.official_price,
           p.genre, p.brand,
           o.price as obs_price, o.is_in_stock, o.source_id
    FROM alerts a
    JOIN products p ON p.id = a.product_id
    LEFT JOIN observations o ON o.id = a.observation_id
    WHERE a.estimated_profit IS NOT NULL AND a.estimated_profit > 0
    ORDER BY a.estimated_profit DESC
    LIMIT 50
""")

if df.empty:
    st.info("利益データなし。Collectorを実行してからscore-latestを実行してください。")
    st.stop()

# 在庫あり / なしに分離
in_stock = df[df["is_in_stock"] == 1]
out_of_stock = df[df["is_in_stock"] != 1]

st.subheader("🟢 在庫あり・購入可能")
if not in_stock.empty:
    display = in_stock.copy()
    display["定価"] = display.apply(lambda r: fmt_price(r["official_price"] or r["retail_price"]), axis=1)
    display["取得価格"] = display["obs_price"].apply(fmt_price)
    display["想定利益"] = display["estimated_profit"].apply(lambda x: f"+¥{int(x):,}")
    display["在庫"] = "🟢 あり"
    display["信頼度"] = display["confidence"].apply(lambda x: f"{x:.0%}" if x else "---")
    rank_icons = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "⚪"}
    display["Rank"] = display["alert_rank"].apply(lambda x: f"{rank_icons.get(x, '')} {x}")

    # URLをbodyから抽出
    display["URL"] = display["body"].apply(
        lambda b: next((l.split(":", 1)[1].strip() for l in (b or "").split("\n") if l.startswith("URL:")), "")
    )

    st.dataframe(
        display[["Rank", "product_name", "source_id", "定価", "取得価格",
                 "想定利益", "在庫", "信頼度", "URL"]].rename(columns={
            "product_name": "商品", "source_id": "情報源",
        }),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("在庫あり商品の利益データなし。")

st.markdown("---")
st.subheader("🔴 在庫なし・SOLD OUT・販売休止中")
if not out_of_stock.empty:
    display2 = out_of_stock.copy()
    display2["定価"] = display2.apply(lambda r: fmt_price(r["official_price"] or r["retail_price"]), axis=1)
    display2["取得価格"] = display2["obs_price"].apply(fmt_price)
    display2["想定利益"] = display2["estimated_profit"].apply(lambda x: f"+¥{int(x):,}" if x > 0 else f"¥{int(x):,}")
    display2["在庫"] = "🔴 なし"
    display2["信頼度"] = display2["confidence"].apply(lambda x: f"{x:.0%}" if x else "---")
    rank_icons = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "⚪"}
    display2["Rank"] = display2["alert_rank"].apply(lambda x: f"{rank_icons.get(x, '')} {x}")

    st.dataframe(
        display2[["Rank", "product_name", "source_id", "定価", "取得価格",
                  "想定利益", "在庫", "信頼度"]].rename(columns={
            "product_name": "商品", "source_id": "情報源",
        }),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("在庫なし商品の利益データなし。")
