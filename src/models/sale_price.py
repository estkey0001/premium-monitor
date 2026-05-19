"""販売価格モデル（仕入れ候補店の販売価格）。"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SalePriceModel(BaseModel):
    """店舗の販売価格（仕入れ候補）。"""

    id: str = Field(...)
    product_id: str = Field(default="")
    product_alias: str = Field(default="", description="商品エイリアス (例: iphone17pro256)")
    shop_name: str = Field(default="", description="店舗名")
    shop_id: str = Field(default="", description="店舗ID")
    sale_price: int = Field(..., description="販売価格（税込、円）")
    condition: str = Field(default="new_unopened", description="商品状態")
    url: str = Field(default="", description="販売ページURL")
    link_verified: bool = Field(default=False, description="URLが検証済みか")
    observed_at: datetime = Field(default_factory=datetime.now)
    data_source: str = Field(default="manual", description="データソース")
    is_active: bool = Field(default=True)


# 販売条件ラベル
CONDITION_LABELS = {
    "new_unopened": "新品未開封",
    "new_unopened_simfree": "新品未開封 SIMフリー",
    "new_opened": "新品開封済",
    "used_a": "中古A（美品）",
    "used_b": "中古B（良品）",
    "used_c": "中古C（傷あり）",
}


class SedoriRouteModel(BaseModel):
    """せどりルート（仕入れ→売却の組み合わせ）。"""

    id: str = Field(...)
    product_id: str = Field(default="")
    product_name: str = Field(default="")
    product_alias: str = Field(default="")
    # 仕入れ側（販売店から購入）
    buy_shop_name: str = Field(default="")
    buy_shop_id: str = Field(default="")
    buy_price: int = Field(..., description="仕入れ価格（円）")
    buy_url: str = Field(default="")
    buy_condition: str = Field(default="")
    # 売却側（買取店へ売却）
    sell_shop_name: str = Field(default="")
    sell_shop_id: str = Field(default="")
    sell_price: int = Field(..., description="売却価格（買取価格、円）")
    sell_url: str = Field(default="")
    # 利益計算
    gross_profit: int = Field(default=0, description="粗利（売却価格 - 仕入れ価格）")
    shipping_fee: int = Field(default=1000, description="送料（円）")
    transfer_fee: int = Field(default=300, description="振込手数料（円）")
    travel_fee: int = Field(default=500, description="交通費（円）")
    other_costs: int = Field(default=0, description="その他コスト（円）")
    estimated_costs: int = Field(default=0, description="推定総コスト（円）")
    net_profit: int = Field(default=0, description="実質利益（円）")
    profit_rate: float = Field(default=0.0, description="利益率（仕入れ価格対比）")
    rank: int = Field(default=0, description="利益順ランク（1が最高）")
    calculated_at: datetime = Field(default_factory=datetime.now)
    # Phase 15: 品質チェックフィールド
    route_quality_score: float = Field(default=1.0, description="品質スコア (0.0-1.0) 高いほど信頼性が高い")
    route_warning_flags: list = Field(default_factory=list, description="警告フラグリスト (JSON配列)")
    needs_review: bool = Field(default=False, description="要確認フラグ (異常値・条件ズレ等)")
    sort_score: float = Field(default=0.0, description="ソートスコア = net_profit × route_quality_score")
