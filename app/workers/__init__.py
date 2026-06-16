# Import directly from submodules — do not add eager imports here.
# Importing ocr_worker at package level would force celery_app to load
# during FastAPI startup, before the broker connection is established.
#
#   from app.workers.ocr_worker import submit_processing_task  ✓ (in scan.py)
