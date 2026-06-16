"""
SQLAlchemy ORM model for scan documents.

This model only lives inside the repository layer.
Nothing outside app/repositories/ should import ScanDocument directly.
Use app/schemas/scan_document.ScanDocumentRecord for cross-boundary data transfer.
"""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schemas.scan_document import OCRStatus


class ScanDocument(Base):
    __tablename__ = "scan_documents"

    document_id:       Mapped[str]           = mapped_column(String(36),   primary_key=True)
    file_name:         Mapped[str]           = mapped_column(String(512),  nullable=False)
    upload_time:       Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False)
    ocr_status:        Mapped[str]           = mapped_column(String(20),   nullable=False, default=OCRStatus.PENDING)
    document_location: Mapped[str]           = mapped_column(String(1024), nullable=False)
    ocr_text_location: Mapped[str | None]    = mapped_column(String(1024), nullable=True)
    content_type:      Mapped[str]           = mapped_column(String(100),  nullable=False)
    file_size_bytes:   Mapped[int]           = mapped_column(Integer,       nullable=False)
    error_message:     Mapped[str | None]    = mapped_column(String(2048), nullable=True)
    scan_source:       Mapped[str]           = mapped_column(String(100),  nullable=False, default="IBML_SIMULATED")

    def __repr__(self) -> str:
        return f"<ScanDocument id={self.document_id!r} status={self.ocr_status!r}>"
