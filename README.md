# Flyway + Ansible MySQL Migration Demo

This demo shows a safe, version-controlled database migration workflow using:

- Flyway for schema versioning
- Ansible for repeatable automation
- MySQL for Dev, QA, and Prod databases
- Docker Compose for local environment simulation

## Project Structure

```text
db-migration-demo/
├── docker/
├── docker-compose.yml
├── migrations/
│   ├── V1__create_users_table.sql
│   ├── V2__add_email_column.sql
│   ├── V3__drop_temp_table.sql
│   ├── V4__add_age_column.sql
│   ├── V5__rollback_demo.sql
│   ├── V7__create_temp_data_table.sql
│   ├── V8__add_columns_to_temp_data.sql
│   └── V99__invalid_migration_demo.sql
├── flyway/
│   ├── dev.conf
│   ├── qa.conf
│   └── prod.conf
├── ansible/
│   ├── inventory
│   ├── migrate.yml
│   └── backup.yml
├── scripts/
│   └── promote.sh
└── README.md
```

## Environment Mapping

- Development: `localhost:3307` (`dev-db`)
- QA: `localhost:3308` (`qa-db`)
- Production: `localhost:3309` (`prod-db`)
- DB name for all envs: `demo`
- MySQL root password for all envs: `root`

## Prerequisites (Linux)

- Docker + Docker Compose plugin (`docker compose`)
- Ansible (`ansible-playbook`)

Quick checks:

```bash
docker --version
docker compose version
ansible-playbook --version
```

## Step 1: Start Docker Environments

```bash
cd db-migration-demo
docker compose up -d
docker compose ps
```

Expected:

- `dev-db`, `qa-db`, `prod-db` are running
- Ports exposed as `3307`, `3308`, `3309`

## Step 2: Run Migrations on Development

```bash
ansible-playbook -i ansible/inventory ansible/migrate.yml -e env=dev
```

Expected:

- Flyway applies migrations in order: `V1`, `V2`, `V3`, `V4`, `V5`
- Migration state is recorded in `flyway_schema_history`

## Step 3: Promote Migrations to QA

```bash
ansible-playbook -i ansible/inventory ansible/migrate.yml -e env=qa
```

Expected:

- QA receives same ordered migration history as Dev
- No manual SQL execution needed

## Step 4: Promote to Production (with Backup)

```bash
ansible-playbook -i ansible/inventory ansible/backup.yml -e env=prod
ansible-playbook -i ansible/inventory ansible/migrate.yml -e env=prod
```

Or run the scripted workflow:

```bash
./scripts/promote.sh prod
```

Expected:

- A timestamped backup file appears under `backups/`
- Production migrations run only after backup is complete

## Step 5: Show Flyway Schema History

Run this for each environment:

```bash
docker exec dev-db mysql -uroot -proot -D demo -e "SELECT installed_rank, version, description, success FROM flyway_schema_history ORDER BY installed_rank;"
docker exec qa-db mysql -uroot -proot -D demo -e "SELECT installed_rank, version, description, success FROM flyway_schema_history ORDER BY installed_rank;"
docker exec prod-db mysql -uroot -proot -D demo -e "SELECT installed_rank, version, description, success FROM flyway_schema_history ORDER BY installed_rank;"
```

Expected versions:

- `1`, `2`, `3`, `4`, `5`, `7`, `8` with `success=1`

## Step 6: Demonstrate Rollback Scenarios

This demo uses a forward-only rollback strategy:

- `V4` adds `users.age`
- `V5` removes `users.age` (returns schema to stable state)

Check final `users` table columns:

```bash
docker exec prod-db mysql -uroot -proot -D demo -e "DESCRIBE users;"
```

Expected:

- Column `age` is not present after `V5`

## Failure Simulation (Flyway Protection Demo)

`V99__invalid_migration_demo.sql` intentionally contains bad SQL.
Normal promotions are safe because env configs pin target to version `8`.

To simulate failure in Dev:

```bash
docker run --rm --network host \
  -v "$(pwd):/flyway/project" -w /flyway/project \
  flyway/flyway:10.17.0 \
  -configFiles=flyway/dev.conf \
  -target=99 migrate
```

Expected:

- Flyway exits with error at version `99`
- Deployment stops immediately
- Already applied successful migrations remain intact

Inspect failed migration status:

```bash
docker exec dev-db mysql -uroot -proot -D demo -e "SELECT installed_rank, version, description, success FROM flyway_schema_history ORDER BY installed_rank;"
```

