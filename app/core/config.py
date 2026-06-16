from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_env: str = "development"
    app_name: str = "DMS Document Service"
    app_version: str = "1.0.0"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin123"
    minio_secure: bool = False

    minio_bucket_contributors: str = "dms-contributors"
    minio_bucket_beneficiaries: str = "dms-beneficiaries"
    minio_bucket_employees: str = "dms-employees"
    minio_bucket_temp: str = "dms-temp"

    minio_presigned_expiry: int = 3600  # seconds

    # Security
    api_key: str = "dms-local-dev-key-change-in-prod"
    allowed_origins: str = "http://localhost:3000,http://localhost:8080"

    # Logging
    log_level: str = "DEBUG"
    log_file: str = "logs/dms.log"

    # Database (Scenario 1 — scan metadata)
    # SQLite for dev/local. PostgreSQL for production:
    # DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dms
    database_url: str = "sqlite:///./data/dms_scan.db"

    # OCR buckets (Scenario 1)
    ocr_bucket_scanned: str = "scanned-documents"
    ocr_bucket_output:  str = "ocr-output"
    ocr_dpi:            int = 300   # DPI for PDF→image conversion (300 = NIS minimum)
    ocr_lang:           str = "eng" # Tesseract language code; 'eng+fra' for bilingual

    # Async task queue (Celery + Redis)
    redis_url:          str = "redis://localhost:6379/0"
    celery_task_queue:  str = "ocr"   # named queue so OCR workers can be isolated

    @property
    def bucket_map(self) -> dict[str, str]:
        return {
            "contributors": self.minio_bucket_contributors,
            "beneficiaries": self.minio_bucket_beneficiaries,
            "employees": self.minio_bucket_employees,
            "temp": self.minio_bucket_temp,
        }

    def get_bucket(self, entity_type: str) -> str:
        bucket = self.bucket_map.get(entity_type.lower())
        if not bucket:
            raise ValueError(f"Unknown entity_type '{entity_type}'. Valid: {list(self.bucket_map.keys())}")
        return bucket


@lru_cache
def get_settings() -> Settings:
    return Settings()
