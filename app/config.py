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

    # Central discovery DB  (medicalcircle_dev.cluster_hospitals)
    # All values injected at runtime via --set-secrets from Secret Manager
    discovery_db_host: str
    discovery_db_port: int = 3306
    discovery_db_user: str
    discovery_db_password: str
    discovery_db_name: str = "medicalcircle_dev"
    discovery_db_connect_timeout: int = 10

    # cluster_hospitals column names
    tenant_metadata_table: str = "cluster_hospitals"
    tenant_uuid_col: str = "id"
    tenant_name_col: str = "name"
    tenant_hospital_id_col: str = "hospital_id"
    tenant_cluster_type_col: str = "cluster_type"
    tenant_status_col: str = "status"

    # Secret naming: hyphens in UUID are replaced with underscores
    # e.g.  ab3b7a1d-aeb8-... → ab3b7a1d_aeb8_..._DATABASE_URI
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
