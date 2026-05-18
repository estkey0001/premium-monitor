"""列挙型定義 - システム全体で使用するEnum."""

from enum import Enum


class Genre(str, Enum):
    """商品ジャンル。後から追加可能。"""

    IPHONE = "iphone"
    PC = "pc"
    GAME_CONSOLE = "game_console"
    CAMERA = "camera"
    # --- 将来追加 ---
    # WATCH = "watch"
    # TRADING_CARD = "trading_card"
    # SNEAKER = "sneaker"
    # GPU = "gpu"
    # APPLIANCE = "appliance"
    # HOBBY = "hobby"


class SourceType(str, Enum):
    """情報源の種別。"""

    OFFICIAL_STORE = "official_store"
    ELECTRONICS_RETAILER = "electronics_retailer"
    USED_MARKETPLACE = "used_marketplace"
    BUYBACK_SHOP = "buyback_shop"
    AUCTION_MARKET = "auction_market"
    FLEA_MARKET = "flea_market"
    SNS = "sns"
    NEWS_BLOG = "news_blog"
    OVERSEAS_MARKET = "overseas_market"
    PRICE_COMPARISON = "price_comparison"


class ObservationType(str, Enum):
    """取得データの種別。"""

    STOCK = "stock"
    PRICE = "price"
    BUYBACK = "buyback"
    LOTTERY = "lottery"
    SNS = "sns"
    OVERSEAS = "overseas"


class AlertRank(str, Enum):
    """通知ランク。"""

    S = "S"
    A = "A"
    B = "B"
    C = "C"


class AlertType(str, Enum):
    """通知のトリガー種別。"""

    STOCK_AVAILABLE = "stock_available"
    LOTTERY_OPEN = "lottery_open"
    PRICE_DROP = "price_drop"
    BUYBACK_SURGE = "buyback_surge"
    SNS_MENTION = "sns_mention"
    OVERSEAS_PRICE_GAP = "overseas_price_gap"


class LotteryStatus(str, Enum):
    """抽選ステータス。"""

    UPCOMING = "upcoming"
    OPEN = "open"
    CLOSED = "closed"


class PriceType(str, Enum):
    """価格の種別。"""

    RETAIL = "retail"
    USED = "used"
    BUYBACK = "buyback"
    AUCTION = "auction"
    OVERSEAS = "overseas"


class CollectorStatus(str, Enum):
    """Collector実行結果のステータス。"""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
