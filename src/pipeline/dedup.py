"""重複通知防止モジュール。

dedup_key = hash(product_id + source_id + alert_type + rank + date_bucket)

date_bucket:
  S  → 30分
  A  → 2時間
  B/C → 通知しないのでdedupチェック不要
"""

import hashlib
import logging
import math
from datetime import datetime, timedelta
from typing import Optional

import ulid

from src.db.repository import Repository
from src.models.alert import NotificationDedupModel

logger = logging.getLogger(__name__)

# ランク別 date_bucket 幅（分）
BUCKET_MINUTES = {
    "S": 30,
    "A": 120,
}


class DedupChecker:
    """重複通知チェッカー。"""

    def __init__(self, repository: Repository):
        self.repository = repository

    @staticmethod
    def _make_date_bucket(rank: str, now: Optional[datetime] = None) -> str:
        """現在時刻をランク別バケットに丸める。

        S → 30分単位 (例: 2026-05-17T14:00, 2026-05-17T14:30)
        A → 2時間単位 (例: 2026-05-17T14:00, 2026-05-17T16:00)
        """
        now = now or datetime.now()
        minutes = BUCKET_MINUTES.get(rank, 120)
        bucket_index = math.floor(
            (now.hour * 60 + now.minute) / minutes
        )
        return f"{now.strftime('%Y-%m-%d')}_{minutes}m_{bucket_index}"

    @staticmethod
    def generate_key(
        product_id: str,
        source_id: str,
        alert_type: str,
        rank: str,
        now: Optional[datetime] = None,
    ) -> str:
        """重複チェック用キーを生成する。"""
        bucket = DedupChecker._make_date_bucket(rank, now)
        raw = f"{product_id}:{source_id}:{alert_type}:{rank}:{bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def is_duplicate(
        self,
        product_id: str,
        source_id: str,
        alert_type: str,
        rank: str,
    ) -> bool:
        """重複かどうかをチェックする。

        B/Cは通知しないので常にFalse（dedupチェック不要）。
        """
        if rank not in ("S", "A"):
            return False

        key = self.generate_key(product_id, source_id, alert_type, rank)
        is_dup = self.repository.check_dedup(key)

        if is_dup:
            logger.info(
                "DEDUP: %s x %s [%s/%s] → skip (key=%s...)",
                product_id, source_id, alert_type, rank, key[:10],
            )
        return is_dup

    def register(
        self,
        product_id: str,
        source_id: str,
        alert_type: str,
        rank: str,
        alert_id: str,
    ) -> None:
        """送信済みとして登録する。"""
        if rank not in ("S", "A"):
            return

        key = self.generate_key(product_id, source_id, alert_type, rank)
        ttl_minutes = BUCKET_MINUTES.get(rank, 120)
        now = datetime.now()

        dedup = NotificationDedupModel(
            id=str(ulid.new()),
            dedup_key=key,
            alert_id=alert_id,
            created_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
        try:
            self.repository.insert_dedup(dedup)
        except Exception as e:
            logger.warning("Dedup register failed: %s", e)

    def cleanup(self) -> int:
        """期限切れレコードを削除する。"""
        count = self.repository.cleanup_expired_dedup()
        if count > 0:
            logger.info("Cleaned up %d expired dedup records.", count)
        return count
