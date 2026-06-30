"""Tenant database operations: connection, history table, SQL execution."""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import pymysql
import pymysql.cursors
from pymysql.connections import Connection

from app.config import settings
from app.models import AppliedMigration

logger = logging.getLogger(__name__)

_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS `{table}` (
    `id`                INT AUTO_INCREMENT PRIMARY KEY,
    `version`           VARCHAR(50)  NOT NULL,
    `description`       VARCHAR(200) NOT NULL,
    `filename`          VARCHAR(300) NOT NULL,
    `checksum`          VARCHAR(64)  NOT NULL,
    `applied_at`        DATETIME     DEFAULT CURRENT_TIMESTAMP,
    `applied_by`        VARCHAR(100) DEFAULT 'migration-service',
    `execution_time_ms` INT,
    `success`           TINYINT(1)   DEFAULT 1,
    UNIQUE KEY `uq_version` (`version`),
    INDEX `idx_applied_at` (`applied_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


class DBService:
    def connect(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
    ) -> Connection:
        return pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connect_timeout=settings.discovery_db_connect_timeout,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )

    def ensure_history_table(self, conn: Connection) -> None:
        table = settings.migration_history_table
        with conn.cursor() as cur:
            cur.execute(_HISTORY_DDL.format(table=table))
        conn.commit()

    def get_applied_versions(self, conn: Connection) -> Dict[str, dict]:
        """Return {version: row_dict} for every successfully applied migration."""
        table = settings.migration_history_table
        self.ensure_history_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT version, description, filename, checksum, applied_at, "
                f"applied_by, execution_time_ms, success "
                f"FROM `{table}` WHERE success = 1 ORDER BY applied_at"
            )
            rows = cur.fetchall()
        return {row["version"]: row for row in rows}

    def get_last_applied(self, conn: Connection) -> Optional[dict]:
        table = settings.migration_history_table
        self.ensure_history_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT version, description, filename, checksum, applied_at, "
                f"applied_by, execution_time_ms "
                f"FROM `{table}` WHERE success = 1 ORDER BY applied_at DESC LIMIT 1"
            )
            return cur.fetchone()

    def get_full_history(self, conn: Connection) -> List[dict]:
        table = settings.migration_history_table
        self.ensure_history_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM `{table}` ORDER BY applied_at DESC"
            )
            return cur.fetchall()

    def execute_sql(self, conn: Connection, sql: str) -> None:
        """
        Execute a multi-statement SQL script.
        Splits on semicolons while skipping blank statements.
        """
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()

    def record_migration(
        self,
        conn: Connection,
        *,
        version: str,
        description: str,
        filename: str,
        checksum: str,
        execution_time_ms: int,
        success: bool,
    ) -> None:
        table = settings.migration_history_table
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO `{table}` "
                f"(version, description, filename, checksum, applied_by, execution_time_ms, success) "
                f"VALUES (%s, %s, %s, %s, 'migration-service', %s, %s)",
                (version, description, filename, checksum, execution_time_ms, int(success)),
            )
        conn.commit()

    def delete_migration_record(self, conn: Connection, version: str) -> None:
        """Remove a history record (used when rolling back)."""
        table = settings.migration_history_table
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM `{table}` WHERE version = %s", (version,))
        conn.commit()
