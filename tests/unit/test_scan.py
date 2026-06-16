"""
Unit tests for Scenario 1 — Scan / OCR endpoints.

All MinIO, database, and OCR calls are mocked.
Tests verify:
  - HTTP status codes and response shapes
  - Authentication (401 / 403)
  - Validation (400 empty file, 415 wrong type)
  - 404 for missing document
  - OCR preview in metadata endpoint
"""
import io
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1.endpoints.scan import get_processor
from app.core.config import get_settings
from app.schemas.scan_document import OCRStatus, ScanDocumentRecord
from tests.conftest import TEST_API_KEY

AUTH = {"X-API-Key": TEST_API_KEY}

# ── Fixtures ──────────────────────────────────────────────────────────────────

_COMPLETED_RECORD = ScanDocumentRecord(
    document_id="test-doc-uuid-001",
    file_name="claim_form.pdf",
    upload_time=datetime(2024, 6, 15, 9, 30, 0, tzinfo=timezone.utc),
    ocr_status=OCRStatus.COMPLETED,
    document_location="scanned-documents/2024/06/test-doc-uuid-001.pdf",
    ocr_text_location="ocr-output/2024/06/test-doc-uuid-001.txt",
    content_type="application/pdf",
    file_size_bytes=204800,
    error_message=None,
    scan_source="IBML_SIMULATED",
)

_FAILED_RECORD = ScanDocumentRecord(
    document_id="test-doc-uuid-002",
    file_name="damaged_scan.pdf",
    upload_time=datetime(2024, 6, 15, 9, 31, 0, tzinfo=timezone.utc),
    ocr_status=OCRStatus.FAILED,
    document_location="scanned-documents/2024/06/test-doc-uuid-002.pdf",
    ocr_text_location=None,
    content_type="application/pdf",
    file_size_bytes=512,
    error_message="Tesseract executable not found.",
    scan_source="IBML_SIMULATED",
)


@pytest.fixture
def mock_processor():
    proc = MagicMock()
    proc.process_document.return_value  = _COMPLETED_RECORD
    proc.get_document.return_value      = _COMPLETED_RECORD
    proc.get_ocr_text.return_value      = "NATIONAL INSURANCE SCHEME\nCLAIM FORM\nContributor: U001"
    return proc


@pytest.fixture
def scan_client(mock_processor, mock_settings):
    """
    TestClient with:
    - DocumentProcessor replaced by mock (no OCR / MinIO / DB calls)
    - get_settings overridden with mock_settings (known API key)
    """
    app.dependency_overrides[get_processor]  = lambda: mock_processor
    app.dependency_overrides[get_settings]   = lambda: mock_settings

    with patch("app.core.security.get_settings", return_value=mock_settings):
        yield TestClient(app)

    app.dependency_overrides.clear()


# ── POST /scan/process ────────────────────────────────────────────────────────

