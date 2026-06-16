from fastapi import HTTPException, status


class DocumentNotFoundError(HTTPException):
    def __init__(self, object_name: str, bucket: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{object_name}' not found in bucket '{bucket}'.",
        )


class DocumentUploadError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {detail}",
        )


class DocumentDeleteError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Delete failed: {detail}",
        )


class BucketNotFoundError(HTTPException):
    def __init__(self, bucket: str):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Storage bucket '{bucket}' is not available.",
        )


class InvalidEntityTypeError(HTTPException):
    def __init__(self, entity_type: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid entity_type '{entity_type}'. Must be one of: contributors, beneficiaries, employees, temp.",
        )


class StorageConnectionError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Storage service unavailable: {detail}",
        )
