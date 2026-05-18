"""アラート振り分け・通知パイプライン。

フロー:
  Observation
    → Scorer (ランク判定)
    → Alert生成 (alertsテーブル保存)
    → Dedup (重複チェック)
    → Notifier送信 (S/Aのみ)

通知ルール:
  S → Log + Discord + Telegram
  A → Log + Discord
  B/C → Log のみ（記録用）
"""

import json
import logging
from datetime import datetime
from typing import Optional

import ulid

from src.db.repository import Repository
from src.models.alert import AlertModel
from src.models.observation import ObservationModel
from src.models.product import ProductModel
from src.models.source import SourceModel
from src.pipeline.scorer import Scorer, ScoringResult
from src.pipeline.dedup import DedupChecker
from src.notifiers.base import BaseNotifier

logger = logging.getLogger(__name__)

# source_id → 表示名マッピング
SOURCE_DISPLAY_NAMES = {
    "src_kakaku": "価格.com",
    "src_yodobashi": "ヨドバシカメラ",
    "src_map_camera": "マップカメラ",
    "src_biccamera": "ビックカメラ",
    "src_sofmap": "ソフマップ",
    "src_janpara": "じゃんぱら",
    "src_iosys": "イオシス",
    "src_mercari": "メルカリ",
    "src_yahoo_auction": "ヤフオク",
    "src_apple_store": "Apple Store",
    "src_sony_store": "Sony Store",
    "src_nintendo_store": "My Nintendo Store",
}


class AlertDispatcher:
    """アラート生成・重複チェック・通知送信を統括する。"""

    def __init__(
        self,
        repository: Repository,
        scorer: Scorer,
        dedup: DedupChecker,
        notifiers: list[BaseNotifier],
    ):
        self.repository = repository
        self.scorer = scorer
        self.dedup = dedup
        self.notifiers = notifiers

    def score_latest(self) -> list[AlertModel]:
        """未処理のObservation全てをスコアリングし、alertsに保存する。

        通知は送信しない（dispatch_alertsで別途行う）。
        """
        observations = self.repository.list_unscored_observations()
        alerts = []

        for obs in observations:
            product = self.repository.get_product(obs.product_id)
            source = self.repository.get_source(obs.source_id)
            if not product or not source:
                continue

            score_result = self.scorer.score(obs, product, source)
            alert = self._create_alert(obs, product, source, score_result)

            try:
                self.repository.insert_alert(alert)
                alerts.append(alert)
            except Exception as e:
                logger.error("Failed to save alert: %s", e)

        self.dedup.cleanup()
        return alerts

    def dispatch_alerts(self) -> list[AlertModel]:
        """未送信のS/Aアラートを通知送信する。"""
        # 未送信のS/Aアラートを取得
        all_alerts = self.repository.list_alerts(limit=100)
        unsent = [
            a for a in all_alerts
            if not a.is_sent and a.alert_rank in ("S", "A")
        ]

        dispatched = []
        for alert in unsent:
            product = self.repository.get_product(alert.product_id)

            # Dedup チェック
            if self.dedup.is_duplicate(
                alert.product_id,
                self._extract_source_id(alert),
                alert.alert_type,
                alert.alert_rank,
            ):
                continue

            # 通知送信
            sent_channels = []
            for notifier in self.notifiers:
                if notifier.should_send(alert):
                    try:
                        ok = notifier.send(alert, product=product)
                        if ok:
                            sent_channels.append(notifier.CHANNEL_NAME)
                    except Exception as e:
                        logger.error("Notifier %s failed: %s", notifier.CHANNEL_NAME, e)

            if sent_channels:
                alert.is_sent = True
                alert.sent_channels = sent_channels
                alert.sent_at = datetime.now()
                try:
                    self.repository.update_alert_sent(
                        alert.id, sent_channels, alert.sent_at
                    )
                except Exception as e:
                    logger.error("Failed to update alert: %s", e)

                # Dedup登録
                self.dedup.register(
                    alert.product_id,
                    self._extract_source_id(alert),
                    alert.alert_type,
                    alert.alert_rank,
                    alert.id,
                )

                dispatched.append(alert)
                logger.info(
                    "Dispatched [%s] %s → %s",
                    alert.alert_rank, alert.title, sent_channels,
                )

        return dispatched

    def _create_alert(
        self,
        obs: ObservationModel,
        product: ProductModel,
        source: SourceModel,
        score: ScoringResult,
    ) -> AlertModel:
        title = self._make_title(product, score)
        body = self._make_body(obs, product, source, score)

        return AlertModel(
            id=str(ulid.new()),
            observation_id=obs.id,
            product_id=product.id,
            alert_rank=score.alert_rank,
            alert_type=score.alert_type,
            title=title,
            body=body,
            estimated_profit=score.estimated_profit,
            score=score.total_score,
            confidence=score.confidence,
        )

    def _make_title(self, product: ProductModel, score: ScoringResult) -> str:
        type_labels = {
            "stock_available": "在庫復活",
            "stock_unavailable": "在庫なし",
            "price_premium": "プレ値検知",
            "buyback_premium": "買取プレミアム",
            "buyback_surge": "買取急騰",
            "lottery_open": "抽選開始",
            "sold_out": "SOLD OUT",
            "market_signal": "市場シグナル",
        }
        label = type_labels.get(score.alert_type, score.alert_type)
        return f"{product.name} - {label}"

    def _make_body(
        self,
        obs: ObservationModel,
        product: ProductModel,
        source: SourceModel,
        score: ScoringResult,
    ) -> str:
        """alertsテーブルに保存するbody。Notifierはここからデータを読む。"""
        source_name = SOURCE_DISPLAY_NAMES.get(source.id, source.name)

        # target_urlを取得
        config = self.repository.get_product_source_config(product.id, source.id)
        url = config.target_url if config else ""

        lines = []
        if obs.price:
            lines.append(f"取得価格: ¥{obs.price:,}")
        if product.retail_price:
            lines.append(f"定価: ¥{product.retail_price:,}")
        if score.estimated_profit is not None:
            sign = "+" if score.estimated_profit > 0 else ""
            lines.append(f"想定利益: {sign}¥{score.estimated_profit:,}")
        if obs.buyback_price:
            lines.append(f"買取価格: ¥{obs.buyback_price:,}")

        if obs.is_in_stock is True:
            lines.append("在庫: あり")
        elif obs.is_in_stock is False:
            lines.append("在庫: なし")

        change = score.details.get("change", "")
        if change and change not in ("no_significant_change",):
            lines.append(f"変化: {change}")

        lines.append(f"情報源: {source_name}")
        if url:
            lines.append(f"URL: {url}")

        return "\n".join(lines)

    @staticmethod
    def _extract_source_id(alert: AlertModel) -> str:
        """alertのbodyから情報源IDを推定する。"""
        for line in alert.body.split("\n"):
            if line.startswith("情報源:") or line.startswith("情報源："):
                name = line.split(":", 1)[-1].split("：", 1)[-1].strip()
                # 逆引き
                for sid, sname in SOURCE_DISPLAY_NAMES.items():
                    if sname == name:
                        return sid
                return name
        return "unknown"
