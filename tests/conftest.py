import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from app.main import app
from app.services.minio_service import get_minio_service
from app.core.config import get_settings
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentMetadata,
    PresignedUrlResponse,
)
from app.schemas.nis_document import DocumentListItem

# This key is sent in all protected test requests and returned by mock_settings.api_key.
TEST_API_KEY = "test-nis-api-key-12345"


@pytest.fixture
def mock_minio_service():
    """Fully mocked MinIOService — no real MinIO connection needed."""
    svc = MagicMock()

    svc.upload_document.return_value = DocumentUploadResponse(
        object_name="contributors/U001/IDENTITY/passport.pdf",
        bucket="dms-contributors",
        entity_type="contributors",
        content_type="application/pdf",
        size_bytes=1024,
        etag="abc123",
        uploaded_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        version_id="v1",
    )

    svc.download_document.return_value = (b"%PDF-fake-content", "application/pdf")

    svc.get_document_metadata.return_value = DocumentMetadata(
        object_name="contributors/U001/IDENTITY/passport.pdf",
        bucket="dms-contributors",
        size_bytes=1024,
        content_type="application/pdf",
        etag="abc123",
        last_modified=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
    )

    svc.generate_presigned_download_url.return_value = PresignedUrlResponse(
        url="http://localhost:9000/dms-contributors/contributors/U001/IDENTITY/passport.pdf?sig=xxx",
        object_name="contributors/U001/IDENTITY/passport.pdf",
        bucket="dms-contributors",
        expiry_seconds=3600,
        method="GET",
    )

    svc.generate_presigned_upload_url.return_value = PresignedUrlResponse(
        url="http://localhost:9000/dms-contributors/contributors/U001/IDENTITY/passport.pdf?sig=xxx",
        object_name="contributors/U001/IDENTITY/passport.pdf",
        bucket="dms-contributors",
        expiry_seconds=3600,
        method="PUT",
    )

    # list_documents returns two documents for U001
    svc.list_documents.return_value = [
        DocumentListItem(
            object_name="contributors/U001/IDENTITY/passport.pdf",
            document_type="IDENTITY",
            filename="passport.pdf",
            size_bytes=1024,
            etag="abc123",
            last_modified=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            version_id="v1",
        ),
        DocumentListItem(
            object_name="contributors/U001/CONTRACT/employment_contract.pdf",
            document_type="CONTRACT",
            filename="employment_contract.pdf",
            size_bytes=51200,
            etag="def456",
            last_modified=datetime(2024, 1, 10, 8, 0, 0, tzinfo=timezone.utc),
            version_id="v1",
        ),
    ]

    svc.health_check.return_value = {
        "dms-contributors":  "ok",
        "dms-beneficiaries": "ok",
        "dms-employees":     "ok",
        "dms-temp":          "ok",
    }

    return svc


@pytest.fixture
def mock_settings():
    """Settings mock that injects TEST_API_KEY so verify_api_key accepts it in tests."""
    s = MagicMock()
    s.api_key = TEST_API_KEY
    s.app_name = "DMS Document Service"
    s.app_version = "1.0.0"
    s.app_env = "test"
    s.get_bucket.side_effect = lambda entity_type: f"dms-{entity_type}"
    s.bucket_map = {
        "contributors": "dms-contributors",
        "beneficiaries": "dms-beneficiaries",
        "employees": "dms-employees",
        "temp": "dms-temp",
    }
    s.minio_presigned_expiry = 3600
    return s


@pytest.fixture
def client(mock_minio_service, mock_settings):
    """
    Test client with:
    - MinIOService replaced by mock (no real S3 calls)
    - get_settings overridden via FastAPI dependency_overrides (endpoint injections)
    - get_settings patched in security module (direct call inside verify_api_key)

    Send X-API-Key: TEST_API_KEY in all /documents/ requests.
    Health endpoint needs no key.
    """
    app.dependency_overrides[get_minio_service] = lambda: mock_minio_service
    app.dependency_overrides[get_settings] = lambda: mock_settings

    with patch("app.core.security.get_settings", return_value=mock_settings):
        yield TestClient(app)

    app.dependency_overrides.clear()
