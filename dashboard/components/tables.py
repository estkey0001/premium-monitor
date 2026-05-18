"""共通テーブル表示ユーティリティ。"""

import pandas as pd
import streamlit as st
from dashboard.components.db_helper import fmt_price, fmt_stock, fmt_rank


def style_stock_column(df: pd.DataFrame, col: str = "is_in_stock") -> pd.DataFrame:
    """在庫カラムを視覚化したコピーを返す。"""
    if col not in df.columns:
        return df
    df = df.copy()
    df[col] = df[col].apply(fmt_stock)
    return df


def style_price_columns(df: pd.DataFrame, cols: list[str] | None = None) -> pd.DataFrame:
    """価格カラムをフォーマットしたコピーを返す。"""
    df = df.copy()
    price_cols = cols or [c for c in df.columns if "price" in c.lower()]
    for c in price_cols:
        if c in df.columns:
            df[c] = df[c].apply(fmt_price)
    return df


def style_rank_column(df: pd.DataFrame, col: str = "alert_rank") -> pd.DataFrame:
    """ランクカラムを視覚化したコピーを返す。"""
    if col not in df.columns:
        return df
    df = df.copy()
    df[col] = df[col].apply(fmt_rank)
    return df
