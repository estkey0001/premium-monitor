"""市場比較スナップショットモデル。"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class MarketSnapshotModel(BaseModel):
    id: str = Field(...)
    product_id: Optional[str] = Field(default=None)
    candidate_id: Optional[str] = Field(default=None)
    category: str = Field(default="")
    brand: str = Field(default="")
    product_name: str = Field(default="")
    official_price_jpy: Optional[int] = Field(default=None)
    domestic_used_price_jpy: Optional[int] = Field(default=None)
    domestic_buyback_price_jpy: Optional[int] = Field(default=None)
    overseas_price_jpy: Optional[int] = Field(default=None)
    overseas_source: str = Field(default="")
    stock_status: str = Field(default="")
    sale_method: str = Field(default="")   # normal/lottery/preorder/soldout/discontinued
    premium_gap_jpy: Optional[int] = Field(default=None)
    premium_gap_percent: Optional[float] = Field(default=None)
    overseas_gap_jpy: Optional[int] = Field(default=None)
    overseas_gap_percent: Optional[float] = Field(default=None)
    premium_score: float = Field(default=0)
    scarcity_score: float = Field(default=0)
    liquidity_score: float = Field(default=0)
    overseas_gap_score: float = Field(default=0)
    source_confidence: float = Field(default=0)
    overall_score: float = Field(default=0)
    # Phase 7B-2: 初心者/上級者評価
    beginner_score: float = Field(default=0, description="初心者向け度 (0.0〜1.0)")
    difficulty_score: float = Field(default=0, description="入手難易度 (0.0〜1.0, 高=困難)")
    beginner_profit_score: float = Field(default=0, description="初心者向け利益スコア (0.0〜1.0)")
    user_level: str = Field(default="", description="beginner_easy/beginner_watch/advanced_high_profit/expert_only")
    recommended_action: str = Field(default="", description="check_official/check_buyback/watch_price/lottery_only/avoid")
    captured_at: datetime = Field(default_factory=datetime.now)
