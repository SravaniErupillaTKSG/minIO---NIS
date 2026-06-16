"""
Document Metadata table — one row per uploaded document.

Why this table exists:
  MinIO is an object store, not a database. It holds bytes. This table holds
  every piece of business metadata attached to those bytes: who owns the
  document (nis_id), what type it is, when it was uploaded, where it lives
  in MinIO (bucket + object_path), and whether it has been soft-deleted.

Soft-delete strategy:
  is_deleted=True + deleted_at=<timestamp> marks the row as deleted without
  physically removing it from the database or from MinIO. The actual MinIO
  object gets a delete marker (versioning), so the bytes are recoverable.
  This satisfies audit requirements — nothing is ever truly gone.

Design decisions:
  - doc_id is always "DOC-XXXXXXXX" (8 uppercase hex chars) — generated in the
    service layer, never by the database. This gives a human-readable ID that is
    still globally unique and sortable by insertion order.
  - All nullable fields are optional MinIO/Salesforce metadata that may not be
    present in all upload scenarios.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class DocumentMetadata(Base):
    __tablename__ = "document_metadata"

    # ── Primary identity ──────────────────────────────────────────────────────
    doc_id  = Column(String(50),  primary_key=True, index=True)           # DOC-XXXXXXXX
    nis_id  = Column(String(50),  ForeignKey("nis_master.nis_id"),
                     nullable=False, index=True)

    # ── File identity ─────────────────────────────────────────────────────────
    file_name       = Column(String(500), nullable=False)
    document_type   = Column(String(100), nullable=False)                  # NISDocumentType
    document_class  = Column(String(50),  nullable=False, default="ORIGINAL")  # NISDocumentClass
    content_type    = Column(String(100), nullable=True)
    file_size_bytes = Column(BigInteger,  nullable=True)

    # ── MinIO location ────────────────────────────────────────────────────────
    bucket_name = Column(String(100), nullable=False)
    object_path = Column(Text,        nullable=False)   # full path in MinIO
    etag        = Column(String(100), nullable=True)    # MD5 checksum from MinIO
    version_id  = Column(String(100), nullable=True)    # MinIO version ID

    # ── Salesforce / MuleSoft traceability ───────────────────────────────────
    uploaded_by           = Column(String(255), nullable=True)
    correlation_id        = Column(String(100), nullable=True)
    salesforce_record_id  = Column(String(100), nullable=True)
    salesforce_object_type = Column(String(100), nullable=True)

    # ── Optional document metadata ────────────────────────────────────────────
    description = Column(Text,        nullable=True)
    expiry_date = Column(String(50),  nullable=True)    # ISO date string

    # ── Lifecycle timestamps ──────────────────────────────────────────────────
    uploaded_at = Column(DateTime, nullable=False, default=func.now())
    deleted_at  = Column(DateTime, nullable=True)
    is_deleted  = Column(Boolean,  nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<DocumentMetadata doc_id={self.doc_id!r} "
            f"nis_id={self.nis_id!r} deleted={self.is_deleted}>"
        )
