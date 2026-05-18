"""共通フィルタUI。"""

import streamlit as st
import pandas as pd
from dashboard.components.db_helper import query_df


def genre_filter(key: str = "genre") -> str | None:
    genres = query_df("SELECT DISTINCT genre FROM products WHERE is_active=1 ORDER BY genre")
    if genres.empty:
        return None
    options = ["全て"] + genres["genre"].tolist()
    sel = st.selectbox("ジャンル", options, key=key)
    return None if sel == "全て" else sel


def brand_filter(key: str = "brand") -> str | None:
    brands = query_df("SELECT DISTINCT brand FROM products WHERE is_active=1 AND brand!='' ORDER BY brand")
    if brands.empty:
        return None
    options = ["全て"] + brands["brand"].tolist()
    sel = st.selectbox("ブランド", options, key=key)
    return None if sel == "全て" else sel


def source_filter(key: str = "source") -> str | None:
    sources = query_df("SELECT id, name FROM sources WHERE is_active=1 ORDER BY name")
    if sources.empty:
        return None
    options = {"全て": None}
    for _, r in sources.iterrows():
        options[f"{r['name']} ({r['id']})"] = r["id"]
    sel = st.selectbox("情報源", list(options.keys()), key=key)
    return options[sel]


def rank_filter(key: str = "rank") -> str | None:
    sel = st.selectbox("ランク", ["全て", "S", "A", "B", "C"], key=key)
    return None if sel == "全て" else sel


def product_filter(key: str = "product") -> str | None:
    products = query_df("SELECT id, name FROM products WHERE is_active=1 ORDER BY name")
    if products.empty:
        return None
    options = {"全て": None}
    for _, r in products.iterrows():
        options[r["name"]] = r["id"]
    sel = st.selectbox("商品", list(options.keys()), key=key)
    return options[sel]
