"""
NIS Person registration and document lookup endpoints.

Route prefix: /api/v1/nis
All endpoints require X-API-Key authentication.

Endpoints:
  POST /nis/register            — Register a new NIS person (Contributor/Beneficiary/Employee)
  GET  /nis/{nis_id}            — Get NIS person details + active document count
  GET  /nis/{nis_id}/documents  — Get all documents for a NIS ID (with presigned URLs)
  GET  /documents/{doc_id}      — Get a single document by its DOC-XXXXXXXX identifier
  DELETE /documents/{doc_id}    — Soft-delete a document by its DOC-XXXXXXXX identifier

Design notes:
  - doc_id routes use a path regex pattern (^DOC-[0-9A-F]{8}$) to differentiate
    from entity_type paths in documents.py (which never start with "DOC-").
  - All 404/409 exceptions originate as ValueError from the service layer.
    The endpoints catch ValueError and translate to the correct HTTP status code.
  - Presigned URLs are generated on-the-fly — they are NOT stored in the database.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_api_key
from app.repositories.document_metadata_repository import DocumentMetadataRepository
from app.repositories.nis_repository import NISRepository
from app.schemas.document import ErrorResponse
from app.schemas.nis import (
    NISDocumentDeleteResponse,
    NISDocumentDetailResponse,
    NISPersonResponse,
    NISRegisterRequest,
    NISWithDocumentsResponse,
)
from app.services.minio_service import MinIOService, get_minio_service
from app.services.nis_service import NISService


# ── Router ────────────────────────────────────────────────────────────────────

nis_router      = APIRouter(prefix="/nis",       tags=["NIS"])
doc_ext_router  = APIRouter(prefix="/documents", tags=["Documents"])   # doc_id-based routes


# ── Dependency factory ────────────────────────────────────────────────────────

def get_nis_service(db: Session = Depends(get_db)) -> NISService:
    """Build a NISService for the current request."""
    return NISService(
        nis_repo=NISRepository(db),
        doc_repo=DocumentMetadataRepository(db),
    )


# ─── POST /nis/register ───────────────────────────────────────────────────────

@nis_router.post(
    "/register",
    response_model=NISPersonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new NIS person",
    description="""
Register a new Contributor, Beneficiary, or Employee with a unique NIS ID.

**Must be called before uploading documents** — the upload endpoint validates
that the `nis_id` exists in this registry.

**Returns 409 Conflict** if the `nis_id` is already registered.
""",
    responses={
        201: {"model": NISPersonResponse, "description": "NIS person registered successfully"},
        401: {"model": ErrorResponse, "description": "Missing API key"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
        409: {"model": ErrorResponse, "description": "NIS ID already registered"},
        422: {"description": "Validation error (invalid entity_type, nis_id too short, etc.)"},
    },
)
async def register_nis(
    body: NISRegisterRequest,
    _: str = Depends(verify_api_key),
    svc: NISService = Depends(get_nis_service),
) -> NISPersonResponse:
    logger.info(
        f"NIS register | nis_id={body.nis_id!r} | entity_type={body.entity_type} "
        f"| person={body.person_name!r}"
    )
    try:
        return svc.register(
            nis_id=body.nis_id,
            person_name=body.person_name,
            entity_type=body.entity_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ─── GET /nis/{nis_id} ────────────────────────────────────────────────────────

@nis_router.get(
    "/{nis_id}",
    response_model=NISPersonResponse,
    summary="Get NIS person details",
    description="""
Returns the registered person's details (name, entity type) and the **count**
of active documents linked to this NIS ID.

Use `GET /api/v1/nis/{nis_id}/documents` to retrieve the full document list.
""",
    responses={
        200: {"model": NISPersonResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse, "description": "NIS ID not found"},
    },
)
async def get_nis_person(
    nis_id: Annotated[str, Path(description="NIS person identifier (e.g. NIS001)")],
    _: str = Depends(verify_api_key),
    svc: NISService = Depends(get_nis_service),
) -> NISPersonResponse:
    logger.info(f"NIS lookup | nis_id={nis_id!r}")
    try:
        return svc.get_person(nis_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ─── GET /nis/{nis_id}/documents ──────────────────────────────────────────────

@nis_router.get(
    "/{nis_id}/documents",
    response_model=NISWithDocumentsResponse,
    summary="Get all documents for a NIS ID",
    description="""
