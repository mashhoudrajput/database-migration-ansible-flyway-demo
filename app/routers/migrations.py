from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.models import (
    BucketListResponse,
    RunMigrationRequest,
    RunMigrationResponse,
    RollbackRequest,
    RollbackResponse,
    MigrationStatusResponse,
    ValidateResponse,
)
from app.services.migration_service import MigrationService

router = APIRouter(prefix="/migrations", tags=["Migrations"])
_svc = MigrationService()


@router.get(
    "/status",
    response_model=MigrationStatusResponse,
    summary="Check migration status across tenants",
)
def migration_status(
    tenant_ids: Optional[List[str]] = Query(
        default=None,
        description="Filter to specific tenant IDs. Omit for all tenants.",
    )
):
    """
    Compares migration files in the GCS bucket against each tenant's applied history.
    Shows what is pending per tenant so you can decide whether to run.
    """
    return _svc.get_status(tenant_ids)


@router.get("/last", summary="Last applied migration per tenant")
def last_migration(
    tenant_ids: Optional[List[str]] = Query(default=None)
):
    """Returns the most recently applied migration for each tenant."""
    return {"tenants": _svc.get_last_migration(tenant_ids)}


@router.get("/history", summary="Full migration history per tenant")
def migration_history(
    tenant_ids: Optional[List[str]] = Query(default=None)
):
    """Returns complete migration history (all versions, applied_at, checksum) per tenant."""
    return {"tenants": _svc.get_history(tenant_ids)}


@router.get(
    "/bucket",
    response_model=BucketListResponse,
    summary="List migration files in GCS bucket",
)
def bucket_list():
    """
    Lists all forward migration files (V*.sql) and undo scripts (U*.sql)
    currently in the configured GCS bucket.
    """
    gcs = _svc.gcs
    migrations = gcs.list_migration_files()
    undos = list(gcs.list_undo_files().values())
    return BucketListResponse(
        bucket=settings.gcs_migration_bucket,
        prefix=settings.gcs_migration_prefix,
        migration_count=len(migrations),
        undo_count=len(undos),
        migrations=migrations,
        undo_scripts=undos,
    )


@router.get(
    "/validate",
    response_model=ValidateResponse,
    summary="Validate migration files in bucket",
)
def validate():
    """
    Checks bucket contents for:
    - Duplicate version numbers
    - Empty migration files
    - Undo scripts without a matching forward migration
    Does NOT connect to tenant databases.
    """
    return _svc.validate()


@router.post(
    "/run",
    response_model=RunMigrationResponse,
    summary="Run pending migrations",
)
def run_migrations(body: RunMigrationRequest):
    """
    Applies all pending migrations from the GCS bucket to each tenant database.

    - Set `confirm: true` to execute (prevents accidental runs).
    - Set `dry_run: true` to preview without making changes.
    - Optionally scope to `tenant_ids` (omit for all tenants).
    - Migrations are applied concurrently across tenants, sequentially within each tenant.
    - If a migration fails for a tenant, that tenant stops; others continue.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set 'confirm: true' to run migrations. "
                   "Preview pending changes with GET /migrations/status first.",
        )
    return _svc.run_migrations(tenant_ids=body.tenant_ids, dry_run=body.dry_run)


@router.post(
    "/rollback",
    response_model=RollbackResponse,
    summary="Rollback the last (or target) migration",
)
def rollback(body: RollbackRequest):
    """
    Rolls back the last applied migration using the matching U{version}__.sql undo script
    from the GCS bucket.

    - Upload `U{N}__<description>.sql` to the bucket before calling this endpoint.
    - `target_version` defaults to the most recently applied version per tenant.
    - Set `confirm: true` to execute.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set 'confirm: true' to run rollback.",
        )
    return _svc.rollback(
        tenant_ids=body.tenant_ids,
        target_version=body.target_version,
    )
