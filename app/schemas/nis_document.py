from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# ─── NIS document taxonomy ────────────────────────────────────────────────────

class NISDocumentType(str, Enum):
    """
    All document categories used by NIS.
    The value is used as the folder name inside MinIO:
    {entity_type}/{entity_id}/{NISDocumentType}/{filename}
    e.g.  contributors/U001/IDENTITY/passport.pdf
    """
    IDENTITY      = "IDENTITY"       # Passport, national ID, birth certificate
    CONTRACT      = "CONTRACT"       # Employment contract, contribution agreement
    CLAIM         = "CLAIM"          # Claim form, claim supporting documents
    BANK_DETAIL   = "BANK_DETAIL"    # Bank statement, account confirmation letter
    MEDICAL       = "MEDICAL"        # Medical report, doctor's certificate
    PAYROLL       = "PAYROLL"        # Payslip, P60, tax certificate
    CORRESPONDENCE = "CORRESPONDENCE" # Letters, notices, circulars from/to NIS
    LEGAL         = "LEGAL"          # Court orders, legal certificates
    DECLARATION   = "DECLARATION"    # Statutory declarations, affidavits
    OTHER         = "OTHER"          # Catch-all for uncategorised documents


class NISDocumentClass(str, Enum):
    """
    Describes the authenticity / origin of the document copy being stored.
    Required by NIS compliance rules.
    """
    ORIGINAL       = "ORIGINAL"        # The physical original was scanned / presented
    CERTIFIED_COPY = "CERTIFIED_COPY"  # Officially certified copy (notary, solicitor, etc.)
    SCAN           = "SCAN"            # Uncertified scan of a physical document
    DIGITAL        = "DIGITAL"         # Born-digital — never existed as a physical document


# ─── Upload response ──────────────────────────────────────────────────────────

class NISUploadResponse(BaseModel):
    """
    Complete response after a successful NIS document upload.

    Contains three groups of fields:
    1. Primary identifiers — doc_id (DB primary key), nis_id (business owner)
    2. Storage fields      — from MinIO (object_name, etag, version_id, size_bytes, uploaded_at)
    3. Business fields     — echoed from the form (entity context, MuleSoft traceability)

    MuleSoft / Salesforce must persist at minimum:
      doc_id               — to retrieve / delete the document by its unique ID
      nis_id               — to list all documents for this person later
      object_name + bucket — alternative retrieval address (MinIO path)
      etag                 — for integrity checks
      correlation_id       — to close the MuleSoft transaction
      salesforce_record_id — to link back to the originating SF record
    """

    # ── Primary NIS identifiers (NEW) ────────────────────────────────────────
    doc_id: str = Field(
        ...,
        description="Unique Document ID (DOC-XXXXXXXX). Store this in Salesforce for direct retrieval.",
        examples=["DOC-A3F4B2C1"],
    )
    nis_id: str = Field(
        ...,
        description="NIS person identifier this document is linked to.",
        examples=["NIS001"],
    )

    # ── Storage identifiers ──────────────────────────────────────────────────
    object_name: str = Field(
        ...,
        description="MinIO object key. STORE THIS in Salesforce — it is the retrieval address.",
        examples=["contributors/U001/IDENTITY/passport.pdf"],
    )
    bucket: str = Field(..., examples=["dms-contributors"])
    etag: str = Field(..., description="MD5 checksum of stored bytes — use for integrity checks.")
    version_id: Optional[str] = Field(
        None,
        description="MinIO version ID. Present when bucket versioning is enabled (always for NIS).",
    )
    size_bytes: int = Field(..., description="File size in bytes as received by MinIO.")
    content_type: str = Field(..., examples=["application/pdf"])
    uploaded_at: datetime = Field(..., description="UTC timestamp of the upload operation.")

    # ── NIS business context ─────────────────────────────────────────────────
    entity_type: str = Field(
        ...,
        description="The NIS entity bucket: contributors | beneficiaries | employees",
    )
    entity_id: str = Field(
        ...,
        description="Unique NIS entity identifier (contributor number, employee ID, etc.).",
        examples=["U001"],
    )
    document_type: NISDocumentType = Field(
        ...,
        description="NIS document category — determines the storage folder.",
    )
    document_class: NISDocumentClass = Field(
        ...,
        description="Authenticity classification of the document copy.",
    )

    # ── MuleSoft / Salesforce traceability ───────────────────────────────────
    correlation_id: str = Field(
        ...,
        description="MuleSoft correlation ID — propagate this through all downstream calls.",
        examples=["CORR-2024-ABC-00123"],
    )
    salesforce_record_id: str = Field(
        ...,
        description="Salesforce record ID this document is attached to.",
        examples=["a0B5g000004XXXEAA0"],
    )
    salesforce_object_type: Optional[str] = Field(
        None,
        description="Salesforce object type: Contact | Case | Account | Opportunity",
        examples=["Contact"],
    )
    uploaded_by: str = Field(
        ...,
        description="Salesforce user ID or system name that triggered the upload.",
        examples=["john.smith@nis.gov"],
    )

    # ── Optional document metadata ───────────────────────────────────────────
    description: Optional[str] = Field(None, description="Free-text description of the document.")
    expiry_date: Optional[str] = Field(
        None,
        description="ISO 8601 date (YYYY-MM-DD) if the document expires (e.g. passport).",
        examples=["2029-06-30"],
    )

    # ── Replacement result ───────────────────────────────────────────────────
    replaced: bool = Field(
        False,
        description="True when an existing document was replaced by this upload (replace=true was passed).",
    )
    replaced_doc_id: Optional[str] = Field(
        None,
        description="doc_id of the document that was overwritten, populated only when replaced=true.",
        examples=["DOC-B7E1C4D2"],
    )

    model_config = {"json_schema_extra": {"example": {
        "doc_id":                 "DOC-A3F4B2C1",
        "nis_id":                 "NIS001",
        "object_name":            "contributors/NIS001/IDENTITY/passport.pdf",
        "bucket":                 "dms-contributors",
        "etag":                   "d41d8cd98f00b204e9800998ecf8427e",
        "version_id":             "3e1a2b4c",
        "size_bytes":             204800,
        "content_type":           "application/pdf",
        "uploaded_at":            "2024-01-15T10:30:00Z",
        "entity_type":            "contributors",
        "entity_id":              "NIS001",
        "document_type":          "IDENTITY",
        "document_class":         "ORIGINAL",
        "correlation_id":         "CORR-2024-ABC-00123",
        "salesforce_record_id":   "a0B5g000004XXXEAA0",
        "salesforce_object_type": "Contact",
        "uploaded_by":            "john.smith@nis.gov",
        "description":            "Applicant passport — valid until 2029",
        "expiry_date":            "2029-06-30",
        "replaced":               False,
        "replaced_doc_id":        None,
    }}}


