"""LogNotifier - ログファイルへの通知出力（開発・記録用）。

実際の外部サービスへの送信は行わず、ファイルとコンソールにログを出力する。
全ランク（S/A/B/C）を記録できるため、開発時やバックアップ記録として使う。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models.alert import AlertModel
from src.models.product import ProductModel
from src.notifiers.base import BaseNotifier

logger = logging.getLogger(__name__)


class LogNotifier(BaseNotifier):
    """ログファイル出力による通知チャネル。"""

    CHANNEL_NAME = "log"

    def __init__(
        self,
        enabled: bool = True,
        send_ranks: Optional[list[str]] = None,
        log_dir: str = "data/logs",
    ):
        super().__init__(enabled=enabled, send_ranks=send_ranks or ["S", "A", "B", "C"])
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # アラート専用ロガーをセットアップ
        self._alert_logger = logging.getLogger("premium_monitor.alerts")
        if not self._alert_logger.handlers:
            log_file = self.log_dir / f"alerts_{datetime.now().strftime('%Y%m%d')}.log"
            handler = logging.FileHandler(str(log_file), encoding="utf-8")
            handler.setFormatter(
                logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
            )
            self._alert_logger.addHandler(handler)
            self._alert_logger.setLevel(logging.INFO)

    def send(self, alert: AlertModel, product: Optional[ProductModel] = None) -> bool:
        """アラートをログに出力する。"""
        if not self.should_send(alert):
            return False

        message = self.format_message(alert, product)

        # ファイルに書き出し
        self._alert_logger.info(
            "[%s] %s | %s | profit=%s | confidence=%s",
            alert.alert_rank,
            alert.alert_type,
            product.name if product else alert.product_id,
            f"¥{alert.estimated_profit:,}" if alert.estimated_profit else "N/A",
            f"{alert.confidence:.0%}" if alert.confidence else "N/A",
        )

        # コンソールにも出力
        self.logger.info("Alert logged:\n%s", message)

        return True

    def test_connection(self) -> bool:
        """ログ出力は常に成功。"""
        test_file = self.log_dir / "test_connection.log"
        try:
            test_file.write_text(
                f"LogNotifier test: {datetime.now().isoformat()}\n", encoding="utf-8"
            )
            self.logger.info("LogNotifier connection test: OK (log_dir=%s)", self.log_dir)
            return True
        except OSError as e:
            self.logger.error("LogNotifier connection test FAILED: %s", e)
            return False
