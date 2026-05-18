"""新製品候補モデル。"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ProductCandidateModel(BaseModel):
    """メーカー公式等で検出された新製品候補。"""

    id: str = Field(...)
    source_id: str = Field(...)
    product_name: str = Field(...)
    detected_keyword: str = Field(default="")
    detected_url: str = Field(default="")
    detected_at: datetime = Field(default_factory=datetime.now)
    confidence: float = Field(default=0.5)
    status: str = Field(default="pending")  # pending / approved / rejected
    genre: str = Field(default="")
    brand: str = Field(default="")
    estimated_price: Optional[int] = Field(default=None)
    notes: str = Field(default="")
    reviewed_at: Optional[datetime] = Field(default=None)
    approved_product_id: Optional[str] = Field(default=None)
    # Phase 7B-2: 初心者/上級者評価
    user_level: str = Field(default="", description="beginner_easy/beginner_watch/advanced_high_profit/expert_only")
    beginner_score: float = Field(default=0, description="初心者向け度")
    difficulty_score: float = Field(default=0, description="入手難易度")
    reason_for_beginner: str = Field(default="", description="初心者向けの理由")
    caution_note: str = Field(default="", description="注意事項")
