"""商品マスタモデル."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProductModel(BaseModel):
    """監視対象の商品を表すモデル。"""

    id: str = Field(..., description="商品ID (例: prod_iphone16pm_256)")
    genre: str = Field(..., description="ジャンル (例: iphone, camera)")
    name: str = Field(..., description="商品名")
    brand: str = Field(default="", description="メーカー名")
    model_number: str = Field(default="", description="型番")
    jan_code: Optional[str] = Field(default=None, description="JANコード")
    retail_price: int = Field(default=0, description="定価（税込、円）")
    keywords: list[str] = Field(default_factory=list, description="検索用キーワード")
    image_url: Optional[str] = Field(default=None, description="商品画像URL")
    is_active: bool = Field(default=True, description="監視対象か")
    memo: str = Field(default="", description="管理者メモ")
    # --- 公式価格管理 (Phase 3.5) ---
    official_price: Optional[int] = Field(default=None, description="公式取得定価")
    official_price_source: str = Field(default="", description="公式価格取得元source_id")
    official_price_updated_at: Optional[datetime] = Field(default=None, description="公式価格取得日時")
    official_stock_status: str = Field(default="", description="公式在庫状態")
    is_lottery: bool = Field(default=False, description="抽選販売中か")
    is_discontinued: bool = Field(default=False, description="販売終了か")
    is_production_ended: bool = Field(default=False, description="製造完了か")
    retail_price_update_candidate: bool = Field(default=False, description="定価更新候補フラグ")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
