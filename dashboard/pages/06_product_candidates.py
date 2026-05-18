"""🆕 新製品候補管理"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df, fmt_price, execute_sql

st.set_page_config(page_title="新製品候補", page_icon="🆕", layout="wide")
check_db()
st.title("🆕 新製品候補管理")

status_filter = st.selectbox("ステータス", ["全て", "pending", "approved", "rejected"])

try:
    where = ""
    params = []
    if status_filter != "全て":
        where = "WHERE status=?"
        params.append(status_filter)

    df = query_df(f"""
        SELECT id, source_id, product_name, detected_keyword, detected_url,
               detected_at, confidence, status, genre, brand, estimated_price, notes
        FROM product_candidates {where}
        ORDER BY detected_at DESC LIMIT 50
    """, tuple(params))
except Exception:
    st.info("product_candidatesテーブルが見つかりません。init-dbを再実行してください。")
    st.stop()

if df.empty:
    st.info("新製品候補なし。scan-new-productsを実行してください。")
    st.stop()

st.markdown(f"**{len(df)} 件**")

for _, r in df.iterrows():
    status_icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(r["status"], "❓")
    with st.expander(f"{status_icon} {r['product_name']} ({r['brand']}) - {r['detected_keyword']}"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"- **ソース**: {r['source_id']}")
            st.markdown(f"- **キーワード**: {r['detected_keyword']}")
            st.markdown(f"- **ジャンル**: {r['genre']}")
            st.markdown(f"- **ブランド**: {r['brand']}")
        with col2:
            st.markdown(f"- **推定価格**: {fmt_price(r['estimated_price'])}")
            st.markdown(f"- **信頼度**: {r['confidence']:.0%}")
            st.markdown(f"- **検出日時**: {r['detected_at']}")
            if r["detected_url"]:
                st.markdown(f"- **URL**: {r['detected_url']}")

        st.markdown(f"- **ID**: `{r['id']}`")

        if r["status"] == "pending":
            bc1, bc2 = st.columns(2)
            with bc1:
                if st.button("✅ 承認", key=f"approve_{r['id']}"):
                    ok = execute_sql(
                        "UPDATE product_candidates SET status='approved', reviewed_at=datetime('now') WHERE id=?",
                        (r["id"],),
                    )
                    if ok:
                        st.success("承認しました。products.yamlに追加してseedしてください。")
                        st.rerun()
            with bc2:
                if st.button("❌ 却下", key=f"reject_{r['id']}"):
                    ok = execute_sql(
                        "UPDATE product_candidates SET status='rejected', reviewed_at=datetime('now') WHERE id=?",
                        (r["id"],),
                    )
                    if ok:
                        st.warning("却下しました。")
                        st.rerun()
