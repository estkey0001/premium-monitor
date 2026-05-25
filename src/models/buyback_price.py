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
    data_source: str = Field(default="manual_today", description="live/manual_today/manual_recent/stale")
    link_verified: bool = Field(default=False, description="URLが検証済みか")
    confidence: str = Field(default="high", description="価格信頼度: high=商品名マッチ確認済, mid=部分マッチ, low=最高値フォールバック")


# 買取店マスタ
BUYBACK_SHOPS = {
    "src_mobile_ichiban": {
        "name": "モバイル一番",
        "url": "https://mobileno1.com/",
        "kaitori_url": "https://mobileno1.com/",
        "supports": ["iphone", "ipad", "apple_watch", "macbook"],
    },
    "src_kaitori_shouten": {
        "name": "買取商店",
        "url": "https://kaitori-shouten.com/",
        "kaitori_url": "https://kaitori-shouten.com/",
        "supports": ["iphone", "ipad", "game_console", "camera"],
    },
    "src_kaitori_itchome": {
        "name": "買取一丁目",
        "url": "https://kaitori-1chome.com/",
        "kaitori_url": "https://kaitori-1chome.com/",
        "supports": ["iphone", "ipad", "macbook"],
    },
    "src_janpara": {
        "name": "じゃんぱら",
        "url": "https://www.janpara.co.jp/",
        "kaitori_url": "https://www.janpara.co.jp/sell/",
        "supports": ["iphone", "ipad", "macbook", "camera", "pc", "game_console"],
    },
    "src_iosys": {
        "name": "イオシス",
        "url": "https://iosys.co.jp/",
        "kaitori_url": "https://iosys.co.jp/",
        "supports": ["iphone", "ipad", "macbook", "camera", "pc", "game_console"],
    },
    "src_geo": {
        "name": "ゲオ",
        "url": "https://www.geo-online.co.jp/",
        "kaitori_url": "https://www.geo-online.co.jp/",
        "supports": ["iphone", "ipad", "game_console", "camera"],
    },
    "src_sofmap": {
        "name": "ソフマップ",
        "url": "https://www.sofmap.com/",
        "kaitori_url": "https://www.sofmap.com/buy_list.aspx",
        "supports": ["iphone", "ipad", "macbook", "camera", "pc", "game_console"],
    },
    "src_kitamura": {
        "name": "カメラのキタムラ",
        "url": "https://www.kitamura.co.jp/",
        "kaitori_url": "https://www.kitamura.co.jp/service/kaitori/",
        "supports": ["camera"],
    },
    "src_mapcamera": {
        "name": "マップカメラ",
        "url": "https://www.mapcamera.com/",
        "kaitori_url": "https://www.mapcamera.com/",
        "supports": ["camera"],
    },
    "src_fujiya": {
        "name": "フジヤカメラ",
        "url": "https://www.fujiyacamera.com/",
        "kaitori_url": "https://www.fujiyacamera.com/",
        "supports": ["camera"],
    },
    "src_bookoff": {
        "name": "ブックオフ",
        "url": "https://www.bookoff.co.jp/",
        "kaitori_url": "https://www.bookoffgroup.co.jp/sell/",
        "supports": ["game_console", "iphone", "camera"],
    },
    "src_surugaya": {
        "name": "駿河屋",
        "url": "https://www.suruga-ya.jp/",
        "kaitori_url": "https://www.suruga-ya.jp/kaitori/",
        "supports": ["game_console", "camera"],
    },
    "src_tsutaya": {
        "name": "TSUTAYA",
        "url": "https://tsutaya.tsite.jp/",
        "kaitori_url": "https://tsutaya.tsite.jp/feature/kaitori/",
        "supports": ["game_console"],
    },
    "src_hardoff": {
        "name": "ハードオフ",
        "url": "https://www.hardoff.co.jp/",
        "kaitori_url": "https://www.hardoff.co.jp/search/",
        "supports": ["game_console", "iphone", "pc"],
    },
    "src_geo_mobile": {
        "name": "ゲオモバイル",
        "url": "https://geomobile.jp/",
        "kaitori_url": "https://geomobile.jp/purchase/",
        "supports": ["iphone", "ipad"],
    },
    "src_dosupara": {
        "name": "ドスパラ",
        "url": "https://www.dospara.co.jp/",
        "kaitori_url": "https://www.dospara.co.jp/kaitori/",
        "supports": ["game_console", "pc"],
    },
    "src_pasoko": {
        "name": "パソコン工房",
        "url": "https://www.pc-koubou.jp/",
        "kaitori_url": "https://www.pc-koubou.jp/pc/used/buy/",
        "supports": ["game_console", "pc"],
    },
    "src_2ndstreet": {
        "name": "セカンドストリート",
        "url": "https://www.2ndstreet.jp/",
        "kaitori_url": "https://www.2ndstreet.jp/sell/",
        "supports": ["iphone", "ipad"],
    },
    "src_netoff": {
        "name": "ネットオフ",
        "url": "https://www.netoff.co.jp/",
        "kaitori_url": "https://www.netoff.co.jp/sell/",
        "supports": ["iphone", "ipad"],
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
