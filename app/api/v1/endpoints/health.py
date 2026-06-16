from fastapi import APIRouter, Depends
from app.services.minio_service import MinIOService, get_minio_service
from app.schemas.document import HealthResponse
from app.core.config import get_settings, Settings

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    description="Returns liveness status of the API and connectivity status of all MinIO buckets.",
)
async def health_check(
    settings: Settings = Depends(get_settings),
    svc: MinIOService = Depends(get_minio_service),
) -> HealthResponse:
    bucket_statuses = svc.health_check()
    all_ok = all(v == "ok" for v in bucket_statuses.values())

    return HealthResponse(
        status="healthy" if all_ok else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        storage="connected" if all_ok else "partially_connected",
        buckets=bucket_statuses,
    )
