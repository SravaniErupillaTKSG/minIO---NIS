"""
OCR Worker — Celery task definition and submit bridge.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Task: process_ocr_task
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Runs in the Celery worker process. Receives only the document_id (UUID).
Fetches all resources it needs (MinIO, SQLite, settings) from the environment
— no file bytes are passed through Redis.

Retry policy:
  max_retries=3, delay=60s per attempt.
  Transient failures (network blip, MinIO restart) are automatically retried.
  Permanent OCR failures (corrupt file, Tesseract crash) are caught inside
  run_ocr_pipeline() and recorded as status=FAILED (no retry for those).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bridge: submit_processing_task
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Called by the FastAPI endpoint. Stores the original file + creates PENDING
record (Phase 1), then enqueues the Celery task for background OCR (Phase 2).
Returns the PENDING record immediately.

Fallback: if Redis / Celery is unavailable (or not installed), falls back to
synchronous in-process OCR so the endpoint still works without a running worker.
"""
from __future__ import annotations

from loguru import logger

from app.workers.celery_app import celery_app


# ── Celery task ───────────────────────────────────────────────────────────────

def _ocr_task_impl(self, document_id: str) -> dict:
    """
    Core OCR task logic — runs in Celery worker process.

    Receives the document_id, rebuilds all dependencies from config/env,
    and runs DocumentProcessor.run_ocr_pipeline().

    Returns a plain dict (JSON-serialisable) for the Celery result backend:
      { "document_id": str, "ocr_status": "COMPLETED" | "FAILED" }
    """
    # Lazy imports — keep them here so the module can be imported
    # by FastAPI without pulling in SQLAlchemy / OCR packages at startup.
    from app.core.config import get_settings
    from app.core.database import get_session_factory
    from app.repositories.sqlite_repository import SQLiteDocumentRepository
    from app.services.metadata_service import MetadataService
    from app.services.minio_service import MinIOService
    from app.services.ocr_service import get_ocr_service
    from app.services.document_processor import DocumentProcessor

    logger.info(f"OCR task started | id={document_id} | attempt={self.request.retries + 1}")

    settings = get_settings()
    db = get_session_factory()()
    try:
        repo      = SQLiteDocumentRepository(db)
        metadata  = MetadataService(repo)
        minio     = MinIOService()
        ocr       = get_ocr_service(dpi=settings.ocr_dpi, lang=settings.ocr_lang)
        processor = DocumentProcessor(
            minio=minio, ocr=ocr, metadata=metadata, settings=settings
        )

        record = processor.run_ocr_pipeline(document_id)
        logger.info(
            f"OCR task finished | id={document_id} | status={record.ocr_status}"
        )
        return {"document_id": record.document_id, "ocr_status": record.ocr_status}

    except Exception as exc:
        logger.error(f"OCR task error | id={document_id} | error={exc}")
        raise self.retry(exc=exc)
    finally:
        db.close()


# Register as a Celery task only when the broker is available.
# process_ocr_task is None when celery_app is None (no celery package / no Redis).
# submit_processing_task checks for None and falls back to sync OCR automatically.
if celery_app is not None:
    process_ocr_task = celery_app.task(
        bind=True,
        name="dms.ocr.process_document",
        max_retries=3,
        default_retry_delay=60,
        queue="ocr",
    )(_ocr_task_impl)
else:
    process_ocr_task = None


# ── Submit bridge (called by the API endpoint) ────────────────────────────────

def submit_processing_task(
    processor,
    document_id:  str,
    file_data:    bytes,
    file_name:    str,
    content_type: str,
    scan_source:  str = "IBML_SIMULATED",
):
    """
    Phase 1 + enqueue Phase 2.

    1. Calls processor.store_original() — uploads file, creates PENDING record.
    2. Enqueues process_ocr_task via Celery (async, returns immediately).
    3. Returns the PENDING record.

    Fallback: if process_ocr_task is None (celery not installed) or Redis is
    unreachable, runs OCR synchronously in-process and returns the final
    (COMPLETED/FAILED) record. A warning is logged in both cases.
    """
    from app.core.config import get_settings

    record = processor.store_original(
        document_id=document_id,
        file_data=file_data,
        file_name=file_name,
        content_type=content_type,
        scan_source=scan_source,
    )

    try:
        if process_ocr_task is None:
            raise RuntimeError("Celery not available — no broker or package missing")
        process_ocr_task.apply_async(
            args=[document_id],
            queue=get_settings().celery_task_queue,
        )
        logger.info(f"OCR task queued | id={document_id} | mode=ASYNC")
    except Exception as exc:
        logger.warning(
            f"Async OCR unavailable ({type(exc).__name__}: {exc}) — "
            f"running OCR synchronously | id={document_id}"
        )
        final = processor.run_ocr_pipeline(document_id)
        return final

    return record