Returns the complete NIS person record **plus** a list of all active documents
with metadata and presigned download URLs.

**This is the primary endpoint for Salesforce to populate the document panel.**
One call returns everything needed to show the document history for a person:

```
NIS001 — John Doe (CONTRIBUTOR)
├── DOC-A3F4B2C1  passport.pdf       IDENTITY    2024-01-15  [download URL]
├── DOC-B7E1C4D2  contract.pdf       CONTRACT    2024-01-16  [download URL]
└── DOC-C9D2E3F4  bank_statement.pdf BANK_DETAIL 2024-01-20  [download URL]
```

Download URLs are presigned MinIO GET URLs valid for `MINIO_PRESIGNED_EXPIRY` seconds (default 1 hour).
""",
    responses={
        200: {"model": NISWithDocumentsResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse, "description": "NIS ID not found"},
        503: {"model": ErrorResponse, "description": "Storage unavailable (presigned URLs omitted)"},
    },
)
async def get_nis_documents(
    nis_id: Annotated[str, Path(description="NIS person identifier (e.g. NIS001)")],
    _: str = Depends(verify_api_key),
    svc: NISService = Depends(get_nis_service),
    minio: MinIOService = Depends(get_minio_service),
) -> NISWithDocumentsResponse:
    logger.info(f"NIS document list | nis_id={nis_id!r}")
    try:
        return svc.get_person_with_documents(nis_id=nis_id, minio_svc=minio)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ─── GET /documents/{doc_id} ──────────────────────────────────────────────────
# These routes extend the existing /documents prefix via doc_ext_router.
# doc_id pattern: DOC-XXXXXXXX (8 uppercase hex chars) — never conflicts with
# entity_type values (contributors / beneficiaries / employees / temp).

@doc_ext_router.get(
    "/{doc_id}",
    response_model=NISDocumentDetailResponse,
    summary="Get document by Document ID",
    description="""
Returns full metadata for a single document identified by its `doc_id`
(`DOC-XXXXXXXX`), including a presigned download URL.

Use this when Salesforce has stored the `doc_id` from the upload response
and needs to fetch or re-download the file.
""",
    responses={
        200: {"model": NISDocumentDetailResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse, "description": "Document not found"},
    },
)
async def get_document_by_id(
    doc_id: Annotated[
        str,
        Path(
            description="Document ID returned by the upload endpoint (format: DOC-XXXXXXXX)",
            pattern=r"^DOC-[0-9A-F]{8}$",
        ),
    ],
    _: str = Depends(verify_api_key),
    svc: NISService = Depends(get_nis_service),
    minio: MinIOService = Depends(get_minio_service),
) -> NISDocumentDetailResponse:
    logger.info(f"Document fetch by doc_id | doc_id={doc_id!r}")
    try:
        return svc.get_document(doc_id=doc_id, minio_svc=minio)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ─── DELETE /documents/{doc_id} ───────────────────────────────────────────────

@doc_ext_router.delete(
    "/{doc_id}",
    response_model=NISDocumentDeleteResponse,
    summary="Soft-delete a document by Document ID",
    description="""
Soft-deletes a document:

1. Marks the database record as `is_deleted=true` with a `deleted_at` timestamp.
2. Adds a **MinIO delete marker** (versioning is enabled — the bytes are NOT destroyed).
3. The document no longer appears in `GET /nis/{nis_id}/documents` listings.

To permanently destroy the bytes, an administrator must purge the MinIO version.
This design satisfies NIS audit requirements — nothing is ever irrecoverably lost.

**Returns 404** if the document is not found or was already deleted.
""",
    responses={
        200: {"model": NISDocumentDeleteResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse, "description": "Document not found or already deleted"},
    },
)
async def delete_document_by_id(
    doc_id: Annotated[
        str,
        Path(
            description="Document ID to delete (format: DOC-XXXXXXXX)",
            pattern=r"^DOC-[0-9A-F]{8}$",
        ),
    ],
    _: str = Depends(verify_api_key),
    svc: NISService = Depends(get_nis_service),
    minio: MinIOService = Depends(get_minio_service),
) -> NISDocumentDeleteResponse:
    logger.info(f"Document soft-delete | doc_id={doc_id!r}")
    try:
        return svc.delete_document(doc_id=doc_id, minio_svc=minio)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
