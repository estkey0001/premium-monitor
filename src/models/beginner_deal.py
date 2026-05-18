"""初心者向け案件モデル。"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class BeginnerDealModel(BaseModel):
    """初心者向けプレ値案件。"""

    id: str = Field(...)
    product_id: str = Field(...)
    product_name: str = Field(...)
    category: str = Field(default="")
    brand: str = Field(default="")

    # 公式側
    official_price_jpy: Optional[int] = Field(default=None)
    official_url: str = Field(default="")
    stock_status: str = Field(default="")
    sale_method: str = Field(default="normal")

    # 買取側（単一最高値）
    best_buyback_price: Optional[int] = Field(default=None)
    best_buyback_shop: str = Field(default="")
    best_buyback_url: str = Field(default="")
    best_link_verified: bool = Field(default=False)
    buyback_condition: str = Field(default="")

    # 買取側（複数店舗統計）
    median_buyback_price: Optional[int] = Field(default=None, description="中央値買取価格")
    buyback_shop_count: int = Field(default=1, description="参照店舗数")
    buyback_prices_json: str = Field(default="", description="上位5店舗の価格JSON")

    # 実利益計算
    gross_profit_jpy: int = Field(default=0, description="粗利（買取 - 公式）")
    estimated_costs_jpy: int = Field(default=0, description="推定コスト（送料+手数料等）")
    net_profit_jpy: int = Field(default=0, description="実質利益")
    net_profit_rate: float = Field(default=0, description="利益率 (net_profit / official)")

    # スコア
    beginner_score: float = Field(default=0)
    difficulty_score: float = Field(default=0)
    user_level: str = Field(default="")
    recommended_action: str = Field(default="")

    is_active: bool = Field(default=True)
    scanned_at: datetime = Field(default_factory=datetime.now)
    notes: str = Field(default="")


# コスト見積もりのデフォルト値
DEFAULT_COSTS = {
    "shipping_jpy": 1000,       # 送料
    "transfer_fee_jpy": 300,    # 振込手数料
    "transport_jpy": 500,       # 移動コスト
    "cc_fee_rate": 0.0,         # クレカ手数料率（Apple公式=0%）
    "insurance_jpy": 0,         # 保険
}
