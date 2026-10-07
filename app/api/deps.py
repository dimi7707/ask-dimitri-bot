"""FastAPI dependencies resolving the configured providers.

Thin wrappers around the factories so routes depend on `Depends(...)` callables that tests can
override, without FastAPI trying to bind the factories' own `settings` argument as a query param.

Taking no arguments also makes these wrappers the right place to cache a provider that owns
connections: FastAPI's own dependency cache spans a single request, so an uncached wrapper builds a
new provider — and a new connection pool — per request.
"""

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.integrations.embeddings.base import EmbeddingProvider
from app.integrations.embeddings.factory import get_embedding_provider
from app.integrations.generation.base import GenerationProvider
from app.integrations.generation.factory import get_generation_provider
from app.integrations.vector_store.base import VectorStoreProvider
from app.integrations.vector_store.factory import get_vector_store_provider


def get_app_settings() -> Settings:
    return get_settings()


def get_embedder() -> EmbeddingProvider:
    return get_embedding_provider()


@lru_cache
def get_vector_store() -> VectorStoreProvider:
    """One provider per process, so its SQLAlchemy engine and pool survive across requests.

    On Lambda the cache spans invocations of a warm execution environment, which is the point: an
    engine per request pays a full TCP+TLS handshake per question and exhausts Aurora's
    `max_connections`. Call `reset_vector_store()` — not `cache_clear()` — to drop the provider.
    """
    return get_vector_store_provider()


def reset_vector_store() -> None:
    """Dispose the cached provider's engine, then drop it from the cache.

    Clearing the cache alone would leave the pool holding its connections open until the garbage
    collector finalizes the engine — the very leak the cache exists to prevent. Disposing first
    makes a reset release the connections immediately.
    """
    try:
        # Guard on the cache being populated, so a reset never *builds* a provider just to drop it.
        if get_vector_store.cache_info().currsize:
            engine = getattr(get_vector_store(), "_engine", None)
            if engine is not None:
                engine.dispose()
    finally:
        # Clear even if disposing blew up: this is the only isolation the API tests have, so a
        # failed dispose must not leave the stale provider behind for everything that runs next.
        get_vector_store.cache_clear()


def get_generator() -> GenerationProvider:
    return get_generation_provider()
