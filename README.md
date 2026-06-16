# DMS — Document Management System

Local PoC for a production-style document storage pipeline:

```
Salesforce Portal → MuleSoft Process API → MuleSoft System API → FastAPI → MinIO
```

---

## Quick Start (5 minutes)

### Prerequisites
- Docker Desktop running
- Python 3.11+

### Step 1 — Bootstrap

```powershell
# Run from the DMS folder
.\scripts\setup_dev.ps1
```

This copies `.env`, installs Python deps, and starts MinIO + bucket init.

### Step 2 — Start the API

```powershell
.venv\Scripts\activate
uvicorn app.main:app --reload
```

### Step 3 — Verify

| URL | Purpose |
|-----|---------|
| http://localhost:8000/docs | Swagger UI (try all endpoints) |
| http://localhost:8000/api/v1/health | JSON health check |
| http://localhost:9001 | MinIO Console (minioadmin / minioadmin123) |

---

## Folder Structure

```
DMS/
├── app/
│   ├── main.py                        # FastAPI app factory
│   ├── api/v1/
│   │   ├── router.py                  # Mounts all routers
│   │   └── endpoints/
│   │       ├── documents.py           # Upload, download, delete, presigned, metadata
│   │       └── health.py              # Health check
│   ├── core/
│   │   ├── config.py                  # Pydantic Settings (reads .env)
│   │   ├── logging.py                 # Loguru setup
│   │   └── exceptions.py             # Typed HTTP exceptions
│   ├── schemas/
│   │   └── document.py               # Request / response Pydantic models
│   └── services/
│       └── minio_service.py          # All MinIO SDK calls
│
├── infra/
│   ├── docker/Dockerfile             # FastAPI container
│   └── minio/init-buckets.sh        # Creates buckets + versioning + lifecycle
│
├── tests/
│   ├── conftest.py                   # Shared fixtures (mocked service)
│   ├── unit/test_documents.py        # Unit tests (no MinIO needed)
│   └── integration/test_minio_integration.py  # Requires live Docker MinIO
│
├── docs/
│   ├── API_CONTRACTS.md             # Full request/response reference
│   ├── mulesoft/MULESOFT_INTEGRATION_DESIGN.md
│   └── sequences/SEQUENCE_DIAGRAMS.md
│
├── postman/DMS_Collection.json      # Import into Postman to test all endpoints
├── tests/fixtures/sample_data.md   # Entity IDs and filenames for testing
├── docker-compose.yml
├── requirements.txt
├── .env                             # Local secrets (not committed)
└── .env.example                     # Committed template
```

---

## Bucket Strategy

| Bucket | Owner | Auto-expiry |
|--------|-------|------------|
| `dms-contributors`  | Contributors  | None (versioned) |
| `dms-beneficiaries` | Beneficiaries | None (versioned) |
| `dms-employees`     | Employees     | None (versioned) |
| `dms-temp`          | Temp uploads  | 7 days |

All buckets have **versioning enabled** — deleting a file adds a delete marker; bytes are never permanently lost.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`    | `/api/v1/health` | Service + bucket health |
| `POST`   | `/api/v1/documents/upload` | Upload a file |
| `GET`    | `/api/v1/documents/download/{entity_type}/{entity_id}/{document_type}/{filename}` | Download binary |
| `GET`    | `/api/v1/documents/metadata/{entity_type}/{entity_id}/{document_type}/{filename}` | Get metadata only |
| `DELETE` | `/api/v1/documents/{entity_type}/{entity_id}/{document_type}/{filename}` | Delete |
| `GET`    | `/api/v1/documents/presigned/download/{...}` | Presigned GET URL |
| `GET`    | `/api/v1/documents/presigned/upload/{...}` | Presigned PUT URL |

Full contract: [docs/API_CONTRACTS.md](docs/API_CONTRACTS.md)

---

## Running Tests

```powershell
# Unit tests only (no Docker needed)
pytest tests/unit/ -v

# Integration tests (requires: docker compose up -d minio minio-init)
pytest tests/integration/ -v -m integration

# All tests
pytest -v
```

---

## Running Everything in Docker

```powershell
docker compose up --build
```

All three services start: MinIO, bucket init, and FastAPI.

---

## MuleSoft Integration

See [docs/mulesoft/MULESOFT_INTEGRATION_DESIGN.md](docs/mulesoft/MULESOFT_INTEGRATION_DESIGN.md) for:
- Process API RAML and flow designs
- System API proxy flows
- Error mapping table

See [docs/sequences/SEQUENCE_DIAGRAMS.md](docs/sequences/SEQUENCE_DIAGRAMS.md) for ASCII sequence diagrams of all flows.
