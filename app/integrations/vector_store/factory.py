from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.vector_store.base import VectorStoreProvider

PROVIDERS: dict[str, Callable[[], VectorStoreProvider]] = {}


def get_vector_store_provider(settings: Settings | None = None) -> VectorStoreProvider:
    settings = settings or get_settings()
    return resolve_provider("vector store", settings.vector_store_provider, PROVIDERS)
