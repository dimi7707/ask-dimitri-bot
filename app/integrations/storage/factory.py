from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.storage.base import StorageProvider

PROVIDERS: dict[str, Callable[[], StorageProvider]] = {}


def get_storage_provider(settings: Settings | None = None) -> StorageProvider:
    settings = settings or get_settings()
    return resolve_provider("storage", settings.storage_provider, PROVIDERS)
