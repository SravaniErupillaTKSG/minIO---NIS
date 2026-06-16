# DMS API Contracts — v1

Base URL: `http://localhost:8000/api/v1`

All requests and responses use `application/json` unless otherwise noted.

---

## Health Check

### `GET /health`

**Purpose:** Verify the service and all MinIO buckets are reachable.

**Response 200**
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

**Response 200 (degraded)**
```json
{
  "status": "degraded",
  "service": "DMS Document Service",
  "version": "1.0.0",
  "storage": "partially_connected",
  "buckets": {
    "dms-contributors":  "ok",
    "dms-beneficiaries": "missing",
    "dms-employees":     "ok",
    "dms-temp":          "ok"
  }
}
```

---

## Upload Document

### `POST /documents/upload`

**Content-Type:** `multipart/form-data`

**Form Fields**

| Field           | Type   | Required | Description                                              |
|-----------------|--------|----------|----------------------------------------------------------|
| `file`          | binary | Yes      | The document file                                        |
| `entity_type`   | string | Yes      | `contributors` \| `beneficiaries` \| `employees` \| `temp` |
| `entity_id`     | string | Yes      | Unique ID of the owner (e.g. `U001`, `E042`)            |
| `document_type` | string | Yes      | Category folder (e.g. `identity`, `contracts`, `claims`) |
| `uploaded_by`   | string | No       | System or user initiating the upload                     |

**Object stored at:** `{entity_type}/{entity_id}/{document_type}/{filename}`

**Response 201**
```json
{
  "object_name":  "contributors/U001/identity/passport.pdf",
  "bucket":       "dms-contributors",
  "entity_type":  "contributors",
  "content_type": "application/pdf",
  "size_bytes":   204800,
  "etag":         "d41d8cd98f00b204e9800998ecf8427e",
  "uploaded_at":  "2024-01-15T10:30:00Z",
  "version_id":   "3e1a2b4c"
}
```

**Error Responses**

| Status | Condition |
|--------|-----------|
| 400    | Invalid `entity_type` |
| 500    | MinIO write error |
| 503    | MinIO unreachable |

---

## Download Document

### `GET /documents/download/{entity_type}/{entity_id}/{document_type}/{filename}`

**Response 200** — raw file bytes with headers:
```
Content-Type: application/pdf
Content-Disposition: attachment; filename="passport.pdf"
```

**Error Responses**

| Status | Body |
|--------|------|
| 404    | `{"detail": "Document '...' not found in bucket '...'."}` |
| 503    | `{"detail": "Storage service unavailable: ..."}` |

---

## Get Document Metadata

### `GET /documents/metadata/{entity_type}/{entity_id}/{document_type}/{filename}`

**Response 200**
```json
{
  "object_name":    "employees/E001/contracts/offer_letter.docx",
  "bucket":         "dms-employees",
  "size_bytes":     51200,
  "content_type":   "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "etag":           "abc123",
  "last_modified":  "2024-01-10T08:00:00Z",
  "version_id":     "1a2b3c",
  "metadata": {
    "uploaded_by":   "HR_SYSTEM",
    "entity_id":     "E001",
    "document_type": "contracts"
  }
}
```

---

## Delete Document

### `DELETE /documents/{entity_type}/{entity_id}/{document_type}/{filename}`

**Response 200**
```json
{
  "object_name": "beneficiaries/B001/claim/claim_form.pdf",
  "bucket":      "dms-beneficiaries",
  "deleted":     true,
  "message":     "Document deleted successfully."
}
```

**Error Responses**

| Status | Condition |
|--------|-----------|
| 404    | Document not found |
| 503    | MinIO unreachable |

---

## Presigned Download URL

### `GET /documents/presigned/download/{entity_type}/{entity_id}/{document_type}/{filename}`

**Purpose:** Generate a time-limited URL that allows a browser or external system to download
the file directly from MinIO without API credentials.

**Response 200**
```json
{
  "url":            "http://localhost:9000/dms-contributors/contributors/U001/passport.pdf?X-Amz-Signature=...",
  "object_name":    "contributors/U001/identity/passport.pdf",
  "bucket":         "dms-contributors",
  "expiry_seconds": 3600,
  "method":         "GET"
}
```

---

## Presigned Upload URL

### `GET /documents/presigned/upload/{entity_type}/{entity_id}/{document_type}/{filename}`

**Purpose:** Generate a time-limited PUT URL so the Salesforce portal can upload a file
directly to MinIO (bypasses the API server for large files).

**Response 200**
```json
{
  "url":            "http://localhost:9000/dms-contributors/contributors/U001/passport.pdf?X-Amz-Signature=...",
  "object_name":    "contributors/U001/identity/passport.pdf",
  "bucket":         "dms-contributors",
  "expiry_seconds": 3600,
  "method":         "PUT"
}
```

**Usage pattern (Salesforce flow):**
1. Salesforce calls `GET /presigned/upload/...` to get the PUT URL.
2. Salesforce uploads the file binary directly to that URL via HTTP PUT.
3. Salesforce calls `GET /metadata/...` to confirm the upload succeeded.
4. Salesforce stores `object_name` + `bucket` + `etag` as metadata in its own records.

---

## Error Response Schema

All error responses share this shape:
```json
{ "detail": "Human-readable error message." }
```

## Path Parameter Reference

| Parameter       | Values                                               | Example           |
|-----------------|------------------------------------------------------|-------------------|
| `entity_type`   | `contributors`, `beneficiaries`, `employees`, `temp` | `contributors`    |
| `entity_id`     | Any string ID                                        | `U001`            |
| `document_type` | Any folder name                                      | `identity`        |
| `filename`      | Filename with extension                              | `passport.pdf`    |
