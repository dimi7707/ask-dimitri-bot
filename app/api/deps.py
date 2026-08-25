"""FastAPI dependencies resolving the configured providers.

Thin wrappers around the factories so routes depend on `Depends(...)` callables that tests can
override, without FastAPI trying to bind the factories' own `settings` argument as a query param.
"""

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


def get_vector_store() -> VectorStoreProvider:
    return get_vector_store_provider()


def get_generator() -> GenerationProvider:
    return get_generation_provider()
