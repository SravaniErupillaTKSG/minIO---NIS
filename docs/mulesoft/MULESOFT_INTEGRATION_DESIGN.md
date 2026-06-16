# MuleSoft Integration Design — DMS

## Architecture Overview

```
Salesforce Experience Cloud
        |
        | (REST / Named Credentials)
        v
┌─────────────────────────────┐
│   MuleSoft Process API      │  ← Business logic layer
│   dms-process-api           │    Orchestrates, transforms, enriches
└─────────────┬───────────────┘
              |
              | (HTTP / Internal)
              v
┌─────────────────────────────┐
│   MuleSoft System API       │  ← Technical adapter layer
│   dms-system-api            │    Maps to FastAPI contract
└─────────────┬───────────────┘
              |
              | (HTTP)
              v
┌─────────────────────────────┐
│   FastAPI Document Service  │
│   localhost:8000/api/v1     │
└─────────────┬───────────────┘
              |
              v
         MinIO Storage
```

---

## Process API — `dms-process-api`

The Process API owns business orchestration. It knows about entity types, user context, and
validation rules. It never calls MinIO directly.

### Flows

#### 1. `upload-document-flow`

**Trigger:** `POST /process/v1/documents/upload`

**Steps:**
1. Receive multipart request from Salesforce (file + metadata)
2. Validate: entity_type, entity_id, file size limit (25 MB), allowed MIME types
3. Enrich: add `uploaded_by` (from Salesforce session), timestamp
4. Call System API `POST /system/v1/documents/upload` (forward multipart)
5. Receive `DocumentUploadResponse` from System API
6. Store `object_name`, `bucket`, `etag`, `version_id` as metadata in Salesforce via Salesforce Connector
7. Return success response to Salesforce

**Error handling:**
- File too large → 413 with `{"code": "FILE_TOO_LARGE", "maxBytes": 26214400}`
- Invalid MIME → 415 with allowed types list
- System API 503 → retry once (delay 2s), then circuit-break

---

#### 2. `download-document-flow`

**Trigger:** `GET /process/v1/documents/{recordId}/download`

**Steps:**
1. Receive `recordId` (Salesforce record ID)
2. Query Salesforce for `object_name` and `bucket` linked to that record
3. Call System API `GET /system/v1/documents/download/{entity_type}/...`
4. Stream response bytes back to Salesforce caller

**Alternative (presigned URL flow — recommended for large files):**
1. Call System API `GET /system/v1/documents/presigned/download/...`
2. Return URL to Salesforce
3. Salesforce redirects user browser to presigned URL directly

---

#### 3. `delete-document-flow`

**Trigger:** `DELETE /process/v1/documents/{recordId}`

**Steps:**
1. Receive `recordId`
2. Salesforce lookup → get `object_name`, `bucket`
3. Authorization check: confirm caller has permission on this record
4. Call System API `DELETE /system/v1/documents/...`
5. On success → mark Salesforce record as `Deleted`, store `deleted_at`, `deleted_by`
6. Return 200

**Note:** MinIO versioning means the bytes are not physically removed (delete marker added).
A hard delete requires explicit version removal (out of scope for v1).

---

#### 4. `generate-presigned-url-flow`

**Trigger:** `GET /process/v1/documents/{recordId}/presigned-url?type=download|upload`

**Steps:**
1. Resolve `object_name` from Salesforce record (for download) or construct it (for upload)
2. Call System API presigned endpoint
3. Return `{url, expiry_seconds}` to Salesforce

---

### Process API RAML (fragment)

