"""📋 実行ログ"""

import streamlit as st
from dashboard.components.db_helper import check_db, query_df
from dashboard.components.filters import source_filter

st.set_page_config(page_title="実行ログ", page_icon="📋", layout="wide")
check_db()
st.title("📋 Collector実行ログ")

source_id = source_filter("log_source")

# サマリ
st.subheader("情報源別成功率")
summary = query_df("""
    SELECT source_id,
           COUNT(*) as total,
           SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
           SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
           SUM(CASE WHEN status='timeout' THEN 1 ELSE 0 END) as timeouts,
           ROUND(AVG(duration_ms)) as avg_ms,
           MAX(started_at) as last_run
    FROM collector_logs GROUP BY source_id ORDER BY source_id
""")

if not summary.empty:
    summary["成功率"] = (summary["success"] / summary["total"] * 100).round(1).astype(str) + "%"
    summary["平均時間"] = summary["avg_ms"].apply(lambda x: f"{int(x)}ms" if x else "---")
    st.dataframe(
        summary[["source_id", "total", "success", "errors", "timeouts",
                 "成功率", "平均時間", "last_run"]].rename(columns={
            "source_id": "情報源", "total": "実行数", "success": "成功",
            "errors": "エラー", "timeouts": "タイムアウト", "last_run": "最終実行",
        }),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("ログなし。")

# 詳細ログ
st.markdown("---")
st.subheader("詳細ログ")

where = ""
params = []
if source_id:
    where = "WHERE source_id=?"
    params.append(source_id)

status_filter = st.selectbox("ステータス", ["全て", "success", "error", "timeout", "skipped"], key="log_status")
if status_filter != "全て":
    where = (where + " AND " if where else "WHERE ") + "status=?"
    params.append(status_filter)

logs = query_df(f"""
    SELECT id, source_id, product_id, started_at, finished_at,
           status, http_status, error_message, duration_ms
    FROM collector_logs {where}
    ORDER BY started_at DESC LIMIT 100
""", tuple(params))

if not logs.empty:
    st.markdown(f"**{len(logs)} 件**")

    # ステータス別色分け
    display = logs.copy()
    status_icons = {"success": "✅", "error": "❌", "timeout": "⏰", "skipped": "⏭️"}
    display["状態"] = display["status"].apply(lambda x: f"{status_icons.get(x, '❓')} {x}")
    display["時間"] = display["duration_ms"].apply(lambda x: f"{int(x)}ms" if x else "---")

    st.dataframe(
        display[["started_at", "source_id", "product_id", "状態",
                 "http_status", "error_message", "時間"]].rename(columns={
            "started_at": "開始日時", "source_id": "情報源",
            "product_id": "商品ID", "http_status": "HTTP",
            "error_message": "エラー",
        }),
        use_container_width=True, hide_index=True, height=500,
    )

    # エラー一覧
    errors = logs[logs["status"] == "error"]
    if not errors.empty:
        st.markdown("---")
        st.subheader("❌ エラー詳細")
        for _, r in errors.head(10).iterrows():
            st.error(f"**{r['source_id']}** ({r['started_at']}): {r['error_message']}")
else:
    st.info("該当ログなし。")
