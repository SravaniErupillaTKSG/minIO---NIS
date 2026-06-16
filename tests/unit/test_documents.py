import io
import pytest
from fastapi import status

from tests.conftest import TEST_API_KEY

# All protected endpoints require this header.
AUTH = {"X-API-Key": TEST_API_KEY}

# Minimum form fields required by the upload endpoint.
UPLOAD_BASE = {
    "entity_type":          "contributors",
    "entity_id":            "U001",
    "document_type":        "IDENTITY",
    "uploaded_by":          "test.user@nis.gov",
    "correlation_id":       "CORR-TEST-001",
    "salesforce_record_id": "a0B5g000004XXXEAA0",
}


# ─── Health (no auth required) ────────────────────────────────────────────────

def test_health_returns_healthy(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["storage"] == "connected"
    assert "dms-contributors" in body["buckets"]


# ─── Authentication ───────────────────────────────────────────────────────────

def test_upload_missing_api_key_returns_401(client):
    """No X-API-Key header → 401 Unauthorized."""
    resp = client.post(
        "/api/v1/documents/upload",
        data=UPLOAD_BASE,
        files={"file": ("passport.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")},
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Missing API key" in resp.json()["detail"]


def test_upload_wrong_api_key_returns_403(client):
    """Wrong X-API-Key value → 403 Forbidden."""
    resp = client.post(
        "/api/v1/documents/upload",
        headers={"X-API-Key": "wrong-key"},
        data=UPLOAD_BASE,
        files={"file": ("passport.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert "Invalid API key" in resp.json()["detail"]


# ─── Upload ───────────────────────────────────────────────────────────────────

def test_upload_success(client):
    resp = client.post(
        "/api/v1/documents/upload",
        headers=AUTH,
        data=UPLOAD_BASE,
        files={"file": ("passport.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    body = resp.json()
    # Storage fields from mock
    assert body["object_name"] == "contributors/U001/IDENTITY/passport.pdf"
    assert body["bucket"] == "dms-contributors"
    assert body["etag"] == "abc123"
    assert body["version_id"] == "v1"
    # NIS business fields echoed from form
    assert body["entity_type"] == "contributors"
    assert body["entity_id"] == "U001"
    assert body["document_type"] == "IDENTITY"
    assert body["document_class"] == "ORIGINAL"   # default
    assert body["correlation_id"] == "CORR-TEST-001"
    assert body["salesforce_record_id"] == "a0B5g000004XXXEAA0"
    assert body["uploaded_by"] == "test.user@nis.gov"


def test_upload_with_optional_fields(client):
    resp = client.post(
        "/api/v1/documents/upload",
        headers=AUTH,
        data={
            **UPLOAD_BASE,
            "document_class":         "CERTIFIED_COPY",
            "salesforce_object_type": "Contact",
            "description":            "Applicant passport",
            "expiry_date":            "2029-06-30",
        },
        files={"file": ("passport.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    body = resp.json()
    assert body["document_class"] == "CERTIFIED_COPY"
    assert body["salesforce_object_type"] == "Contact"
    assert body["description"] == "Applicant passport"
    assert body["expiry_date"] == "2029-06-30"


def test_upload_invalid_entity_type_returns_400(client):
    """_resolve_bucket raises 400 for unrecognised entity_type."""
    resp = client.post(
        "/api/v1/documents/upload",
        headers=AUTH,
        data={**UPLOAD_BASE, "entity_type": "invalid_type"},
        files={"file": ("doc.pdf", io.BytesIO(b"data"), "application/pdf")},
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "invalid_type" in resp.json()["detail"]


def test_upload_invalid_document_type_returns_422(client):
    """Enum validation: FastAPI rejects unknown document_type with 422."""
    resp = client.post(
        "/api/v1/documents/upload",
        headers=AUTH,
        data={**UPLOAD_BASE, "document_type": "NOT_A_VALID_TYPE"},
        files={"file": ("doc.pdf", io.BytesIO(b"data"), "application/pdf")},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_upload_missing_required_fields_returns_422(client):
    """Missing correlation_id and salesforce_record_id → 422."""
    resp = client.post(
        "/api/v1/documents/upload",
        headers=AUTH,
        data={
            "entity_type":   "contributors",
            "entity_id":     "U001",
            "document_type": "IDENTITY",
            "uploaded_by":   "test.user@nis.gov",
            # correlation_id and salesforce_record_id deliberately omitted
        },
        files={"file": ("doc.pdf", io.BytesIO(b"data"), "application/pdf")},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


# ─── Download ─────────────────────────────────────────────────────────────────

def test_download_success(client):
    resp = client.get(
        "/api/v1/documents/download/contributors/U001/IDENTITY/passport.pdf",
        headers=AUTH,
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.content == b"%PDF-fake-content"
    assert "attachment" in resp.headers["content-disposition"]


def test_download_invalid_entity_type_returns_400(client):
    resp = client.get(
        "/api/v1/documents/download/unknown/U001/IDENTITY/passport.pdf",
        headers=AUTH,
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_download_missing_auth_returns_401(client):
    resp = client.get(
        "/api/v1/documents/download/contributors/U001/IDENTITY/passport.pdf"
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ─── Metadata ─────────────────────────────────────────────────────────────────

def test_get_metadata_success(client):
    resp = client.get(
        "/api/v1/documents/metadata/contributors/U001/IDENTITY/passport.pdf",
        headers=AUTH,
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["object_name"] == "contributors/U001/IDENTITY/passport.pdf"
    assert body["size_bytes"] == 1024


# ─── Delete ───────────────────────────────────────────────────────────────────

def test_delete_success(client):
    resp = client.delete(
        "/api/v1/documents/contributors/U001/IDENTITY/passport.pdf",
        headers=AUTH,
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["deleted"] is True


# ─── Presigned URLs ───────────────────────────────────────────────────────────

def test_presigned_download_url(client):
    resp = client.get(
        "/api/v1/documents/presigned/download/contributors/U001/IDENTITY/passport.pdf",
        headers=AUTH,
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["method"] == "GET"
    assert "sig=xxx" in body["url"]
    assert body["expiry_seconds"] == 3600


def test_presigned_upload_url(client):
    resp = client.get(
        "/api/v1/documents/presigned/upload/contributors/U001/IDENTITY/passport.pdf",
        headers=AUTH,
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["method"] == "PUT"


# ─── List documents ───────────────────────────────────────────────────────────

def test_list_documents_success(client):
    """Returns all documents for the entity."""
    resp = client.get(
        "/api/v1/documents/contributors/U001",
        headers=AUTH,
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["entity_type"] == "contributors"
    assert body["entity_id"] == "U001"
    assert body["total"] == 2
    assert body["document_type_filter"] is None
    names = [d["object_name"] for d in body["documents"]]
    assert "contributors/U001/IDENTITY/passport.pdf" in names
    assert "contributors/U001/CONTRACT/employment_contract.pdf" in names


def test_list_documents_filter_by_type(client, mock_minio_service):
    """document_type query param filters results in Python after listing."""
    resp = client.get(
        "/api/v1/documents/contributors/U001?document_type=IDENTITY",
        headers=AUTH,
    )
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["total"] == 1
    assert body["document_type_filter"] == "IDENTITY"
    assert body["documents"][0]["document_type"] == "IDENTITY"


def test_list_documents_missing_auth_returns_401(client):
    resp = client.get("/api/v1/documents/contributors/U001")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_documents_invalid_entity_type_returns_400(client):
    resp = client.get(
        "/api/v1/documents/unknown_type/U001",
        headers=AUTH,
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ─── All entity types ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("entity_type", ["contributors", "beneficiaries", "employees", "temp"])
def test_upload_all_entity_types(client, entity_type):
    resp = client.post(
        "/api/v1/documents/upload",
        headers=AUTH,
        data={
            "entity_type":          entity_type,
            "entity_id":            "X001",
            "document_type":        "OTHER",
            "uploaded_by":          "test.user@nis.gov",
            "correlation_id":       "CORR-TEST-PARAM",
            "salesforce_record_id": "SF-PARAM-001",
        },
        files={"file": ("file.pdf", io.BytesIO(b"data"), "application/pdf")},
    )
    assert resp.status_code == status.HTTP_201_CREATED
