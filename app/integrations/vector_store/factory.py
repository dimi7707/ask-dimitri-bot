from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.vector_store.base import VectorStoreProvider


def _build_pgvector_provider() -> VectorStoreProvider:
    from app.integrations.vector_store.pgvector_provider import PgVectorStoreProvider

    return PgVectorStoreProvider(database_url=get_settings().database_url)


PROVIDERS: dict[str, Callable[[], VectorStoreProvider]] = {
    "pgvector": _build_pgvector_provider,
}


def get_vector_store_provider(settings: Settings | None = None) -> VectorStoreProvider:
    """Deliberately uncached: `Settings` is a Pydantic model and therefore unhashable, so
    `@lru_cache` here would raise `TypeError` for every caller that passes settings explicitly.
    Provider reuse is the responsibility of `app.api.deps.get_vector_store`, which takes no
    arguments.
    """
    settings = settings or get_settings()
    return resolve_provider("vector store", settings.vector_store_provider, PROVIDERS)
