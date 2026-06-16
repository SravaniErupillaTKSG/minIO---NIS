"""
Metadata Service — thin facade over the document repository.

Why this exists instead of calling the repository directly:
  - Services depend on an abstract interface, not a concrete class
  - Business logic about status transitions lives here, not in the repository
  - Easy to add caching, validation, or audit logging in one place later
"""
from datetime import datetime, timezone
from typing import Optional

from app.repositories.base import AbstractDocumentRepository
from app.schemas.scan_document import (
    OCRStatus,
    ScanDocumentCreate,
    ScanDocumentRecord,
)


class MetadataService:

    def __init__(self, repo: AbstractDocumentRepository) -> None:
        self._repo = repo

    def create_document(
        self,
        *,
        document_id:       str,
        file_name:         str,
        content_type:      str,
        file_size_bytes:   int,
        document_location: str,
        scan_source:       str,
        ocr_status:        OCRStatus = OCRStatus.PROCESSING,
    ) -> ScanDocumentRecord:
        payload = ScanDocumentCreate(
            document_id=document_id,
            file_name=file_name,
            upload_time=datetime.now(timezone.utc),
            ocr_status=ocr_status,
            document_location=document_location,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
            scan_source=scan_source,
        )
        return self._repo.create(payload)

    def get_document(self, document_id: str) -> Optional[ScanDocumentRecord]:
        return self._repo.get_by_id(document_id)

    def update_processing(self, document_id: str) -> ScanDocumentRecord:
        """PENDING → PROCESSING: worker has started OCR."""
        return self._repo.update_status(document_id, OCRStatus.PROCESSING)

    def update_completed(
        self,
        document_id: str,
        ocr_text_location: str,
    ) -> ScanDocumentRecord:
        return self._repo.update_status(
            document_id,
            OCRStatus.COMPLETED,
            ocr_text_location=ocr_text_location,
        )

    def update_failed(
        self,
        document_id: str,
        error_message: str,
    ) -> ScanDocumentRecord:
        return self._repo.update_status(
            document_id,
            OCRStatus.FAILED,
            error_message=error_message[:2000],  # Guard against DB column width
        )

    def list_documents(self, limit: int = 100, offset: int = 0) -> list[ScanDocumentRecord]:
        return self._repo.list_all(limit=limit, offset=offset)
