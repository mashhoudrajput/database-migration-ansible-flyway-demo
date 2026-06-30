from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    # GCP project
    gcp_project_id: str

    # GCS bucket where migration SQL files are uploaded
    gcs_migration_bucket: str
    gcs_migration_prefix: str = "migrations/"

    # Central discovery DB (holds tenant metadata: uuid, host, db_name)
    discovery_db_host: str
    discovery_db_port: int = 3306
    discovery_db_user: str
    discovery_db_password: str          # Injected via Cloud Run --set-secrets
    discovery_db_name: str
    discovery_db_connect_timeout: int = 10
    tenant_metadata_table: str = "tenant_metadata"
    tenant_uuid_col: str = "tenant_uuid"
    tenant_db_host_col: str = "db_host"
    tenant_db_name_col: str = "db_name"
    tenant_db_port_col: str = "db_port"

    # Secret Manager: tenant secrets are named {tenant_uuid}{suffix}
    secret_tenant_suffix: str = "_DATABASE_URI"

    # Table created inside each tenant DB to track migration history
    migration_history_table: str = "_migration_history"

    # Max concurrent tenant operations
    migration_max_workers: int = 10

    # App metadata
    app_name: str = "db-migration-service"
    app_version: str = "1.0.0"
    log_level: str = "INFO"


settings = Settings()
