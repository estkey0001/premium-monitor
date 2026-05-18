"""BaseNotifier - 全通知チャネルの共通基盤。

仕様フォーマット:
🔴【S級プレ値速報】
商品：RICOH GR IIIx
ジャンル：camera
情報源：価格.com
定価：¥139,700
取得価格：¥208,764
想定利益：¥46,688
在庫状態：在庫あり
ランク：S
信頼度：95%
URL：https://kakaku.com/item/K0001382380/
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Optional

from src.models.alert import AlertModel
from src.models.product import ProductModel

logger = logging.getLogger(__name__)

RANK_EMOJI = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "⚪"}
RANK_LABEL = {"S": "S級プレ値速報", "A": "A級注目速報", "B": "B級記録", "C": "C級観測"}


class BaseNotifier(ABC):
    """通知チャネルの基底クラス。"""

    CHANNEL_NAME: str = "base"

    def __init__(self, enabled: bool = True, send_ranks: Optional[list[str]] = None):
        self.enabled = enabled
        self.send_ranks = send_ranks or ["S", "A"]
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def should_send(self, alert: AlertModel) -> bool:
        if not self.enabled:
            return False
        return alert.alert_rank in self.send_ranks

    @abstractmethod
    def send(self, alert: AlertModel, product: Optional[ProductModel] = None) -> bool:
        ...

    def format_message(
        self,
        alert: AlertModel,
        product: Optional[ProductModel] = None,
    ) -> str:
        """仕様通りの通知メッセージを生成する。"""
        emoji = RANK_EMOJI.get(alert.alert_rank, "❓")
        label = RANK_LABEL.get(alert.alert_rank, "速報")

        lines = [
            f"{emoji}【{label}】",
            f"商品：{product.name if product else alert.product_id}",
        ]

        if product:
            lines.append(f"ジャンル：{product.genre}")

        # bodyからsource_idを抽出
        source_name = ""
        url = ""
        try:
            body_lines = alert.body.split("\n")
            for bl in body_lines:
                if bl.startswith("情報源:") or bl.startswith("情報源："):
                    source_name = bl.split(":", 1)[-1].split("：", 1)[-1].strip()
                if bl.startswith("URL:") or bl.startswith("URL："):
                    url = bl.split(":", 1)[-1].strip()
        except Exception:
            pass

        if source_name:
            lines.append(f"情報源：{source_name}")

        if product and product.retail_price:
            lines.append(f"定価：¥{product.retail_price:,}")

        # bodyから取得価格を抽出
        for bl in alert.body.split("\n"):
            if bl.startswith("取得価格:") or bl.startswith("取得価格："):
                lines.append(f"取得価格：{bl.split(':', 1)[-1].split('：', 1)[-1].strip()}")
                break

        if alert.estimated_profit is not None:
            sign = "+" if alert.estimated_profit > 0 else ""
            lines.append(f"想定利益：{sign}¥{alert.estimated_profit:,}")

        # 在庫状態
        for bl in alert.body.split("\n"):
            if bl.startswith("在庫:") or bl.startswith("在庫："):
                lines.append(f"在庫状態：{bl.split(':', 1)[-1].split('：', 1)[-1].strip()}")
                break

        lines.append(f"ランク：{alert.alert_rank}")

        if alert.confidence is not None:
            lines.append(f"信頼度：{alert.confidence:.0%}")

        if url:
            lines.append(f"URL：{url}")

        lines.append(f"検出：{alert.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(lines)

    @abstractmethod
    def test_connection(self) -> bool:
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} enabled={self.enabled} ranks={self.send_ranks}>"
