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
    `max_connections`. Tests that need a fresh provider call `get_vector_store.cache_clear()`.
    """
    return get_vector_store_provider()


def get_generator() -> GenerationProvider:
    return get_generation_provider()
