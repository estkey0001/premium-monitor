"""📈 ダッシュボード"""

import streamlit as st
from pathlib import Path
import yaml

from dashboard.components.db_helper import check_db, query_df, fmt_price
from dashboard.components.charts import rank_pie_chart

st.set_page_config(page_title="ダッシュボード", page_icon="📈", layout="wide")
check_db()
st.title("📈 ダッシュボード")

# === Scheduler Status ===
STATUS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "scheduler_status.yaml"
sched_status = {}
if STATUS_FILE.exists():
    try:
        with open(STATUS_FILE) as f:
            sched_status = yaml.safe_load(f) or {}
    except Exception:
        pass

running = sched_status.get("scheduler_running", False)
st.markdown(
    f"**Scheduler:** {'🟢 稼働中' if running else '🔴 停止中'}"
    f"　最終更新: {sched_status.get('updated_at', 'N/A')}"
)

# === KPI ===
c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1:
    v = query_df("SELECT COUNT(*) c FROM products WHERE is_active=1")["c"].iloc[0]
    st.metric("監視商品", f"{v}")
with c2:
    v = query_df("SELECT COUNT(*) c FROM sources WHERE is_active=1")["c"].iloc[0]
    st.metric("情報源", f"{v}")
with c3:
    v = query_df("SELECT COUNT(*) c FROM observations")["c"].iloc[0]
    st.metric("観測数", f"{v}")
with c4:
    v = query_df("SELECT COUNT(*) c FROM products WHERE official_price IS NOT NULL AND official_price>0")["c"].iloc[0]
    st.metric("公式価格取得済", f"{v}")
with c5:
    v = query_df("SELECT COUNT(*) c FROM products WHERE retail_price_update_candidate=1")["c"].iloc[0]
    st.metric("定価更新候補", f"{v}")
with c6:
    try:
        v = query_df("SELECT COUNT(*) c FROM product_candidates WHERE status='pending'")["c"].iloc[0]
    except Exception:
        v = 0
    st.metric("新製品候補", f"{v}")

st.markdown("---")

# === ジョブ状況 ===
jobs = sched_status.get("jobs", {})
if jobs:
    st.subheader("ジョブ実行状況")
    job_cols = st.columns(min(len([j for j in jobs if not j.startswith("_")]), 5))
    i = 0
    for name, info in jobs.items():
        if name.startswith("_"):
            continue
        s = info.get("status", "?")
        icon = "✅" if s == "success" else "❌"
        with job_cols[i % len(job_cols)]:
            st.markdown(f"{icon} **{name}**")
            st.caption(f"{info.get('last_run', 'N/A')[:19]}")
        i += 1
    st.markdown("---")

# === Collector失敗警告 ===
try:
    health_df = query_df("""
        SELECT h.* FROM source_health h
        INNER JOIN sources s ON s.id = h.source_id
        WHERE h.consecutive_errors >= 3 OR h.auto_disabled=1
    """)
    if not health_df.empty:
        st.subheader("⚠️ Collector失敗警告")
        for _, h in health_df.iterrows():
            icon = "🚫" if h.get("auto_disabled") else "⚠️"
            st.warning(
                f"{icon} **{h['source_id']}** "
                f"連続エラー: {h['consecutive_errors']}回 "
                f"{'(自動無効化候補)' if h.get('auto_disabled') else ''}"
            )
        st.markdown("---")
except Exception:
    pass

# === ランク別 ===
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("ランク別アラート")
    rank_df = query_df("SELECT alert_rank, COUNT(*) as count FROM alerts GROUP BY alert_rank ORDER BY alert_rank")
    if not rank_df.empty:
        st.plotly_chart(rank_pie_chart(rank_df), use_container_width=True)
    else:
        st.info("アラートなし")

with col_b:
    st.subheader("直近S/Aアラート")
    alerts = query_df("""
        SELECT created_at, alert_rank, title, estimated_profit, confidence
        FROM alerts WHERE alert_rank IN ('S','A') ORDER BY created_at DESC LIMIT 10
    """)
    if not alerts.empty:
        for _, r in alerts.iterrows():
            icon = "🔴" if r["alert_rank"] == "S" else "🟠"
            profit = fmt_price(r["estimated_profit"])
            st.markdown(f"{icon} **{r['title']}** 利益:{profit} 信頼度:{r['confidence']:.0%}")
    else:
        st.info("S/Aアラートなし")

# === Collector稼働状況 ===
st.markdown("---")
st.subheader("Collector稼働状況")
logs = query_df("""
    SELECT source_id,
           COUNT(*) as total,
           SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
           SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
           MAX(started_at) as last_run
    FROM collector_logs GROUP BY source_id ORDER BY last_run DESC
""")
if not logs.empty:
    logs["成功率"] = (logs["success"] / logs["total"] * 100).round(1).astype(str) + "%"
    st.dataframe(logs.rename(columns={
        "source_id": "情報源", "total": "実行数", "success": "成功",
        "errors": "エラー", "last_run": "最終実行"
    }), use_container_width=True, hide_index=True)
else:
    st.info("Collector実行ログなし")
