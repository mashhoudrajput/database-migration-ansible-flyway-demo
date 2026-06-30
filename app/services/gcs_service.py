"""GCS bucket operations: list, download, and validate migration files."""
from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Tuple

from google.cloud import storage

from app.config import settings
from app.models import MigrationFile

# V3__add_email_column.sql  or  V3.1__hotfix.sql
_MIGRATE_RE = re.compile(r"^V(\d+(?:\.\d+)?)__(.+)\.sql$", re.IGNORECASE)
# U3__undo_add_email_column.sql
_UNDO_RE = re.compile(r"^U(\d+(?:\.\d+)?)__(.+)\.sql$", re.IGNORECASE)


def _version_key(v: str) -> list:
    return [int(x) for x in v.split(".")]


class GCSService:
    def __init__(self) -> None:
        self._client = storage.Client()

    def _iter_blobs(self):
        return self._client.list_blobs(
            settings.gcs_migration_bucket,
            prefix=settings.gcs_migration_prefix,
        )

    def list_migration_files(self) -> List[MigrationFile]:
        """Return all forward migration files sorted by version."""
        results: List[MigrationFile] = []
        for blob in self._iter_blobs():
            filename = blob.name.rsplit("/", 1)[-1]
            m = _MIGRATE_RE.match(filename)
            if not m:
                continue
            content = blob.download_as_bytes()
            results.append(
                MigrationFile(
                    version=m.group(1),
                    description=m.group(2).replace("_", " "),
                    filename=filename,
                    checksum=hashlib.sha256(content).hexdigest(),
                    size_bytes=blob.size or len(content),
                    gcs_path=blob.name,
                    is_undo=False,
                )
            )
        results.sort(key=lambda f: _version_key(f.version))
        return results

    def list_undo_files(self) -> Dict[str, MigrationFile]:
        """Return undo scripts keyed by their version string."""
        results: Dict[str, MigrationFile] = {}
        for blob in self._iter_blobs():
            filename = blob.name.rsplit("/", 1)[-1]
            m = _UNDO_RE.match(filename)
            if not m:
                continue
            content = blob.download_as_bytes()
            results[m.group(1)] = MigrationFile(
                version=m.group(1),
                description=m.group(2).replace("_", " "),
                filename=filename,
                checksum=hashlib.sha256(content).hexdigest(),
                size_bytes=blob.size or len(content),
                gcs_path=blob.name,
                is_undo=True,
            )
        return results

    def download_sql(self, gcs_path: str) -> str:
        """Download SQL content from a GCS path."""
        bucket = self._client.bucket(settings.gcs_migration_bucket)
        blob = bucket.blob(gcs_path)
        return blob.download_as_text(encoding="utf-8")

    def bucket_exists(self) -> bool:
        try:
            bucket = self._client.bucket(settings.gcs_migration_bucket)
            bucket.reload()
            return True
        except Exception:
            return False
