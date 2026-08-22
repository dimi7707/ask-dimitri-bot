from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.embeddings.base import EmbeddingProvider

PROVIDERS: dict[str, Callable[[], EmbeddingProvider]] = {}


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    return resolve_provider("embedding", settings.embedding_provider, PROVIDERS)
