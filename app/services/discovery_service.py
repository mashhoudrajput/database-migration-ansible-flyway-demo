"""Discover tenant metadata from medicalcircle_dev.cluster_hospitals."""
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
    tenant_id: str        # UUID e.g. ab3b7a1d-aeb8-4b2d-a18f-a408e13d7636
    name: str             # display name  e.g. "Katzen Krankenhaus"
    hospital_id: str      # short ID e.g. "542562"
    cluster_type: str     # "big_hospital" | "small_clinic"
    tenant_status: str    # "active" | "inactive"
    # NOTE: db_host / db_name / password come from Secret Manager at migration time,
    #       NOT from this table.


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

    def ping(self) -> tuple:
        """Returns (True, None) on success or (False, error_str) on failure."""
        try:
            conn = self._connect()
            conn.ping()
            conn.close()
            return True, None
        except Exception as exc:
            return False, str(exc)

    def discover_tenants(self, where: Optional[str] = None) -> List[Tenant]:
        c = settings
        sql = (
            f"SELECT `{c.tenant_uuid_col}`, `{c.tenant_name_col}`, "
            f"`{c.tenant_hospital_id_col}`, `{c.tenant_cluster_type_col}`, "
            f"`{c.tenant_status_col}` "
            f"FROM `{c.tenant_metadata_table}`"
        )
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
                tenant_id=str(row[c.tenant_uuid_col]),
                name=row.get(c.tenant_name_col) or "",
                hospital_id=str(row.get(c.tenant_hospital_id_col) or ""),
                cluster_type=row.get(c.tenant_cluster_type_col) or "unknown",
                tenant_status=row.get(c.tenant_status_col) or "unknown",
            )
            for row in rows
        ]

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        col = settings.tenant_uuid_col
        tenants = self.discover_tenants(where=f"`{col}` = '{tenant_id}'")
        return tenants[0] if tenants else None
