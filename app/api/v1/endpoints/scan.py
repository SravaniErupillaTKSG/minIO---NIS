"""
Scan / OCR endpoints (Scenario 1 — Physical Document ingestion).

Route prefix: /api/v1/scan
All endpoints require X-API-Key authentication.

IBML simulation:
  In production the IBML scanner pushes files to an internal landing zone
  and MuleSoft calls this API.  In local development, upload files directly
  to POST /scan/process — same as if the scanner submitted them.

Processing model (current: synchronous):
  POST /scan/process  →  blocks until OCR completes  →  returns COMPLETED record
  Future: POST returns status=PENDING immediately; client polls GET /{id}.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile, status
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import verify_api_key
from app.schemas.document import ErrorResponse
from app.schemas.scan_document import OCRStatus, ScanDocumentMetadata, ScanDocumentRecord
from app.services.document_processor import DocumentProcessor
from app.services.metadata_service import MetadataService
from app.services.minio_service import MinIOService, get_minio_service
from app.services.ocr_service import OCRService, get_ocr_service, SUPPORTED_OCR_MIME_TYPES
from app.repositories.sqlite_repository import SQLiteDocumentRepository
from app.workers.ocr_worker import submit_processing_task

router = APIRouter(prefix="/scan", tags=["Scan / OCR"])

# ── Dependency factory ─────────────────────────────────────────────────────────

def get_processor(
    db:       Session  = Depends(get_db),
    minio:    MinIOService = Depends(get_minio_service),
    settings: Settings    = Depends(get_settings),
) -> DocumentProcessor:
    """
    Build the DocumentProcessor for this request.
    Override this in tests:  app.dependency_overrides[get_processor] = lambda: mock_processor
    """
    repo     = SQLiteDocumentRepository(db)
    metadata = MetadataService(repo)
    ocr      = get_ocr_service(dpi=settings.ocr_dpi, lang=settings.ocr_lang)
    return DocumentProcessor(minio=minio, ocr=ocr, metadata=metadata, settings=settings)


# ── Validators ────────────────────────────────────────────────────────────────

def _validate_ocr_file(file: UploadFile) -> None:
    """Raise 400/413/415 early — before any MinIO/OCR call."""
    size = file.size or 0
    if size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )
    # OCR documents can be larger — 100 MB limit for scanned TIFFs
    max_bytes = 100 * 1024 * 1024
    if size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size {size / (1024*1024):.1f} MB exceeds the 100 MB OCR limit.",
        )
    base_type = (file.content_type or "").split(";")[0].strip().lower()
    if base_type and base_type not in SUPPORTED_OCR_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Content type '{base_type}' is not supported for OCR. "
                f"Supported: {sorted(SUPPORTED_OCR_MIME_TYPES)}"
            ),
        )


# ── POST /scan/process ────────────────────────────────────────────────────────

@router.post(
    "/process",
    response_model=ScanDocumentRecord,
    status_code=202,
    summary="Submit a scanned document for OCR processing",
    description="""
Simulate an IBML scanner submission: upload a scanned PDF, JPG, PNG, or TIFF.

**Processing flow (synchronous):**
```
Receive file
  → store original  → scanned-documents/{year}/{month}/{documentId}.ext
  → run OCR         → pytesseract extracts text
  → store OCR text  → ocr-output/{year}/{month}/{documentId}.txt
  → save metadata   → SQLite (documentId, status, locations, timestamps)
  → return record
```

**Future async upgrade:** When a task queue (Celery + Redis) is added, this endpoint
will return `status=PENDING` immediately and the client polls `GET /scan/{documentId}`.
The processing code is already isolated in `DocumentProcessor` — no endpoint changes needed.

**Scan source values:**
- `IBML_SIMULATED` (default) — local development
- `IBML_SCANNER` — production IBML hardware
""",
    responses={
        202: {"model": ScanDocumentRecord, "description": "Document accepted, OCR completed (or failed — check ocr_status)"},
        400: {"model": ErrorResponse, "description": "Empty file"},
        401: {"model": ErrorResponse, "description": "Missing API key"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
        413: {"model": ErrorResponse, "description": "File exceeds 100 MB limit"},
        415: {"model": ErrorResponse, "description": "Unsupported file type"},
        503: {"model": ErrorResponse, "description": "MinIO storage unavailable"},
    },
)
async def process_document(
    file: Annotated[UploadFile, File(
        description="Scanned document: PDF, JPEG, PNG, or TIFF"
    )],
    scan_source: Annotated[str, Form(
        description="Source identifier: `IBML_SIMULATED` (default) or `IBML_SCANNER`"
    )] = "IBML_SIMULATED",
    _: str = Depends(verify_api_key),
    processor: DocumentProcessor = Depends(get_processor),
) -> ScanDocumentRecord:

    _validate_ocr_file(file)

    document_id  = str(uuid.uuid4())
    file_data    = await file.read()
    file_name    = file.filename or f"{document_id}"
    content_type = file.content_type or "application/octet-stream"

    logger.info(
        f"Scan submitted | id={document_id} | file={file_name!r} "
        f"| size={len(file_data)} | source={scan_source}"
    )

    return submit_processing_task(
        processor=processor,
        document_id=document_id,
        file_data=file_data,
        file_name=file_name,
        content_type=content_type,
        scan_source=scan_source,
    )


# ── GET /scan/{documentId} ────────────────────────────────────────────────────

@router.get(
    "/{document_id}",
    response_model=ScanDocumentRecord,
    summary="Get scan document status",
    description=(
        "Returns the current state of a scan job. "
        "Poll this endpoint when the async worker upgrade is applied — "
        "status will transition from `PENDING` → `PROCESSING` → `COMPLETED` (or `FAILED`)."
    ),
    responses={
        200: {"model": ScanDocumentRecord},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse, "description": "Document not found"},
        503: {"model": ErrorResponse},
    },
)
async def get_document(
    document_id: Annotated[str, Path(description="UUID returned by POST /scan/process")],
    _: str = Depends(verify_api_key),
    processor: DocumentProcessor = Depends(get_processor),
) -> ScanDocumentRecord:
    record = processor.get_document(document_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan document '{document_id}' not found.",
        )
    return record


# ── GET /scan/{documentId}/metadata ──────────────────────────────────────────

@router.get(
    "/{document_id}/metadata",
    response_model=ScanDocumentMetadata,
    summary="Get scan document metadata with OCR preview",
    description=(
        "Returns full document metadata plus the first 500 characters of the OCR-extracted text. "
        "The `ocr_preview` field is null when `ocr_status` is not `COMPLETED`."
    ),
    responses={
        200: {"model": ScanDocumentMetadata},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def get_document_metadata(
    document_id: Annotated[str, Path(description="UUID returned by POST /scan/process")],
    _: str = Depends(verify_api_key),
    processor: DocumentProcessor = Depends(get_processor),
) -> ScanDocumentMetadata:
    record = processor.get_document(document_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan document '{document_id}' not found.",
        )
    ocr_preview = processor.get_ocr_text(document_id, max_chars=500)
    return ScanDocumentMetadata(**record.model_dump(), ocr_preview=ocr_preview)
