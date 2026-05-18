"""買取価格モデル。"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class BuybackPriceModel(BaseModel):
    """買取店ごとの買取価格。"""

    id: str = Field(...)
    product_id: str = Field(...)
    shop_id: str = Field(..., description="買取店ID (例: src_mobile_ichiban)")
    shop_name: str = Field(default="", description="買取店名")
    buyback_price: int = Field(..., description="買取価格（税込、円）")
    condition: str = Field(default="new_unopened", description="買取条件 (new_unopened/new_opened/used_a/used_b)")
    buyback_url: str = Field(default="", description="買取ページURL")
    observed_at: datetime = Field(default_factory=datetime.now)
    is_active: bool = Field(default=True)
    notes: str = Field(default="")


# 買取店マスタ
BUYBACK_SHOPS = {
    "src_mobile_ichiban": {
        "name": "モバイル一番",
        "url": "https://mobileno1.com/",
        "supports": ["iphone", "ipad", "apple_watch", "macbook"],
    },
    "src_kaitori_shouten": {
        "name": "買取商店",
        "url": "https://kaitori-shouten.com/",
        "supports": ["iphone", "ipad", "game_console", "camera"],
    },
    "src_kaitori_itchome": {
        "name": "買取一丁目",
        "url": "https://kaitori-1chome.com/",
        "supports": ["iphone", "ipad", "macbook"],
    },
    "src_janpara": {
        "name": "じゃんぱら",
        "url": "https://www.janpara.co.jp/",
        "supports": ["iphone", "ipad", "macbook", "camera", "pc", "game_console"],
    },
    "src_iosys": {
        "name": "イオシス",
        "url": "https://iosys.co.jp/",
        "supports": ["iphone", "ipad", "macbook", "camera", "pc", "game_console"],
    },
}

# 買取条件ラベル
CONDITION_LABELS = {
    "new_unopened": "新品未開封",
    "new_unopened_simfree": "新品未開封 SIMフリー",
    "new_opened": "新品開封済",
    "used_a": "中古A（美品）",
    "used_b": "中古B（良品）",
}
