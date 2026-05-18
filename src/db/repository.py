"""CRUD操作のRepository層."""

import json
import logging
from datetime import datetime
from typing import Optional

from src.db.database import Database
from src.models.product import ProductModel
from src.models.source import SourceModel
from src.models.observation import ObservationModel, CollectorLogModel, PriceHistoryModel
from src.models.alert import AlertModel, NotificationDedupModel

logger = logging.getLogger(__name__)


class Repository:
    """全テーブルのCRUD操作を提供する。"""

    def __init__(self, db: Database):
        self.db = db

    # =========================================
    # Products
    # =========================================

    def upsert_product(self, product: ProductModel) -> None:
        """商品を挿入または更新する。"""
        now = datetime.now().isoformat()
        self.db.connection.execute(
            """
            INSERT INTO products (id, genre, name, brand, model_number, jan_code,
                                  retail_price, keywords, image_url, is_active, memo,
                                  created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                genre = excluded.genre,
                name = excluded.name,
                brand = excluded.brand,
                model_number = excluded.model_number,
                jan_code = excluded.jan_code,
                retail_price = excluded.retail_price,
                keywords = excluded.keywords,
                image_url = excluded.image_url,
                is_active = excluded.is_active,
                memo = excluded.memo,
                updated_at = ?
            """,
            (
                product.id,
                product.genre,
                product.name,
                product.brand,
                product.model_number,
                product.jan_code,
                product.retail_price,
                json.dumps(product.keywords, ensure_ascii=False),
                product.image_url,
                int(product.is_active),
                product.memo,
                now,
                now,
                now,  # updated_at for ON CONFLICT
            ),
        )
        self.db.connection.commit()

    def get_product(self, product_id: str) -> Optional[ProductModel]:
        """IDで商品を取得。"""
        row = self.db.connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_product(row)

    def list_products(self, genre: Optional[str] = None, active_only: bool = True) -> list[ProductModel]:
        """商品一覧を取得。"""
        query = "SELECT * FROM products WHERE 1=1"
        params: list = []
        if active_only:
            query += " AND is_active = 1"
        if genre:
            query += " AND genre = ?"
            params.append(genre)
        query += " ORDER BY genre, name"
        rows = self.db.connection.execute(query, params).fetchall()
        return [self._row_to_product(r) for r in rows]

    def _row_to_product(self, row) -> ProductModel:
        d = dict(row)
        return ProductModel(
            id=d["id"],
            genre=d["genre"],
            name=d["name"],
            brand=d["brand"],
            model_number=d["model_number"],
            jan_code=d.get("jan_code"),
            retail_price=d["retail_price"],
            keywords=json.loads(d["keywords"]) if d.get("keywords") else [],
            image_url=d.get("image_url"),
            is_active=bool(d["is_active"]),
            memo=d.get("memo", ""),
            official_price=d.get("official_price"),
            official_price_source=d.get("official_price_source", ""),
            official_price_updated_at=(
                datetime.fromisoformat(d["official_price_updated_at"])
                if d.get("official_price_updated_at") else None
            ),
            official_stock_status=d.get("official_stock_status", ""),
            is_lottery=bool(d.get("is_lottery", 0)),
            is_discontinued=bool(d.get("is_discontinued", 0)),
            is_production_ended=bool(d.get("is_production_ended", 0)),
            retail_price_update_candidate=bool(d.get("retail_price_update_candidate", 0)),
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
        )

    def update_product_official_price(
        self, product_id: str, price: int, source_id: str, observed_at: "datetime"
    ) -> None:
        """公式価格でretail_priceとofficial_priceを更新する。"""
        now = datetime.now().isoformat()
        self.db.connection.execute(
            """
            UPDATE products SET
                retail_price = ?,
                official_price = ?,
                official_price_source = ?,
                official_price_updated_at = ?,
                retail_price_update_candidate = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (price, price, source_id, observed_at.isoformat(), now, product_id),
        )
        self.db.connection.commit()

    def mark_official_price_candidate(
        self, product_id: str, price: int, source_id: str,
        stock_status: str = "", is_lottery: bool = False,
        is_discontinued: bool = False,
    ) -> None:
        """公式価格情報を更新候補として記録する（retail_priceは変更しない）。"""
        now = datetime.now().isoformat()
        self.db.connection.execute(
            """
            UPDATE products SET
                official_price = ?,
                official_price_source = ?,
                official_price_updated_at = ?,
                official_stock_status = ?,
                is_lottery = ?,
                is_discontinued = ?,
                retail_price_update_candidate = CASE
                    WHEN retail_price != ? AND ? > 0 THEN 1 ELSE 0 END,
                updated_at = ?
            WHERE id = ?
            """,
            (price, source_id, now, stock_status,
             int(is_lottery), int(is_discontinued),
             price, price, now, product_id),
        )
        self.db.connection.commit()

    # =========================================
    # Sources
    # =========================================

    def upsert_source(self, source: SourceModel) -> None:
        """情報源を挿入または更新する。"""
        now = datetime.now().isoformat()
        self.db.connection.execute(
            """
            INSERT INTO sources (id, name, source_type, base_url, collector_module,
                                 rate_limit_sec, requires_js, is_active, robots_txt_url,
                                 memo, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                source_type = excluded.source_type,
                base_url = excluded.base_url,
                collector_module = excluded.collector_module,
                rate_limit_sec = excluded.rate_limit_sec,
                requires_js = excluded.requires_js,
                is_active = excluded.is_active,
                robots_txt_url = excluded.robots_txt_url,
                memo = excluded.memo,
                updated_at = ?
            """,
            (
                source.id,
                source.name,
                source.source_type,
                source.base_url,
                source.collector_module,
                source.rate_limit_sec,
                int(source.requires_js),
                int(source.is_active),
                source.robots_txt_url,
                source.memo,
                now,
                now,
                now,  # updated_at for ON CONFLICT
            ),
        )
        self.db.connection.commit()

    def get_source(self, source_id: str) -> Optional[SourceModel]:
        """IDで情報源を取得。"""
        row = self.db.connection.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_source(row)

    def list_sources(
        self, source_type: Optional[str] = None, active_only: bool = True
    ) -> list[SourceModel]:
        """情報源一覧を取得。"""
        query = "SELECT * FROM sources WHERE 1=1"
        params: list = []
        if active_only:
            query += " AND is_active = 1"
        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)
        query += " ORDER BY source_type, name"
        rows = self.db.connection.execute(query, params).fetchall()
        return [self._row_to_source(r) for r in rows]

    def _row_to_source(self, row) -> SourceModel:
        return SourceModel(
            id=row["id"],
            name=row["name"],
            source_type=row["source_type"],
            base_url=row["base_url"],
            collector_module=row["collector_module"],
            rate_limit_sec=row["rate_limit_sec"],
            requires_js=bool(row["requires_js"]),
            is_active=bool(row["is_active"]),
            robots_txt_url=row["robots_txt_url"],
            memo=row["memo"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # =========================================
    # Observations
    # =========================================

    def insert_observation(self, obs: ObservationModel) -> None:
        """観測データを保存。"""
        self.db.connection.execute(
            """
            INSERT INTO observations (id, product_id, source_id, observation_type,
                                      observed_at, is_in_stock, price, buyback_price,
                                      lottery_status, lottery_deadline, raw_text,
                                      raw_html_hash, confidence, is_false_positive,
                                      is_manually_verified, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                obs.id,
                obs.product_id,
                obs.source_id,
                obs.observation_type,
                obs.observed_at.isoformat(),
                int(obs.is_in_stock) if obs.is_in_stock is not None else None,
                obs.price,
                obs.buyback_price,
                obs.lottery_status,
                obs.lottery_deadline.isoformat() if obs.lottery_deadline else None,
                obs.raw_text,
                obs.raw_html_hash,
                obs.confidence,
                int(obs.is_false_positive),
                int(obs.is_manually_verified),
                datetime.now().isoformat(),
            ),
        )
        self.db.connection.commit()

    def get_latest_observation(
        self, product_id: str, source_id: str, observation_type: str
    ) -> Optional[ObservationModel]:
        """指定商品×情報源×種別の最新観測を取得。"""
        row = self.db.connection.execute(
            """
            SELECT * FROM observations
            WHERE product_id = ? AND source_id = ? AND observation_type = ?
            ORDER BY observed_at DESC LIMIT 1
            """,
            (product_id, source_id, observation_type),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_observation(row)

    def _row_to_observation(self, row) -> ObservationModel:
        return ObservationModel(
            id=row["id"],
            product_id=row["product_id"],
            source_id=row["source_id"],
            observation_type=row["observation_type"],
            observed_at=datetime.fromisoformat(row["observed_at"]),
            is_in_stock=bool(row["is_in_stock"]) if row["is_in_stock"] is not None else None,
            price=row["price"],
            buyback_price=row["buyback_price"],
            lottery_status=row["lottery_status"],
            lottery_deadline=(
                datetime.fromisoformat(row["lottery_deadline"])
                if row["lottery_deadline"]
                else None
            ),
            raw_text=row["raw_text"],
            raw_html_hash=row["raw_html_hash"],
            confidence=row["confidence"],
            is_false_positive=bool(row["is_false_positive"]),
            is_manually_verified=bool(row["is_manually_verified"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_observations(
        self,
        product_id: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[ObservationModel]:
        """観測データ一覧を取得。"""
        query = "SELECT * FROM observations WHERE 1=1"
        params: list = []
        if product_id:
            query += " AND product_id = ?"
            params.append(product_id)
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        query += " ORDER BY observed_at DESC LIMIT ?"
        params.append(limit)
        rows = self.db.connection.execute(query, params).fetchall()
        return [self._row_to_observation(r) for r in rows]

    # =========================================
    # Price History
    # =========================================

    def insert_price_history(self, ph: PriceHistoryModel) -> None:
        """価格履歴を保存。"""
        self.db.connection.execute(
            """
            INSERT INTO price_history (id, product_id, source_id, price_type,
                                       price, currency, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ph.id,
                ph.product_id,
                ph.source_id,
                ph.price_type,
                ph.price,
                ph.currency,
                ph.recorded_at.isoformat(),
            ),
        )
        self.db.connection.commit()

    def list_price_history(
        self,
        product_id: Optional[str] = None,
        source_id: Optional[str] = None,
        price_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[PriceHistoryModel]:
        """価格履歴一覧を取得。"""
        query = "SELECT * FROM price_history WHERE 1=1"
        params: list = []
        if product_id:
            query += " AND product_id = ?"
            params.append(product_id)
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        if price_type:
            query += " AND price_type = ?"
            params.append(price_type)
        query += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)
        rows = self.db.connection.execute(query, params).fetchall()
        return [self._row_to_price_history(r) for r in rows]

    def _row_to_price_history(self, row) -> PriceHistoryModel:
        return PriceHistoryModel(
            id=row["id"],
            product_id=row["product_id"],
            source_id=row["source_id"],
            price_type=row["price_type"],
            price=row["price"],
            currency=row["currency"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
        )

    # =========================================
    # Product Source Config
    # =========================================

    def upsert_product_source_config(self, config) -> None:
        """商品×情報源設定を挿入/更新する。"""
        from src.models.source import ProductSourceConfigModel

        now = datetime.now().isoformat()
        self.db.connection.execute(
            """
            INSERT INTO product_source_config (id, product_id, source_id, target_url,
                                                css_selector_stock, css_selector_price,
                                                extra_config, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                target_url = excluded.target_url,
                css_selector_stock = excluded.css_selector_stock,
                css_selector_price = excluded.css_selector_price,
                extra_config = excluded.extra_config,
                is_active = excluded.is_active
            """,
            (
                config.id,
                config.product_id,
                config.source_id,
                config.target_url,
                config.css_selector_stock,
                config.css_selector_price,
                json.dumps(config.extra_config) if config.extra_config else "{}",
                int(config.is_active),
                now,
            ),
        )
        self.db.connection.commit()

    def get_product_source_config(
        self, product_id: str, source_id: str
    ) -> Optional["ProductSourceConfigModel"]:
        """商品×情報源の設定を取得。"""
        from src.models.source import ProductSourceConfigModel

        row = self.db.connection.execute(
            "SELECT * FROM product_source_config WHERE product_id = ? AND source_id = ? AND is_active = 1",
            (product_id, source_id),
        ).fetchone()
        if row is None:
            return None
        return ProductSourceConfigModel(
            id=row["id"],
            product_id=row["product_id"],
            source_id=row["source_id"],
            target_url=row["target_url"],
            css_selector_stock=row["css_selector_stock"],
            css_selector_price=row["css_selector_price"],
            extra_config=json.loads(row["extra_config"]) if row["extra_config"] else {},
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # =========================================
    # Alerts
    # =========================================

    def insert_alert(self, alert: AlertModel) -> None:
        """アラートを保存。"""
        self.db.connection.execute(
            """
            INSERT INTO alerts (id, observation_id, product_id, alert_rank, alert_type,
                                title, body, estimated_profit, score, confidence,
                                is_sent, sent_channels, is_false_positive, is_published,
                                created_at, sent_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.id,
                alert.observation_id,
                alert.product_id,
                alert.alert_rank,
                alert.alert_type,
                alert.title,
                alert.body,
                alert.estimated_profit,
                alert.score,
                alert.confidence,
                int(alert.is_sent),
                json.dumps(alert.sent_channels),
                int(alert.is_false_positive),
                int(alert.is_published),
                alert.created_at.isoformat(),
                alert.sent_at.isoformat() if alert.sent_at else None,
            ),
        )
        self.db.connection.commit()

    def list_alerts(
        self,
        rank: Optional[str] = None,
        limit: int = 50,
    ) -> list[AlertModel]:
        """アラート一覧を取得。"""
        query = "SELECT * FROM alerts WHERE 1=1"
        params: list = []
        if rank:
            query += " AND alert_rank = ?"
            params.append(rank)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.db.connection.execute(query, params).fetchall()
        return [self._row_to_alert(r) for r in rows]

    def _row_to_alert(self, row) -> AlertModel:
        return AlertModel(
            id=row["id"],
            observation_id=row["observation_id"],
            product_id=row["product_id"],
            alert_rank=row["alert_rank"],
            alert_type=row["alert_type"],
            title=row["title"],
            body=row["body"],
            estimated_profit=row["estimated_profit"],
            score=row["score"],
            confidence=row["confidence"],
            is_sent=bool(row["is_sent"]),
            sent_channels=json.loads(row["sent_channels"]) if row["sent_channels"] else [],
            is_false_positive=bool(row["is_false_positive"]),
            is_published=bool(row["is_published"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
        )

    def update_alert_sent(
        self, alert_id: str, sent_channels: list[str], sent_at: "datetime"
    ) -> None:
        """アラートの送信状態を更新する。"""
        self.db.connection.execute(
            """
            UPDATE alerts SET is_sent = 1, sent_channels = ?, sent_at = ?
            WHERE id = ?
            """,
            (json.dumps(sent_channels), sent_at.isoformat(), alert_id),
        )
        self.db.connection.commit()

    def list_unscored_observations(self, limit: int = 100) -> list[ObservationModel]:
        """アラートが未生成のobservationsを取得する。"""
        rows = self.db.connection.execute(
            """
            SELECT o.* FROM observations o
            LEFT JOIN alerts a ON a.observation_id = o.id
            WHERE a.id IS NULL
            ORDER BY o.observed_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_observation(r) for r in rows]

    # =========================================
    # Collector Logs
    # =========================================

    def insert_collector_log(self, log: CollectorLogModel) -> None:
        """Collector実行ログを保存。"""
        self.db.connection.execute(
            """
            INSERT INTO collector_logs (id, source_id, product_id, started_at,
                                        finished_at, status, http_status,
                                        error_message, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log.id,
                log.source_id,
                log.product_id,
                log.started_at.isoformat(),
                log.finished_at.isoformat() if log.finished_at else None,
                log.status,
                log.http_status,
                log.error_message,
                log.duration_ms,
            ),
        )
        self.db.connection.commit()

    # =========================================
    # Notification Dedup
    # =========================================

    def check_dedup(self, dedup_key: str) -> bool:
        """重複通知かどうかチェック。Trueなら重複（送信スキップすべき）。"""
        now = datetime.now().isoformat()
        row = self.db.connection.execute(
            "SELECT id FROM notification_dedup WHERE dedup_key = ? AND expires_at > ?",
            (dedup_key, now),
        ).fetchone()
        return row is not None

    def insert_dedup(self, dedup: NotificationDedupModel) -> None:
        """重複防止レコードを挿入。"""
        self.db.connection.execute(
            """
            INSERT OR IGNORE INTO notification_dedup (id, dedup_key, alert_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                dedup.id,
                dedup.dedup_key,
                dedup.alert_id,
                dedup.created_at.isoformat(),
                dedup.expires_at.isoformat(),
            ),
        )
        self.db.connection.commit()

    def cleanup_expired_dedup(self) -> int:
        """期限切れの重複防止レコードを削除。削除件数を返す。"""
        now = datetime.now().isoformat()
        cursor = self.db.connection.execute(
            "DELETE FROM notification_dedup WHERE expires_at <= ?", (now,)
        )
        self.db.connection.commit()
        return cursor.rowcount

    # =========================================
    # Stats
    # =========================================

    def count_products(self, active_only: bool = True) -> int:
        query = "SELECT COUNT(*) FROM products"
        if active_only:
            query += " WHERE is_active = 1"
        return self.db.connection.execute(query).fetchone()[0]

    def count_sources(self, active_only: bool = True) -> int:
        query = "SELECT COUNT(*) FROM sources"
        if active_only:
            query += " WHERE is_active = 1"
        return self.db.connection.execute(query).fetchone()[0]

    # =========================================
    # Product Candidates
    # =========================================

    def insert_product_candidate(self, c) -> None:
        from src.models.product_candidate import ProductCandidateModel
        self.db.connection.execute(
            """
            INSERT OR IGNORE INTO product_candidates
            (id, source_id, product_name, detected_keyword, detected_url,
             detected_at, confidence, status, genre, brand, estimated_price, notes,
             user_level, beginner_score, difficulty_score, reason_for_beginner, caution_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (c.id, c.source_id, c.product_name, c.detected_keyword,
             c.detected_url, c.detected_at.isoformat(), c.confidence,
             c.status, c.genre, c.brand, c.estimated_price, c.notes,
             c.user_level, c.beginner_score, c.difficulty_score,
             c.reason_for_beginner, c.caution_note),
        )
        self.db.connection.commit()

    def list_product_candidates(self, status: Optional[str] = None, limit: int = 50):
        from src.models.product_candidate import ProductCandidateModel
        query = "SELECT * FROM product_candidates WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        rows = self.db.connection.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            result.append(ProductCandidateModel(
                id=d["id"], source_id=d["source_id"], product_name=d["product_name"],
                detected_keyword=d.get("detected_keyword", ""),
                detected_url=d.get("detected_url", ""),
                detected_at=datetime.fromisoformat(d["detected_at"]),
                confidence=d.get("confidence", 0.5),
                status=d.get("status", "pending"),
                genre=d.get("genre", ""), brand=d.get("brand", ""),
                estimated_price=d.get("estimated_price"),
                notes=d.get("notes", ""),
                user_level=d.get("user_level", ""),
                beginner_score=d.get("beginner_score", 0),
                difficulty_score=d.get("difficulty_score", 0),
                reason_for_beginner=d.get("reason_for_beginner", ""),
                caution_note=d.get("caution_note", ""),
            ))
        return result

    def update_product_candidate_status(self, candidate_id: str, status: str,
                                         approved_product_id: Optional[str] = None) -> None:
        now = datetime.now().isoformat()
        self.db.connection.execute(
            "UPDATE product_candidates SET status = ?, reviewed_at = ?, approved_product_id = ? WHERE id = ?",
            (status, now, approved_product_id, candidate_id),
        )
        self.db.connection.commit()

    # =========================================
    # Publish Queue
    # =========================================

    def insert_publish_item(self, item) -> None:
        self.db.connection.execute(
            """INSERT OR IGNORE INTO publish_queue
               (id, source_type, source_id, channel, title, body, hashtags, rank, status, generated_at, memo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.id, item.source_type, item.source_id, item.channel,
             item.title, item.body, item.hashtags, item.rank, item.status,
             item.generated_at.isoformat(), item.memo),
        )
        self.db.connection.commit()

    def list_publish_queue(self, channel: Optional[str] = None,
                           status: Optional[str] = None, limit: int = 50) -> list:
        from src.models.publish_item import PublishItemModel
        query = "SELECT * FROM publish_queue WHERE 1=1"
        params: list = []
        if channel:
            query += " AND channel=?"
            params.append(channel)
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY generated_at DESC LIMIT ?"
        params.append(limit)
        rows = self.db.connection.execute(query, tuple(params)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            result.append(PublishItemModel(
                id=d["id"], source_type=d["source_type"], source_id=d.get("source_id", ""),
                channel=d["channel"], title=d["title"], body=d["body"],
                hashtags=d.get("hashtags", ""), rank=d.get("rank", ""),
                status=d["status"], generated_at=datetime.fromisoformat(d["generated_at"]),
                approved_at=datetime.fromisoformat(d["approved_at"]) if d.get("approved_at") else None,
                published_at=datetime.fromisoformat(d["published_at"]) if d.get("published_at") else None,
                memo=d.get("memo", ""),
            ))
        return result

    def get_publish_item(self, item_id: str):
        from src.models.publish_item import PublishItemModel
        row = self.db.connection.execute("SELECT * FROM publish_queue WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        return PublishItemModel(
            id=d["id"], source_type=d["source_type"], source_id=d.get("source_id", ""),
            channel=d["channel"], title=d["title"], body=d["body"],
            hashtags=d.get("hashtags", ""), rank=d.get("rank", ""),
            status=d["status"], generated_at=datetime.fromisoformat(d["generated_at"]),
            approved_at=datetime.fromisoformat(d["approved_at"]) if d.get("approved_at") else None,
            published_at=datetime.fromisoformat(d["published_at"]) if d.get("published_at") else None,
            memo=d.get("memo", ""),
        )

    def update_publish_item_status(self, item_id: str, status: str) -> None:
        now = datetime.now().isoformat()
        col = "approved_at" if status == "approved" else ("published_at" if status == "published" else None)
        if col:
            self.db.connection.execute(
                f"UPDATE publish_queue SET status=?, {col}=? WHERE id=?",
                (status, now, item_id),
            )
        else:
            self.db.connection.execute(
                "UPDATE publish_queue SET status=? WHERE id=?", (status, item_id),
            )
        self.db.connection.commit()

    # =========================================
    # Market Snapshots
    # =========================================

    def insert_market_snapshot(self, s) -> None:
        self.db.connection.execute(
            """INSERT INTO market_snapshots
               (id, product_id, candidate_id, category, brand, product_name,
                official_price_jpy, domestic_used_price_jpy, domestic_buyback_price_jpy,
                overseas_price_jpy, overseas_source, stock_status, sale_method,
                premium_gap_jpy, premium_gap_percent, overseas_gap_jpy, overseas_gap_percent,
                premium_score, scarcity_score, liquidity_score, overseas_gap_score,
                source_confidence, overall_score,
                beginner_score, difficulty_score, beginner_profit_score,
                user_level, recommended_action, captured_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (s.id, s.product_id, s.candidate_id, s.category, s.brand, s.product_name,
             s.official_price_jpy, s.domestic_used_price_jpy, s.domestic_buyback_price_jpy,
             s.overseas_price_jpy, s.overseas_source, s.stock_status, s.sale_method,
             s.premium_gap_jpy, s.premium_gap_percent, s.overseas_gap_jpy, s.overseas_gap_percent,
             s.premium_score, s.scarcity_score, s.liquidity_score, s.overseas_gap_score,
             s.source_confidence, s.overall_score,
             s.beginner_score, s.difficulty_score, s.beginner_profit_score,
             s.user_level, s.recommended_action, s.captured_at.isoformat()),
        )
        self.db.connection.commit()

    def list_market_snapshots(self, category: Optional[str] = None,
                               min_score: float = 0, limit: int = 50,
                               user_level: Optional[str] = None) -> list:
        from src.models.market_snapshot import MarketSnapshotModel
        query = "SELECT * FROM market_snapshots WHERE overall_score >= ?"
        params: list = [min_score]
        if category:
            query += " AND category = ?"
            params.append(category)
        if user_level == "beginner":
            query += " AND user_level IN ('beginner_easy', 'beginner_watch')"
        elif user_level == "advanced":
            query += " AND user_level IN ('advanced_high_profit', 'expert_only')"
        elif user_level and user_level != "all":
            query += " AND user_level = ?"
            params.append(user_level)
        query += " ORDER BY overall_score DESC, captured_at DESC LIMIT ?"
        params.append(limit)
        rows = self.db.connection.execute(query, tuple(params)).fetchall()
        return [MarketSnapshotModel(**dict(r)) for r in rows]

    def list_premium_candidates_with_snapshots(self, limit: int = 50,
                                                user_level: Optional[str] = None) -> list:
        """premium_score > 0のmarket_snapshotsをプレ値候補として返す。"""
        from src.models.market_snapshot import MarketSnapshotModel
        query = """SELECT * FROM market_snapshots
               WHERE (premium_score > 0.3 OR scarcity_score > 0.5
                      OR (user_level = 'beginner_easy' AND beginner_profit_score > 0))"""
        params: list = []
        if user_level == "beginner":
            query += " AND user_level IN ('beginner_easy', 'beginner_watch')"
        elif user_level == "advanced":
            query += " AND user_level IN ('advanced_high_profit', 'expert_only')"
        elif user_level and user_level != "all":
            query += " AND user_level = ?"
            params.append(user_level)
        query += " ORDER BY overall_score DESC LIMIT ?"
        params.append(limit)
        rows = self.db.connection.execute(query, tuple(params)).fetchall()
        return [MarketSnapshotModel(**dict(r)) for r in rows]

    def update_market_snapshot_scores(self, snapshot_id: str, **kwargs) -> None:
        """market_snapshotのスコア等を部分更新する。"""
        allowed = {
            "premium_score", "scarcity_score", "liquidity_score", "overseas_gap_score",
            "source_confidence", "overall_score",
            "beginner_score", "difficulty_score", "beginner_profit_score",
            "user_level", "recommended_action",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [snapshot_id]
        self.db.connection.execute(
            f"UPDATE market_snapshots SET {set_clause} WHERE id = ?", values,
        )
        self.db.connection.commit()

    def list_all_market_snapshots_raw(self, limit: int = 500) -> list:
        """全market_snapshotsを取得する（再計算用）。"""
        from src.models.market_snapshot import MarketSnapshotModel
        rows = self.db.connection.execute(
            "SELECT * FROM market_snapshots ORDER BY captured_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [MarketSnapshotModel(**dict(r)) for r in rows]

    # =========================================
    # Buyback Prices (Phase 9A)
    # =========================================

    def insert_buyback_price(self, bp) -> None:
        from src.models.buyback_price import BuybackPriceModel
        self.db.connection.execute(
            """INSERT OR REPLACE INTO buyback_prices
               (id, product_id, shop_id, shop_name, buyback_price,
                condition, buyback_url, observed_at, is_active, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (bp.id, bp.product_id, bp.shop_id, bp.shop_name, bp.buyback_price,
             bp.condition, bp.buyback_url, bp.observed_at.isoformat(),
             int(bp.is_active), bp.notes),
        )
        self.db.connection.commit()

    def list_buyback_prices(self, product_id: Optional[str] = None,
                             shop_id: Optional[str] = None,
                             active_only: bool = True, limit: int = 50) -> list:
        from src.models.buyback_price import BuybackPriceModel
        query = "SELECT * FROM buyback_prices WHERE 1=1"
        params: list = []
        if active_only:
            query += " AND is_active = 1"
        if product_id:
            query += " AND product_id = ?"
            params.append(product_id)
        if shop_id:
            query += " AND shop_id = ?"
            params.append(shop_id)
        query += " ORDER BY buyback_price DESC LIMIT ?"
        params.append(limit)
        try:
            rows = self.db.connection.execute(query, params).fetchall()
        except Exception:
            return []
        result = []
        for r in rows:
            d = dict(r)
            result.append(BuybackPriceModel(
                id=d["id"], product_id=d["product_id"],
                shop_id=d["shop_id"], shop_name=d.get("shop_name", ""),
                buyback_price=d["buyback_price"],
                condition=d.get("condition", "new_unopened"),
                buyback_url=d.get("buyback_url", ""),
                observed_at=datetime.fromisoformat(d["observed_at"]),
                is_active=bool(d.get("is_active", 1)),
                notes=d.get("notes", ""),
            ))
        return result

    # =========================================
    # Beginner Deals (Phase 9A)
    # =========================================

    def upsert_beginner_deal(self, deal) -> None:
        from src.models.beginner_deal import BeginnerDealModel
        self.db.connection.execute(
            """INSERT OR REPLACE INTO beginner_deals
               (id, product_id, product_name, category, brand,
                official_price_jpy, official_url, stock_status, sale_method,
                best_buyback_price, best_buyback_shop, best_buyback_url, buyback_condition,
                gross_profit_jpy, estimated_costs_jpy, net_profit_jpy, net_profit_rate,
                beginner_score, difficulty_score, user_level, recommended_action,
                is_active, scanned_at, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (deal.id, deal.product_id, deal.product_name, deal.category, deal.brand,
             deal.official_price_jpy, deal.official_url, deal.stock_status, deal.sale_method,
             deal.best_buyback_price, deal.best_buyback_shop, deal.best_buyback_url,
             deal.buyback_condition,
             deal.gross_profit_jpy, deal.estimated_costs_jpy, deal.net_profit_jpy,
             deal.net_profit_rate,
             deal.beginner_score, deal.difficulty_score, deal.user_level,
             deal.recommended_action,
             int(deal.is_active), deal.scanned_at.isoformat(), deal.notes),
        )
        self.db.connection.commit()

    def list_beginner_deals(self, user_level: Optional[str] = None,
                             category: Optional[str] = None,
                             min_profit: int = 0, limit: int = 50) -> list:
        from src.models.beginner_deal import BeginnerDealModel
        query = "SELECT * FROM beginner_deals WHERE is_active = 1 AND net_profit_jpy >= ?"
        params: list = [min_profit]
        if user_level == "beginner":
            query += " AND user_level IN ('beginner_easy', 'beginner_watch')"
        elif user_level == "advanced":
            query += " AND user_level IN ('advanced_high_profit', 'expert_only')"
        elif user_level and user_level != "all":
            query += " AND user_level = ?"
            params.append(user_level)
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY net_profit_jpy DESC LIMIT ?"
        params.append(limit)
        try:
            rows = self.db.connection.execute(query, params).fetchall()
        except Exception:
            return []
        result = []
        for r in rows:
            d = dict(r)
            result.append(BeginnerDealModel(
                id=d["id"], product_id=d["product_id"],
                product_name=d["product_name"],
                category=d.get("category", ""), brand=d.get("brand", ""),
                official_price_jpy=d.get("official_price_jpy"),
                official_url=d.get("official_url", ""),
                stock_status=d.get("stock_status", ""),
                sale_method=d.get("sale_method", "normal"),
                best_buyback_price=d.get("best_buyback_price"),
                best_buyback_shop=d.get("best_buyback_shop", ""),
                best_buyback_url=d.get("best_buyback_url", ""),
                buyback_condition=d.get("buyback_condition", ""),
                gross_profit_jpy=d.get("gross_profit_jpy", 0),
                estimated_costs_jpy=d.get("estimated_costs_jpy", 0),
                net_profit_jpy=d.get("net_profit_jpy", 0),
                net_profit_rate=d.get("net_profit_rate", 0),
                beginner_score=d.get("beginner_score", 0),
                difficulty_score=d.get("difficulty_score", 0),
                user_level=d.get("user_level", ""),
                recommended_action=d.get("recommended_action", ""),
                is_active=bool(d.get("is_active", 1)),
                scanned_at=datetime.fromisoformat(d["scanned_at"]),
                notes=d.get("notes", ""),
            ))
        return result

    # =========================================
    # Buyback History (Phase 10修正)
    # =========================================

    def insert_buyback_history(self, product_id: str, shop_id: str,
                                shop_name: str, price: int,
                                condition: str = "new_unopened",
                                observed_at: "datetime | None" = None) -> None:
        import ulid as _ulid
        now = observed_at or datetime.now()
        self.db.connection.execute(
            """INSERT INTO buyback_history (id, product_id, shop_id, shop_name, price, condition, observed_at)
               VALUES (?,?,?,?,?,?,?)""",
            (str(_ulid.new()), product_id, shop_id, shop_name, price, condition, now.isoformat()),
        )
        self.db.connection.commit()

    def get_latest_buyback_price(self, product_id: str, shop_id: str) -> Optional[int]:
        try:
            row = self.db.connection.execute(
                "SELECT price FROM buyback_history WHERE product_id=? AND shop_id=? ORDER BY observed_at DESC LIMIT 1",
                (product_id, shop_id),
            ).fetchone()
            return row["price"] if row else None
        except Exception:
            return None

    def get_previous_buyback_price(self, product_id: str, shop_id: str, offset: int = 1) -> Optional[int]:
        try:
            rows = self.db.connection.execute(
                "SELECT price FROM buyback_history WHERE product_id=? AND shop_id=? ORDER BY observed_at DESC LIMIT 1 OFFSET ?",
                (product_id, shop_id, offset),
            ).fetchall()
            return rows[0]["price"] if rows else None
        except Exception:
            return None

    def list_buyback_history(self, product_id: Optional[str] = None,
                              shop_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        query = "SELECT * FROM buyback_history WHERE 1=1"
        params: list = []
        if product_id:
            query += " AND product_id=?"
            params.append(product_id)
        if shop_id:
            query += " AND shop_id=?"
            params.append(shop_id)
        query += " ORDER BY observed_at DESC LIMIT ?"
        params.append(limit)
        try:
            return [dict(r) for r in self.db.connection.execute(query, params).fetchall()]
        except Exception:
            return []

    def insert_buyback_alert(self, product_id: str, product_name: str,
                              shop_id: str, shop_name: str,
                              alert_type: str, previous_price: int,
                              current_price: int, price_change: int) -> None:
        import ulid as _ulid
        self.db.connection.execute(
            """INSERT INTO buyback_alerts (id, product_id, product_name, shop_id, shop_name,
                alert_type, previous_price, current_price, price_change, detected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (str(_ulid.new()), product_id, product_name, shop_id, shop_name,
             alert_type, previous_price, current_price, price_change, datetime.now().isoformat()),
        )
        self.db.connection.commit()

    def list_buyback_alerts(self, limit: int = 30) -> list[dict]:
        try:
            return [dict(r) for r in self.db.connection.execute(
                "SELECT * FROM buyback_alerts ORDER BY detected_at DESC LIMIT ?", (limit,)
            ).fetchall()]
        except Exception:
            return []

    # =========================================
    # データ鮮度ヘルパー (Phase 13+)
    # =========================================

    def get_latest_buyback_observed_at(self) -> "Optional[datetime]":
        """buyback_prices の最新 observed_at を返す。"""
        try:
            row = self.db.connection.execute(
                "SELECT MAX(observed_at) AS ts FROM buyback_prices WHERE is_active = 1"
            ).fetchone()
            val = row["ts"] if row else None
            return datetime.fromisoformat(val) if val else None
        except Exception:
            return None

    def get_latest_beginner_deals_at(self) -> "Optional[datetime]":
        """beginner_deals の最新 scanned_at を返す。"""
        try:
            row = self.db.connection.execute(
                "SELECT MAX(scanned_at) AS ts FROM beginner_deals WHERE is_active = 1"
            ).fetchone()
            val = row["ts"] if row else None
            return datetime.fromisoformat(val) if val else None
        except Exception:
            return None

    def get_latest_buyback_history_at(self) -> "Optional[datetime]":
        """buyback_history の最新 observed_at を返す。"""
        try:
            row = self.db.connection.execute(
                "SELECT MAX(observed_at) AS ts FROM buyback_history"
            ).fetchone()
            val = row["ts"] if row else None
            return datetime.fromisoformat(val) if val else None
        except Exception:
            return None

    def list_watch_candidates(self, genres: "list[str] | None" = None, limit: int = 20) -> list:
        """上級者向け監視候補をproductsテーブルから取得する。

        camera / game_console など希少性・価格差が注目される商品を返す。
        buyback_prices の最新価格も LEFT JOIN で付加する。
        """
        if genres is None:
            genres = ["camera", "game_console"]

        placeholders = ",".join("?" * len(genres))
        query = f"""
            SELECT
                p.id, p.genre, p.name, p.brand,
                COALESCE(p.official_price, p.retail_price) AS price,
                p.is_lottery, p.is_discontinued, p.is_production_ended,
                bp.buyback_price, bp.shop_name, bp.buyback_url,
                bp.observed_at AS buyback_observed_at,
                ms.overall_score, ms.premium_score,
                ms.scarcity_score, ms.overseas_gap_score
            FROM products p
            LEFT JOIN (
                SELECT product_id, MAX(buyback_price) AS buyback_price,
                       shop_name, buyback_url, observed_at
                FROM buyback_prices
                WHERE is_active = 1
                GROUP BY product_id
            ) bp ON bp.product_id = p.id
            LEFT JOIN (
                SELECT product_id,
                       overall_score, premium_score,
                       scarcity_score, overseas_gap_score
                FROM market_snapshots
                WHERE id IN (
                    SELECT id FROM market_snapshots ms2
                    WHERE ms2.product_id = market_snapshots.product_id
                    ORDER BY captured_at DESC LIMIT 1
                )
            ) ms ON ms.product_id = p.id
            WHERE p.genre IN ({placeholders})
              AND p.is_active = 1
            ORDER BY COALESCE(ms.overall_score, 0) DESC, p.retail_price DESC
            LIMIT ?
        """
        try:
            rows = self.db.connection.execute(query, genres + [limit]).fetchall()
        except Exception:
            return []

        result = []
        for r in rows:
            d = dict(r)
            flags = []
            if d.get("is_lottery"):       flags.append("抽選販売")
            if d.get("is_discontinued"):  flags.append("SOLD OUT")
            if d.get("is_production_ended"): flags.append("生産終了")
            # カメラは希少性コメントを追加
            if d["genre"] == "camera":
                flags.append("中古プレ値あり")
            result.append({
                "product_id":       d["id"],
                "genre":            d["genre"],
                "product_name":     d["name"],
                "brand":            d.get("brand", ""),
                "official_price":   d.get("price") or 0,
                "buyback_price":    d.get("buyback_price"),
                "shop_name":        d.get("shop_name", ""),
                "buyback_url":      d.get("buyback_url", ""),
                "buyback_at":       d.get("buyback_observed_at"),
                "overall_score":    d.get("overall_score") or 0.0,
                "premium_score":    d.get("premium_score") or 0.0,
                "scarcity_score":   d.get("scarcity_score") or 0.0,
                "overseas_gap_score": d.get("overseas_gap_score") or 0.0,
                "flags":            flags,
            })
        return result
