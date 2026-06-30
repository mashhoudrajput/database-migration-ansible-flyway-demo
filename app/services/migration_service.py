"""Core migration orchestration: status, run, rollback across all tenants."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from app.config import settings
from app.models import (
    MigrationFile,
    MigrationStatusResponse,
    RunMigrationResponse,
    RollbackResponse,
    TenantMigrationStatus,
    TenantRunResult,
    TenantRollbackResult,
    TenantState,
    ValidateResponse,
    ValidationIssue,
)
from app.services.db_service import DBService
from app.services.discovery_service import DiscoveryService, Tenant
from app.services.gcs_service import GCSService
from app.services.secret_service import SecretService

logger = logging.getLogger(__name__)


def _version_key(v: str) -> list:
    return [int(x) for x in v.split(".")]


class MigrationService:
    def __init__(self) -> None:
        self.gcs = GCSService()
        self.secret = SecretService()
        self.discovery = DiscoveryService()
        self.db = DBService()

    # ─── Status ──────────────────────────────────────────────────────────────

    def get_status(
        self, tenant_ids: Optional[List[str]] = None
    ) -> MigrationStatusResponse:
        bucket_migrations = self.gcs.list_migration_files()
        undo_map = self.gcs.list_undo_files()
        tenants = self._resolve_tenants(tenant_ids)

        tenant_statuses = self._parallel(
            self._tenant_status,
            tenants,
            bucket_migrations=bucket_migrations,
        )

        all_pending: set[str] = set()
        for ts in tenant_statuses:
            for m in ts.pending_migrations:
                all_pending.add(m.version)

        return MigrationStatusResponse(
            has_pending=any(ts.pending_count > 0 for ts in tenant_statuses),
            bucket_migration_count=len(bucket_migrations),
            undo_script_count=len(undo_map),
            pending_version_count=len(all_pending),
            pending_versions=sorted(all_pending, key=_version_key),
            tenants=tenant_statuses,
        )

    def _tenant_status(
        self, tenant: Tenant, *, bucket_migrations: List[MigrationFile]
    ) -> TenantMigrationStatus:
        try:
            conn_info = self.secret.get_tenant_connection_info(tenant.tenant_id)
            if not conn_info["connected"]:
                return TenantMigrationStatus(
                    tenant_id=tenant.tenant_id,
                    name=tenant.name,
                    hospital_id=tenant.hospital_id,
                    cluster_type=tenant.cluster_type,
                    state=TenantState.NOT_CONNECTED,
                    error=conn_info["error"],
                )

            host, port, user, password, database = self.secret.get_tenant_credentials(
                tenant.tenant_id
            )
            conn = self.db.connect(host, port, user, password, database)
            try:
                applied = self.db.get_applied_versions(conn)
                last = self.db.get_last_applied(conn)
            finally:
                conn.close()

            pending = [m for m in bucket_migrations if m.version not in applied]
            mismatches = [
                m.version
                for m in bucket_migrations
                if m.version in applied
                and applied[m.version]["checksum"] != m.checksum
            ]

            state = TenantState.UP_TO_DATE
            if mismatches:
                state = TenantState.CHECKSUM_MISMATCH
            elif pending:
                state = TenantState.PENDING

            return TenantMigrationStatus(
                tenant_id=tenant.tenant_id,
                name=tenant.name,
                hospital_id=tenant.hospital_id,
                cluster_type=tenant.cluster_type,
                db_host=host,
                db_name=database,
                last_applied_version=last["version"] if last else None,
                last_applied_at=last["applied_at"] if last else None,
                applied_count=len(applied),
                pending_count=len(pending),
                pending_migrations=pending,
                checksum_mismatches=mismatches,
                state=state,
            )
        except Exception as exc:
            logger.error("Status check failed for %s: %s", tenant.tenant_id, exc)
            return TenantMigrationStatus(
                tenant_id=tenant.tenant_id,
                name=tenant.name,
                hospital_id=getattr(tenant, "hospital_id", ""),
                cluster_type=getattr(tenant, "cluster_type", ""),
                state=TenantState.ERROR,
                error=str(exc),
            )

    # ─── Last applied ─────────────────────────────────────────────────────────

    def get_last_migration(
        self, tenant_ids: Optional[List[str]] = None
    ) -> List[dict]:
        tenants = self._resolve_tenants(tenant_ids)
        return self._parallel(self._tenant_last, tenants)

    def _tenant_last(self, tenant: Tenant) -> dict:
        try:
            host, port, user, password, database = self.secret.get_tenant_credentials(
                tenant.tenant_id
            )
            conn = self.db.connect(host, port, user, password, database)
            try:
                last = self.db.get_last_applied(conn)
            finally:
                conn.close()
            return {"tenant_id": tenant.tenant_id, "name": tenant.name, "last_migration": last}
        except Exception as exc:
            return {"tenant_id": tenant.tenant_id, "name": tenant.name, "error": str(exc)}

    # ─── History ──────────────────────────────────────────────────────────────

    def get_history(self, tenant_ids: Optional[List[str]] = None) -> List[dict]:
        tenants = self._resolve_tenants(tenant_ids)
        return self._parallel(self._tenant_history, tenants)

    def _tenant_history(self, tenant: Tenant) -> dict:
        try:
            host, port, user, password, database = self.secret.get_tenant_credentials(
                tenant.tenant_id
            )
            conn = self.db.connect(host, port, user, password, database)
            try:
                history = self.db.get_full_history(conn)
            finally:
                conn.close()
            return {
                "tenant_id": tenant.tenant_id,
                "total": len(history),
                "history": history,
            }
        except Exception as exc:
            return {"tenant_id": tenant.tenant_id, "error": str(exc)}

    # ─── Run ─────────────────────────────────────────────────────────────────

    def run_migrations(
        self,
        tenant_ids: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> RunMigrationResponse:
        bucket_migrations = self.gcs.list_migration_files()
        tenants = self._resolve_tenants(tenant_ids)

        results: List[TenantRunResult] = self._parallel(
            self._run_for_tenant,
            tenants,
            bucket_migrations=bucket_migrations,
            dry_run=dry_run,
        )

        succeeded = sum(1 for r in results if r.success)
        return RunMigrationResponse(
            success=succeeded == len(results),
            dry_run=dry_run,
            tenants_processed=len(results),
            tenants_succeeded=succeeded,
            tenants_failed=len(results) - succeeded,
            results=results,
        )

    def _run_for_tenant(
        self,
        tenant: Tenant,
        *,
        bucket_migrations: List[MigrationFile],
        dry_run: bool,
    ) -> TenantRunResult:
        try:
            host, port, user, password, database = self.secret.get_tenant_credentials(
                tenant.tenant_id
            )
            conn = self.db.connect(host, port, user, password, database)
            try:
                applied = self.db.get_applied_versions(conn)
                pending = [m for m in bucket_migrations if m.version not in applied]

                if not pending:
                    return TenantRunResult(
                        tenant_id=tenant.tenant_id,
                        name=tenant.name,
                        success=True,
                        message="Already up to date",
                    )

                if dry_run:
                    return TenantRunResult(
                        tenant_id=tenant.tenant_id,
                        name=tenant.name,
                        success=True,
                        would_apply=[m.version for m in pending],
                        message=f"Dry run: {len(pending)} migration(s) pending",
                    )

                applied_versions: List[str] = []
                for migration in pending:
                    sql = self.gcs.download_sql(migration.gcs_path)
                    t0 = time.time()
                    try:
                        self.db.execute_sql(conn, sql)
                        elapsed = int((time.time() - t0) * 1000)
                        self.db.record_migration(
                            conn,
                            version=migration.version,
                            description=migration.description,
                            filename=migration.filename,
                            checksum=migration.checksum,
                            execution_time_ms=elapsed,
                            success=True,
                        )
                        applied_versions.append(migration.version)
                        logger.info(
                            "tenant=%s version=%s elapsed_ms=%d",
                            tenant.tenant_id, migration.version, elapsed,
                        )
                    except Exception as exc:
                        conn.rollback()
                        elapsed = int((time.time() - t0) * 1000)
                        self.db.record_migration(
                            conn,
                            version=migration.version,
                            description=migration.description,
                            filename=migration.filename,
                            checksum=migration.checksum,
                            execution_time_ms=elapsed,
                            success=False,
                        )
                        raise RuntimeError(
                            f"Migration {migration.version} failed: {exc}"
                        ) from exc

                return TenantRunResult(
                    tenant_id=tenant.tenant_id,
                    name=tenant.name,
                    success=True,
                    applied=applied_versions,
                    message=f"Applied {len(applied_versions)} migration(s)",
                )
            finally:
                conn.close()

        except Exception as exc:
            logger.error("Run failed for %s: %s", tenant.tenant_id, exc)
            return TenantRunResult(
                tenant_id=tenant.tenant_id,
                name=tenant.name,
                success=False,
                error=str(exc),
            )

    # ─── Rollback ─────────────────────────────────────────────────────────────

    def rollback(
        self,
        tenant_ids: Optional[List[str]] = None,
        target_version: Optional[str] = None,
    ) -> RollbackResponse:
        undo_map = self.gcs.list_undo_files()
        tenants = self._resolve_tenants(tenant_ids)

        results: List[TenantRollbackResult] = self._parallel(
            self._rollback_tenant,
            tenants,
            undo_map=undo_map,
            target_version=target_version,
        )

        succeeded = sum(1 for r in results if r.success)
        return RollbackResponse(
            success=succeeded == len(results),
            tenants_processed=len(results),
            tenants_succeeded=succeeded,
            tenants_failed=len(results) - succeeded,
            results=results,
        )

    def _rollback_tenant(
        self,
        tenant: Tenant,
        *,
        undo_map: Dict[str, MigrationFile],
        target_version: Optional[str],
    ) -> TenantRollbackResult:
        try:
            host, port, user, password, database = self.secret.get_tenant_credentials(
                tenant.tenant_id
            )
            conn = self.db.connect(host, port, user, password, database)
            try:
                last = self.db.get_last_applied(conn)
                if not last:
                    return TenantRollbackResult(
                        tenant_id=tenant.tenant_id,
                        name=tenant.name,
                        success=False,
                        error="No migrations applied — nothing to roll back",
                    )

                version = target_version or last["version"]

                if version not in undo_map:
                    return TenantRollbackResult(
                        tenant_id=tenant.tenant_id,
                        name=tenant.name,
                        success=False,
                        error=(
                            f"No undo script for version {version}. "
                            f"Upload U{version}__<description>.sql to the bucket."
                        ),
                    )

                undo_sql = self.gcs.download_sql(undo_map[version].gcs_path)
                self.db.execute_sql(conn, undo_sql)
                self.db.delete_migration_record(conn, version)

                logger.info(
                    "Rolled back version=%s tenant=%s", version, tenant.tenant_id
                )
                return TenantRollbackResult(
                    tenant_id=tenant.tenant_id,
                    name=tenant.name,
                    success=True,
                    rolled_back_version=version,
                    message=f"Rolled back migration {version}",
                )
            finally:
                conn.close()

        except Exception as exc:
            logger.error("Rollback failed for %s: %s", tenant.tenant_id, exc)
            return TenantRollbackResult(
                tenant_id=tenant.tenant_id,
                name=tenant.name,
                success=False,
                error=str(exc),
            )

    # ─── Validate ─────────────────────────────────────────────────────────────

    def validate(self) -> ValidateResponse:
        migrations = self.gcs.list_migration_files()
        undos = self.gcs.list_undo_files()
        issues: List[ValidationIssue] = []

        versions_seen: set[str] = set()
        for m in migrations:
            if m.version in versions_seen:
                issues.append(ValidationIssue(
                    level="error",
                    filename=m.filename,
                    message=f"Duplicate version {m.version}",
                ))
            versions_seen.add(m.version)

        migration_versions = {m.version for m in migrations}
        for v, undo in undos.items():
            if v not in migration_versions:
                issues.append(ValidationIssue(
                    level="warning",
                    filename=undo.filename,
                    message=f"Undo script for version {v} has no matching forward migration",
                ))

        for m in migrations:
            if m.size_bytes == 0:
                issues.append(ValidationIssue(
                    level="error",
                    filename=m.filename,
                    message="Migration file is empty",
                ))

        return ValidateResponse(
            valid=not any(i.level == "error" for i in issues),
            migration_count=len(migrations),
            undo_count=len(undos),
            issues=issues,
        )

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _resolve_tenants(self, tenant_ids: Optional[List[str]]) -> List[Tenant]:
        all_tenants = self.discovery.discover_tenants()
        if tenant_ids:
            return [t for t in all_tenants if t.tenant_id in tenant_ids]
        return all_tenants

    def _parallel(self, fn, tenants: List[Tenant], **kwargs) -> list:
        results = []
        workers = min(settings.migration_max_workers, len(tenants) or 1)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fn, t, **kwargs): t for t in tenants}
            for fut in as_completed(futures):
                results.append(fut.result())
        return results
