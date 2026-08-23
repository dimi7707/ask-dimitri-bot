from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.storage.base import StorageProvider


def _build_s3_provider() -> StorageProvider:
    from app.integrations.storage.s3_provider import S3StorageProvider

    settings = get_settings()
    return S3StorageProvider(
        bucket_name=settings.s3_bucket_name,
        region=settings.aws_region,
        endpoint_url=settings.s3_endpoint_url,
    )


PROVIDERS: dict[str, Callable[[], StorageProvider]] = {
    "s3": _build_s3_provider,
}


def get_storage_provider(settings: Settings | None = None) -> StorageProvider:
    settings = settings or get_settings()
    return resolve_provider("storage", settings.storage_provider, PROVIDERS)
