from typing import Optional, Annotated
from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile, status
from fastapi.responses import Response
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import get_settings, Settings
from app.core.database import get_db
from app.core.exceptions import InvalidEntityTypeError
from app.core.security import verify_api_key
from app.repositories.document_metadata_repository import DocumentMetadataRepository
from app.repositories.nis_repository import NISRepository
from app.schemas.document import (
    DocumentMetadata,
    DocumentDeleteResponse,
    ErrorResponse,
    PresignedUrlResponse,
)
from app.schemas.nis_document import (
    NISDocumentType,
    NISDocumentClass,
    NISUploadResponse,
    DocumentListResponse,
    DocumentListItem,
)
from app.services.minio_service import MinIOService, get_minio_service
from app.services.nis_service import generate_doc_id
from app.utils.validators import validate_file_size, validate_mime_type

router = APIRouter(prefix="/documents", tags=["Documents"])

VALID_ENTITY_TYPES = ["contributors", "beneficiaries", "employees", "temp"]


def _resolve_bucket(entity_type: str, settings: Settings) -> str:
    """Map entity_type to its MinIO bucket name, raise 400 if unrecognised."""
    if entity_type.lower() not in VALID_ENTITY_TYPES:
        raise InvalidEntityTypeError(entity_type)
    return settings.get_bucket(entity_type)


