# DMS Local Testing Guide

Complete step-by-step walkthrough from a cold machine to a fully verified DMS.

---

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Docker Desktop | Latest | `docker --version` |
| Python | 3.11+ | `python --version` |
| curl | any | `curl --version` |
| Postman | any | (optional, for GUI testing) |

---

## Step 1 — Start Docker and MinIO

Open a terminal in the `DMS` folder.

```powershell
# Start MinIO + bucket initialisation (detached)
docker compose up -d minio minio-init
```

Watch the init container finish:

```powershell
docker logs dms-minio-init --follow
```

Expected output:
```
>>> Waiting for MinIO to be ready...
>>> MinIO is up. Creating buckets...
    [OK]   Created bucket: dms-contributors
    [OK]   Versioning enabled: dms-contributors
    [OK]   Created bucket: dms-beneficiaries
    ...
>>> Bucket initialization complete.
```

Verify MinIO is running:

```powershell
docker ps --filter name=dms-minio
```

| Port | Purpose |
|------|---------|
| `localhost:9000` | S3-compatible API (used by FastAPI) |
| `localhost:9001` | Web Console — open in browser |

**MinIO Console login:** http://localhost:9001  
Username: `minioadmin` | Password: `minioadmin123`

---

## Step 2 — Create / Verify Buckets in the Console

1. Open http://localhost:9001
2. Go to **Buckets** in the left sidebar
3. Confirm all four buckets exist:
   - `dms-contributors`
   - `dms-beneficiaries`
   - `dms-employees`
   - `dms-temp`

If any are missing, the init container may have failed. Re-run it:

```powershell
docker compose up minio-init
```

---

## Step 3 — Start the FastAPI Service

```powershell
# Activate the virtual environment
.venv\Scripts\activate

# Start with hot-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected startup output:
```
INFO  | DMS startup: verifying MinIO buckets
INFO  | All buckets ready: ['dms-contributors', 'dms-beneficiaries', 'dms-employees', 'dms-temp']
INFO  | Application startup complete.
INFO  | Uvicorn running on http://0.0.0.0:8000
```

Open Swagger UI: http://localhost:8000/docs

---

## Step 4 — Health Check

```powershell
curl -s http://localhost:8000/api/v1/health | python -m json.tool
```

Expected response:
```json
{
  "status": "healthy",
  "service": "DMS Document Service",
  "version": "1.0.0",
  "storage": "connected",
  "buckets": {
    "dms-contributors":  "ok",
    "dms-beneficiaries": "ok",
    "dms-employees":     "ok",
    "dms-temp":          "ok"
  }
}
```

If `status` is `degraded`, MinIO isn't fully ready — wait 10 seconds and retry.

---

## Step 5 — Upload a Document

Using `curl` with the sample test file:

```powershell
curl -s -X POST http://localhost:8000/api/v1/documents/upload `
  -F "file=@tests/fixtures/test_upload.pdf;type=application/pdf" `
  -F "entity_type=contributors" `
  -F "entity_id=U001" `
  -F "document_type=identity" `
  -F "uploaded_by=TEST_USER" `
  | python -m json.tool
```

Expected response (HTTP 201):
```json
{
  "object_name":  "contributors/U001/identity/test_upload.pdf",
  "bucket":       "dms-contributors",
  "entity_type":  "contributors",
  "content_type": "application/pdf",
  "size_bytes":   218,
  "etag":         "abc123...",
  "uploaded_at":  "2024-01-15T10:30:00Z",
  "version_id":   "..."
}
```

> **Save the `object_name` value** — you'll use it in the next steps.

---

## Step 6 — Verify Object in MinIO Console

1. Open http://localhost:9001
2. Click **Object Browser** → `dms-contributors`
3. Navigate: `contributors` → `U001` → `identity`
4. You should see `test_upload.pdf` listed with its size and date.

