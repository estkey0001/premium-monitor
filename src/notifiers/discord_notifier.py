"""Discord Webhook Notifier。

通知ルール:
  S → 送信
  A → 送信
  B/C → 送信しない

未設定時はskip（エラーにしない）。
"""

import logging
from typing import Optional

import requests

from src.models.alert import AlertModel
from src.models.product import ProductModel
from src.notifiers.base import BaseNotifier, RANK_EMOJI, RANK_LABEL

logger = logging.getLogger(__name__)


class DiscordNotifier(BaseNotifier):
    """Discord Webhook通知。"""

    CHANNEL_NAME = "discord"

    def __init__(
        self,
        webhook_url: str = "",
        enabled: bool = True,
        send_ranks: Optional[list[str]] = None,
        timeout: int = 10,
    ):
        super().__init__(enabled=enabled, send_ranks=send_ranks or ["S", "A"])
        self.webhook_url = webhook_url
        self.timeout = timeout

    def send(self, alert: AlertModel, product: Optional[ProductModel] = None) -> bool:
        if not self.should_send(alert):
            return False

        if not self.webhook_url:
            self.logger.info("Discord: webhook_url not set → skip")
            return False

        payload = self._build_embed(alert, product)

        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code in (200, 204):
                self.logger.info("Discord sent: [%s] %s", alert.alert_rank, alert.title)
                return True
            else:
                self.logger.error("Discord failed: %d %s", resp.status_code, resp.text[:200])
                return False
        except requests.RequestException as e:
            self.logger.error("Discord error: %s", e)
            return False

    def _build_embed(self, alert: AlertModel, product: Optional[ProductModel]) -> dict:
        colors = {"S": 0xFF0000, "A": 0xFF8C00, "B": 0xFFD700, "C": 0x808080}
        emoji = RANK_EMOJI.get(alert.alert_rank, "❓")
        label = RANK_LABEL.get(alert.alert_rank, "速報")

        fields = []
        if product:
            fields.append({"name": "ジャンル", "value": product.genre, "inline": True})
            if product.retail_price:
                fields.append({"name": "定価", "value": f"¥{product.retail_price:,}", "inline": True})

        if alert.estimated_profit is not None:
            sign = "+" if alert.estimated_profit > 0 else ""
            fields.append({"name": "想定利益", "value": f"{sign}¥{alert.estimated_profit:,}", "inline": True})
        if alert.confidence is not None:
            fields.append({"name": "信頼度", "value": f"{alert.confidence:.0%}", "inline": True})
        fields.append({"name": "ランク", "value": alert.alert_rank, "inline": True})

        # bodyの各行をパース
        for line in alert.body.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                k, v = k.strip(), v.strip()
                if k and v and k not in ("定価", "想定利益"):
                    fields.append({"name": k, "value": v, "inline": True})

        embed = {
            "title": f"{emoji}【{label}】{alert.title}",
            "color": colors.get(alert.alert_rank, 0x808080),
            "fields": fields[:25],
            "footer": {"text": f"検出: {alert.created_at.strftime('%Y-%m-%d %H:%M:%S')} | score: {alert.score:.2f}"},
        }
        return {"embeds": [embed]}

    def test_connection(self) -> bool:
        if not self.webhook_url:
            self.logger.info("Discord: webhook_url not set → skip test")
            return False
        try:
            resp = requests.post(
                self.webhook_url,
                json={"content": "🔔 Premium Monitor 接続テスト"},
                timeout=self.timeout,
            )
            ok = resp.status_code in (200, 204)
            self.logger.info("Discord test: %s", "OK" if ok else f"FAIL({resp.status_code})")
            return ok
        except requests.RequestException as e:
            self.logger.error("Discord test error: %s", e)
            return False
