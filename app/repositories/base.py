"""
Abstract repository interface for scan documents.

Why this exists:
  The concrete implementation is SQLiteDocumentRepository.
  Changing the database to PostgreSQL, MySQL, or a document store requires only:
  1. Write a new class that implements AbstractDocumentRepository
  2. Swap the injection in app/api/v1/endpoints/scan.py

No endpoint or service code needs to change.
"""
from abc import ABC, abstractmethod
from typing import Optional

from app.schemas.scan_document import ScanDocumentCreate, ScanDocumentRecord, OCRStatus


class AbstractDocumentRepository(ABC):

    @abstractmethod
    def create(self, document: ScanDocumentCreate) -> ScanDocumentRecord:
        """Persist a new document record and return it."""

    @abstractmethod
    def get_by_id(self, document_id: str) -> Optional[ScanDocumentRecord]:
        """Return the document or None if it does not exist."""

    @abstractmethod
    def update_status(
        self,
        document_id: str,
        status: OCRStatus,
        ocr_text_location: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> ScanDocumentRecord:
        """
        Transition the document to a new OCR status.

        For COMPLETED: pass ocr_text_location.
        For FAILED:    pass error_message.
        """

    @abstractmethod
    def list_all(self, limit: int = 100, offset: int = 0) -> list[ScanDocumentRecord]:
        """Return paginated list of all documents, newest first."""
