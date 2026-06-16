"""
OCR Service — text extraction from scanned documents.

Supported inputs:
  - PDF  (via pdf2image: poppler converts pages to PIL images, then pytesseract reads them)
  - JPEG, PNG, TIFF  (via PIL → pytesseract directly)

Tesseract installation:
  Linux (Docker): apt-get install tesseract-ocr poppler-utils
  Windows (local): https://github.com/UB-Mannheim/tesseract/wiki
                   Also: pip install poppler-utils or add poppler/bin to PATH

If tesseract is not installed, OCR processing will fail with a clear error message.
The document will still be stored in MinIO (status=FAILED); the error is recorded in metadata.
"""
import io
from typing import Optional

from loguru import logger

try:
    import pytesseract
    from PIL import Image
    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_AVAILABLE = False

try:
    from pdf2image import convert_from_bytes
    _PDF2IMAGE_AVAILABLE = True
except ImportError:
    _PDF2IMAGE_AVAILABLE = False


# MIME types this service can process
SUPPORTED_OCR_MIME_TYPES: set[str] = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/tiff",
    "image/tif",
}


class OCRServiceError(Exception):
    """Raised when OCR processing fails for a recoverable reason (logged, stored as FAILED)."""


class OCRService:
    """
    Stateless OCR service.  Create once, call extract_text() many times.

    Args:
        dpi:  DPI used when rasterising PDF pages (higher = better quality, slower).
              300 is the NIS recommended minimum for legible document scans.
        lang: Tesseract language code(s).  'eng' for English; 'eng+fra' for bilingual.
    """

    def __init__(self, dpi: int = 300, lang: str = "eng") -> None:
        self._dpi  = dpi
        self._lang = lang

    # ── Public API ─────────────────────────────────────────────────────────────

    def extract_text(self, file_data: bytes, content_type: str, file_name: str = "") -> str:
        """
        Extract text from a document and return it as a plain string.

        All pages of a multi-page PDF are joined with a page-break marker.
        Raises OCRServiceError for any processing failure.
        """
        if not _TESSERACT_AVAILABLE:
            raise OCRServiceError(
                "pytesseract or Pillow not installed. "
                "Run: pip install pytesseract Pillow"
            )

        base_type = content_type.split(";")[0].strip().lower()
        logger.info(f"OCR | file={file_name!r} | type={base_type} | dpi={self._dpi}")

        try:
            if base_type == "application/pdf":
                return self._extract_from_pdf(file_data)
            elif base_type in SUPPORTED_OCR_MIME_TYPES:
                return self._extract_from_image(file_data)
            else:
                # Best-effort: try treating unknown type as image
                logger.warning(f"OCR | unsupported type {base_type!r}, attempting image decode")
                return self._extract_from_image(file_data)
        except OCRServiceError:
            raise
        except Exception as exc:
            raise OCRServiceError(f"OCR extraction failed for {file_name!r}: {exc}") from exc

    # ── Private helpers ────────────────────────────────────────────────────────

    def _extract_from_pdf(self, file_data: bytes) -> str:
        if not _PDF2IMAGE_AVAILABLE:
            raise OCRServiceError(
                "pdf2image not installed or poppler not found. "
                "Docker: apt-get install poppler-utils. "
                "Windows: install poppler and add its bin/ to PATH."
            )
        try:
            images = convert_from_bytes(file_data, dpi=self._dpi)
        except Exception as exc:
            raise OCRServiceError(f"PDF to image conversion failed: {exc}") from exc

        if not images:
            raise OCRServiceError("PDF produced 0 pages after conversion.")

        page_texts: list[str] = []
        for i, img in enumerate(images, start=1):
            try:
                text = pytesseract.image_to_string(img, lang=self._lang)
                page_texts.append(text)
                logger.debug(f"OCR | page {i}/{len(images)} extracted ({len(text)} chars)")
            except pytesseract.TesseractNotFoundError:
                raise OCRServiceError(
                    "Tesseract executable not found. "
                    "Docker: apt-get install tesseract-ocr. "
                    "Windows: https://github.com/UB-Mannheim/tesseract/wiki"
                )
            except Exception as exc:
                raise OCRServiceError(f"Tesseract failed on page {i}: {exc}") from exc

        return "\n\n--- PAGE BREAK ---\n\n".join(page_texts)

    def _extract_from_image(self, file_data: bytes) -> str:
        try:
            image = Image.open(io.BytesIO(file_data))
            # Convert to RGB if needed (TIFF can be CMYK or other modes)
            if image.mode not in ("RGB", "L", "RGBA"):
                image = image.convert("RGB")
            return pytesseract.image_to_string(image, lang=self._lang)
        except pytesseract.TesseractNotFoundError:
            raise OCRServiceError(
                "Tesseract executable not found. "
                "Docker: apt-get install tesseract-ocr. "
                "Windows: https://github.com/UB-Mannheim/tesseract/wiki"
            )
        except Exception as exc:
            raise OCRServiceError(f"Image OCR failed: {exc}") from exc


# ── Module-level singleton ──────────────────────────────────────────────────

_ocr_service: Optional[OCRService] = None


def get_ocr_service(dpi: int = 300, lang: str = "eng") -> OCRService:
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OCRService(dpi=dpi, lang=lang)
    return _ocr_service
