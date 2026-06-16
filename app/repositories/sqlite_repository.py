"""
SQLite repository — concrete implementation of AbstractDocumentRepository.

To swap to PostgreSQL:
  1. Install psycopg2:  pip install psycopg2-binary
  2. Set DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dms
  3. No code changes needed here or anywhere else.

Why SQLAlchemy ORM instead of raw SQL:
  - Parameterised queries prevent SQL injection automatically
  - The ORM handles type mapping (Python datetime ↔ DB timestamp etc.)
  - Migrations via Alembic need only the models, not this file
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.scan_document import ScanDocument
from app.repositories.base import AbstractDocumentRepository
from app.schemas.scan_document import (
    OCRStatus,
    ScanDocumentCreate,
    ScanDocumentRecord,
)


def _to_record(doc: ScanDocument) -> ScanDocumentRecord:
    """Convert a SQLAlchemy ORM row to a Pydantic record. Keeps ORM out of services."""
    return ScanDocumentRecord.model_validate(doc)


class SQLiteDocumentRepository(AbstractDocumentRepository):

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, document: ScanDocumentCreate) -> ScanDocumentRecord:
        row = ScanDocument(
            document_id=document.document_id,
            file_name=document.file_name,
            upload_time=document.upload_time,
            ocr_status=document.ocr_status.value,
            document_location=document.document_location,
            ocr_text_location=document.ocr_text_location,
            content_type=document.content_type,
            file_size_bytes=document.file_size_bytes,
            error_message=document.error_message,
            scan_source=document.scan_source,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return _to_record(row)

    def get_by_id(self, document_id: str) -> Optional[ScanDocumentRecord]:
        row = self._db.get(ScanDocument, document_id)
        return _to_record(row) if row else None

    def update_status(
        self,
        document_id: str,
        status: OCRStatus,
        ocr_text_location: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> ScanDocumentRecord:
        row = self._db.get(ScanDocument, document_id)
        if row is None:
            raise ValueError(f"Document '{document_id}' not found in database.")
        row.ocr_status = status.value
        if ocr_text_location is not None:
            row.ocr_text_location = ocr_text_location
        if error_message is not None:
            row.error_message = error_message
        self._db.commit()
        self._db.refresh(row)
        return _to_record(row)

    def list_all(self, limit: int = 100, offset: int = 0) -> list[ScanDocumentRecord]:
        rows = (
            self._db.query(ScanDocument)
            .order_by(ScanDocument.upload_time.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_to_record(r) for r in rows]
