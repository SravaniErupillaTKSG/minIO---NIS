"""
Unit tests for NIS person registration and document lookup endpoints.

Tests use FastAPI's TestClient with dependency overrides so no real database
or MinIO is needed. All external services are replaced with MagicMock objects.

Test coverage:
  - POST /api/v1/nis/register   — success, duplicate, validation errors
  - GET  /api/v1/nis/{nis_id}   — success, not found
  - GET  /api/v1/nis/{nis_id}/documents — success (with docs), empty list, not found
  - GET  /api/v1/documents/{doc_id}     — success, not found, invalid pattern
  - DELETE /api/v1/documents/{doc_id}   — success, not found
  - POST /api/v1/documents/upload       — success with nis_id, unregistered nis_id
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import verify_api_key
from app.core.database import get_db
from app.services.minio_service import get_minio_service

TEST_API_KEY = "test-api-key-12345"
NOW = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """In-memory mock DB session — no SQLite needed."""
    return MagicMock()


@pytest.fixture
def mock_minio():
    """Mock MinIOService with safe defaults."""
    m = MagicMock()
    m.generate_presigned_download_url.return_value = MagicMock(
        url="https://minio.example.com/signed-url"
    )
    m.delete_document.return_value = None
    return m


@pytest.fixture
def client(mock_db, mock_minio) -> Generator:
    """
    TestClient with dependency overrides:
      - API key always accepted
      - DB session is a MagicMock
      - MinIOService is a MagicMock
    """
    app.dependency_overrides[verify_api_key]   = lambda: TEST_API_KEY
    app.dependency_overrides[get_db]           = lambda: mock_db
    app.dependency_overrides[get_minio_service] = lambda: mock_minio
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Helper builders ────────────────────────────────────────────────────────────

def _nis_record(nis_id="NIS001", person_name="John Doe", entity_type="CONTRIBUTOR"):
    """Build a mock NISMaster ORM object."""
    r = MagicMock()
    r.nis_id      = nis_id
    r.person_name = person_name
    r.entity_type = entity_type
    r.created_at  = NOW
    return r


def _doc_record(
    doc_id="DOC-A3F4B2C1",
    nis_id="NIS001",
    file_name="passport.pdf",
    document_type="IDENTITY",
):
    """Build a mock DocumentMetadata ORM object."""
    r = MagicMock()
    r.doc_id                = doc_id
    r.nis_id                = nis_id
    r.file_name             = file_name
    r.document_type         = document_type
    r.document_class        = "ORIGINAL"
    r.bucket_name           = "dms-contributors"
    r.object_path           = f"contributors/{nis_id}/{document_type}/{file_name}"
    r.content_type          = "application/pdf"
    r.file_size_bytes       = 204800
    r.uploaded_by           = "john.smith@nis.gov"
    r.correlation_id        = "CORR-001"
    r.salesforce_record_id  = "SF-001"
    r.salesforce_object_type = "Contact"
    r.description           = None
    r.expiry_date           = None
    r.etag                  = "abc123"
    r.version_id            = "v1"
    r.uploaded_at           = NOW
    r.is_deleted            = False
    r.deleted_at            = None
    return r


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/nis/register
# ══════════════════════════════════════════════════════════════════════════════

class TestNISRegister:
    def test_register_success(self, client):
        """Happy path — new NIS person registered, returns 201."""
        with (
            patch("app.api.v1.endpoints.nis.NISRepository") as MockRepo,
        ):
            mock_repo = MockRepo.return_value
            mock_repo.create.return_value = _nis_record()

            resp = client.post(
                "/api/v1/nis/register",
                json={
                    "nis_id":      "NIS001",
                    "person_name": "John Doe",
                    "entity_type": "CONTRIBUTOR",
                },
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["nis_id"]      == "NIS001"
        assert body["person_name"] == "John Doe"
        assert body["entity_type"] == "CONTRIBUTOR"
        assert "created_at" in body

    def test_register_duplicate_returns_409(self, client):
        """Registering an existing nis_id returns 409 Conflict."""
        with patch("app.api.v1.endpoints.nis.NISRepository") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.create.side_effect = ValueError("NIS ID 'NIS001' is already registered.")

            resp = client.post(
                "/api/v1/nis/register",
                json={
                    "nis_id":      "NIS001",
                    "person_name": "Jane Doe",
                    "entity_type": "BENEFICIARY",
                },
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 409
        assert "already registered" in resp.json()["detail"]

    def test_register_missing_api_key_returns_401(self, client):
        """No X-API-Key header → 401."""
        app.dependency_overrides.pop(verify_api_key, None)
        resp = client.post(
            "/api/v1/nis/register",
            json={"nis_id": "NIS001", "person_name": "X", "entity_type": "CONTRIBUTOR"},
        )
        assert resp.status_code in (401, 403)
        app.dependency_overrides[verify_api_key] = lambda: TEST_API_KEY

    def test_register_invalid_entity_type_returns_422(self, client):
        """Invalid entity_type value → 422 from Pydantic."""
        resp = client.post(
            "/api/v1/nis/register",
            json={
                "nis_id":      "NIS002",
                "person_name": "Jane Doe",
                "entity_type": "UNKNOWN_TYPE",
            },
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 422

    def test_register_short_nis_id_returns_422(self, client):
        """nis_id shorter than 3 chars → 422 from Pydantic min_length."""
        resp = client.post(
            "/api/v1/nis/register",
            json={"nis_id": "NI", "person_name": "X", "entity_type": "CONTRIBUTOR"},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/nis/{nis_id}
# ══════════════════════════════════════════════════════════════════════════════

class TestGetNISPerson:
    def test_get_person_success(self, client):
        """Existing nis_id returns 200 with person details."""
        with (
            patch("app.api.v1.endpoints.nis.NISRepository") as MockNIS,
            patch("app.api.v1.endpoints.nis.DocumentMetadataRepository") as MockDoc,
        ):
            MockNIS.return_value.get_by_id.return_value  = _nis_record()
            MockDoc.return_value.count_by_nis_id.return_value = 3

            resp = client.get(
                "/api/v1/nis/NIS001",
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["nis_id"]         == "NIS001"
        assert body["person_name"]    == "John Doe"
        assert body["document_count"] == 3

    def test_get_person_not_found_returns_404(self, client):
        """Unknown nis_id returns 404."""
        with (
            patch("app.api.v1.endpoints.nis.NISRepository") as MockNIS,
            patch("app.api.v1.endpoints.nis.DocumentMetadataRepository") as MockDoc,
        ):
            MockNIS.return_value.get_by_id.return_value  = None
            MockDoc.return_value.count_by_nis_id.return_value = 0

            resp = client.get(
                "/api/v1/nis/UNKNOWN",
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/nis/{nis_id}/documents
# ══════════════════════════════════════════════════════════════════════════════

class TestGetNISDocuments:
    def test_get_documents_success(self, client, mock_minio):
        """Returns NIS person + document list with presigned URLs."""
        doc = _doc_record()
        with (
            patch("app.api.v1.endpoints.nis.NISRepository") as MockNIS,
            patch("app.api.v1.endpoints.nis.DocumentMetadataRepository") as MockDoc,
        ):
            MockNIS.return_value.get_by_id.return_value   = _nis_record()
            MockDoc.return_value.get_by_nis_id.return_value = [doc]

            resp = client.get(
                "/api/v1/nis/NIS001/documents",
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["nis_id"]          == "NIS001"
        assert body["total_documents"] == 1
        assert len(body["documents"])  == 1

        first = body["documents"][0]
        assert first["doc_id"]        == "DOC-A3F4B2C1"
        assert first["file_name"]     == "passport.pdf"
        assert first["document_type"] == "IDENTITY"
        assert first["download_url"]  == "https://minio.example.com/signed-url"

    def test_get_documents_empty_list(self, client):
        """NIS person exists but has no documents → returns 200 with empty list."""
        with (
            patch("app.api.v1.endpoints.nis.NISRepository") as MockNIS,
            patch("app.api.v1.endpoints.nis.DocumentMetadataRepository") as MockDoc,
        ):
            MockNIS.return_value.get_by_id.return_value   = _nis_record()
            MockDoc.return_value.get_by_nis_id.return_value = []

            resp = client.get(
                "/api/v1/nis/NIS001/documents",
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_documents"] == 0
        assert body["documents"]       == []

    def test_get_documents_nis_not_found(self, client):
        """Unknown nis_id returns 404."""
        with (
            patch("app.api.v1.endpoints.nis.NISRepository") as MockNIS,
            patch("app.api.v1.endpoints.nis.DocumentMetadataRepository") as MockDoc,
        ):
            MockNIS.return_value.get_by_id.return_value   = None
            MockDoc.return_value.get_by_nis_id.return_value = []

            resp = client.get(
                "/api/v1/nis/GHOST/documents",
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/documents/{doc_id}
# ══════════════════════════════════════════════════════════════════════════════

class TestGetDocumentById:
    def test_get_document_success(self, client, mock_minio):
        """Existing doc_id returns 200 with metadata and download URL."""
        with (
            patch("app.api.v1.endpoints.nis.NISRepository"),
            patch("app.api.v1.endpoints.nis.DocumentMetadataRepository") as MockDoc,
        ):
            MockDoc.return_value.get_by_doc_id.return_value = _doc_record()

            resp = client.get(
                "/api/v1/documents/DOC-A3F4B2C1",
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["doc_id"]       == "DOC-A3F4B2C1"
        assert body["nis_id"]       == "NIS001"
        assert body["file_name"]    == "passport.pdf"
        assert body["download_url"] == "https://minio.example.com/signed-url"

    def test_get_document_not_found_returns_404(self, client):
        """Non-existent doc_id returns 404."""
        with (
            patch("app.api.v1.endpoints.nis.NISRepository"),
            patch("app.api.v1.endpoints.nis.DocumentMetadataRepository") as MockDoc,
        ):
            MockDoc.return_value.get_by_doc_id.return_value = None

            resp = client.get(
                "/api/v1/documents/DOC-FFFFFFFF",
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 404

    def test_get_document_invalid_id_pattern_returns_422(self, client):
        """doc_id that doesn't match DOC-XXXXXXXX pattern → 422."""
        resp = client.get(
            "/api/v1/documents/contributors",   # not a DOC-XXXXXXXX pattern
            headers={"X-API-Key": TEST_API_KEY},
        )
        # 422 from path regex validation OR 404 if routed to a different endpoint
        assert resp.status_code in (404, 422)


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /api/v1/documents/{doc_id}
# ══════════════════════════════════════════════════════════════════════════════

