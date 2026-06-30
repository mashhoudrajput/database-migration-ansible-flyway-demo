from fastapi import APIRouter, HTTPException

from app.models import TenantListResponse, TenantInfo, TenantMigrationStatus
from app.services.discovery_service import DiscoveryService
from app.services.migration_service import MigrationService

router = APIRouter(prefix="/tenants", tags=["Tenants"])
_disc = DiscoveryService()
_svc = MigrationService()


@router.get("/", response_model=TenantListResponse, summary="List all tenants")
def list_tenants():
    """Returns all tenants from the central discovery database."""
    tenants = _disc.discover_tenants()
    return TenantListResponse(
        count=len(tenants),
        tenants=[
            TenantInfo(
                tenant_id=t.tenant_id,
                db_host=t.db_host,
                db_name=t.db_name,
                db_port=t.db_port,
            )
            for t in tenants
        ],
    )


@router.get(
    "/{tenant_id}/status",
    response_model=TenantMigrationStatus,
    summary="Migration status for a single tenant",
)
def tenant_status(tenant_id: str):
    """
    Shows pending migrations, applied count, checksum mismatches,
    and last applied version for a single tenant.
    """
    tenant = _disc.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")

    bucket_migrations = _svc.gcs.list_migration_files()
    return _svc._tenant_status(tenant, bucket_migrations=bucket_migrations)


@router.get("/{tenant_id}/history", summary="Full migration history for one tenant")
def tenant_history(tenant_id: str):
    """Returns every migration ever applied (or attempted) for this tenant."""
    from app.services.db_service import DBService
    from app.services.secret_service import SecretService

    tenant = _disc.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")

    db_svc = DBService()
    secret_svc = SecretService()

    host, port, user, password, database = secret_svc.get_tenant_credentials(tenant_id)
    conn = db_svc.connect(host, port, user, password, database)
    try:
        history = db_svc.get_full_history(conn)
        last = db_svc.get_last_applied(conn)
    finally:
        conn.close()

    return {
        "tenant_id": tenant_id,
        "db_host": tenant.db_host,
        "db_name": tenant.db_name,
        "total_applied": sum(1 for h in history if h.get("success")),
        "last_migration": last,
        "history": history,
    }
