from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import settings
from app.services.discovery_service import DiscoveryService
from app.services.gcs_service import GCSService

router = APIRouter()


@router.get("/health", summary="Quick liveness check")
def health():
    """Returns 200 immediately. Used by Cloud Run health probes."""
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}


@router.get("/status", summary="Detailed readiness check")
def status():
    """
    Checks connectivity to GCS bucket and discovery DB.
    Returns overall status plus per-dependency checks.
    """
    checks: dict = {}

    # GCS bucket
    try:
        gcs = GCSService()
        ok = gcs.bucket_exists()
        checks["gcs_bucket"] = {
            "status": "ok" if ok else "error",
            "bucket": settings.gcs_migration_bucket,
            "detail": None if ok else "Bucket not found or not accessible",
        }
    except Exception as exc:
        checks["gcs_bucket"] = {"status": "error", "detail": str(exc)}

    # Discovery DB
    try:
        disc = DiscoveryService()
        ok, err = disc.ping()
        checks["discovery_db"] = {
            "status": "ok" if ok else "error",
            "host": settings.discovery_db_host,
            "port": settings.discovery_db_port,
            "detail": err,
        }
    except Exception as exc:
        checks["discovery_db"] = {"status": "error", "detail": str(exc)}

    overall = "ok" if all(c["status"] == "ok" for c in checks.values()) else "degraded"

    return {
        "status": overall,
        "service": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
