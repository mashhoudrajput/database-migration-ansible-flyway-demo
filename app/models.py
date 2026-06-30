from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ─── Bucket / migration file ─────────────────────────────────────────────────

class MigrationFile(BaseModel):
    version: str
    description: str
    filename: str
    checksum: str
    size_bytes: int
    gcs_path: str
    is_undo: bool = False


# ─── Per-tenant migration status ─────────────────────────────────────────────

class TenantState(str, Enum):
    UP_TO_DATE        = "up_to_date"
    PENDING           = "pending"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    NOT_CONNECTED     = "not_connected"
    ERROR             = "error"


class TenantMigrationStatus(BaseModel):
    tenant_id: str
    name: str = ""
    hospital_id: str = ""
    cluster_type: str = ""
    db_host: Optional[str] = None       # populated from Secret Manager URI
    db_name: Optional[str] = None
    last_applied_version: Optional[str] = None
    last_applied_at: Optional[datetime] = None
    applied_count: int = 0
    pending_count: int = 0
    pending_migrations: List[MigrationFile] = []
    checksum_mismatches: List[str] = []
    state: TenantState = TenantState.UP_TO_DATE
    error: Optional[str] = None


# ─── Aggregated migration status ─────────────────────────────────────────────

class MigrationStatusResponse(BaseModel):
    has_pending: bool
    bucket_migration_count: int
    undo_script_count: int
    pending_version_count: int
    pending_versions: List[str]
    tenants: List[TenantMigrationStatus]


# ─── Run ─────────────────────────────────────────────────────────────────────

class RunMigrationRequest(BaseModel):
    confirm: bool
    tenant_ids: Optional[List[str]] = None
    dry_run: bool = False


class TenantRunResult(BaseModel):
    tenant_id: str
    name: str = ""
    success: bool
    applied: List[str] = []
    would_apply: List[str] = []
    error: Optional[str] = None
    message: str = ""


class RunMigrationResponse(BaseModel):
    success: bool
    dry_run: bool
    tenants_processed: int
    tenants_succeeded: int
    tenants_failed: int
    results: List[TenantRunResult]


# ─── Rollback ─────────────────────────────────────────────────────────────────

class RollbackRequest(BaseModel):
    confirm: bool
    tenant_ids: Optional[List[str]] = None
    target_version: Optional[str] = None


class TenantRollbackResult(BaseModel):
    tenant_id: str
    name: str = ""
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


# ─── Validate ─────────────────────────────────────────────────────────────────

class ValidationIssue(BaseModel):
    level: str
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
    name: str
    hospital_id: str
    cluster_type: str           # "big_hospital" | "small_clinic"
    tenant_status: str          # "active" | "inactive"
    connection: str             # "connected" | "not_connected"
    db_host: Optional[str] = None
    db_name: Optional[str] = None
    applied_count: int = 0
    pending_count: int = 0
    has_pending: bool = False
    last_applied_version: Optional[str] = None
    error: Optional[str] = None


class TenantListResponse(BaseModel):
    count: int
    connected_count: int
    with_pending_count: int
    tenants: List[TenantInfo]


# ─── Bucket listing ──────────────────────────────────────────────────────────

class BucketListResponse(BaseModel):
    bucket: str
    prefix: str
    migration_count: int
    undo_count: int
    migrations: List[MigrationFile]
    undo_scripts: List[MigrationFile]
