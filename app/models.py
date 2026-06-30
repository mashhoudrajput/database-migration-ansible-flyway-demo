from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


# ─── Bucket / migration file ─────────────────────────────────────────────────

class MigrationFile(BaseModel):
    version: str
    description: str
    filename: str
    checksum: str        # SHA-256 of file content
    size_bytes: int
    gcs_path: str
    is_undo: bool = False


# ─── History record (stored inside each tenant DB) ───────────────────────────

class AppliedMigration(BaseModel):
    id: Optional[int] = None
    version: str
    description: str
    filename: str
    checksum: str
    applied_at: Optional[datetime] = None
    applied_by: str = "migration-service"
    execution_time_ms: Optional[int] = None
    success: bool = True

    model_config = {"from_attributes": True}


# ─── Per-tenant status ───────────────────────────────────────────────────────

class TenantState(str, Enum):
    UP_TO_DATE = "up_to_date"
    PENDING = "pending"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    ERROR = "error"


class TenantMigrationStatus(BaseModel):
    tenant_id: str
    db_host: str
    db_name: str
    last_applied_version: Optional[str] = None
    last_applied_at: Optional[datetime] = None
    applied_count: int = 0
    pending_count: int = 0
    pending_migrations: List[MigrationFile] = []
    checksum_mismatches: List[str] = []   # list of versions with changed files
    state: TenantState = TenantState.UP_TO_DATE
    error: Optional[str] = None


# ─── Migration status (aggregated) ───────────────────────────────────────────

class MigrationStatusResponse(BaseModel):
    has_pending: bool
    bucket_migration_count: int
    undo_script_count: int
    pending_version_count: int
    pending_versions: List[str]           # sorted across all tenants
    tenants: List[TenantMigrationStatus]


# ─── Run request / response ───────────────────────────────────────────────────

class RunMigrationRequest(BaseModel):
    confirm: bool
    tenant_ids: Optional[List[str]] = None   # None → all tenants
    dry_run: bool = False


class TenantRunResult(BaseModel):
    tenant_id: str
    success: bool
    applied: List[str] = []
    would_apply: List[str] = []     # dry_run only
    error: Optional[str] = None
    message: str = ""


class RunMigrationResponse(BaseModel):
    success: bool
    dry_run: bool
    tenants_processed: int
    tenants_succeeded: int
    tenants_failed: int
    results: List[TenantRunResult]


# ─── Rollback request / response ─────────────────────────────────────────────

class RollbackRequest(BaseModel):
    confirm: bool
    tenant_ids: Optional[List[str]] = None
    target_version: Optional[str] = None    # roll back to this version; None = one step


class TenantRollbackResult(BaseModel):
    tenant_id: str
    success: bool
    rolled_back_version: Optional[str] = None
    error: Optional[str] = None
    message: str = ""


class RollbackResponse(BaseModel):
    success: bool
    tenants_processed: int
    tenants_succeeded: int
    tenants_failed: int
    results: List[TenantRollbackResult]


# ─── Validate response ────────────────────────────────────────────────────────

class ValidationIssue(BaseModel):
    level: str     # "error" | "warning"
    filename: str
    message: str


class ValidateResponse(BaseModel):
    valid: bool
    migration_count: int
    undo_count: int
    issues: List[ValidationIssue]


# ─── Tenant list ─────────────────────────────────────────────────────────────

class TenantInfo(BaseModel):
    tenant_id: str
    db_host: str
    db_name: str
    db_port: Optional[int] = None


class TenantListResponse(BaseModel):
    count: int
    tenants: List[TenantInfo]


# ─── Bucket listing ──────────────────────────────────────────────────────────

class BucketListResponse(BaseModel):
    bucket: str
    prefix: str
    migration_count: int
    undo_count: int
    migrations: List[MigrationFile]
    undo_scripts: List[MigrationFile]
