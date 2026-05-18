"""通知モデル."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AlertModel(BaseModel):
    """通知アラートを表すモデル。"""

    id: str = Field(..., description="アラートID")
    observation_id: str = Field(..., description="トリガーとなった観測ID")
    product_id: str = Field(..., description="商品ID")
    alert_rank: str = Field(..., description="S / A / B / C")
    alert_type: str = Field(
        ...,
        description="stock_available / lottery_open / price_drop / buyback_surge / sns_mention",
    )
    title: str = Field(..., description="通知タイトル")
    body: str = Field(..., description="通知本文")
    estimated_profit: Optional[int] = Field(default=None, description="想定利益（円）")
    score: Optional[float] = Field(default=None, description="総合スコア")
    confidence: Optional[float] = Field(default=None, description="信頼度")
    is_sent: bool = Field(default=False, description="送信済みか")
    sent_channels: list[str] = Field(default_factory=list, description="送信先チャネル")
    is_false_positive: bool = Field(default=False, description="誤報だった")
    is_published: bool = Field(default=False, description="SNS速報として公開済み")
    created_at: datetime = Field(default_factory=datetime.now)
    sent_at: Optional[datetime] = Field(default=None, description="送信日時")


class NotificationDedupModel(BaseModel):
    """重複通知防止レコード。"""

    id: str = Field(...)
    dedup_key: str = Field(..., description="product_id + alert_type + date のハッシュ")
    alert_id: str = Field(...)
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime = Field(...)
