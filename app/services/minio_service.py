from datetime import datetime, timezone, timedelta
from typing import Optional, BinaryIO

from minio import Minio
from minio.error import S3Error
from minio.versioningconfig import VersioningConfig, ENABLED
from loguru import logger

from app.core.config import get_settings
from app.core.exceptions import (
    DocumentNotFoundError,
    DocumentUploadError,
    DocumentDeleteError,
    BucketNotFoundError,
    StorageConnectionError,
)
from app.schemas.document import DocumentUploadResponse, DocumentMetadata, PresignedUrlResponse
from app.schemas.nis_document import DocumentListItem


class MinIOService:
    """All MinIO operations for the DMS."""

    def __init__(self):
        settings = get_settings()
        try:
            self._client = Minio(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_root_user,
                secret_key=settings.minio_root_password,
                secure=settings.minio_secure,
            )
            self._settings = settings
            logger.info(f"MinIO client initialized | endpoint={settings.minio_endpoint}")
        except Exception as exc:
            logger.error(f"Failed to initialize MinIO client: {exc}")
            raise StorageConnectionError(str(exc))

    # ─── Internal helpers ──────────────────────────────────────────────────────

    def _ensure_bucket(self, bucket: str) -> None:
        """Strict check — raises BucketNotFoundError if the bucket does not exist."""
        try:
            if not self._client.bucket_exists(bucket):
                raise BucketNotFoundError(bucket)
        except S3Error as exc:
            logger.error(f"Bucket check failed | bucket={bucket} | error={exc}")
            raise StorageConnectionError(str(exc))

    def _ensure_bucket_exists(self, bucket: str) -> None:
        """Creates the bucket (with versioning) if it does not exist. Used on write paths."""
        try:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)
                logger.warning(
                    f"Bucket '{bucket}' was missing — auto-created. "
                    "Run init-buckets.sh to apply versioning and lifecycle policies."
                )
            # Always attempt to enable versioning; idempotent if already set.
            try:
                self._client.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
            except Exception:
                pass  # init-buckets.sh handles versioning; this is best-effort only
        except S3Error as exc:
            logger.error(f"Bucket ensure failed | bucket={bucket} | error={exc}")
            raise StorageConnectionError(str(exc))

    def ensure_all_buckets(self) -> dict[str, str]:
        """
        Called at startup. Creates any missing buckets and returns a status dict.
        Does not raise — logs warnings so the app can still start even if MinIO is slow.
        """
        results = {}
        for label, bucket in self._settings.bucket_map.items():
            try:
                self._ensure_bucket_exists(bucket)
                results[bucket] = "ok"
                logger.info(f"Startup bucket check | bucket={bucket} | status=ok")
            except Exception as exc:
                results[bucket] = f"error: {exc}"
                logger.warning(f"Startup bucket check | bucket={bucket} | status=error | detail={exc}")
        return results

    # ─── OCR bucket init ───────────────────────────────────────────────────────

    def ensure_ocr_buckets(self) -> dict[str, str]:
        """
        Create the Scenario 1 OCR buckets if they do not exist.
        Called at startup alongside ensure_all_buckets().
        """
        results = {}
        ocr_buckets = [
            self._settings.ocr_bucket_scanned,
            self._settings.ocr_bucket_output,
        ]
        for bucket in ocr_buckets:
            try:
                self._ensure_bucket_exists(bucket)
                results[bucket] = "ok"
                logger.info(f"Startup bucket check | bucket={bucket} | status=ok")
            except Exception as exc:
                results[bucket] = f"error: {exc}"
                logger.warning(f"Startup bucket check | bucket={bucket} | status=error | detail={exc}")
        return results

    # ─── Upload ────────────────────────────────────────────────────────────────

    def upload_bytes(
        self,
        bucket: str,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload raw bytes to MinIO.  Used for:
        - Scanned originals (stored in scanned-documents bucket)
        - OCR text output   (stored in ocr-output bucket)

        Returns the object_name on success.
        Keeps io.BytesIO allocation inside this method — callers pass plain bytes.
        """
        import io as _io
        self._ensure_bucket_exists(bucket)
        try:
            self._client.put_object(
                bucket_name=bucket,
                object_name=object_name,
                data=_io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            logger.info(f"upload_bytes | bucket={bucket} | object={object_name} | size={len(data)}")
            return object_name
        except S3Error as exc:
            logger.error(f"upload_bytes failed | bucket={bucket} | object={object_name} | error={exc}")
            raise DocumentUploadError(str(exc))

    def upload_document(
        self,
        bucket: str,
        object_name: str,
        file_data: BinaryIO,
        file_size: int,
        content_type: str,
        metadata: Optional[dict] = None,
    ) -> DocumentUploadResponse:
        """
        Stream-upload a document directly from the caller's file object into MinIO.

        Why streaming matters:
          Old approach:  endpoint reads entire file → Python RAM → MinIO
          New approach:  endpoint passes file handle → MinIO reads directly from it
          For a 20 MB file, the old way used 20 MB of application RAM per request.
          The new way uses only the MinIO SDK's internal read buffer (~8 KB).

        Parameters:
          file_data  — a BinaryIO at position 0 (FastAPI's UploadFile.file)
          file_size  — byte count (FastAPI's UploadFile.size, set by multipart parser)
        """
        self._ensure_bucket_exists(bucket)

        extra_headers = {}
        if metadata:
            for key, value in metadata.items():
                extra_headers[f"x-amz-meta-{key}"] = str(value)

        try:
            result = self._client.put_object(
                bucket_name=bucket,
                object_name=object_name,
                data=file_data,            # Stream — no copy into RAM
                length=file_size,          # Known from multipart parser
                content_type=content_type,
                metadata=extra_headers if extra_headers else None,
            )
            logger.info(
                f"Document uploaded | bucket={bucket} | object={object_name} "
                f"| size={file_size} | etag={result.etag}"
            )
            return DocumentUploadResponse(
                object_name=object_name,
                bucket=bucket,
                entity_type=bucket.replace("dms-", ""),
                content_type=content_type,
                size_bytes=file_size,
                etag=result.etag or "",
                uploaded_at=datetime.now(timezone.utc),
                version_id=result.version_id,
            )
        except S3Error as exc:
            logger.error(f"Upload failed | bucket={bucket} | object={object_name} | error={exc}")
            raise DocumentUploadError(str(exc))

    # ─── Download ──────────────────────────────────────────────────────────────

    def download_document(self, bucket: str, object_name: str) -> tuple[bytes, str]:
        """Returns (file_bytes, content_type)."""
        self._ensure_bucket(bucket)
        try:
            response = self._client.get_object(bucket, object_name)
            data = response.read()
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            response.close()
            response.release_conn()
            logger.info(f"Document downloaded | bucket={bucket} | object={object_name} | size={len(data)}")
            return data, content_type
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise DocumentNotFoundError(object_name, bucket)
            logger.error(f"Download failed | bucket={bucket} | object={object_name} | error={exc}")
            raise StorageConnectionError(str(exc))

    # ─── Delete ────────────────────────────────────────────────────────────────

    def delete_document(self, bucket: str, object_name: str) -> None:
        self._ensure_bucket(bucket)
        try:
            # Verify existence before deleting
            self._client.stat_object(bucket, object_name)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise DocumentNotFoundError(object_name, bucket)
            raise StorageConnectionError(str(exc))

        try:
            self._client.remove_object(bucket, object_name)
            logger.info(f"Document deleted | bucket={bucket} | object={object_name}")
        except S3Error as exc:
            logger.error(f"Delete failed | bucket={bucket} | object={object_name} | error={exc}")
            raise DocumentDeleteError(str(exc))

    # ─── Metadata / Stat ───────────────────────────────────────────────────────

    def get_document_metadata(self, bucket: str, object_name: str) -> DocumentMetadata:
        self._ensure_bucket(bucket)
        try:
            stat = self._client.stat_object(bucket, object_name)
            raw_meta = dict(stat.metadata or {})
            # Strip the x-amz-meta- prefix for cleaner output
            clean_meta = {
                k.replace("x-amz-meta-", ""): v
                for k, v in raw_meta.items()
                if k.startswith("x-amz-meta-")
            }
            return DocumentMetadata(
                object_name=object_name,
                bucket=bucket,
                size_bytes=stat.size or 0,
                content_type=stat.content_type or "application/octet-stream",
                etag=stat.etag or "",
                last_modified=stat.last_modified or datetime.now(timezone.utc),
                version_id=stat.version_id,
                metadata=clean_meta,
            )
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise DocumentNotFoundError(object_name, bucket)
            raise StorageConnectionError(str(exc))

    # ─── Presigned URLs ────────────────────────────────────────────────────────

    def generate_presigned_download_url(self, bucket: str, object_name: str) -> PresignedUrlResponse:
        self._ensure_bucket(bucket)
        try:
            # Verify file exists
            self._client.stat_object(bucket, object_name)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise DocumentNotFoundError(object_name, bucket)
            raise StorageConnectionError(str(exc))

        try:
            expiry = self._settings.minio_presigned_expiry
            url = self._client.presigned_get_object(
                bucket_name=bucket,
                object_name=object_name,
                expires=timedelta(seconds=expiry),
            )
            logger.info(f"Presigned GET URL generated | bucket={bucket} | object={object_name}")
            return PresignedUrlResponse(
                url=url,
                object_name=object_name,
                bucket=bucket,
                expiry_seconds=expiry,
                method="GET",
            )
        except S3Error as exc:
            raise StorageConnectionError(str(exc))

    def generate_presigned_upload_url(self, bucket: str, object_name: str) -> PresignedUrlResponse:
        self._ensure_bucket(bucket)
        try:
            expiry = self._settings.minio_presigned_expiry
            url = self._client.presigned_put_object(
                bucket_name=bucket,
                object_name=object_name,
                expires=timedelta(seconds=expiry),
            )
            logger.info(f"Presigned PUT URL generated | bucket={bucket} | object={object_name}")
            return PresignedUrlResponse(
                url=url,
                object_name=object_name,
                bucket=bucket,
                expiry_seconds=expiry,
                method="PUT",
            )
        except S3Error as exc:
            raise StorageConnectionError(str(exc))

    # ─── List ──────────────────────────────────────────────────────────────────

    def list_documents(
        self,
        bucket: str,
        entity_type: str,
        entity_id: str,
    ) -> list[DocumentListItem]:
        """
        Return every object stored under  {entity_type}/{entity_id}/  in the bucket.

        MinIO's list_objects uses a prefix filter so only this entity's objects are
        scanned — not the entire bucket. recursive=True descends into all document-type
        sub-folders (IDENTITY/, CONTRACT/, CLAIM/, …).

        Object path structure:
          {entity_type}/{entity_id}/{document_type}/{filename}
          e.g. contributors/U001/IDENTITY/passport.pdf
          parts[0]=contributors  parts[1]=U001  parts[2]=IDENTITY  parts[3]=passport.pdf
        """
        self._ensure_bucket(bucket)
        prefix = f"{entity_type}/{entity_id}/"
        try:
            objects = self._client.list_objects(
                bucket_name=bucket,
                prefix=prefix,
                recursive=True,
            )
            items: list[DocumentListItem] = []
            for obj in objects:
                parts = (obj.object_name or "").rstrip("/").split("/")
                doc_type = parts[2] if len(parts) >= 4 else "UNKNOWN"
                filename  = parts[-1] if parts else obj.object_name or ""
                items.append(
                    DocumentListItem(
                        object_name=obj.object_name or "",
                        document_type=doc_type,
                        filename=filename,
                        size_bytes=obj.size or 0,
                        etag=obj.etag or "",
                        last_modified=obj.last_modified or datetime.now(timezone.utc),
                        version_id=obj.version_id,
                    )
                )
            logger.info(
                f"Listed {len(items)} documents | bucket={bucket} | prefix={prefix}"
            )
            return items
        except S3Error as exc:
            logger.error(f"List failed | bucket={bucket} | prefix={prefix} | error={exc}")
            raise StorageConnectionError(str(exc))

    # ─── Health ────────────────────────────────────────────────────────────────

    def health_check(self) -> dict[str, str]:
        """Returns status of each bucket: 'ok' or 'missing'."""
        results = {}
        for label, bucket in self._settings.bucket_map.items():
            try:
                exists = self._client.bucket_exists(bucket)
                results[bucket] = "ok" if exists else "missing"
            except Exception as exc:
                results[bucket] = f"error: {exc}"
        return results


# Module-level singleton — one connection pool shared across requests
_service: Optional[MinIOService] = None


def get_minio_service() -> MinIOService:
    global _service
    if _service is None:
        _service = MinIOService()
    return _service
