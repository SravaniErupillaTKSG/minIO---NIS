"""
Document Processor — orchestrates the full scan-to-storage pipeline.

Responsibility:
  This class is the only component that knows the complete processing flow.
  It delegates every unit of work to a focused service:
    - OCRService       extracts text
    - MinIOService     stores and retrieves files
    - MetadataService  persists and queries document records

Split into two cooperating phases to support async processing:

  Phase 1 — store_original()  (called by the API endpoint, synchronous)
    1. Compute MinIO object paths
    2. Upload original file to  scanned-documents bucket
    3. Insert metadata record   (status=PENDING)
    Returns the PENDING record immediately.

  Phase 2 — run_ocr_pipeline()  (called by the Celery worker, runs in background)
    4. Download original from MinIO
    5. Transition status to PROCESSING
    6. Run OCR
    7. Upload OCR text to  ocr-output bucket
    8. Update metadata to COMPLETED (or FAILED on error)

  Convenience wrapper:
    process_document()  — Phase 1 + Phase 2 in sequence (sync path / tests)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from app.core.config import Settings
from app.schemas.scan_document import OCRStatus, ScanDocumentRecord
from app.services.minio_service import MinIOService
from app.services.metadata_service import MetadataService
from app.services.ocr_service import OCRService


def _file_extension(content_type: str, file_name: str) -> str:
    """Best-effort extension: try content_type first, fallback to filename."""
    _ct_map = {
        "application/pdf": ".pdf",
        "image/jpeg":      ".jpg",
        "image/jpg":       ".jpg",
        "image/png":       ".png",
        "image/tiff":      ".tiff",
        "image/tif":       ".tiff",
    }
    base = content_type.split(";")[0].strip().lower()
    if ext := _ct_map.get(base):
        return ext
    if "." in file_name:
        return "." + file_name.rsplit(".", 1)[-1].lower()
    return ".bin"


class DocumentProcessor:
    """
    Orchestrates a single document through the OCR pipeline.

    Designed to be called either:
      - From the endpoint → store_original() then Celery task → run_ocr_pipeline()
      - Directly for sync processing → process_document() (wraps both phases)

    All constructor dependencies are injected — fully testable without patching globals.
    """

    def __init__(
        self,
        minio:    MinIOService,
        ocr:      OCRService,
        metadata: MetadataService,
        settings: Settings,
    ) -> None:
        self._minio    = minio
        self._ocr      = ocr
        self._metadata = metadata
        self._settings = settings

    # ── Phase 1: store original ───────────────────────────────────────────────

    def store_original(
        self,
        document_id:  str,
        file_data:    bytes,
        file_name:    str,
        content_type: str,
        scan_source:  str = "IBML_SIMULATED",
    ) -> ScanDocumentRecord:
        """
        Upload original file to MinIO and create a PENDING metadata record.
        Returns immediately — OCR has not started yet.
        Called by the API endpoint before queuing the async task.
        """
        now    = datetime.now(timezone.utc)
        year   = str(now.year)
        month  = f"{now.month:02d}"
        ext    = _file_extension(content_type, file_name)

        scanned_object = f"{year}/{month}/{document_id}{ext}"
        scanned_bucket = self._settings.ocr_bucket_scanned

        logger.info(
            f"Processor | phase=store_original | id={document_id} | size={len(file_data)}"
        )
        self._minio.upload_bytes(
            bucket=scanned_bucket,
            object_name=scanned_object,
            data=file_data,
            content_type=content_type,
        )
        document_location = f"{scanned_bucket}/{scanned_object}"

        return self._metadata.create_document(
            document_id=document_id,
            file_name=file_name,
            content_type=content_type,
            file_size_bytes=len(file_data),
            document_location=document_location,
            scan_source=scan_source,
            ocr_status=OCRStatus.PENDING,
        )

    # ── Phase 2: OCR pipeline ─────────────────────────────────────────────────

    def run_ocr_pipeline(self, document_id: str) -> ScanDocumentRecord:
        """
        Download the stored original, run OCR, and update metadata.
        Transitions: PENDING → PROCESSING → COMPLETED | FAILED.
        Called by the Celery worker (or synchronously from process_document).
        """
        record = self._metadata.get_document(document_id)
        if not record:
            raise ValueError(f"Document '{document_id}' not found for OCR pipeline.")

        # Mark as PROCESSING so the status endpoint reflects active work
        self._metadata.update_processing(document_id)

        # Derive OCR output path from the stored document_location
        # Format: "{bucket}/{year}/{month}/{id}.ext"
        loc_parts   = record.document_location.split("/")
        year        = loc_parts[1] if len(loc_parts) > 1 else str(datetime.now(timezone.utc).year)
        month       = loc_parts[2] if len(loc_parts) > 2 else f"{datetime.now(timezone.utc).month:02d}"
        ocr_object  = f"{year}/{month}/{document_id}.txt"
        output_bucket = self._settings.ocr_bucket_output

        # Download original from MinIO
        orig_parts  = record.document_location.split("/", 1)
        orig_bucket = orig_parts[0]
        orig_key    = orig_parts[1]

        try:
            logger.info(f"Processor | phase=download | id={document_id}")
            file_data, _ = self._minio.download_document(
                bucket=orig_bucket, object_name=orig_key
            )

            logger.info(f"Processor | phase=ocr | id={document_id}")
            ocr_text = self._ocr.extract_text(file_data, record.content_type, record.file_name)

            logger.info(
                f"Processor | phase=store_ocr | id={document_id} | chars={len(ocr_text)}"
            )
            self._minio.upload_bytes(
                bucket=output_bucket,
                object_name=ocr_object,
                data=ocr_text.encode("utf-8"),
                content_type="text/plain; charset=utf-8",
            )
            ocr_text_location = f"{output_bucket}/{ocr_object}"

            result = self._metadata.update_completed(
                document_id=document_id,
                ocr_text_location=ocr_text_location,
            )
            logger.info(f"Processor | phase=completed | id={document_id}")
            return result

        except Exception as exc:
            error_msg = str(exc)
            logger.error(f"Processor | phase=failed | id={document_id} | error={error_msg}")
            return self._metadata.update_failed(
                document_id=document_id,
                error_message=error_msg,
            )

    # ── Convenience: sync pipeline ────────────────────────────────────────────

    def process_document(
        self,
        document_id:  str,
        file_data:    bytes,
        file_name:    str,
        content_type: str,
        scan_source:  str = "IBML_SIMULATED",
    ) -> ScanDocumentRecord:
        """
        Run Phase 1 + Phase 2 synchronously.
        Used by tests and the sync fallback path in the worker.
        """
        self.store_original(
            document_id=document_id,
            file_data=file_data,
            file_name=file_name,
            content_type=content_type,
            scan_source=scan_source,
        )
        return self.run_ocr_pipeline(document_id)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_document(self, document_id: str) -> Optional[ScanDocumentRecord]:
        return self._metadata.get_document(document_id)

    def get_ocr_text(self, document_id: str, max_chars: int = 500) -> Optional[str]:
        """
        Download and return the first `max_chars` characters of the OCR output.
        Returns None when status is not COMPLETED or the text cannot be retrieved.
        """
        record = self._metadata.get_document(document_id)
        if not record or record.ocr_status != OCRStatus.COMPLETED:
            return None
        if not record.ocr_text_location:
            return None
        try:
            parts       = record.ocr_text_location.split("/", 1)
            bucket      = parts[0]
            object_name = parts[1]
            data, _     = self._minio.download_document(bucket=bucket, object_name=object_name)
            text = data.decode("utf-8", errors="replace")
            return text[:max_chars] if max_chars > 0 else text
        except Exception as exc:
            logger.warning(f"OCR text retrieval failed for {document_id}: {exc}")
            return None
