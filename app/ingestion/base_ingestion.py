"""
Base ingestion interface.

All document sources (manual upload, IBML scanner, SFTP drop, etc.)
implement this interface so the rest of the pipeline is source-agnostic.

Flow:
  AnyIngestion → to_document() → IngestionDocument → DocumentProcessor
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class IngestionDocument:
    """Normalised representation of a document received from any source."""
    file_data:       bytes
    file_name:       str
    content_type:    str
    source_name:     str  # e.g. "IBML_SIMULATED", "IBML_SCANNER", "IBML_SFTP"
    file_size_bytes: int


class BaseIngestion(ABC):
    """
    Abstract base for all ingestion sources.

    Implementors:
      ManualUploadIngestion  — FastAPI UploadFile (current)
      IBMLIngestion          — IBML scanner hardware (placeholder)

    Contract:
      to_document() must return an IngestionDocument with:
        - file_data populated (non-empty bytes)
        - content_type normalised (lower-case, no params, e.g. "image/pdf")
        - source_name set to self.source_name
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Short identifier for this source. Stored in scan metadata."""

    @abstractmethod
    async def to_document(self) -> IngestionDocument:
        """
        Read / fetch the document and return a normalised IngestionDocument.
        May be async because some sources involve network I/O.
        """
