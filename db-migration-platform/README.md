# Multi-Tenant MySQL Migration Platform

Production-ready migration automation for MySQL tenant databases using:

- GCP Secret Manager for credentials
- Python discovery for tenant resolution
- Flyway for schema migrations
- Ansible for orchestration and reporting
- GitHub Actions for branch-based deployment (`dev`, `qa`, `main`)

## Architecture

- **Migration server**: `db-init-cluster-001-dev` (and equivalent QA/Prod hosts)
- **Metadata database**: `medicalcircle-mysql-dev`
- **Tenant DB resolution**:
  - Query `cluster_hospitals.uuid`
  - Query `subnetwork_hospitals.uuid`
  - Convert UUID `-` to `_`
  - Read `${converted_uuid}_DATABASE_URI` from Secret Manager
- **Tenant URI format**:
  - `mysql://username:password@host:port/database`

## Repository Structure

```text
db-migration-platform/
├── migrations/
│   └── V1__create_mashhoud_table.sql
├── scripts/
│   └── discovery.py
├── ansible/
│   ├── inventory/
│   │   ├── dev.ini
│   │   ├── qa.ini
│   │   └── prod.ini
│   └── playbooks/
│       └── migrate.yml
├── .github/workflows/
│   └── db-migrate.yml
├── flyway.conf
├── requirements.txt
└── README.md
```

## 1) Prerequisites

On each migration server (`dev`, `qa`, `prod`):

- Ubuntu/Linux with outbound access to:
  - GCP APIs (`secretmanager.googleapis.com`)
  - Metadata DB private IP
  - Tenant DB private IPs
- Python `3.11+`
- `pip3`
- Ansible `2.14+`
- Flyway CLI `10+`
- Git

Install dependencies:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip ansible git unzip
```

Install Flyway:

```bash
curl -L "https://repo1.maven.org/maven2/org/flywaydb/flyway-commandline/10.15.2/flyway-commandline-10.15.2-linux-x64.tar.gz" -o flyway.tar.gz
sudo tar -xzf flyway.tar.gz -C /opt
sudo ln -sf /opt/flyway-10.15.2/flyway /usr/local/bin/flyway
flyway -v
```

## 2) Service Account and GCP Authentication

The automation uses `terraform-sa.json` with role:

- `roles/secretmanager.secretAccessor`

Set credentials in shell (if running manually):

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$PWD/terraform-sa.json"
export GCP_PROJECT_ID="lively-synapse-400818"
```

## 3) Secret Manager Setup

Create metadata DB secrets in project `lively-synapse-400818`:

- `DB_HOST`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_PORT`

Per tenant, create secret:

- `{tenant_uuid_with_underscores}_DATABASE_URI`

Example:

- `ab3b7a1d_aeb8_4b2d_a18f_a408e13d7636_DATABASE_URI`

Value format:

```text
mysql://username:password@host:3306/database_name
```

## 4) Metadata Database Requirements

The metadata DB configured in `DB_*` secrets must contain:

- `cluster_hospitals(uuid)`
- `subnetwork_hospitals(uuid)`

The discovery process queries both tables, unions UUIDs, and de-duplicates tenants.

## 5) Migration SQL Included

`migrations/V1__create_mashhoud_table.sql`

```sql
CREATE TABLE IF NOT EXISTS mashhoud (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 6) Local Execution (Manual)

From `db-migration-platform/`:

```bash
pip3 install -r requirements.txt
ansible-playbook ansible/playbooks/migrate.yml -i ansible/inventory/dev.ini -e env=dev
```

For QA:

```bash
ansible-playbook ansible/playbooks/migrate.yml -i ansible/inventory/qa.ini -e env=qa
```

For Prod:

```bash
ansible-playbook ansible/playbooks/migrate.yml -i ansible/inventory/prod.ini -e env=prod
```

## 7) GitHub Actions CI/CD

Workflow file:

- `.github/workflows/db-migrate.yml`

Branch mapping:

- `dev` -> `ansible/inventory/dev.ini`
- `qa` -> `ansible/inventory/qa.ini`
- `main` -> `ansible/inventory/prod.ini`

Required GitHub repository secrets:

- `MIGRATION_HOST_DEV`
- `MIGRATION_HOST_QA`
- `MIGRATION_HOST_PROD`
- `MIGRATION_SSH_USER`
- `MIGRATION_SSH_PRIVATE_KEY`
- `MIGRATION_SSH_PORT`

Pipeline behavior:

1. Checkout repository
2. Resolve target environment from branch
3. SSH to migration server
4. Update code from branch
5. Install Python dependencies
6. Run Ansible migration playbook

## 8) Logging and Reporting

Each run creates:

- `logs/tenant_migrations_<env>_<timestamp>.jsonl`
- `logs/migration_summary_<env>_<timestamp>.json`

Per-tenant log fields:

- `tenant_uuid`
- `migration_version`
- `execution_time`
- `status` (`SUCCESS` or `FAILED`)

Failure policy:

- If one tenant fails, remaining tenants continue.
- At the end, the playbook fails if any tenant failed.
- Full failure details are stored in summary JSON.

## 9) Security Notes

- Credentials are pulled at runtime from Secret Manager only.
- Flyway command execution is marked `no_log` in Ansible to avoid password leaks.
- Do not commit or expose `terraform-sa.json` in public repositories.
- Use private network routes between migration servers and databases.

## 10) Troubleshooting

- **Error: `403 secretmanager.versions.access`**
  - Verify service account has `Secret Manager Secret Accessor`.
  - Verify `GCP_PROJECT_ID` matches secret project.
- **Error: metadata connection timeout**
  - Verify private IP routing and firewall rules from migration server.
  - Verify metadata DB host/port in `DB_HOST` and `DB_PORT`.
- **Error: Flyway not found**
  - Ensure `/usr/local/bin/flyway` exists and `flyway -v` works.
- **No tenants discovered**
  - Verify `cluster_hospitals` and `subnetwork_hospitals` contain UUID rows.
  - Verify app user has `SELECT` permissions.
- **Tenant secret missing**
  - Ensure `${uuid_with_underscores}_DATABASE_URI` exists for each UUID.

## 11) Deployment Workflow

Recommended process:

1. Commit migration SQL in feature branch
2. Merge into `dev` and validate run
3. Promote to `qa` and validate run
4. Merge into `main` for production execution
5. Review generated summary files after each run
