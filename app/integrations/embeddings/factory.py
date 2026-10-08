from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.embeddings.base import EmbeddingProvider

def _build_bedrock_provider() -> EmbeddingProvider:
    from app.integrations.embeddings.bedrock_provider import BedrockEmbeddingProvider

    settings = get_settings()
    return BedrockEmbeddingProvider(
        model_id=settings.embedding_model_id,
        region=settings.aws_region,
    )


PROVIDERS: dict[str, Callable[[], EmbeddingProvider]] = {
    "bedrock": _build_bedrock_provider,
}


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Deliberately uncached: `Settings` is a Pydantic model and therefore unhashable, so
    `@lru_cache` here would raise `TypeError` for every caller that passes settings explicitly.
    Provider reuse is the responsibility of `app.api.deps.get_embedder`, which takes no arguments.
    """
    settings = settings or get_settings()
    return resolve_provider("embedding", settings.embedding_provider, PROVIDERS)
