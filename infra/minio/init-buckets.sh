#!/bin/sh
# Waits for MinIO to be ready then creates all DMS buckets.
# Scenario 2 (portal):  dms-contributors, dms-beneficiaries, dms-employees, dms-temp
# Scenario 1 (OCR):     scanned-documents, ocr-output
#
# NOTE: set -e is intentionally NOT used so individual step failures are handled per-command.

MINIO_ALIAS="localminio"
MINIO_URL="http://minio:9000"
MAX_RETRIES=30

echo ">>> Waiting for MinIO to be ready..."
retries=0
until mc alias set $MINIO_ALIAS $MINIO_URL "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" > /dev/null 2>&1; do
  retries=$((retries + 1))
  if [ "$retries" -ge "$MAX_RETRIES" ]; then
    echo "ERROR: MinIO did not become ready after $MAX_RETRIES retries. Aborting."
    exit 1
  fi
  echo "    MinIO not ready yet (attempt $retries/$MAX_RETRIES). Retrying in 3s..."
  sleep 3
done

echo ">>> MinIO is up. Creating buckets..."

create_bucket() {
  BUCKET=$1
  if mc ls $MINIO_ALIAS/$BUCKET > /dev/null 2>&1; then
    echo "    [SKIP] Bucket '$BUCKET' already exists."
  else
    mc mb $MINIO_ALIAS/$BUCKET
    echo "    [OK]   Created bucket: $BUCKET"
  fi

  # Enable versioning — prevents hard deletes; a delete marker is added instead
  mc version enable $MINIO_ALIAS/$BUCKET > /dev/null 2>&1 && \
    echo "    [OK]   Versioning enabled: $BUCKET" || \
    echo "    [WARN] Could not enable versioning on $BUCKET (may already be set)"
}

# ── Scenario 2: portal entity buckets ─────────────────────────────────────────
echo ">>> Creating Scenario 2 (portal) buckets..."
create_bucket "dms-contributors"
create_bucket "dms-beneficiaries"
create_bucket "dms-employees"
create_bucket "dms-temp"

# Lifecycle: auto-expire current object versions in dms-temp after 7 days.
echo ">>> Applying lifecycle policy to dms-temp..."
mc ilm rule add --expiry-days 7 $MINIO_ALIAS/dms-temp > /dev/null 2>&1 || \
mc ilm add        --expire-days 7 $MINIO_ALIAS/dms-temp > /dev/null 2>&1 || \
  echo "    [WARN] Could not apply lifecycle policy (mc version mismatch). Apply manually via MinIO Console."

# ── Scenario 1: OCR buckets ───────────────────────────────────────────────────
echo ">>> Creating Scenario 1 (OCR) buckets..."
create_bucket "scanned-documents"
create_bucket "ocr-output"

echo ">>> Bucket initialization complete."
mc ls $MINIO_ALIAS/
