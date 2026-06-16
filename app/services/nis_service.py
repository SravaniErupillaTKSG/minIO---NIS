"""
NIS Service — business logic for NIS person registration and document lookup.

Responsibility boundary:
  This service coordinates between:
    - NISRepository         (database reads/writes)
    - DocumentMetadataRepository (database reads)
    - MinIOService          (generate presigned download URLs)

  It does NOT touch the database directly — all DB access goes through
  the repositories. It does NOT know about HTTP — all exception translation
  happens in the endpoint layer.

  Raises:
    ValueError   — business rule violation (duplicate nis_id, not found).
                   Endpoint translates to 409 or 404.
    RuntimeError — unexpected system error (re-raised from repo).
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from loguru import logger

from app.models.document_metadata import DocumentMetadata
from app.repositories.document_metadata_repository import DocumentMetadataRepository
from app.repositories.nis_repository import NISRepository
from app.schemas.nis import (
    NISDocumentDeleteResponse,
    NISDocumentItem,
    NISPersonResponse,
    NISWithDocumentsResponse,
)


# ── Doc ID generator ──────────────────────────────────────────────────────────

def generate_doc_id() -> str:
    """
    Generate a globally-unique Document ID.
    Format: DOC-XXXXXXXX  (8 uppercase hexadecimal characters from UUID4).
    Example: DOC-A3F4B2C1
    """
    return f"DOC-{uuid.uuid4().hex[:8].upper()}"


# ── Model → Schema converters ─────────────────────────────────────────────────

def _doc_to_item(
    record: DocumentMetadata,
    download_url: Optional[str] = None,
) -> NISDocumentItem:
    """Convert a DocumentMetadata ORM row to the NISDocumentItem Pydantic schema."""
    return NISDocumentItem(
        doc_id=record.doc_id,
        nis_id=record.nis_id,
        file_name=record.file_name,
        document_type=record.document_type,
        document_class=record.document_class,
        bucket_name=record.bucket_name,
        object_path=record.object_path,
        content_type=record.content_type,
        file_size_bytes=record.file_size_bytes,
        uploaded_by=record.uploaded_by,
        correlation_id=record.correlation_id,
        salesforce_record_id=record.salesforce_record_id,
        salesforce_object_type=record.salesforce_object_type,
        description=record.description,
        expiry_date=record.expiry_date,
        etag=record.etag,
        version_id=record.version_id,
        uploaded_at=record.uploaded_at,
        is_deleted=record.is_deleted,
        download_url=download_url,
    )


# ── Service ───────────────────────────────────────────────────────────────────

class NISService:
    """
    Orchestrates NIS person registration and document lookups.

    Injected per-request via FastAPI Depends — create one instance per request,
    backed by the request-scoped DB Session.
    """

    def __init__(
        self,
        nis_repo: NISRepository,
        doc_repo: DocumentMetadataRepository,
    ) -> None:
        self._nis = nis_repo
        self._doc = doc_repo

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        nis_id:      str,
        person_name: str,
        entity_type: str,
    ) -> NISPersonResponse:
        """
        Register a new NIS person.
        Raises ValueError (→ 409) if nis_id is already taken.
        """
        logger.info(f"Registering NIS person | nis_id={nis_id} | entity_type={entity_type}")
        record = self._nis.create(
            nis_id=nis_id,
            person_name=person_name,
            entity_type=entity_type,
        )
        return NISPersonResponse(
            nis_id=record.nis_id,
            person_name=record.person_name,
            entity_type=record.entity_type,
            created_at=record.created_at,
            document_count=0,
        )

    # ── Person lookups ────────────────────────────────────────────────────────

    def get_person(self, nis_id: str) -> NISPersonResponse:
        """
        Return NIS person details + active document count.
        Raises ValueError (→ 404) if nis_id is not found.
        """
        record = self._nis.get_by_id(nis_id)
        if record is None:
            raise ValueError(f"NIS ID '{nis_id}' not found.")
        count = self._doc.count_by_nis_id(nis_id)
        return NISPersonResponse(
            nis_id=record.nis_id,
            person_name=record.person_name,
            entity_type=record.entity_type,
            created_at=record.created_at,
            document_count=count,
        )

    def get_person_with_documents(
        self,
        nis_id:      str,
        minio_svc,            # MinIOService — not typed to avoid circular import
    ) -> NISWithDocumentsResponse:
        """
        Return full NIS lookup: person info + all active documents with presigned URLs.
        Raises ValueError (→ 404) if nis_id is not found.

        Presigned URL generation is best-effort — if MinIO is unavailable,
        download_url is None (the document record is still returned).
        """
        record = self._nis.get_by_id(nis_id)
        if record is None:
            raise ValueError(f"NIS ID '{nis_id}' not found.")

        doc_rows: List[DocumentMetadata] = self._doc.get_by_nis_id(nis_id)
        doc_items: List[NISDocumentItem] = []

        for row in doc_rows:
            url = self._safe_presigned_url(minio_svc, row.bucket_name, row.object_path)
            doc_items.append(_doc_to_item(row, download_url=url))

        logger.info(
            f"NIS lookup | nis_id={nis_id} | docs={len(doc_items)}"
        )
        return NISWithDocumentsResponse(
            nis_id=record.nis_id,
            person_name=record.person_name,
            entity_type=record.entity_type,
            created_at=record.created_at,
            total_documents=len(doc_items),
            documents=doc_items,
        )

    # ── Document lookups ──────────────────────────────────────────────────────

    def get_document(
        self,
        doc_id:    str,
        minio_svc,            # MinIOService
    ) -> NISDocumentItem:
        """
        Return a single document by its doc_id with a presigned download URL.
        Raises ValueError (→ 404) if doc_id is not found or already deleted.
        """
        row = self._doc.get_by_doc_id(doc_id)
        if row is None:
            raise ValueError(f"Document '{doc_id}' not found.")
        url = self._safe_presigned_url(minio_svc, row.bucket_name, row.object_path)
        return _doc_to_item(row, download_url=url)

    def delete_document(
        self,
        doc_id:    str,
        minio_svc,            # MinIOService — for MinIO delete marker
    ) -> NISDocumentDeleteResponse:
        """
        Soft-delete a document:
          1. Mark row as deleted in database (is_deleted=True, deleted_at=now).
          2. Add MinIO delete marker (versioned — bytes NOT destroyed).

        Raises ValueError (→ 404) if doc_id not found or already deleted.
        """
        row = self._doc.get_by_doc_id(doc_id)
        if row is None:
            raise ValueError(f"Document '{doc_id}' not found or already deleted.")

        # Step 1: soft-delete in DB
        updated = self._doc.soft_delete(doc_id)

        # Step 2: MinIO delete marker (best-effort — DB is source of truth)
        try:
            minio_svc.delete_document(bucket=row.bucket_name, object_name=row.object_path)
        except Exception as exc:
            logger.warning(
                f"MinIO delete marker failed for {doc_id} | error={exc} "
                f"| DB record is still soft-deleted."
            )

        logger.info(f"Document soft-deleted | doc_id={doc_id} | nis_id={row.nis_id}")
        return NISDocumentDeleteResponse(
            doc_id=updated.doc_id,
            nis_id=updated.nis_id,
            deleted=True,
            deleted_at=updated.deleted_at,
        )

    # ── Validation helper ─────────────────────────────────────────────────────

    def validate_nis_exists(self, nis_id: str) -> None:
        """
        Used by the upload endpoint to validate nis_id before uploading to MinIO.
        Raises ValueError (→ 422) if nis_id is not registered.
        """
        if not self._nis.exists(nis_id):
            raise ValueError(
                f"NIS ID '{nis_id}' is not registered. "
                f"Call POST /api/v1/nis/register first."
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _safe_presigned_url(minio_svc, bucket: str, object_path: str) -> Optional[str]:
        """
        Generate a presigned download URL. Returns None if MinIO is unavailable
        (so document list responses still work even if storage is temporarily down).
        """
        try:
            result = minio_svc.generate_presigned_download_url(
                bucket=bucket,
                object_name=object_path,
            )
            return result.url
        except Exception as exc:
            logger.warning(f"Could not generate presigned URL for {bucket}/{object_path}: {exc}")
            return None
