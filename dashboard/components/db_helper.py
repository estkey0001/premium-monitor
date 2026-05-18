"""DB接続ヘルパー。全画面で共有する。"""

import sqlite3
import sys
from pathlib import Path

import streamlit as st
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "premium_monitor.db"


def get_db_path() -> Path:
    """DBパスを返す。"""
    return DB_PATH


def check_db():
    """DBの存在確認。なければ案内を表示してstop。"""
    if not DB_PATH.exists():
        st.error("データベースが見つかりません。")
        st.info("先に以下を実行してください:")
        st.code("python -m src.cli init-db\npython -m src.cli seed", language="bash")
        st.stop()


def get_conn() -> sqlite3.Connection:
    """SQLite接続を取得する。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """SQLを実行してDataFrameで返す。"""
    try:
        conn = get_conn()
        df = pd.read_sql_query(sql, conn, params=params)
        conn.close()
        return df
    except Exception as e:
        st.error(f"クエリエラー: {e}")
        return pd.DataFrame()


def execute_sql(sql: str, params: tuple = ()) -> bool:
    """更新SQLを実行する。"""
    try:
        conn = get_conn()
        conn.execute(sql, params)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"実行エラー: {e}")
        return False


def fmt_price(v) -> str:
    """価格フォーマット。"""
    if v is None or pd.isna(v) or v == 0:
        return "---"
    return f"¥{int(v):,}"


def fmt_stock(v) -> str:
    """在庫フォーマット。"""
    if v is None or pd.isna(v):
        return "❓ 不明"
    return "🟢 在庫あり" if v else "🔴 在庫なし"


def fmt_rank(v) -> str:
    """ランクフォーマット。"""
    icons = {"S": "🔴 S", "A": "🟠 A", "B": "🟡 B", "C": "⚪ C"}
    return icons.get(v, v or "---")