class TestDeleteDocumentById:
    def test_delete_success(self, client, mock_minio):
        """Soft-deletes a document — returns 200 with deleted=true."""
        doc = _doc_record()
        deleted_doc = _doc_record()
        deleted_doc.is_deleted = True
        deleted_doc.deleted_at = NOW

        with (
            patch("app.api.v1.endpoints.nis.NISRepository"),
            patch("app.api.v1.endpoints.nis.DocumentMetadataRepository") as MockDoc,
        ):
            MockDoc.return_value.get_by_doc_id.return_value  = doc
            MockDoc.return_value.soft_delete.return_value    = deleted_doc

            resp = client.delete(
                "/api/v1/documents/DOC-A3F4B2C1",
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["doc_id"]  == "DOC-A3F4B2C1"
        assert body["deleted"] is True
        assert "deleted_at" in body

    def test_delete_not_found_returns_404(self, client):
        """Deleting a non-existent doc_id returns 404."""
        with (
            patch("app.api.v1.endpoints.nis.NISRepository"),
            patch("app.api.v1.endpoints.nis.DocumentMetadataRepository") as MockDoc,
        ):
            MockDoc.return_value.get_by_doc_id.return_value = None

            resp = client.delete(
                "/api/v1/documents/DOC-FFFFFFFF",
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/documents/upload  (enhanced with nis_id + doc_id)
# ══════════════════════════════════════════════════════════════════════════════

class TestUploadWithNISId:
    def _upload(self, client, nis_id="NIS001", registered=True):
        """Helper: POST a small PDF upload with the given nis_id."""
        pdf_bytes = b"%PDF-1.4 test content"

        with (
            patch("app.api.v1.endpoints.documents.NISRepository") as MockNIS,
            patch("app.api.v1.endpoints.documents.DocumentMetadataRepository") as MockDoc,
            patch("app.api.v1.endpoints.documents.generate_doc_id", return_value="DOC-A3F4B2C1"),
        ):
            MockNIS.return_value.exists.return_value = registered
            MockDoc.return_value.find_active_duplicate.return_value = None  # no duplicate by default

            mock_storage = MagicMock()
            mock_storage.object_name = f"contributors/{nis_id}/IDENTITY/test.pdf"
            mock_storage.bucket      = "dms-contributors"
            mock_storage.etag        = "abc123"
            mock_storage.version_id  = "v1"
            mock_storage.size_bytes  = len(pdf_bytes)
            mock_storage.uploaded_at = NOW

            from app.services.minio_service import get_minio_service as _get_minio
            app.dependency_overrides[_get_minio] = lambda: MagicMock(
                upload_document=lambda **kw: mock_storage
            )

            resp = client.post(
                "/api/v1/documents/upload",
                data={
                    "nis_id":               nis_id,
                    "entity_type":          "contributors",
                    "document_type":        "IDENTITY",
                    "correlation_id":       "CORR-001",
                    "salesforce_record_id": "SF-001",
                    "uploaded_by":          "test.user@nis.gov",
                },
                files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
                headers={"X-API-Key": TEST_API_KEY},
            )

        return resp

    def test_upload_with_registered_nis_id_returns_201(self, client):
        """Upload with a valid registered nis_id → 201 with doc_id in response."""
        resp = self._upload(client, nis_id="NIS001", registered=True)
        assert resp.status_code == 201
        body = resp.json()
        assert body["doc_id"] == "DOC-A3F4B2C1"
        assert body["nis_id"] == "NIS001"
        assert "object_name" in body
        assert "etag" in body

    def test_upload_unregistered_nis_id_returns_422(self, client):
        """Upload with an unregistered nis_id → 422 Unprocessable Entity."""
        resp = self._upload(client, nis_id="NIS999", registered=False)
        assert resp.status_code == 422
        assert "not registered" in resp.json()["detail"].lower()

    def test_upload_duplicate_without_replace_returns_409(self, client):
        """Same filename + nis_id + document_type without replace=true → 409 Conflict."""
        pdf_bytes = b"%PDF-1.4 test content"
        existing_doc = _doc_record(doc_id="DOC-00000000")

        with (
            patch("app.api.v1.endpoints.documents.NISRepository") as MockNIS,
            patch("app.api.v1.endpoints.documents.DocumentMetadataRepository") as MockDoc,
            patch("app.api.v1.endpoints.documents.generate_doc_id", return_value="DOC-A3F4B2C1"),
        ):
            MockNIS.return_value.exists.return_value = True
            MockDoc.return_value.find_active_duplicate.return_value = existing_doc

            resp = client.post(
                "/api/v1/documents/upload",
                data={
                    "nis_id":               "NIS001",
                    "entity_type":          "contributors",
                    "document_type":        "IDENTITY",
                    "correlation_id":       "CORR-001",
                    "salesforce_record_id": "SF-001",
                    "uploaded_by":          "test.user@nis.gov",
                },
                files={"file": ("passport.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["existing_doc_id"] == "DOC-00000000"
        assert "passport.pdf" in detail["message"]
        assert "replace=true" in detail["hint"]

    def test_upload_duplicate_with_replace_returns_201(self, client):
        """Same filename + replace=true → 201, old doc soft-deleted, replaced=true in response."""
        pdf_bytes = b"%PDF-1.4 test content"
        existing_doc = _doc_record(doc_id="DOC-00000000")

        with (
            patch("app.api.v1.endpoints.documents.NISRepository") as MockNIS,
            patch("app.api.v1.endpoints.documents.DocumentMetadataRepository") as MockDoc,
            patch("app.api.v1.endpoints.documents.generate_doc_id", return_value="DOC-A3F4B2C1"),
        ):
            MockNIS.return_value.exists.return_value = True
            MockDoc.return_value.find_active_duplicate.return_value = existing_doc
            MockDoc.return_value.soft_delete.return_value = existing_doc

            mock_storage = MagicMock()
            mock_storage.object_name = "contributors/NIS001/IDENTITY/passport.pdf"
            mock_storage.bucket      = "dms-contributors"
            mock_storage.etag        = "newetag456"
            mock_storage.version_id  = "v2"
            mock_storage.size_bytes  = len(pdf_bytes)
            mock_storage.uploaded_at = NOW

            from app.services.minio_service import get_minio_service as _get_minio
            app.dependency_overrides[_get_minio] = lambda: MagicMock(
                upload_document=lambda **kw: mock_storage,
                delete_document=lambda **kw: None,
            )

            resp = client.post(
                "/api/v1/documents/upload",
                data={
                    "nis_id":               "NIS001",
                    "entity_type":          "contributors",
                    "document_type":        "IDENTITY",
                    "correlation_id":       "CORR-001",
                    "salesforce_record_id": "SF-001",
                    "uploaded_by":          "test.user@nis.gov",
                    "replace":              "true",
                },
                files={"file": ("passport.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
                headers={"X-API-Key": TEST_API_KEY},
            )

            MockDoc.return_value.soft_delete.assert_called_once_with("DOC-00000000")

        assert resp.status_code == 201
        body = resp.json()
        assert body["doc_id"]          == "DOC-A3F4B2C1"
        assert body["replaced"]        is True
        assert body["replaced_doc_id"] == "DOC-00000000"
