from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from app.core.config import get_settings

# Declaring the scheme here is enough for FastAPI to add it to the OpenAPI spec
# and render the "Authorize" button in Swagger UI automatically.
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(_API_KEY_HEADER)) -> str:
    """
    FastAPI dependency — enforces X-API-Key header on every protected endpoint.

    Returns the validated key (caller can ignore it with _: str = Depends(...)).
    Raises:
      401  if the header is absent entirely
      403  if the header is present but wrong
    """
    settings = get_settings()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing API key. "
                "Add request header:  X-API-Key: <your-key>  "
                "In Swagger UI click the Authorize button (🔒) at the top of this page."
            ),
        )
    if api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )
    return api_key
