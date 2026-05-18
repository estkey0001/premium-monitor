"""📥 CSVインポート"""

import streamlit as st
from pathlib import Path
from dashboard.components.db_helper import check_db, query_df

st.set_page_config(page_title="CSVインポート", page_icon="📥", layout="wide")
check_db()
st.title("📥 市場価格CSVインポート")

st.markdown("""
### CSV形式
```
product_alias,source,price_type,price,currency,condition,is_sold,url,observed_at
gr4,ebay,overseas,1850,USD,new,true,https://example.com,2026-05-18T10:00:00
x100vi,mercari,used,480000,JPY,used,false,https://example.com,2026-05-18T11:00:00
```

**price_type**: overseas / used / buyback / retail / market
**currency**: JPY / USD / EUR / GBP / HKD / CNY
""")

uploaded = st.file_uploader("CSVファイルを選択", type=["csv"])

if uploaded:
    content = uploaded.read().decode("utf-8")
    st.subheader("プレビュー")

    import csv, io
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    st.dataframe(rows, use_container_width=True)
    st.markdown(f"**{len(rows)} 行**")

    if st.button("📥 インポート実行", type="primary"):
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
            from src.db.database import Database
            from src.db.repository import Repository
            from src.market.csv_importer import CSVImporter

            PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
            db = Database(db_path="data/premium_monitor.db")
            db.db_path = PROJECT_ROOT / "data" / "premium_monitor.db"
            db.init_schema()
            repo = Repository(db)
            imp = CSVImporter(repository=repo)
            result = imp.import_csv(content)
            db.close()

            if result["imported"] > 0:
                st.success(f"✅ {result['imported']} 件インポートしました。")
            if result["skipped"] > 0:
                st.warning(f"⚠️ {result['skipped']} 件スキップ。")
            if result["errors"]:
                for e in result["errors"]:
                    st.error(e)
        except Exception as e:
            st.error(f"インポートエラー: {e}")

# インポート履歴
st.markdown("---")
st.subheader("最近のインポート（CSV由来）")
try:
    recent = query_df("""
        SELECT product_id, source_id, observation_type, price, observed_at, raw_text
        FROM observations WHERE raw_text LIKE '%csv_import%'
        ORDER BY observed_at DESC LIMIT 20
    """)
    if not recent.empty:
        recent["price"] = recent["price"].apply(lambda x: f"¥{int(x):,}" if x else "---")
        st.dataframe(recent.rename(columns={
            "product_id": "商品", "source_id": "ソース", "observation_type": "タイプ",
            "price": "価格", "observed_at": "日時", "raw_text": "備考",
        }), use_container_width=True, hide_index=True)
    else:
        st.info("CSVインポート履歴なし。")
except Exception:
    st.info("データなし。")