Reset Dev state after failure demo:

```bash
docker run --rm --network host \
  -v "$(pwd):/flyway/project" -w /flyway/project \
  flyway/flyway:10.17.0 \
  -configFiles=flyway/dev.conf \
  repair
```

## One-Command Promotion Options

```bash
./scripts/promote.sh dev    # migrate dev only
./scripts/promote.sh qa     # migrate qa only
./scripts/promote.sh prod   # backup + migrate prod
./scripts/promote.sh full   # dev -> qa -> prod (with prod backup)
```

## Client Demo Runbook (Step-by-Step)

Use this sequence during a live client demo to cover the highest-value scenarios.

### 0) Clean reset before starting

```bash
docker compose down -v
rm -rf backups
docker compose up -d
docker compose ps
```

### 1) Show initial state (all envs empty)

```bash
docker exec dev-db mysql -uroot -proot -D demo -e "SHOW TABLES;"
docker exec qa-db mysql -uroot -proot -D demo -e "SHOW TABLES;"
docker exec prod-db mysql -uroot -proot -D demo -e "SHOW TABLES;"
```

### 2) Promote Dev -> QA -> Prod safely

```bash
ansible-playbook -i ansible/inventory ansible/migrate.yml -e env=dev
ansible-playbook -i ansible/inventory ansible/migrate.yml -e env=qa
ansible-playbook -i ansible/inventory ansible/backup.yml -e env=prod
ansible-playbook -i ansible/inventory ansible/migrate.yml -e env=prod
```

### 3) Prove version consistency across environments

```bash
docker exec dev-db mysql -uroot -proot -D demo -e "SELECT version, description, success FROM flyway_schema_history ORDER BY installed_rank;"
docker exec qa-db mysql -uroot -proot -D demo -e "SELECT version, description, success FROM flyway_schema_history ORDER BY installed_rank;"
docker exec prod-db mysql -uroot -proot -D demo -e "SELECT version, description, success FROM flyway_schema_history ORDER BY installed_rank;"
```

Expected in all envs:
- versions `1..5,7,8`
- all `success=1`

### 4) Demonstrate rollback behavior (forward migration rollback)

```bash
docker exec prod-db mysql -uroot -proot -D demo -e "DESCRIBE users;"
```

Expected:
- `email` exists
- `age` does **not** exist (added in `V4`, removed in `V5`)
- `temp_data` exists (re-created in `V7`) with new columns from `V8`

### 5) Show safety guard with bad migration

```bash
docker run --rm --network host \
  -v "$(pwd):/flyway/project" -w /flyway/project \
  flyway/flyway:10.17.0 \
  -configFiles=flyway/dev.conf \
  -target=99 migrate
```

Expected:
- command fails on `V99__invalid_migration_demo.sql`
- Flyway stops deployment immediately

### 6) Show controlled recovery

```bash
docker run --rm --network host \
  -v "$(pwd):/flyway/project" -w /flyway/project \
  flyway/flyway:10.17.0 \
  -configFiles=flyway/dev.conf \
  repair
```

### 7) Show idempotency (safe re-run, no changes)

```bash
./scripts/promote.sh full
```

Expected:
- Flyway reports schema up to date where applicable
- no destructive behavior

## Additional Negative Tests

These are useful to show automation guardrails.

Invalid environment for migrate:

```bash
ansible-playbook -i ansible/inventory ansible/migrate.yml -e env=staging
```

Invalid environment for backup:

```bash
ansible-playbook -i ansible/inventory ansible/backup.yml -e env=staging
```

Invalid promote stage:

```bash
./scripts/promote.sh nonsense
```

Expected:
- each command fails fast with a clear validation message

## Tested Scenarios (Verified Locally)

- docker startup and health checks for `dev-db`, `qa-db`, `prod-db`
- first-time migration on all environments (`V1` -> `V5`)
- production backup creation before production migration
- idempotent re-run of migrations (`no migration necessary`)
- schema validation (`users` exists, `temp_data` re-created by `V7` and extended by `V8`, `age` removed by rollback demo)
- failure simulation with invalid `V99` migration
- post-failure recovery using `flyway repair`
- input validation failures (`env=staging`, invalid promote stage)

## Demo Reset

To reset and re-run from scratch:

```bash
docker compose down -v
docker compose up -d
rm -rf backups
```

Then repeat steps 2-6.
