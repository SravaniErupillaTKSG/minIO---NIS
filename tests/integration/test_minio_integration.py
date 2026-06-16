"""
Integration tests — require a live MinIO instance.

Run with:
    pytest tests/integration/ -v -m integration

These tests connect to the real MinIO at localhost:9000.
Make sure Docker is running: docker compose up -d minio minio-init
"""

import io
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_svc():
    """Real MinIOService connected to local Docker MinIO."""
    import os
    os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
    os.environ.setdefault("MINIO_ROOT_USER", "minioadmin")
    os.environ.setdefault("MINIO_ROOT_PASSWORD", "minioadmin123")
    os.environ.setdefault("MINIO_SECURE", "false")

    from app.services.minio_service import MinIOService
    return MinIOService()


def test_health_check_live(live_svc):
    result = live_svc.health_check()
    for bucket, status in result.items():
        assert status == "ok", f"Bucket {bucket} is not ok: {status}"


def test_upload_and_download_roundtrip(live_svc):
    content = b"Integration test PDF content"
    result = live_svc.upload_document(
        bucket="dms-contributors",
        object_name="test/integration/roundtrip.pdf",
        data=content,
        content_type="application/pdf",
        metadata={"test": "true"},
    )
    assert result.etag
    assert result.size_bytes == len(content)

    downloaded, ct = live_svc.download_document("dms-contributors", "test/integration/roundtrip.pdf")
    assert downloaded == content
    assert ct == "application/pdf"


def test_metadata(live_svc):
    meta = live_svc.get_document_metadata("dms-contributors", "test/integration/roundtrip.pdf")
    assert meta.size_bytes > 0
    assert meta.etag


def test_presigned_download_url(live_svc):
    result = live_svc.generate_presigned_download_url(
        "dms-contributors", "test/integration/roundtrip.pdf"
    )
    assert result.method == "GET"
    assert "X-Amz" in result.url or "sig" in result.url.lower()


def test_delete(live_svc):
    live_svc.delete_document("dms-contributors", "test/integration/roundtrip.pdf")

    from app.core.exceptions import DocumentNotFoundError
    with pytest.raises(DocumentNotFoundError):
        live_svc.download_document("dms-contributors", "test/integration/roundtrip.pdf")