def test_process_document_pdf_success(scan_client):
    resp = scan_client.post(
        "/api/v1/scan/process",
        headers=AUTH,
        files={"file": ("claim_form.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["document_id"] == "test-doc-uuid-001"
    assert body["ocr_status"] == "COMPLETED"
    assert body["document_location"].startswith("scanned-documents/")
    assert body["ocr_text_location"].startswith("ocr-output/")
    assert body["scan_source"] == "IBML_SIMULATED"


def test_process_document_png_success(scan_client):
    resp = scan_client.post(
        "/api/v1/scan/process",
        headers=AUTH,
        files={"file": ("id_card.png", io.BytesIO(b"\x89PNG\r\n"), "image/png")},
    )
    assert resp.status_code == 202
    assert resp.json()["ocr_status"] == "COMPLETED"


def test_process_document_jpeg_success(scan_client):
    resp = scan_client.post(
        "/api/v1/scan/process",
        headers=AUTH,
        files={"file": ("passport.jpg", io.BytesIO(b"\xff\xd8\xff"), "image/jpeg")},
    )
    assert resp.status_code == 202


def test_process_document_tiff_success(scan_client):
    resp = scan_client.post(
        "/api/v1/scan/process",
        headers=AUTH,
        files={"file": ("contract.tiff", io.BytesIO(b"II*\x00"), "image/tiff")},
    )
    assert resp.status_code == 202


def test_process_document_with_custom_scan_source(scan_client):
    resp = scan_client.post(
        "/api/v1/scan/process",
        headers=AUTH,
        data={"scan_source": "IBML_SCANNER"},
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF-1"), "application/pdf")},
    )
    assert resp.status_code == 202


def test_process_document_failed_ocr_still_returns_202(scan_client, mock_processor):
    """A FAILED OCR status is a valid outcome — not an HTTP error."""
    mock_processor.process_document.return_value = _FAILED_RECORD
    resp = scan_client.post(
        "/api/v1/scan/process",
        headers=AUTH,
        files={"file": ("bad.pdf", io.BytesIO(b"%PDF-broken"), "application/pdf")},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["ocr_status"] == "FAILED"
    assert body["error_message"] == "Tesseract executable not found."


# ── Authentication ─────────────────────────────────────────────────────────────

def test_process_missing_api_key_returns_401(scan_client):
    resp = scan_client.post(
        "/api/v1/scan/process",
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )
    assert resp.status_code == 401


def test_process_wrong_api_key_returns_403(scan_client):
    resp = scan_client.post(
        "/api/v1/scan/process",
        headers={"X-API-Key": "wrong-key"},
        files={"file": ("doc.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )
    assert resp.status_code == 403


# ── File validation ────────────────────────────────────────────────────────────

def test_process_empty_file_returns_400(scan_client):
    """Empty file (0 bytes) is rejected before OCR is called."""
    resp = scan_client.post(
        "/api/v1/scan/process",
        headers=AUTH,
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
    )
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_process_unsupported_mime_returns_415(scan_client):
    """Word documents are not supported for OCR."""
    resp = scan_client.post(
        "/api/v1/scan/process",
        headers=AUTH,
        files={"file": ("doc.docx", io.BytesIO(b"PK\x03\x04"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 415


# ── GET /scan/{documentId} ────────────────────────────────────────────────────

def test_get_document_success(scan_client):
    resp = scan_client.get("/api/v1/scan/test-doc-uuid-001", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == "test-doc-uuid-001"
    assert body["ocr_status"] == "COMPLETED"


def test_get_document_not_found_returns_404(scan_client, mock_processor):
    mock_processor.get_document.return_value = None
    resp = scan_client.get("/api/v1/scan/does-not-exist", headers=AUTH)
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_get_document_missing_auth_returns_401(scan_client):
    resp = scan_client.get("/api/v1/scan/test-doc-uuid-001")
    assert resp.status_code == 401


# ── GET /scan/{documentId}/metadata ───────────────────────────────────────────

def test_get_metadata_includes_ocr_preview(scan_client):
    resp = scan_client.get("/api/v1/scan/test-doc-uuid-001/metadata", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == "test-doc-uuid-001"
    assert body["ocr_preview"] == "NATIONAL INSURANCE SCHEME\nCLAIM FORM\nContributor: U001"


def test_get_metadata_no_preview_when_failed(scan_client, mock_processor):
    """FAILED documents have no OCR text — preview is null."""
    mock_processor.get_document.return_value = _FAILED_RECORD
    mock_processor.get_ocr_text.return_value = None
    resp = scan_client.get("/api/v1/scan/test-doc-uuid-002/metadata", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ocr_status"] == "FAILED"
    assert body["ocr_preview"] is None


def test_get_metadata_not_found_returns_404(scan_client, mock_processor):
    mock_processor.get_document.return_value = None
    resp = scan_client.get("/api/v1/scan/no-such-id/metadata", headers=AUTH)
    assert resp.status_code == 404
