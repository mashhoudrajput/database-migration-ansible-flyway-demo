#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANSIBLE_DIR="${PROJECT_ROOT}/ansible"
INVENTORY="${ANSIBLE_DIR}/inventory"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/promote.sh dev
  ./scripts/promote.sh qa
  ./scripts/promote.sh prod
  ./scripts/promote.sh full

Behavior:
  dev   - Run migrations on Development (port 3307).
  qa    - Run migrations on QA (port 3308).
  prod  - Take Production backup, then run migrations on Production (port 3309).
  full  - Run dev -> qa -> prod in sequence, including prod backup.
EOF
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

STAGE="$1"

run_migrate() {
  local env="$1"
  echo "==> Running migrations for ${env}"
  ansible-playbook -i "${INVENTORY}" "${ANSIBLE_DIR}/migrate.yml" -e "env=${env}"
}

run_backup() {
  local env="$1"
  echo "==> Taking backup for ${env}"
  ansible-playbook -i "${INVENTORY}" "${ANSIBLE_DIR}/backup.yml" -e "env=${env}"
}

case "${STAGE}" in
  dev)
    run_migrate dev
    ;;
  qa)
    run_migrate qa
    ;;
  prod)
    run_backup prod
    run_migrate prod
    ;;
  full)
    run_migrate dev
    run_migrate qa
    run_backup prod
    run_migrate prod
    ;;
  *)
    echo "Invalid stage: ${STAGE}"
    usage
    exit 1
    ;;
esac

echo "Promotion stage '${STAGE}' completed successfully."