```yaml
#%RAML 1.0
title: DMS Process API
version: v1
baseUri: http://dms-process-api.internal/{version}
mediaType: application/json

/documents:
  /upload:
    post:
      description: Upload a document on behalf of a Salesforce entity.
      body:
        multipart/form-data:
          properties:
            file:
              type: file
              required: true
            entity_type:
              type: string
              enum: [contributors, beneficiaries, employees, temp]
            entity_id:
              type: string
            document_type:
              type: string
            salesforce_record_id:
              type: string
      responses:
        201:
          body:
            application/json:
              example: |
                {
                  "object_name": "contributors/U001/identity/passport.pdf",
                  "salesforce_record_id": "a0B5g000004XXXEAA0",
                  "etag": "d41d8cd98f00b204e9800998ecf8427e",
                  "uploaded_at": "2024-01-15T10:30:00Z"
                }
  /{recordId}:
    get:
      description: Get presigned download URL for a Salesforce document record.
      queryParameters:
        type:
          type: string
          enum: [download, upload]
          default: download
      responses:
        200:
          body:
            application/json:
              example: |
                {
                  "url": "http://...",
                  "expiry_seconds": 3600
                }
    delete:
      description: Delete a document and update the Salesforce record.
      responses:
        200:
          body:
            application/json:
              example: |
                { "deleted": true, "message": "Document deleted." }
```

---

## System API — `dms-system-api`

The System API is a thin proxy/adapter. It translates between the MuleSoft HTTP request and
the FastAPI contract. No business logic lives here.

### Flows

#### `upload-proxy-flow`
- Input: `POST /system/v1/documents/upload` (multipart)
- Action: Forward as-is to `POST http://dms-fastapi:8000/api/v1/documents/upload`
- Output: Pass through `DocumentUploadResponse`

#### `download-proxy-flow`
- Input: `GET /system/v1/documents/download/{entity_type}/{entity_id}/{document_type}/{filename}`
- Action: HTTP GET to FastAPI
- Output: Stream bytes

#### `delete-proxy-flow`
- Input: `DELETE /system/v1/documents/{entity_type}/{entity_id}/{document_type}/{filename}`
- Action: HTTP DELETE to FastAPI
- Output: Pass through `DocumentDeleteResponse`

#### `presigned-download-proxy-flow`
- Input: `GET /system/v1/documents/presigned/download/...`
- Action: HTTP GET to FastAPI
- Output: `PresignedUrlResponse`

#### `presigned-upload-proxy-flow`
- Input: `GET /system/v1/documents/presigned/upload/...`
- Action: HTTP GET to FastAPI
- Output: `PresignedUrlResponse`

#### `health-proxy-flow`
- Input: `GET /system/v1/health`
- Action: HTTP GET `http://dms-fastapi:8000/api/v1/health`
- Output: `HealthResponse`

---

### System API Error Mapping

| FastAPI Status | MuleSoft Action | Salesforce Sees |
|----------------|-----------------|-----------------|
| 404 | Pass through | `{"code": "DOCUMENT_NOT_FOUND"}` |
| 400 | Pass through | `{"code": "INVALID_REQUEST", "detail": "..."}` |
| 500 | Log + alert | `{"code": "STORAGE_ERROR"}` |
| 503 | Retry (2x) → Circuit Breaker | `{"code": "SERVICE_UNAVAILABLE"}` |

---

### System API RAML (fragment)

```yaml
#%RAML 1.0
title: DMS System API
version: v1
baseUri: http://dms-system-api.internal/{version}
mediaType: application/json

/documents:
  /upload:
    post:
      description: Proxy upload to FastAPI Document Service.
  /download/{entity_type}/{entity_id}/{document_type}/{filename}:
    get:
      description: Proxy download from FastAPI.
  /metadata/{entity_type}/{entity_id}/{document_type}/{filename}:
    get:
      description: Get object metadata.
  /presigned/download/{entity_type}/{entity_id}/{document_type}/{filename}:
    get:
      description: Get presigned GET URL.
  /presigned/upload/{entity_type}/{entity_id}/{document_type}/{filename}:
    get:
      description: Get presigned PUT URL.
  /{entity_type}/{entity_id}/{document_type}/{filename}:
    delete:
      description: Delete object from MinIO via FastAPI.
/health:
  get:
    description: Pass-through health check.
```
