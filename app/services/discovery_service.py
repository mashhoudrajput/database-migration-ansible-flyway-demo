"""Discover tenant metadata from the central MySQL discovery database."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import pymysql
import pymysql.cursors

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    db_host: str
    db_name: str
    db_port: Optional[int]


class DiscoveryService:
    def _connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            host=settings.discovery_db_host,
            port=settings.discovery_db_port,
            user=settings.discovery_db_user,
            password=settings.discovery_db_password,
            database=settings.discovery_db_name,
            connect_timeout=settings.discovery_db_connect_timeout,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def ping(self) -> bool:
        """Return True if the discovery DB is reachable."""
        try:
            conn = self._connect()
            conn.ping()
            conn.close()
            return True
        except Exception:
            return False

    def discover_tenants(self, where: Optional[str] = None) -> List[Tenant]:
        """
        Query the central DB for all tenants.
        `where` is an optional raw SQL WHERE clause (without the WHERE keyword).
        """
        cols = ", ".join([
            settings.tenant_uuid_col,
            settings.tenant_db_host_col,
            settings.tenant_db_name_col,
            settings.tenant_db_port_col,
        ])
        sql = f"SELECT {cols} FROM {settings.tenant_metadata_table}"
        if where:
            sql += f" WHERE {where}"

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        finally:
            conn.close()

        return [
            Tenant(
                tenant_id=row[settings.tenant_uuid_col],
                db_host=row[settings.tenant_db_host_col],
                db_name=row[settings.tenant_db_name_col],
                db_port=row.get(settings.tenant_db_port_col),
            )
            for row in rows
        ]

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        # Use parameterised value but the column/table names come from config
        col = settings.tenant_uuid_col
        tenants = self.discover_tenants(where=f"{col} = '{tenant_id}'")
        return tenants[0] if tenants else None
