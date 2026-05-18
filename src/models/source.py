"""情報源マスタモデル."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SourceModel(BaseModel):
    """情報源（スクレイピング対象サイト）を表すモデル。"""

    id: str = Field(..., description="情報源ID (例: src_yodobashi)")
    name: str = Field(..., description="表示名 (例: ヨドバシカメラ)")
    source_type: str = Field(..., description="種別 (例: electronics_retailer)")
    base_url: str = Field(..., description="サイトベースURL")
    collector_module: str = Field(..., description="Collectorモジュールパス")
    rate_limit_sec: int = Field(default=60, description="最小取得間隔（秒）")
    requires_js: bool = Field(default=False, description="Playwright必須か")
    is_active: bool = Field(default=True, description="有効か")
    robots_txt_url: Optional[str] = Field(default=None, description="robots.txt URL")
    memo: str = Field(default="", description="備考")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ProductSourceConfigModel(BaseModel):
    """商品×情報源の個別設定。"""

    id: str = Field(..., description="設定ID")
    product_id: str = Field(..., description="商品ID")
    source_id: str = Field(..., description="情報源ID")
    target_url: str = Field(default="", description="個別商品ページURL")
    css_selector_stock: str = Field(default="", description="在庫判定用CSSセレクタ")
    css_selector_price: str = Field(default="", description="価格取得用CSSセレクタ")
    extra_config: dict = Field(default_factory=dict, description="サイト固有パラメータ")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.now)
