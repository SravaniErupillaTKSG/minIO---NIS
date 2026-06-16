from fastapi import APIRouter
from app.api.v1.endpoints import documents, health, scan
from app.api.v1.endpoints.nis import nis_router, doc_ext_router

api_router = APIRouter(prefix="/api/v1")

# ── NIS routes (must come before /documents because doc_ext_router also uses /documents prefix)
api_router.include_router(nis_router)
api_router.include_router(doc_ext_router)

# ── Core document and scan routes
api_router.include_router(documents.router)
api_router.include_router(scan.router)
api_router.include_router(health.router)
