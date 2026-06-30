#!/usr/bin/env bash
# Run once to provision the migration service account and grant it the minimum
# required IAM roles. Replace the variables at the top before running.
set -euo pipefail

PROJECT_ID="my-gcp-project"
REGION="us-central1"
SA_NAME="migration-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
GCS_BUCKET="my-migration-bucket"

# ── 1. Create service account ─────────────────────────────────────────────────
gcloud iam service-accounts create "${SA_NAME}" \
  --project="${PROJECT_ID}" \
  --display-name="DB Migration Service (Cloud Run)"

# ── 2. GCS bucket — read migration files ──────────────────────────────────────
gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectViewer"

# ── 3. Secret Manager — read tenant secrets and discovery DB password ──────────
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"

# ── 4. Cloud Run — allow it to run as this SA ─────────────────────────────────
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.serviceAgent"

# ── 5. Cloud Build — allow it to deploy Cloud Run ────────────────────────────
CB_SA="$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')@cloudbuild.gserviceaccount.com"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/run.admin"

gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/iam.serviceAccountUser"

# ── 6. Create GCS bucket (if it does not exist) ───────────────────────────────
gcloud storage buckets create "gs://${GCS_BUCKET}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access 2>/dev/null || echo "Bucket already exists, skipping."

# ── 7. Create the discovery-db-password secret (add your value after) ─────────
gcloud secrets create discovery-db-password \
  --project="${PROJECT_ID}" \
  --replication-policy=automatic 2>/dev/null || echo "Secret already exists."

echo ""
echo "Done. Next steps:"
echo "  1. Add the DB password:  echo -n 'yourpassword' | gcloud secrets versions add discovery-db-password --data-file=-"
echo "  2. Add each tenant secret:  echo -n 'mysql://user:pass@host/db' | gcloud secrets versions add {tenant_uuid}_DATABASE_URI --data-file=-"
echo "  3. Run:  gcloud builds submit --config=cloudbuild.yaml --project=${PROJECT_ID}"
