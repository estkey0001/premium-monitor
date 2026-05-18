"""Telegram Bot Notifier。

通知ルール:
  S → 送信
  A/B/C → 送信しない（デフォルト）

未設定時はskip（エラーにしない）。
"""

import logging
from typing import Optional

import requests

from src.models.alert import AlertModel
from src.models.product import ProductModel
from src.notifiers.base import BaseNotifier, RANK_EMOJI, RANK_LABEL

logger = logging.getLogger(__name__)


class TelegramNotifier(BaseNotifier):
    """Telegram Bot通知。"""

    CHANNEL_NAME = "telegram"
    API_BASE = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        enabled: bool = True,
        send_ranks: Optional[list[str]] = None,
        timeout: int = 10,
    ):
        super().__init__(enabled=enabled, send_ranks=send_ranks or ["S"])
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    def send(self, alert: AlertModel, product: Optional[ProductModel] = None) -> bool:
        if not self.should_send(alert):
            return False

        if not self.bot_token or not self.chat_id:
            self.logger.info("Telegram: bot_token/chat_id not set → skip")
            return False

        message = self.format_message(alert, product)
        url = f"{self.API_BASE}/bot{self.bot_token}/sendMessage"

        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=self.timeout,
            )
            data = resp.json()
            if data.get("ok"):
                self.logger.info("Telegram sent: [%s] %s", alert.alert_rank, alert.title)
                return True
            else:
                self.logger.error("Telegram failed: %s", data.get("description", ""))
                return False
        except requests.RequestException as e:
            self.logger.error("Telegram error: %s", e)
            return False

    def format_message(self, alert: AlertModel, product: Optional[ProductModel] = None) -> str:
        """Telegram HTML形式メッセージ。"""
        emoji = RANK_EMOJI.get(alert.alert_rank, "❓")
        label = RANK_LABEL.get(alert.alert_rank, "速報")

        lines = [f"{emoji} <b>【{label}】</b>"]
        lines.append(f"<b>{alert.title}</b>")
        lines.append("")

        if product:
            lines.append(f"商品：{product.name}")
            lines.append(f"ジャンル：{product.genre}")
            if product.retail_price:
                lines.append(f"定価：¥{product.retail_price:,}")

        if alert.estimated_profit is not None:
            sign = "+" if alert.estimated_profit > 0 else ""
            lines.append(f"想定利益：{sign}¥{alert.estimated_profit:,}")

        # bodyの情報を追加
        for bl in alert.body.split("\n"):
            if bl.startswith("取得価格:"):
                lines.append(f"取得価格：{bl.split(':', 1)[1].strip()}")
            elif bl.startswith("在庫:"):
                lines.append(f"在庫状態：{bl.split(':', 1)[1].strip()}")
            elif bl.startswith("情報源:"):
                lines.append(f"情報源：{bl.split(':', 1)[1].strip()}")
            elif bl.startswith("URL:"):
                lines.append(f"URL：{bl.split(':', 1)[1].strip()}")

        lines.append(f"ランク：{alert.alert_rank}")
        if alert.confidence is not None:
            lines.append(f"信頼度：{alert.confidence:.0%}")
        lines.append(f"検出：{alert.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(lines)

    def test_connection(self) -> bool:
        if not self.bot_token or not self.chat_id:
            self.logger.info("Telegram: bot_token/chat_id not set → skip test")
            return False
        try:
            url = f"{self.API_BASE}/bot{self.bot_token}/getMe"
            resp = requests.get(url, timeout=self.timeout)
            data = resp.json()
            ok = data.get("ok", False)
            if ok:
                self.logger.info("Telegram test: OK (@%s)", data["result"].get("username", "?"))
            else:
                self.logger.error("Telegram test: FAIL (%s)", data)
            return ok
        except requests.RequestException as e:
            self.logger.error("Telegram test error: %s", e)
            return False
