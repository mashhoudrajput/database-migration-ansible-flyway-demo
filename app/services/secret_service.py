"""GCP Secret Manager: retrieve per-tenant database credentials."""
from __future__ import annotations

import re
from typing import Tuple

from google.cloud import secretmanager

from app.config import settings

# Handles passwords that contain the @ character by taking the *last* @
_URI_RE = re.compile(
    r"^(?:jdbc:)?mysql://"
    r"(?P<user>[^:]+):(?P<password>.+)@"
    r"(?P<host>[^:/]+)(?::(?P<port>\d+))?/(?P<database>[^?]+)"
)


class SecretService:
    def __init__(self) -> None:
        self._client = secretmanager.SecretManagerServiceClient()

    def _secret_path(self, name: str) -> str:
        return f"projects/{settings.gcp_project_id}/secrets/{name}/versions/latest"

    def get_raw(self, secret_name: str) -> str:
        """Fetch the latest version of a named secret."""
        resp = self._client.access_secret_version(name=self._secret_path(secret_name))
        return resp.payload.data.decode("utf-8").strip()

    def get_tenant_credentials(
        self, tenant_id: str
    ) -> Tuple[str, int, str, str, str]:
        """
        Returns (host, port, user, password, database) for a tenant.
        Secret name: {uuid_with_underscores}{suffix}
        e.g. ab3b7a1d_aeb8_4b2d_a18f_a408e13d7636_DATABASE_URI
        Secret value: mysql://root:medicalcircle@2023@10.7.1.3:3306/cluster_db
        """
        safe_id = tenant_id.replace("-", "_")   # UUIDs use hyphens; secrets use underscores
        secret_name = f"{safe_id}{settings.secret_tenant_suffix}"
        uri = self.get_raw(secret_name)
        return self._parse_uri(uri)

    def get_tenant_connection_info(self, tenant_id: str) -> dict:
        """
        Returns connection metadata dict — never raises.
        On success: {connected: True, db_host, db_port, db_name, error: None}
        On failure: {connected: False, db_host: None, ..., error: str}
        """
        try:
            host, port, user, _pwd, database = self.get_tenant_credentials(tenant_id)
            return {"connected": True, "db_host": host, "db_port": port,
                    "db_name": database, "error": None}
        except Exception as exc:
            return {"connected": False, "db_host": None, "db_port": None,
                    "db_name": None, "error": str(exc)}

    def _parse_uri(self, uri: str) -> Tuple[str, int, str, str, str]:
        # Strip jdbc: prefix if present
        uri = uri.strip()
        if uri.startswith("jdbc:"):
            uri = uri[5:]

        # Split on last @ to handle @ in passwords
        if "://" not in uri:
            raise ValueError(f"Unrecognised URI scheme: {uri[:40]}")

        scheme_end = uri.index("://") + 3
        authority = uri[scheme_end:]
        last_at = authority.rfind("@")
        if last_at == -1:
            raise ValueError("No @ found in database URI")

        credentials = authority[:last_at]
        rest = authority[last_at + 1:]

        colon = credentials.index(":")
        user = credentials[:colon]
        password = credentials[colon + 1:]

        slash = rest.index("/")
        host_port = rest[:slash]
        database = rest[slash + 1:].split("?")[0]

        if ":" in host_port:
            host, port_str = host_port.rsplit(":", 1)
            port = int(port_str)
        else:
            host = host_port
            port = 3306

        return host, port, user, password, database
