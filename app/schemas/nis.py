"""
Pydantic schemas for NIS person registration and document lookup.

Follows the same pattern as nis_document.py:
  - Request schemas describe what the client sends.
  - Response schemas describe what the API returns.
  - All response schemas are read-only (fields are computed, not editable).

Key design:
  - NISDocumentItem includes a download_url generated on-the-fly by the endpoint
    (presigned MinIO URL). It is Optional because it may fail if MinIO is unavailable.
  - NISWithDocumentsResponse is the "rich" lookup — it embeds the full document list
    so one API call gives Salesforce everything it needs to render a document panel.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ── Entity type values accepted by the NIS system ────────────────────────────

NIS_ENTITY_TYPES = Literal["CONTRIBUTOR", "BENEFICIARY", "EMPLOYEE"]


# ─── Request schemas ──────────────────────────────────────────────────────────

class NISRegisterRequest(BaseModel):
    """
    Body for POST /api/v1/nis/register.

    nis_id must be unique — the API returns 409 if it already exists.
    """
    nis_id:      str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Unique NIS person identifier assigned by the business (e.g. NIS001).",
        examples=["NIS001"],
    )
    person_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full legal name of the person.",
        examples=["John Doe"],
    )
    entity_type: NIS_ENTITY_TYPES = Field(
        ...,
        description="Person category: CONTRIBUTOR | BENEFICIARY | EMPLOYEE",
        examples=["CONTRIBUTOR"],
    )

    model_config = {"json_schema_extra": {"example": {
        "nis_id":      "NIS001",
        "person_name": "John Doe",
        "entity_type": "CONTRIBUTOR",
    }}}


# ─── Response schemas ─────────────────────────────────────────────────────────

class NISPersonResponse(BaseModel):
    """NIS person record — returned by register and get-by-id."""
    nis_id:         str
    person_name:    str
    entity_type:    str
    created_at:     datetime
    document_count: int = Field(default=0, description="Number of active (non-deleted) documents.")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {"example": {
            "nis_id":         "NIS001",
            "person_name":    "John Doe",
            "entity_type":    "CONTRIBUTOR",
            "created_at":     "2024-01-15T10:00:00Z",
            "document_count": 3,
        }},
    }


class NISDocumentItem(BaseModel):
    """
    One document record returned inside a NIS document list.

    download_url is a MinIO presigned GET URL valid for MINIO_PRESIGNED_EXPIRY seconds.
    It is None if MinIO is unavailable at the time of the request.
    """
    doc_id:                str
    nis_id:                str
    file_name:             str
    document_type:         str
    document_class:        str
    bucket_name:           str
    object_path:           str
    content_type:          Optional[str]  = None
    file_size_bytes:       Optional[int]  = None
    uploaded_by:           Optional[str]  = None
    correlation_id:        Optional[str]  = None
    salesforce_record_id:  Optional[str]  = None
    salesforce_object_type: Optional[str] = None
    description:           Optional[str]  = None
    expiry_date:           Optional[str]  = None
    etag:                  Optional[str]  = None
    version_id:            Optional[str]  = None
    uploaded_at:           datetime
    is_deleted:            bool           = False
    download_url:          Optional[str]  = Field(
        None,
        description="MinIO presigned download URL. Valid for MINIO_PRESIGNED_EXPIRY seconds.",
    )

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {"example": {
            "doc_id":               "DOC-A3F4B2C1",
            "nis_id":               "NIS001",
            "file_name":            "passport.pdf",
            "document_type":        "IDENTITY",
            "document_class":       "ORIGINAL",
            "bucket_name":          "dms-contributors",
            "object_path":          "contributors/NIS001/IDENTITY/passport.pdf",
            "content_type":         "application/pdf",
            "file_size_bytes":      204800,
            "uploaded_by":          "john.smith@nis.gov",
            "correlation_id":       "CORR-2024-ABC-00123",
            "salesforce_record_id": "a0B5g000004XXXEAA0",
            "uploaded_at":          "2024-01-15T10:30:00Z",
            "is_deleted":           False,
            "download_url":         "https://minio.example.com/...?X-Amz-Signature=...",
        }},
    }


class NISWithDocumentsResponse(BaseModel):
    """
    Full NIS lookup response: person details + complete document list.

    Returned by GET /api/v1/nis/{nis_id} and GET /api/v1/nis/{nis_id}/documents.
    Gives Salesforce everything it needs in a single API call to render the
    document history panel for a Contact / Case record.
    """
    nis_id:          str
    person_name:     str
    entity_type:     str
    created_at:      datetime
    total_documents: int  = Field(..., description="Count of active (non-deleted) documents.")
    documents:       List[NISDocumentItem]

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {"example": {
            "nis_id":          "NIS001",
            "person_name":     "John Doe",
            "entity_type":     "CONTRIBUTOR",
            "created_at":      "2024-01-15T10:00:00Z",
            "total_documents": 2,
            "documents": [
                {
                    "doc_id":         "DOC-A3F4B2C1",
                    "nis_id":         "NIS001",
                    "file_name":      "passport.pdf",
                    "document_type":  "IDENTITY",
                    "document_class": "ORIGINAL",
                    "bucket_name":    "dms-contributors",
                    "object_path":    "contributors/NIS001/IDENTITY/passport.pdf",
                    "file_size_bytes": 204800,
                    "uploaded_at":    "2024-01-15T10:30:00Z",
                    "is_deleted":     False,
                    "download_url":   "https://minio.example.com/signed-url",
                },
                {
                    "doc_id":         "DOC-B7E1C4D2",
                    "nis_id":         "NIS001",
                    "file_name":      "contract.pdf",
                    "document_type":  "CONTRACT",
                    "document_class": "ORIGINAL",
                    "bucket_name":    "dms-contributors",
                    "object_path":    "contributors/NIS001/CONTRACT/contract.pdf",
                    "file_size_bytes": 51200,
                    "uploaded_at":    "2024-01-16T09:00:00Z",
                    "is_deleted":     False,
                    "download_url":   "https://minio.example.com/signed-url-2",
                },
            ],
        }},
    }


class NISDocumentDetailResponse(NISDocumentItem):
    """
    Single document response — returned by GET /api/v1/documents/{doc_id}.
    Identical to NISDocumentItem but semantically represents a single-record fetch.
    """
    pass


class NISDocumentDeleteResponse(BaseModel):
    """Response after a successful soft-delete of a document."""
    doc_id:    str
    nis_id:    str
    deleted:   bool = True
    deleted_at: datetime
    message:   str  = "Document soft-deleted successfully."

    model_config = {"json_schema_extra": {"example": {
        "doc_id":     "DOC-A3F4B2C1",
        "nis_id":     "NIS001",
        "deleted":    True,
        "deleted_at": "2024-06-12T14:30:00Z",
        "message":    "Document soft-deleted successfully.",
    }}}
