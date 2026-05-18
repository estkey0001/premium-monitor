"""投稿キューアイテムモデル。"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PublishItemModel(BaseModel):
    id: str = Field(...)
    source_type: str = Field(default="alert")   # alert / product_candidate / weekly_report / manual
    source_id: str = Field(default="")
    channel: str = Field(default="x")            # x / threads / line / discord / note
    title: str = Field(default="")
    body: str = Field(default="")
    hashtags: str = Field(default="")
    rank: str = Field(default="")
    status: str = Field(default="draft")         # draft / approved / published / rejected
    generated_at: datetime = Field(default_factory=datetime.now)
    approved_at: Optional[datetime] = Field(default=None)
    published_at: Optional[datetime] = Field(default=None)
    memo: str = Field(default="")
