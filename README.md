# Multi-tenant DB Migration Automation (GCP + Flyway)

This repo discovers tenant databases from a central MySQL database (your “public” database), retrieves per-tenant DB connection URIs from **GCP Secret Manager**, and runs **Flyway** migrations for each tenant using **Ansible**.

## Architecture

1. **Discovery** (`discovery.py`): Connects to the central MySQL DB and outputs `tenants.json`.
2. **Secret retrieval** (Ansible): For each `tenant_uuid`, reads Secret Manager secret `${tenant_uuid}_DATABASE_URI` (payload is a MySQL URI).
3. **Migration** (Flyway): Runs migrations from `flyway/sql` against each tenant DB.
4. **CI/CD** (GitHub Actions): On `dev`, `qa`, `main` pushes, SSH to a private VPC migration server and execute the playbook.

## Security (important)

- **Do not commit service account keys.** This repo currently contains `terraform-sa.json` (a real SA key with a private key). It is in `.gitignore`, but you should remove it from the repo and rotate the key if it has ever been exposed.
- Tenant DB credentials are **only** retrieved at runtime on the migration server (inside the VPC).

## Repo contents

- `discovery.py`: tenant discovery (writes `tenants.json`)
- `ansible/migrate.yml`: playbook that runs discovery, fetches secrets, runs Flyway, summarizes results
- `ansible/inventory/{dev,qa,prod}.ini`: inventories (the playbook runs locally on the migration server)
- `ansible/group_vars/all.yml`: shared variables (GCP project, SA key path, Flyway paths)
- `flyway/conf/flyway.conf`: base Flyway config (no secrets)
- `flyway/sql/V1__init.sql`, `flyway/sql/V2__example_change.sql`: example migrations
- `.github/workflows/db-migrate.yml`: branch-triggered remote execution via SSH

## Migration server setup (inside the VPC)

### 1) VM placement and network

- Place the migration server in the **same VPC** (or peered VPC) as tenant DBs (private IP connectivity).
- Allow egress to:
  - **Secret Manager** APIs (private access as applicable)
  - Any required DNS resolvers
- Ensure the VM can reach the central MySQL DB (private IP).

### 2) Install prerequisites

On the migration server:

- **Python 3** (for `discovery.py`)
- **Ansible** (runs playbook locally)
- **Flyway CLI** (installed on PATH as `flyway`)

Install Ansible + collection:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip
python3 -m pip install --user ansible

ansible-galaxy collection install -r ansible/requirements.yml
```

Install Flyway (example; use your preferred method/package manager):

```bash
flyway -v
```

### 3) GCP service account key file (server-side)

You selected a **service account JSON key file on the server**.

- Place the key file at the path configured by `gcp_sa_key_file` in `ansible/group_vars/all.yml`
  - Default: `/etc/gcp/migration-sa.json`
- Permissions:

```bash
sudo mkdir -p /etc/gcp
sudo chown root:root /etc/gcp
sudo chmod 700 /etc/gcp
sudo chmod 600 /etc/gcp/migration-sa.json
```

IAM permissions (minimum):

- `roles/secretmanager.secretAccessor` on the relevant tenant secrets (or narrower, per-secret IAM).

### 4) Central `public` DB credentials (environment variables)

Set these on the migration server (systemd unit, profile, or a secure runtime mechanism):

- `PUBLIC_DB_HOST`
- `PUBLIC_DB_PORT` (optional; default `3306`)
- `PUBLIC_DB_NAME`
- `PUBLIC_DB_USER`
- `PUBLIC_DB_PASSWORD`
- Optional:
  - `PUBLIC_DB_CONNECT_TIMEOUT` (default `10`)

Example:

```bash
export PUBLIC_DB_HOST="10.0.0.10"
export PUBLIC_DB_PORT="3306"
export PUBLIC_DB_NAME="public"
export PUBLIC_DB_USER="migration_reader"
export PUBLIC_DB_PASSWORD="***"
```

## Secret Manager contract (per-tenant)

- Secret name: `{{ tenant_uuid }}_DATABASE_URI`
- Secret payload: **MySQL URI**, for example:
  - `mysql://user:pass@10.7.1.3:3306/tenant_db`

The playbook converts `mysql://...` to `jdbc:mysql://...` and passes Flyway `-user` / `-password`.

Note: If your password contains `@` (example: `medicalcircle@2023`), a normal URI is ambiguous unless encoded. The playbook intentionally parses the URI using the **last `@`** as the host separator so the example secret value you gave still works.

## Running migrations manually (on the migration server)

From a checked out copy of this repo:

```bash
ansible-playbook -i ansible/inventory/dev.ini ansible/migrate.yml
```

Branch/environment mapping is:

- `dev` → `ansible/inventory/dev.ini`
- `qa` → `ansible/inventory/qa.ini`
- `main` → `ansible/inventory/prod.ini`

## GitHub Actions CI/CD

Workflow: `.github/workflows/db-migrate.yml`

### Required GitHub Secrets

- `MIGRATION_HOST`: migration server DNS or IP
- `MIGRATION_USER`: SSH username
- `MIGRATION_SSH_KEY`: private key (PEM) for SSH
- `MIGRATION_SSH_PORT`: optional (defaults to `22`)

### How it runs

On push to `dev`, `qa`, or `main`:

- The workflow tars the repo (excluding `.git` and `terraform-sa.json`)
- Uploads it to the migration server
- Extracts to `/tmp/db-migrate-$GITHUB_SHA`
- Runs `ansible-playbook` using the inventory matching the branch
- Deletes the extracted directory and tarball

## Failure handling / summary

The playbook attempts **all tenants** and records per-tenant results.

- A failed tenant migration is logged and the play continues.
- At the end, a summary is printed listing succeeded and failed tenants.
- If `fail_on_tenant_error: true` (default), the play fails if any tenant failed (so CI goes red).

## Configuration knobs

Edit these in `ansible/group_vars/all.yml`:

- `gcp_project_id`: GCP project hosting the tenant secrets
- `gcp_sa_key_file`: path to the SA JSON on the migration server
- `flyway_bin`: Flyway executable name/path
- `fail_on_tenant_error`: whether CI should fail if any tenant fails

## First test (Windows): SSH VM, connect DB, SHOW DATABASES

If PowerShell blocks `gcloud` with an execution policy error, use the helper scripts:

- `scripts/gcloud.ps1`: wrapper that runs `gcloud.cmd` (no `.ps1` Cloud SDK wrapper)
- `scripts/first-test.ps1`: authenticates and runs `SHOW DATABASES;` via SSH

Example (PowerShell):

```powershell
.\scripts\gcloud.ps1 version

# Run the full first test (fill in your zone)
.\scripts\first-test.ps1 -Zone "YOUR_ZONE"
```

