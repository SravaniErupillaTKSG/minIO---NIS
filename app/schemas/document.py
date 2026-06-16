from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class DocumentUploadResponse(BaseModel):
    """Returned after a successful document upload."""
    object_name: str = Field(..., description="Unique object key in MinIO (e.g. contracts/2024/doc.pdf)")
    bucket: str = Field(..., description="MinIO bucket where the file is stored")
    entity_type: str = Field(..., description="Logical owner: contributors | beneficiaries | employees | temp")
    content_type: str = Field(..., description="MIME type of the uploaded file")
    size_bytes: int = Field(..., description="File size in bytes")
    etag: str = Field(..., description="MinIO ETag (MD5 of content)")
    uploaded_at: datetime = Field(..., description="UTC timestamp of upload")
    version_id: Optional[str] = Field(None, description="MinIO version ID (when versioning is enabled)")

    model_config = {"json_schema_extra": {
        "example": {
            "object_name": "contributors/U001/identity/passport.pdf",
            "bucket": "dms-contributors",
            "entity_type": "contributors",
            "content_type": "application/pdf",
            "size_bytes": 204800,
            "etag": "d41d8cd98f00b204e9800998ecf8427e",
            "uploaded_at": "2024-01-15T10:30:00Z",
            "version_id": "3e1a2b4c"
        }
    }}


class DocumentMetadata(BaseModel):
    """Object metadata returned from MinIO stat."""
    object_name: str
    bucket: str
    size_bytes: int
    content_type: str
    etag: str
    last_modified: datetime
    version_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

    model_config = {"json_schema_extra": {
        "example": {
            "object_name": "employees/E001/contracts/offer_letter.docx",
            "bucket": "dms-employees",
            "size_bytes": 51200,
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "etag": "abc123",
            "last_modified": "2024-01-10T08:00:00Z",
            "version_id": "1a2b3c",
            "metadata": {"uploaded_by": "HR_SYSTEM", "document_type": "OFFER_LETTER"}
        }
    }}


class PresignedUrlResponse(BaseModel):
    """Presigned URL for direct browser upload or download."""
    url: str = Field(..., description="Presigned URL — valid for expiry_seconds")
    object_name: str
    bucket: str
    expiry_seconds: int = Field(..., description="Seconds until the URL expires")
    method: str = Field(..., description="HTTP method this URL is valid for: GET | PUT")

    model_config = {"json_schema_extra": {
        "example": {
            "url": "http://localhost:9000/dms-contributors/contributors/U001/passport.pdf?X-Amz-Signature=...",
            "object_name": "contributors/U001/passport.pdf",
            "bucket": "dms-contributors",
            "expiry_seconds": 3600,
            "method": "GET"
        }
    }}


class DocumentDeleteResponse(BaseModel):
    """Returned after a successful delete."""
    object_name: str
    bucket: str
    deleted: bool = True
    message: str

    model_config = {"json_schema_extra": {
        "example": {
            "object_name": "beneficiaries/B001/claim/claim_form.pdf",
            "bucket": "dms-beneficiaries",
            "deleted": True,
            "message": "Document deleted successfully."
        }
    }}


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    storage: str
    buckets: dict[str, str]

    model_config = {"json_schema_extra": {
        "example": {
            "status": "healthy",
            "service": "DMS Document Service",
            "version": "1.0.0",
            "storage": "connected",
            "buckets": {
                "dms-contributors": "ok",
                "dms-beneficiaries": "ok",
                "dms-employees": "ok",
                "dms-temp": "ok"
            }
        }
    }}


class ErrorResponse(BaseModel):
    detail: str

    model_config = {"json_schema_extra": {
        "example": {"detail": "Document 'passport.pdf' not found in bucket 'dms-contributors'."}
    }}
