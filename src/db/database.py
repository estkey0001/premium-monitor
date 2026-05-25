"""SQLiteデータベース接続・初期化."""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# プロジェクトルートからの相対パス解決
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class Database:
    """SQLiteデータベースの接続管理とスキーマ初期化。"""

    def __init__(self, db_path: str = "data/premium_monitor.db"):
        self.db_path = PROJECT_ROOT / db_path
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        """接続を取得。未接続なら自動接続する。"""
        if self._connection is None:
            self._connection = self._connect()
        return self._connection

    def _connect(self) -> sqlite3.Connection:
        """SQLiteに接続。data/ ディレクトリがなければ作成。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # ジャーナルモード設定: WAL → DELETE → MEMORY の順にフォールバック
        for mode in ("WAL", "DELETE", "MEMORY"):
            try:
                result = conn.execute(f"PRAGMA journal_mode={mode}").fetchone()
                if result:
                    logger.debug("Journal mode set to: %s", result[0])
                    break
            except sqlite3.OperationalError:
                logger.debug("Journal mode %s not supported, trying next.", mode)
        conn.execute("PRAGMA foreign_keys=ON")
        logger.info("Database connected: %s", self.db_path)
        return conn

    def init_schema(self) -> None:
        """マイグレーションファイルを適用してスキーマを初期化。"""
        conn = self.connection
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

        for mf in migration_files:
            version = mf.stem  # e.g. "001_initial"
            # 既に適用済みか確認
            try:
                row = conn.execute(
                    "SELECT version FROM schema_migrations WHERE version = ?",
                    (version,),
                ).fetchone()
            except sqlite3.OperationalError:
                # schema_migrations テーブルがまだない（初回）
                row = None

            if row is not None:
                logger.debug("Migration %s already applied, skipping.", version)
                continue

            logger.info("Applying migration: %s", version)
            sql = mf.read_text(encoding="utf-8")
            # executescript はジャーナルモードをリセットする場合があるため
            # ステートメント単位で実行する
            # まずコメント行を除去してからセミコロン分割
            lines = [
                line for line in sql.splitlines()
                if not line.strip().startswith("--")
            ]
            clean_sql = "\n".join(lines)
            for statement in clean_sql.split(";"):
                statement = statement.strip()
                if statement:
                    try:
                        conn.execute(statement)
                    except sqlite3.OperationalError as e:
                        # "duplicate column name" は既にカラムが存在するケース（冪等性）
                        if "duplicate column name" in str(e).lower():
                            logger.debug("Migration %s: column already exists, skipping: %s", version, e)
                        else:
                            raise

            # 適用済みとして記録
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now().isoformat()),
            )
            conn.commit()

        logger.info("Schema initialization complete.")

    def close(self) -> None:
        """接続を閉じる。"""
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.debug("Database connection closed.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
