"""共通チャートUI。"""

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


def price_history_chart(df: pd.DataFrame, retail_price: int = 0, product_name: str = "") -> go.Figure:
    """価格推移折れ線グラフ。"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="データなし", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font_size=20)
        return fig

    color_map = {
        "retail": "#2196F3",
        "used": "#FF9800",
        "buyback": "#4CAF50",
        "auction": "#9C27B0",
        "overseas": "#795548",
    }

    fig = go.Figure()
    for pt in df["price_type"].unique():
        sub = df[df["price_type"] == pt].sort_values("recorded_at")
        fig.add_trace(go.Scatter(
            x=sub["recorded_at"], y=sub["price"],
            mode="lines+markers", name=pt,
            line=dict(color=color_map.get(pt, "#607D8B")),
        ))

    if retail_price and retail_price > 0:
        fig.add_hline(y=retail_price, line_dash="dash", line_color="red",
                      annotation_text=f"定価 ¥{retail_price:,}")

    fig.update_layout(
        title=f"価格推移: {product_name}" if product_name else "価格推移",
        xaxis_title="日時", yaxis_title="価格（円）",
        yaxis_tickformat=",", height=450,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def rank_pie_chart(df: pd.DataFrame) -> go.Figure:
    """ランク別円グラフ。"""
    colors = {"S": "#F44336", "A": "#FF9800", "B": "#FFC107", "C": "#9E9E9E"}
    fig = px.pie(df, names="alert_rank", values="count",
                 color="alert_rank", color_discrete_map=colors,
                 title="ランク別アラート")
    fig.update_layout(height=300)
    return fig