Alternatively with curl (using MinIO's S3 list API via mc or awscli), you can verify via the metadata endpoint:

```powershell
curl -s http://localhost:8000/api/v1/documents/metadata/contributors/U001/identity/test_upload.pdf `
  | python -m json.tool
```

Expected response:
```json
{
  "object_name":   "contributors/U001/identity/test_upload.pdf",
  "bucket":        "dms-contributors",
  "size_bytes":    218,
  "content_type":  "application/pdf",
  "etag":          "abc123...",
  "last_modified": "2024-01-15T10:30:00Z",
  "version_id":    "...",
  "metadata": {
    "entity_id":     "U001",
    "document_type": "identity",
    "uploaded_by":   "TEST_USER"
  }
}
```

---

## Step 7 — Generate Presigned Download URL

```powershell
curl -s http://localhost:8000/api/v1/documents/presigned/download/contributors/U001/identity/test_upload.pdf `
  | python -m json.tool
```

Expected response:
```json
{
  "url":            "http://localhost:9000/dms-contributors/contributors/U001/identity/test_upload.pdf?X-Amz-Algorithm=...&X-Amz-Signature=...",
  "object_name":    "contributors/U001/identity/test_upload.pdf",
  "bucket":         "dms-contributors",
  "expiry_seconds": 3600,
  "method":         "GET"
}
```

**Test the presigned URL directly** (paste it into a browser or curl):

```powershell
# Copy the url value from the response and replace URL_HERE
curl -s -o downloaded_test.pdf "URL_HERE"
```

The file should download without any API credentials — this is how Salesforce users access documents directly from MinIO.

---

## Step 8 — Download via API Endpoint

```powershell
curl -s -o downloaded_via_api.pdf `
  http://localhost:8000/api/v1/documents/download/contributors/U001/identity/test_upload.pdf
```

Verify the file was downloaded:

```powershell
Get-Item downloaded_via_api.pdf | Select-Object Name, Length
```

---

## Step 9 — Delete the Document

```powershell
curl -s -X DELETE `
  http://localhost:8000/api/v1/documents/contributors/U001/identity/test_upload.pdf `
  | python -m json.tool
```

Expected response:
```json
{
  "object_name": "contributors/U001/identity/test_upload.pdf",
  "bucket":      "dms-contributors",
  "deleted":     true,
  "message":     "Document deleted successfully."
}
```

**Verify deletion — expect 404:**

```powershell
curl -s -o - -w "\nHTTP Status: %{http_code}\n" `
  http://localhost:8000/api/v1/documents/download/contributors/U001/identity/test_upload.pdf
```

Expected: `HTTP Status: 404`

> **Note on versioning:** MinIO versioning is enabled on all buckets. The delete adds a *delete marker* — the bytes still exist as a prior version. You can see this in the MinIO Console → dms-contributors → test_upload.pdf → Versions.

---

## Step 10 — Run Unit Tests

No Docker needed for unit tests (MinIO is fully mocked):

```powershell
pytest tests/unit/ -v
```

Expected output:
```
tests/unit/test_documents.py::test_health_returns_healthy PASSED
tests/unit/test_documents.py::test_upload_success PASSED
tests/unit/test_documents.py::test_upload_invalid_entity_type PASSED
tests/unit/test_documents.py::test_download_success PASSED
...
15 passed in 0.8s
```

---

## Step 11 — Run Integration Tests

Requires MinIO running (`docker compose up -d minio minio-init`):

```powershell
pytest tests/integration/ -v -m integration
```

Expected output:
```
tests/integration/test_minio_integration.py::test_health_check_live PASSED
tests/integration/test_minio_integration.py::test_upload_and_download_roundtrip PASSED
tests/integration/test_minio_integration.py::test_metadata PASSED
tests/integration/test_minio_integration.py::test_presigned_download_url PASSED
tests/integration/test_minio_integration.py::test_delete PASSED
5 passed in 1.2s
```

---

## Step 12 — Postman Testing

1. Open Postman
2. **Import** → `postman/DMS_Collection.json`
3. **Import** → `postman/DMS_Environment.json`
4. Select the **DMS Local Development** environment in the top-right dropdown
5. Open the **Upload Document** request:
   - Go to **Body** → **form-data**
   - For the `file` field, change type from `Text` to `File`
   - Select `tests/fixtures/test_upload.pdf`
6. Click **Send**
7. Run the full collection: **Collections** → **DMS Document Service** → **Run**

---

## Step 13 — Run Everything in Docker (Full Stack)

```powershell
docker compose up --build
```

This starts MinIO, initialises buckets, and runs FastAPI — all three containers.
FastAPI inside Docker connects to MinIO via the internal Docker network (`minio:9000`).
The `.env` file's `MINIO_ENDPOINT=localhost:9000` is overridden by the `environment:` block in `docker-compose.yml` which sets `MINIO_ENDPOINT=minio:9000`.

Verify:
```powershell
curl -s http://localhost:8000/api/v1/health | python -m json.tool
```

---

## Validation Error Reference

| Scenario | Expected HTTP Status | Body |
|---|---|---|
| `entity_type=invalid` | 400 | `{"detail": "Invalid entity_type 'invalid'..."}` |
| Empty file | 400 | `{"detail": "Uploaded file is empty (0 bytes)."}` |
| File > 25 MB | 413 | `{"detail": "File size X MB exceeds..."}` |
| Unsupported MIME type | 415 | `{"detail": "Content type '...' is not allowed."}` |
| File not found | 404 | `{"detail": "Document '...' not found in bucket '...'."}` |
| MinIO down | 503 | `{"detail": "Storage service unavailable: ..."}` |

---

## Stopping Everything

```powershell
# Stop containers (data persisted in Docker volume)
docker compose stop

# Stop and remove containers + volumes (clean slate)
docker compose down -v
```
