#!/usr/bin/env python3
"""Discover tenant databases from metadata DB and GCP Secret Manager."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from typing import List, Set
from urllib.parse import unquote, urlparse

import pymysql
from google.cloud import secretmanager


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("tenant-discovery")


@dataclass(frozen=True)
class Tenant:
    tenant_uuid: str
    host: str
    port: int
    database: str
    username: str
    password: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover tenant databases and emit Flyway-ready JSON."
    )
    parser.add_argument(
        "--project-id",
        default=os.getenv("GCP_PROJECT_ID"),
        help="GCP project id hosting the secrets.",
    )
    parser.add_argument(
        "--credentials-file",
        default=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        help="Path to service account JSON for Google APIs.",
    )
    parser.add_argument(
        "--metadata-host-secret",
        default=os.getenv("METADATA_DB_HOST_SECRET", "DB_HOST"),
    )
    parser.add_argument(
        "--metadata-name-secret",
        default=os.getenv("METADATA_DB_NAME_SECRET", "DB_NAME"),
    )
    parser.add_argument(
        "--metadata-user-secret",
        default=os.getenv("METADATA_DB_USER_SECRET", "DB_USER"),
    )
    parser.add_argument(
        "--metadata-password-secret",
        default=os.getenv("METADATA_DB_PASSWORD_SECRET", "DB_PASSWORD"),
    )
    parser.add_argument(
        "--metadata-port-secret",
        default=os.getenv("METADATA_DB_PORT_SECRET", "DB_PORT"),
    )
    return parser.parse_args()


def build_secret_client(credentials_file: str | None) -> secretmanager.SecretManagerServiceClient:
    if credentials_file:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_file
    return secretmanager.SecretManagerServiceClient()


def access_secret(
    client: secretmanager.SecretManagerServiceClient,
    project_id: str,
    secret_name: str,
) -> str:
    secret_path = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": secret_path})
    return response.payload.data.decode("utf-8").strip()


def fetch_metadata_credentials(
    client: secretmanager.SecretManagerServiceClient,
    project_id: str,
    args: argparse.Namespace,
) -> dict:
    return {
        "host": access_secret(client, project_id, args.metadata_host_secret),
        "database": access_secret(client, project_id, args.metadata_name_secret),
        "user": access_secret(client, project_id, args.metadata_user_secret),
        "password": access_secret(client, project_id, args.metadata_password_secret),
        "port": int(access_secret(client, project_id, args.metadata_port_secret)),
    }


def fetch_uuids(conn: pymysql.connections.Connection) -> Set[str]:
    uuids: Set[str] = set()
    query_tables = ("cluster_hospitals", "subnetwork_hospitals")
    with conn.cursor() as cursor:
        for table in query_tables:
            cursor.execute(f"SELECT uuid FROM {table}")
            for row in cursor.fetchall():
                value = row.get("uuid")
                if value:
                    uuids.add(str(value))
    return uuids


def uuid_to_secret_name(uuid_value: str) -> str:
    return f"{uuid_value.replace('-', '_')}_DATABASE_URI"


def parse_mysql_uri(tenant_uuid: str, uri: str) -> Tenant:
    parsed = urlparse(uri)
    if parsed.scheme != "mysql":
        raise ValueError(
            f"Unsupported URI scheme for tenant {tenant_uuid}: {parsed.scheme}"
        )
    if not parsed.hostname or not parsed.path:
        raise ValueError(f"Incomplete MySQL URI for tenant {tenant_uuid}")

    database = parsed.path.lstrip("/")
    if not database:
        raise ValueError(f"Missing database name in URI for tenant {tenant_uuid}")

    return Tenant(
        tenant_uuid=tenant_uuid,
        host=parsed.hostname,
        port=parsed.port or 3306,
        database=database,
        username=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
    )


def discover_tenants(args: argparse.Namespace) -> List[Tenant]:
    if not args.project_id:
        raise ValueError("Missing --project-id or GCP_PROJECT_ID.")

    sm_client = build_secret_client(args.credentials_file)
    metadata = fetch_metadata_credentials(sm_client, args.project_id, args)

    LOGGER.info("Connecting metadata database at %s:%s", metadata["host"], metadata["port"])
    conn = pymysql.connect(
        host=metadata["host"],
        user=metadata["user"],
        password=metadata["password"],
        database=metadata["database"],
        port=metadata["port"],
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
        autocommit=True,
    )

    try:
        uuids = fetch_uuids(conn)
    finally:
        conn.close()

    tenants: List[Tenant] = []
    for tenant_uuid in sorted(uuids):
        secret_name = uuid_to_secret_name(tenant_uuid)
        try:
            db_uri = access_secret(sm_client, args.project_id, secret_name)
            tenant = parse_mysql_uri(tenant_uuid, db_uri)
            tenants.append(tenant)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.error(
                "Skipping tenant %s because secret '%s' could not be used: %s",
                tenant_uuid,
                secret_name,
                exc,
            )

    return tenants


def main() -> int:
    args = parse_args()
    try:
        tenants = discover_tenants(args)
        json.dump([asdict(t) for t in tenants], sys.stdout, indent=2)
        sys.stdout.write("\n")
        LOGGER.info("Discovered %d tenant databases", len(tenants))
        return 0
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Tenant discovery failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