# ─── Upload ───────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=NISUploadResponse,
    status_code=201,
    summary="Upload a document",
    description="""
Upload a document for a specific NIS entity.

**Object stored at:** `{entity_type}/{entity_id}/{document_type}/{filename}`
Example: `contributors/U001/IDENTITY/passport.pdf`

**MuleSoft must send:**
- `correlation_id` — the MuleSoft correlation ID for end-to-end tracing
- `salesforce_record_id` — the SF object ID to link this document to
- `uploaded_by` — the Salesforce user or system name

**Salesforce must persist from the response:**
- `object_name` — the retrieval address
- `etag` — for integrity checks
- `version_id` — for versioned access
""",
    responses={
        201: {"model": NISUploadResponse},
        400: {"model": ErrorResponse, "description": "Invalid entity_type or empty file"},
        401: {"model": ErrorResponse, "description": "Missing API key"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
        409: {"description": "File already exists — pass replace=true to overwrite"},
        413: {"model": ErrorResponse, "description": "File exceeds 25 MB limit"},
        415: {"model": ErrorResponse, "description": "Unsupported MIME type"},
        422: {"description": "Validation error — invalid document_type or document_class enum value"},
        500: {"model": ErrorResponse, "description": "Upload failed"},
        503: {"model": ErrorResponse, "description": "Storage unavailable"},
    },
)
async def upload_document(
    # ── Required fields — NO Python default, so they come first ──────────
    # FastAPI 0.136.x has a serialization bug when required form fields use
    # `= ...` and the field is missing: jsonable_encoder crashes on Ellipsis.
    # Declaring required params without any default avoids this entirely and
    # is also the cleaner Python style.
    file: Annotated[UploadFile, File(description="Document file to upload")],
    nis_id: Annotated[str, Form(
        description="NIS person identifier (must be registered via POST /api/v1/nis/register first)"
    )],
    entity_type: Annotated[str, Form(
        description="NIS entity bucket: `contributors` | `beneficiaries` | `employees` | `temp`"
    )],
    document_type: Annotated[NISDocumentType, Form(
        description=(
            "NIS document category. Must be one of: "
            "IDENTITY | CONTRACT | CLAIM | BANK_DETAIL | MEDICAL | "
            "PAYROLL | CORRESPONDENCE | LEGAL | DECLARATION | OTHER"
        )
    )],
    correlation_id: Annotated[str, Form(
        description="MuleSoft correlation ID — required for end-to-end request tracing"
    )],
    salesforce_record_id: Annotated[str, Form(
        description="Salesforce record ID this document belongs to"
    )],
    uploaded_by: Annotated[str, Form(
        description="Salesforce user ID or system name that triggered the upload"
    )],

    # ── Optional fields — have Python defaults, so they come after ────────
    document_class: Annotated[NISDocumentClass, Form(
        description="Authenticity classification: ORIGINAL | CERTIFIED_COPY | SCAN | DIGITAL"
    )] = NISDocumentClass.ORIGINAL,
    salesforce_object_type: Annotated[Optional[str], Form(
        description="Salesforce object type: Contact | Case | Account | Opportunity"
    )] = None,
    description: Annotated[Optional[str], Form(
        description="Free-text description of the document"
    )] = None,
    expiry_date: Annotated[Optional[str], Form(
        description="ISO 8601 date (YYYY-MM-DD) if the document expires (e.g. passport)"
    )] = None,
    replace: Annotated[bool, Form(
        description=(
            "Pass true to overwrite an existing document with the same filename, "
            "NIS ID, and document type. Without this flag a duplicate returns 409."
        )
    )] = False,

    # ── Dependencies ──────────────────────────────────────────────────────
    _: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
    svc: MinIOService = Depends(get_minio_service),
    db: Session = Depends(get_db),
) -> NISUploadResponse:

    # ── 1. Validate NIS ID exists before touching MinIO ───────────────────
    nis_repo = NISRepository(db)
    doc_repo = DocumentMetadataRepository(db)
    if not nis_repo.exists(nis_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"NIS ID '{nis_id}' is not registered. "
                f"Call POST /api/v1/nis/register first."
            ),
        )

    # ── 2. Duplicate detection ────────────────────────────────────────────
    # Only meaningful when a filename is present (nameless uploads are always unique).
    replaced_doc_id: Optional[str] = None
    if file.filename:
        existing = doc_repo.find_active_duplicate(
            nis_id=nis_id,
            document_type=document_type.value,
            file_name=file.filename,
        )
        if existing and not replace:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        f"A document named '{file.filename}' already exists for "
                        f"NIS ID '{nis_id}' under document type '{document_type.value}'."
                    ),
                    "existing_doc_id": existing.doc_id,
                    "uploaded_at": (
                        existing.uploaded_at.isoformat()
                        if existing.uploaded_at else None
                    ),
                    "hint": "Pass replace=true in the form to overwrite the existing document.",
                },
            )
        if existing and replace:
            replaced_doc_id = existing.doc_id
            doc_repo.soft_delete(existing.doc_id)
            try:
                svc.delete_document(
                    bucket=existing.bucket_name,
                    object_name=existing.object_path,
                )
            except Exception as exc:
                logger.warning(
                    f"MinIO delete marker failed for replaced doc {existing.doc_id}: {exc}"
                )
            logger.info(
                f"Replacing document | old_doc_id={existing.doc_id} | nis_id={nis_id}"
            )

    # ── 3. Validate file before touching MinIO ────────────────────────────
    # file.size is set by Starlette's multipart parser — no need to read the file.
    validate_file_size(file.size or 0)
    validate_mime_type(file.content_type or "application/octet-stream")

    # ── 3. Generate unique identifiers ────────────────────────────────────
    doc_id       = generate_doc_id()          # DOC-XXXXXXXX
    bucket       = _resolve_bucket(entity_type, settings)
    # nis_id is now the entity identifier in the MinIO path
    object_name  = f"{entity_type}/{nis_id}/{document_type.value}/{file.filename}"
    content_type = file.content_type or "application/octet-stream"

    logger.info(
        f"Upload | doc_id={doc_id} | nis_id={nis_id} | corr={correlation_id} | "
        f"sf={salesforce_record_id} | entity={entity_type} | "
        f"doc_type={document_type.value} | file={file.filename} | size={file.size}"
    )

    # ── 4. Build MinIO metadata (stored as x-amz-meta-* headers) ─────────
    metadata = {
        "doc_id":                 doc_id,
        "nis_id":                 nis_id,
        "document_type":          document_type.value,
        "document_class":         document_class.value,
        "correlation_id":         correlation_id,
        "salesforce_record_id":   salesforce_record_id,
        "uploaded_by":            uploaded_by,
    }
    if salesforce_object_type:
        metadata["salesforce_object_type"] = salesforce_object_type
    if description:
        metadata["description"] = description
    if expiry_date:
        metadata["expiry_date"] = expiry_date

    # ── 5. Stream directly to MinIO — file.file is never fully read into RAM
    file.file.seek(0)  # Defensive: ensure stream is at start
    storage = svc.upload_document(
        bucket=bucket,
        object_name=object_name,
        file_data=file.file,    # BinaryIO stream — no in-memory copy
        file_size=file.size or 0,
        content_type=content_type,
        metadata=metadata,
    )

    # ── 6. Persist metadata to SQLite (after successful MinIO upload) ─────
    doc_repo.create(
        doc_id=doc_id,
        nis_id=nis_id,
        file_name=file.filename or doc_id,
        document_type=document_type.value,
        document_class=document_class.value,
        bucket_name=bucket,
        object_path=object_name,
        content_type=content_type,
        file_size_bytes=file.size or 0,
        uploaded_by=uploaded_by,
        correlation_id=correlation_id,
        salesforce_record_id=salesforce_record_id,
        salesforce_object_type=salesforce_object_type,
        description=description,
        expiry_date=expiry_date,
        etag=storage.etag,
        version_id=storage.version_id,
    )

    # ── 7. Assemble NIS response ──────────────────────────────────────────
    return NISUploadResponse(
        # Primary NIS identifiers (NEW)
        doc_id=doc_id,
        nis_id=nis_id,
        # Storage fields (from MinIO)
        object_name=storage.object_name,
        bucket=storage.bucket,
        etag=storage.etag,
        version_id=storage.version_id,
        size_bytes=storage.size_bytes,
        content_type=content_type,
        uploaded_at=storage.uploaded_at,
        # NIS business fields (from form)
        entity_type=entity_type,
        entity_id=nis_id,          # entity_id = nis_id (NIS ID is the entity identifier)
        document_type=document_type,
        document_class=document_class,
        correlation_id=correlation_id,
        salesforce_record_id=salesforce_record_id,
        salesforce_object_type=salesforce_object_type,
        uploaded_by=uploaded_by,
        description=description,
        expiry_date=expiry_date,
        replaced=replaced_doc_id is not None,
        replaced_doc_id=replaced_doc_id,
    )


