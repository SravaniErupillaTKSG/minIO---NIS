from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
# pyrefly: ignore [missing-import]
from loguru import logger

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.api.v1.router import api_router

setup_logging()
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup: initialise DB tables then verify all MinIO buckets."""
    # ── Database ──────────────────────────────────────────────────────────────
    try:
        from app.core.database import init_db
        init_db()
        logger.info("DB tables verified / created.")
    except Exception as exc:
        logger.warning(f"DB init failed: {exc} — scan metadata endpoints may fail.")

    # ── MinIO buckets (Scenario 2: portal + Scenario 1: OCR) ─────────────────
    logger.info("=== DMS startup: verifying MinIO buckets ===")
    try:
        from app.services.minio_service import get_minio_service
        svc = get_minio_service()

        # Scenario 2 — portal entity buckets
        results = svc.ensure_all_buckets()

        # Scenario 1 — OCR buckets
        ocr_results = svc.ensure_ocr_buckets()
        results.update(ocr_results)

        ok = all(v == "ok" for v in results.values())
        if ok:
            logger.info(f"All buckets ready: {sorted(results.keys())}")
        else:
            logger.warning(f"Some buckets had issues at startup: {results}")
    except Exception as exc:
        logger.warning(
            f"Startup bucket check failed: {exc} — "
            "Ensure MinIO is running. Requests will fail until it is reachable."
        )
    yield
    logger.info("=== DMS shutdown ===")


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "## DMS Document Service\n\n"
        "Production-ready document storage API backed by MinIO (S3-compatible).\n\n"
        "### Architecture\n"
        "```\n"
        "Salesforce Portal\n"
        "  → MuleSoft Process API\n"
        "  → MuleSoft System API\n"
        "  → FastAPI Document Service  ← you are here\n"
        "  → MinIO Object Storage\n"
        "```\n\n"
        "### Bucket Strategy\n"
        "| Bucket | Owner |\n"
        "|---|---|\n"
        "| `dms-contributors` | Contributors |\n"
        "| `dms-beneficiaries` | Beneficiaries |\n"
        "| `dms-employees` | Employees |\n"
        "| `dms-temp` | Temporary uploads (7-day TTL) |\n\n"
        "### Object Naming Convention\n"
        "`{entity_type}/{entity_id}/{document_type}/{filename}`\n\n"
        "Example: `contributors/U001/IDENTITY/passport.pdf`\n\n"
        "### Authentication\n"
        "All `/documents/` endpoints require an API key in the request header:\n"
        "```\n"
        "X-API-Key: <your-key>\n"
        "```\n"
        "**In Swagger UI:** click the **Authorize** 🔒 button at the top of this page, "
        "enter your key, and click **Authorize**. All subsequent requests will include "
        "the header automatically.\n\n"
        "The health endpoint (`/api/v1/health`) does **not** require a key.\n\n"
        "| Response | Meaning |\n"
        "|---|---|\n"
        "| `401 Unauthorized` | Header `X-API-Key` is missing |\n"
        "| `403 Forbidden` | Header is present but the key is wrong |"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
origins = [o.strip() for o in settings.allowed_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Request logging middleware ────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"→ {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"← {request.method} {request.url.path} | status={response.status_code}")
    return response

# ─── Global exception handler ─────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred."})

# ─── Routes ───────────────────────────────────────────────────────────────────
app.include_router(api_router)

# Root redirect info
@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/api/v1/health",
    }


logger.info(f"{settings.app_name} v{settings.app_version} started | env={settings.app_env}")
