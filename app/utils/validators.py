from fastapi import HTTPException, status

# 25 MB hard limit — matches MuleSoft Process API documented constraint
MAX_FILE_SIZE_BYTES: int = 25 * 1024 * 1024

# Allowed MIME types for document uploads
ALLOWED_MIME_TYPES: set[str] = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        # .xlsx
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation", # .pptx
    "image/jpeg",
    "image/png",
    "image/tiff",
    "text/plain",
    "text/csv",
    "application/zip",
    "application/octet-stream",  # generic binary — allowed as fallback
}


def validate_file_size(size_bytes: int) -> None:
    if size_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )
    if size_bytes > MAX_FILE_SIZE_BYTES:
        mb = size_bytes / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File size {mb:.2f} MB exceeds the maximum allowed size of "
                f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
            ),
        )


def validate_mime_type(content_type: str) -> None:
    # Strip charset suffix (e.g. "text/plain; charset=utf-8" → "text/plain")
    base_type = content_type.split(";")[0].strip().lower()
    if base_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Content type '{base_type}' is not allowed. "
                f"Allowed types: {sorted(ALLOWED_MIME_TYPES)}"
            ),
        )
