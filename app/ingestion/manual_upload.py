"""
Manual upload ingestion — wraps a FastAPI UploadFile.

This is the active implementation used by POST /scan/process and POST /scan/bulk.
When IBML integration is ready, those endpoints will switch to IBMLIngestion
while the rest of the pipeline stays unchanged.
"""
from __future__ import annotations

from fastapi import UploadFile

from app.ingestion.base_ingestion import BaseIngestion, IngestionDocument


class ManualUploadIngestion(BaseIngestion):
    """
    Ingestion from a FastAPI multipart file upload.

    Usage:
        ingestion = ManualUploadIngestion(file=upload_file, source_name="IBML_SIMULATED")
        doc = await ingestion.to_document()
    """

    def __init__(self, file: UploadFile, source_name: str = "IBML_SIMULATED") -> None:
        self._file = file
        self._source_name = source_name

    @property
    def source_name(self) -> str:
        return self._source_name

    async def to_document(self) -> IngestionDocument:
        file_data = await self._file.read()
        raw_ct = self._file.content_type or "application/octet-stream"
        content_type = raw_ct.split(";")[0].strip().lower()
        return IngestionDocument(
            file_data=file_data,
            file_name=self._file.filename or "unknown",
            content_type=content_type,
            source_name=self._source_name,
            file_size_bytes=len(file_data),
        )