# ─── List response ────────────────────────────────────────────────────────────

class DocumentListItem(BaseModel):
    """One document entry in a listing response."""
    object_name: str = Field(..., description="Full MinIO object key for retrieval.")
    document_type: str = Field(..., description="NIS document category folder.")
    filename: str = Field(..., description="Original filename.")
    size_bytes: int
    etag: str
    last_modified: datetime
    version_id: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {
        "object_name":    "contributors/U001/IDENTITY/passport.pdf",
        "document_type":  "IDENTITY",
        "filename":       "passport.pdf",
        "size_bytes":     204800,
        "etag":           "abc123",
        "last_modified":  "2024-01-15T10:30:00Z",
        "version_id":     "v1",
    }}}


class DocumentListResponse(BaseModel):
    """Response from GET /documents/{entity_type}/{entity_id}."""
    entity_type: str
    entity_id: str
    bucket: str
    document_type_filter: Optional[str] = Field(
        None, description="The document_type query filter applied, if any."
    )
    total: int = Field(..., description="Number of documents returned (after any filter).")
    documents: list[DocumentListItem]

    model_config = {"json_schema_extra": {"example": {
        "entity_type":           "contributors",
        "entity_id":             "U001",
        "bucket":                "dms-contributors",
        "document_type_filter":  None,
        "total":                 2,
        "documents": [
            {
                "object_name":   "contributors/U001/IDENTITY/passport.pdf",
                "document_type": "IDENTITY",
                "filename":      "passport.pdf",
                "size_bytes":    204800,
                "etag":          "abc123",
                "last_modified": "2024-01-15T10:30:00Z",
                "version_id":    "v1",
            },
            {
                "object_name":   "contributors/U001/CONTRACT/employment_contract.pdf",
                "document_type": "CONTRACT",
                "filename":      "employment_contract.pdf",
                "size_bytes":    51200,
                "etag":          "def456",
                "last_modified": "2024-01-10T08:00:00Z",
                "version_id":    "v1",
            },
        ],
    }}}
