import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import pymysql


@dataclass(frozen=True)
class Tenant:
    tenant_uuid: str
    db_host: str
    db_name: str
    db_port: int | None = None


def _env(name: str, *, required: bool = True, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if required and (val is None or val == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    assert val is not None
    return val


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Discover tenant DBs from the central public database.")
    p.add_argument("--table", default=os.environ.get("TENANT_METADATA_TABLE", "tenant_metadata"))
    p.add_argument("--tenant-uuid-col", default=os.environ.get("TENANT_UUID_COL", "tenant_uuid"))
    p.add_argument("--db-host-col", default=os.environ.get("TENANT_DB_HOST_COL", "db_host"))
    p.add_argument("--db-name-col", default=os.environ.get("TENANT_DB_NAME_COL", "db_name"))
    p.add_argument("--db-port-col", default=os.environ.get("TENANT_DB_PORT_COL", "db_port"))
    p.add_argument("--include-port", action="store_true", default=False)
    p.add_argument("--where", default=os.environ.get("TENANT_METADATA_WHERE", ""))
    p.add_argument("--limit", type=int, default=int(os.environ.get("TENANT_METADATA_LIMIT", "0")))
    p.add_argument("--output", default=os.environ.get("TENANTS_OUTPUT", "tenants.json"))
    return p.parse_args()


def _build_query(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    cols = [
        f"{args.tenant_uuid_col} AS tenant_uuid",
        f"{args.db_host_col} AS db_host",
        f"{args.db_name_col} AS db_name",
    ]
    if args.include_port:
        cols.append(f"{args.db_port_col} AS db_port")

    sql = f"SELECT {', '.join(cols)} FROM {args.table}"
    params: dict[str, Any] = {}

    if args.where.strip():
        sql += f" WHERE {args.where}"

    sql += " ORDER BY 1"

    if args.limit and args.limit > 0:
        # MySQL doesn't allow binding LIMIT in all drivers consistently; use int.
        sql += f" LIMIT {int(args.limit)}"

    return sql, params


def discover_tenants(args: argparse.Namespace) -> list[Tenant]:
    sql, params = _build_query(args)

    tenants: list[Tenant] = []
    conn = pymysql.connect(
        host=_env("PUBLIC_DB_HOST"),
        port=int(_env("PUBLIC_DB_PORT", required=False, default="3306")),
        user=_env("PUBLIC_DB_USER"),
        password=_env("PUBLIC_DB_PASSWORD"),
        database=_env("PUBLIC_DB_NAME"),
        connect_timeout=int(_env("PUBLIC_DB_CONNECT_TIMEOUT", required=False, default="10")),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.Cursor,
    )
    try:
        with conn.cursor() as cur:
            # Params are only used for optional WHERE fragments in some deployments; keep for future.
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            rows: Sequence[tuple[Any, ...]] = cur.fetchall()
    finally:
        conn.close()

    for row in rows:
        tenant_uuid, db_host, db_name, *rest = row
        db_port = rest[0] if rest else None
        if db_port is not None:
            try:
                db_port = int(db_port)
            except Exception:
                raise RuntimeError(f"Invalid db_port for tenant {tenant_uuid}: {db_port!r}")

        tenants.append(
            Tenant(
                tenant_uuid=str(tenant_uuid),
                db_host=str(db_host),
                db_name=str(db_name),
                db_port=db_port,
            )
        )

    return tenants


def main() -> int:
    args = _parse_args()
    try:
        tenants = discover_tenants(args)
    except Exception as e:
        print(f"[discovery] ERROR: {e}", file=sys.stderr)
        return 2

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(tenants),
        "tenants": [asdict(t) for t in tenants],
    }

    try:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
    except Exception as e:
        print(f"[discovery] ERROR writing {args.output}: {e}", file=sys.stderr)
        return 3

    print(f"[discovery] Wrote {len(tenants)} tenants to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

