# DMS Sequence Diagrams

## 1. Document Upload Flow

```
Salesforce       Process API       System API       FastAPI          MinIO
    |                 |                |               |               |
    |─POST /upload───>|                |               |               |
    |  (multipart)    |                |               |               |
    |                 |─validate───────|               |               |
    |                 |─enrich metadata|               |               |
    |                 |                |               |               |
    |                 |─POST /upload──>|               |               |
    |                 |                |─POST /upload─>|               |
    |                 |                |               |─PUT object───>|
    |                 |                |               |<──ETag/ver────|
    |                 |                |<─201 response─|               |
    |                 |<─201 response──|               |               |
    |                 |                |               |               |
    |                 |─update SF record (object_name, etag)           |
    |<─201 success────|                |               |               |
```

## 2. Document Download via Presigned URL (Recommended)

```
Salesforce       Process API       System API       FastAPI          MinIO
    |                 |                |               |               |
    |─GET /presigned─>|                |               |               |
    |  /{recordId}    |                |               |               |
    |                 |─lookup SF record (object_name)|               |
    |                 |                |               |               |
    |                 |─GET /presigned>|               |               |
    |                 |                |─GET /presigned>|              |
    |                 |                |               |─sign URL─────>|
    |                 |                |               |<─presigned URL|
    |                 |                |<─{url, expiry}|               |
    |                 |<─{url, expiry}─|               |               |
    |<─{url, expiry}──|                |               |               |
    |                 |                |               |               |
    |─GET {presignedURL}────────────────────────────────────────────>|
    |<─file bytes───────────────────────────────────────────────────|
```

## 3. Document Delete Flow

```
Salesforce       Process API       System API       FastAPI          MinIO
    |                 |                |               |               |
    |─DELETE /records─>|               |               |               |
    |  /{recordId}    |                |               |               |
    |                 |─lookup SF record               |               |
    |                 |─authz check────|               |               |
    |                 |                |               |               |
    |                 |─DELETE /docs──>|               |               |
    |                 |                |─DELETE /docs─>|               |
    |                 |                |               |─stat (exists?)|
    |                 |                |               |─remove_object>|
    |                 |                |               |<─ack──────────|
    |                 |                |<─200 deleted──|               |
    |                 |<─200 deleted───|               |               |
    |                 |─mark SF record Deleted         |               |
    |<─200 success────|                |               |               |
```

## 4. Health Check Flow

```
Monitoring       Process API       System API       FastAPI          MinIO
    |                 |                |               |               |
    |─GET /health────>|                |               |               |
    |                 |─GET /health───>|               |               |
    |                 |                |─GET /health──>|               |
    |                 |                |               |─bucket_exists>|
    |                 |                |               |<─ok───────────|
    |                 |                |<─{healthy}────|               |
    |                 |<─{healthy}─────|               |               |
    |<─{healthy}──────|                |               |               |
```

## 5. Direct Upload Flow (Salesforce → MinIO via Presigned PUT)

```
Salesforce       Process API       System API       FastAPI          MinIO
    |                 |                |               |               |
    |─GET /presigned──>|               |               |               |
    |  upload/{id}    |                |               |               |
    |                 |─GET /presigned/upload/...─────>|               |
    |                 |                |               |─presigned PUT>|
    |                 |                |               |<─signed URL───|
    |<─{url}──────────|                |               |               |
    |                 |                |               |               |
    |─PUT {url} ─────────────────────────────────────────────────────>|
    |  (file bytes directly to MinIO — no API server in the path)     |
    |<─200 OK─────────────────────────────────────────────────────────|
    |                 |                |               |               |
    |─POST /confirm──>|                |               |               |
    |  (notify upload done)           |               |               |
    |                 |─GET /metadata/...─────────────>|               |
    |                 |<─{etag, size}──────────────────|               |
    |                 |─update SF record               |               |
    |<─200 confirmed──|                |               |               |
```
