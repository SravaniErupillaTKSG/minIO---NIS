"""
Celery application instance for DMS async task processing.

Broker: Redis  (redis://redis:6379/0  in Docker; localhost for local dev)
Backend: Redis (task results stored for 1 hour)

Worker command:
  celery -A app.workers.celery_app worker --loglevel=info -Q ocr --concurrency=4

Scaling:
  - Increase --concurrency for more parallel OCR jobs per host
  - Add more worker replicas in docker-compose for horizontal scaling
  - Each worker is stateless — safe to scale to N replicas

Graceful degradation:
  If celery or Redis is not available, celery_app is set to None.
  The OCR endpoint falls back to synchronous in-process processing automatically.
"""
from __future__ import annotations

from loguru import logger

from app.core.config import get_settings


def _build_celery():
    try:
        from celery import Celery
    except ImportError:
        logger.warning(
            "celery package not installed — async OCR disabled. "
            "Install with: pip install 'celery[redis]'  "
            "Falling back to synchronous OCR processing."
        )
        return None

    settings = get_settings()
    app = Celery("dms", broker=settings.redis_url, backend=settings.redis_url)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # Reliability settings
        task_acks_late=True,               # re-queue if worker crashes mid-task
        task_reject_on_worker_lost=True,   # don't silently drop on SIGKILL
        worker_prefetch_multiplier=1,      # one task per worker slot (fair dispatch)
        # Result TTL — keep result for 1 hour then auto-expire from Redis
        result_expires=3600,
    )
    return app


celery_app = _build_celery()