# ─── Download ─────────────────────────────────────────────────────────────────

@router.get(
    "/download/{entity_type}/{entity_id}/{document_type}/{filename}",
    summary="Download a document (binary stream)",
    description=(
        "Returns raw file bytes. The `Content-Disposition: attachment` header causes "
        "browsers to download rather than display the file."
    ),
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "File bytes"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def download_document(
    entity_type:   Annotated[str, Path(description="contributors | beneficiaries | employees | temp")],
    entity_id:     Annotated[str, Path(description="Entity ID")],
    document_type: Annotated[str, Path(description="NIS document type folder (e.g. IDENTITY)")],
    filename:      Annotated[str, Path(description="Filename")],
    _: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
    svc: MinIOService = Depends(get_minio_service),
) -> Response:
    bucket      = _resolve_bucket(entity_type, settings)
    object_name = f"{entity_type}/{entity_id}/{document_type}/{filename}"
    logger.info(f"Download | bucket={bucket} | object={object_name}")
    data, content_type = svc.download_document(bucket=bucket, object_name=object_name)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Metadata ─────────────────────────────────────────────────────────────────

@router.get(
    "/metadata/{entity_type}/{entity_id}/{document_type}/{filename}",
    response_model=DocumentMetadata,
    summary="Get document metadata",
    description=(
        "Returns object metadata (size, content-type, ETag, MinIO version, and all "
        "custom x-amz-meta-* fields) without downloading the file bytes. "
        "Salesforce can call this to verify a document was stored correctly after upload."
    ),
    responses={
        200: {"model": DocumentMetadata},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def get_document_metadata(
    entity_type:   Annotated[str, Path()],
    entity_id:     Annotated[str, Path()],
    document_type: Annotated[str, Path()],
    filename:      Annotated[str, Path()],
    _: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
    svc: MinIOService = Depends(get_minio_service),
) -> DocumentMetadata:
    bucket      = _resolve_bucket(entity_type, settings)
    object_name = f"{entity_type}/{entity_id}/{document_type}/{filename}"
    return svc.get_document_metadata(bucket=bucket, object_name=object_name)


# ─── Delete ───────────────────────────────────────────────────────────────────

@router.delete(
    "/{entity_type}/{entity_id}/{document_type}/{filename}",
    response_model=DocumentDeleteResponse,
    summary="Delete a document",
    description=(
        "Removes the object from MinIO. Because versioning is enabled on all NIS buckets, "
        "this adds a *delete marker* — the bytes are not permanently destroyed. "
        "Prior versions remain accessible via the MinIO Console."
    ),
    responses={
        200: {"model": DocumentDeleteResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def delete_document(
    entity_type:   Annotated[str, Path()],
    entity_id:     Annotated[str, Path()],
    document_type: Annotated[str, Path()],
    filename:      Annotated[str, Path()],
    _: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
    svc: MinIOService = Depends(get_minio_service),
) -> DocumentDeleteResponse:
    bucket      = _resolve_bucket(entity_type, settings)
    object_name = f"{entity_type}/{entity_id}/{document_type}/{filename}"
    logger.info(f"Delete | bucket={bucket} | object={object_name}")
    svc.delete_document(bucket=bucket, object_name=object_name)
    return DocumentDeleteResponse(
        object_name=object_name,
        bucket=bucket,
        deleted=True,
        message="Document deleted successfully.",
    )


# ─── Presigned Download URL ───────────────────────────────────────────────────

@router.get(
    "/presigned/download/{entity_type}/{entity_id}/{document_type}/{filename}",
    response_model=PresignedUrlResponse,
    summary="Generate presigned download URL",
    description=(
        "Returns a time-limited URL that allows a Salesforce user's browser to download "
        "the file **directly from MinIO** without routing through this API or requiring "
        "an API key. The URL embeds a signed credential that expires after "
        "`MINIO_PRESIGNED_EXPIRY` seconds (default: 1 hour)."
    ),
    responses={
        200: {"model": PresignedUrlResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def presigned_download_url(
    entity_type:   Annotated[str, Path()],
    entity_id:     Annotated[str, Path()],
    document_type: Annotated[str, Path()],
    filename:      Annotated[str, Path()],
    _: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
    svc: MinIOService = Depends(get_minio_service),
) -> PresignedUrlResponse:
    bucket      = _resolve_bucket(entity_type, settings)
    object_name = f"{entity_type}/{entity_id}/{document_type}/{filename}"
    return svc.generate_presigned_download_url(bucket=bucket, object_name=object_name)


# ─── Presigned Upload URL ─────────────────────────────────────────────────────

@router.get(
    "/presigned/upload/{entity_type}/{entity_id}/{document_type}/{filename}",
    response_model=PresignedUrlResponse,
    summary="Generate presigned upload URL",
    description=(
        "Returns a time-limited PUT URL so a Salesforce portal user can upload a large "
        "file **directly to MinIO** — the file never passes through this API server. "
        "Recommended for files > 25 MB. After the PUT completes, call `GET /metadata/...` "
        "to confirm the upload and retrieve the ETag."
    ),
    responses={
        200: {"model": PresignedUrlResponse},
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def presigned_upload_url(
    entity_type:   Annotated[str, Path()],
    entity_id:     Annotated[str, Path()],
    document_type: Annotated[str, Path()],
    filename:      Annotated[str, Path()],
    _: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
    svc: MinIOService = Depends(get_minio_service),
) -> PresignedUrlResponse:
    bucket      = _resolve_bucket(entity_type, settings)
    object_name = f"{entity_type}/{entity_id}/{document_type}/{filename}"
    return svc.generate_presigned_upload_url(bucket=bucket, object_name=object_name)


# ─── List Documents ───────────────────────────────────────────────────────────
# IMPORTANT: this route is defined LAST.
# FastAPI resolves routes top-to-bottom. Defining /{entity_type}/{entity_id} last
# ensures the literal-prefix routes above (/download/, /metadata/, /presigned/)
# always take priority and are never captured by this variable-segment route.

@router.get(
    "/{entity_type}/{entity_id}",
    response_model=DocumentListResponse,
    summary="List documents for an entity",
    description=(
        "Returns all documents stored under `{entity_type}/{entity_id}/` in MinIO. "
        "Salesforce can call this to populate a document history panel for a Contact, "
        "Case, or Account record. "
        "Use the optional `document_type` query parameter to filter by NIS document category."
    ),
    responses={
        200: {"model": DocumentListResponse},
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def list_documents(
    entity_type: Annotated[str, Path(description="contributors | beneficiaries | employees | temp")],
    entity_id:   Annotated[str, Path(description="Entity ID")],
    document_type: Annotated[Optional[NISDocumentType], Query(
        description="Filter by NIS document type (optional)"
    )] = None,
    _: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
    svc: MinIOService = Depends(get_minio_service),
) -> DocumentListResponse:
    bucket = _resolve_bucket(entity_type, settings)
    items: list[DocumentListItem] = svc.list_documents(
        bucket=bucket,
        entity_type=entity_type,
        entity_id=entity_id,
    )

    # Optional client-side filter by document type
    if document_type:
        items = [i for i in items if i.document_type == document_type.value]

    logger.info(
        f"List | entity={entity_type}/{entity_id} | filter={document_type} | count={len(items)}"
    )
    return DocumentListResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        bucket=bucket,
        document_type_filter=document_type.value if document_type else None,
        total=len(items),
        documents=items,
    )
