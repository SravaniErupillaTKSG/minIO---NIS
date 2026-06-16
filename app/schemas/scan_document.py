"""
Pydantic models for the Scan / OCR pipeline (Scenario 1).

Separation from app/models/scan_document.py (SQLAlchemy):
  - These are the objects that cross the service boundary (API response, repository output)
  - SQLAlchemy models live only inside the repository layer
  - Everything outside repositories works with these Pydantic models
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class OCRStatus(str, Enum):
    """Lifecycle states of a scan document through the OCR pipeline."""
    PENDING    = "PENDING"     # Queued, not yet picked up by a worker
    PROCESSING = "PROCESSING"  # Worker has started OCR extraction
    COMPLETED  = "COMPLETED"   # OCR done, text stored in MinIO
    FAILED     = "FAILED"      # OCR failed — see error_message


class ScanDocumentCreate(BaseModel):
    """Internal model used to create a new document record in the repository."""
    document_id:       str
    file_name:         str
    upload_time:       datetime
    ocr_status:        OCRStatus
    document_location: str
    content_type:      str
    file_size_bytes:   int
    scan_source:       str
    ocr_text_location: Optional[str] = None
    error_message:     Optional[str] = None


class ScanDocumentRecord(BaseModel):
    """
    Canonical transfer object returned by the repository and the API.
    Has no SQLAlchemy session attached — safe to pass across layer boundaries.
    """
    document_id: str = Field(
        ...,
        description="UUID identifying this scan job.",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )
    file_name: str = Field(..., description="Original filename as submitted.")
    upload_time: datetime = Field(..., description="UTC timestamp when the file was received.")
    ocr_status: OCRStatus = Field(..., description="Current status in the OCR pipeline.")
    document_location: str = Field(
        ...,
        description="MinIO path of the original scanned file: `{bucket}/{year}/{month}/{id}.ext`",
        examples=["scanned-documents/2024/06/3fa85f64.pdf"],
    )
    ocr_text_location: Optional[str] = Field(
        None,
        description="MinIO path of the extracted OCR text: `{bucket}/{year}/{month}/{id}.txt`",
        examples=["ocr-output/2024/06/3fa85f64.txt"],
    )
    content_type:    str = Field(..., examples=["application/pdf"])
    file_size_bytes: int = Field(..., description="File size in bytes.")
    error_message:   Optional[str] = Field(None, description="Set when ocr_status=FAILED.")
    scan_source:     str = Field(
        ...,
        description="System that submitted the scan. `IBML_SIMULATED` for local dev.",
        examples=["IBML_SIMULATED", "IBML_SCANNER"],
    )

    model_config = {"from_attributes": True}


class ScanDocumentMetadata(ScanDocumentRecord):
    """
    Extended response from GET /scan/{documentId}/metadata.
    Includes the first 500 characters of OCR-extracted text as a preview.
    """
    ocr_preview: Optional[str] = Field(
        None,
        description=(
            "First 500 characters of the OCR-extracted text. "
            "Null when status is not COMPLETED or the OCR text cannot be retrieved."
        ),
    )

    model_config = {"from_attributes": True, "json_schema_extra": {"example": {
        "document_id":       "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "file_name":         "claim_form_U001.pdf",
        "upload_time":       "2024-06-15T09:30:00Z",
        "ocr_status":        "COMPLETED",
        "document_location": "scanned-documents/2024/06/3fa85f64.pdf",
        "ocr_text_location": "ocr-output/2024/06/3fa85f64.txt",
        "content_type":      "application/pdf",
        "file_size_bytes":   204800,
        "error_message":     None,
        "scan_source":       "IBML_SIMULATED",
        "ocr_preview":       "NATIONAL INSURANCE SCHEME\nCLAIM FORM\nContributor ID: U001\n...",
    }}}


# ── Async status endpoint ─────────────────────────────────────────────────────

class ScanStatusResponse(BaseModel):
    """
    Lightweight response from GET /scan/{documentId}/status.
    Designed for polling — smaller payload than the full ScanDocumentRecord.
    """
    document_id:        str       = Field(..., description="Document UUID.")
    ocr_status:         OCRStatus = Field(..., description="Current pipeline status.")
    upload_time:        datetime  = Field(..., description="UTC timestamp when file was received.")
    error_message:      Optional[str] = Field(None, description="Set when ocr_status=FAILED.")
    ocr_text_available: bool = Field(
        False,
        description="True when ocr_status=COMPLETED and OCR text is stored in MinIO.",
    )


# ── Bulk processing ───────────────────────────────────────────────────────────

class BulkScanItem(BaseModel):
    """Per-file result in a bulk submission response."""
    document_id: Optional[str]  = Field(None, description="UUID assigned to this document. Null if rejected.")
    file_name:   str             = Field(..., description="Original filename.")
    ocr_status:  OCRStatus       = Field(OCRStatus.PENDING, description="PENDING (queued) or FAILED (validation error).")
    error:       Optional[str]   = Field(None, description="Validation error if this file was rejected before queuing.")


class BulkScanResponse(BaseModel):
    """
    Response from POST /scan/bulk.
    All accepted documents are queued immediately (status=PENDING).
    Poll GET /scan/{documentId}/status for each document_id.
    """
    documents: List[BulkScanItem] = Field(..., description="One item per uploaded file.")
    total:     int = Field(..., description="Total files submitted.")
    queued:    int = Field(..., description="Files accepted and queued for OCR.")
    rejected:  int = Field(..., description="Files rejected due to validation errors.")
