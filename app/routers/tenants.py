from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.models import TenantListResponse, TenantInfo, TenantMigrationStatus
from app.services.discovery_service import DiscoveryService, Tenant
from app.services.migration_service import MigrationService
from app.services.secret_service import SecretService

router = APIRouter(prefix="/tenants", tags=["Tenants"])
_disc = DiscoveryService()
_svc = MigrationService()


def _enrich_tenant(t: Tenant, secret_svc: SecretService, bucket_total: int) -> TenantInfo:
    """Build a TenantInfo card: connection status + quick migration counts."""
    conn = secret_svc.get_tenant_connection_info(t.tenant_id)

    applied_count = 0
    pending_count = 0
    last_version = None

    if conn["connected"]:
        try:
            from app.services.db_service import DBService
            db_svc = DBService()
            host, port, user, pwd, database = secret_svc.get_tenant_credentials(t.tenant_id)
            db_conn = db_svc.connect(host, port, user, pwd, database)
            try:
                applied = db_svc.get_applied_versions(db_conn)
                last = db_svc.get_last_applied(db_conn)
                applied_count = len(applied)
                pending_count = max(0, bucket_total - applied_count)
                last_version = last["version"] if last else None
            finally:
                db_conn.close()
        except Exception:
            pass

    return TenantInfo(
        tenant_id=t.tenant_id,
        name=t.name,
        hospital_id=t.hospital_id,
        cluster_type=t.cluster_type,
        tenant_status=t.tenant_status,
        connection="connected" if conn["connected"] else "not_connected",
        db_host=conn["db_host"],
        db_name=conn["db_name"],
        applied_count=applied_count,
        pending_count=pending_count,
        has_pending=pending_count > 0,
        last_applied_version=last_version,
        error=conn["error"],
    )


@router.get(
    "/",
    response_model=TenantListResponse,
    summary="List all tenants with connection and migration status",
)
def list_tenants():
    """
    Returns every tenant from cluster_hospitals, enriched with:
    - Whether a Secret Manager URI exists for it (connected / not_connected)
    - Applied and pending migration counts
    Connected tenants are sorted first, then alphabetically by name.
    """
    tenants = _disc.discover_tenants()
    secret_svc = SecretService()
    bucket_total = len(_svc.gcs.list_migration_files())

    results: List[TenantInfo] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_enrich_tenant, t, secret_svc, bucket_total): t
            for t in tenants
        }
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda x: (0 if x.connection == "connected" else 1, x.name.lower()))

    return TenantListResponse(
        count=len(results),
        connected_count=sum(1 for r in results if r.connection == "connected"),
        with_pending_count=sum(1 for r in results if r.has_pending),
        tenants=results,
    )


@router.get(
    "/{tenant_id}/status",
    response_model=TenantMigrationStatus,
    summary="Full migration status for one tenant",
)
def tenant_status(tenant_id: str):
    """
    Shows the complete migration picture for a single tenant:
    which bucket migrations are applied (green) vs pending (orange),
    checksum mismatches, and last applied version.
    """
    tenant = _disc.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")

    bucket_migrations = _svc.gcs.list_migration_files()
    return _svc._tenant_status(tenant, bucket_migrations=bucket_migrations)


@router.get("/{tenant_id}/history", summary="Full migration history for one tenant")
def tenant_history(tenant_id: str):
    """Complete audit log (every version ever applied or attempted) for one tenant."""
    from app.services.db_service import DBService

    tenant = _disc.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")

    secret_svc = SecretService()
    conn_info = secret_svc.get_tenant_connection_info(tenant_id)
    if not conn_info["connected"]:
        raise HTTPException(
            status_code=503,
            detail=f"No Secret Manager entry found for tenant {tenant_id}: {conn_info['error']}",
        )

    db_svc = DBService()
    host, port, user, password, database = secret_svc.get_tenant_credentials(tenant_id)
    conn = db_svc.connect(host, port, user, password, database)
    try:
        history = db_svc.get_full_history(conn)
        last = db_svc.get_last_applied(conn)
    finally:
        conn.close()

    return {
        "tenant_id": tenant_id,
        "name": tenant.name,
        "hospital_id": tenant.hospital_id,
        "cluster_type": tenant.cluster_type,
        "db_host": conn_info["db_host"],
        "db_name": conn_info["db_name"],
        "total_applied": sum(1 for h in history if h.get("success")),
        "last_migration": last,
        "history": history,
    }
