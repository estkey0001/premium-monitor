"""取得データモデル."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ObservationModel(BaseModel):
    """Collectorが取得した1回分のデータを表すモデル。"""

    id: str = Field(..., description="観測ID")
    product_id: str = Field(..., description="商品ID")
    source_id: str = Field(..., description="情報源ID")
    observation_type: str = Field(
        ..., description="種別: stock / price / buyback / lottery / sns / overseas"
    )
    observed_at: datetime = Field(default_factory=datetime.now, description="取得日時")
    is_in_stock: Optional[bool] = Field(default=None, description="在庫あり/なし")
    price: Optional[int] = Field(default=None, description="取得価格（円）")
    buyback_price: Optional[int] = Field(default=None, description="買取価格（円）")
    lottery_status: Optional[str] = Field(
        default=None, description="抽選: upcoming / open / closed"
    )
    lottery_deadline: Optional[datetime] = Field(default=None, description="抽選締切日時")
    raw_text: str = Field(default="", description="取得した生テキスト")
    raw_html_hash: str = Field(default="", description="HTML SHA256ハッシュ")
    confidence: float = Field(default=1.0, description="情報信頼度 0.0〜1.0")
    is_false_positive: bool = Field(default=False, description="誤報フラグ")
    is_manually_verified: bool = Field(default=False, description="手動確認済み")
    created_at: datetime = Field(default_factory=datetime.now)


class PriceHistoryModel(BaseModel):
    """価格推移レコード。"""

    id: str = Field(...)
    product_id: str = Field(...)
    source_id: str = Field(...)
    price_type: str = Field(..., description="retail / used / buyback / auction / overseas")
    price: int = Field(...)
    currency: str = Field(default="JPY")
    recorded_at: datetime = Field(default_factory=datetime.now)


class CollectorLogModel(BaseModel):
    """Collector実行ログ。"""

    id: str = Field(...)
    source_id: str = Field(...)
    product_id: Optional[str] = Field(default=None)
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: Optional[datetime] = Field(default=None)
    status: str = Field(..., description="success / error / timeout / skipped")
    http_status: Optional[int] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    duration_ms: Optional[int] = Field(default=None)
