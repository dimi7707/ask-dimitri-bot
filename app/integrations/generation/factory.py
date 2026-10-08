from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.generation.base import GenerationProvider

def _build_bedrock_provider() -> GenerationProvider:
    """Takes no arguments on purpose, and reads the process-wide settings itself.

    An explicit `Settings` passed to `get_generation_provider` selects *which* provider is built —
    it is the registry key — not how it is configured. Giving this callable a parameter would make
    the registry's signature a configuration surface, which is not what the dispatch is for.
    """
    from app.integrations.generation.bedrock_provider import BedrockGenerationProvider

    settings = get_settings()
    return BedrockGenerationProvider(
        model_id=settings.bedrock_model_id,
        region=settings.aws_region,
        connect_timeout=settings.bedrock_connect_timeout,
        read_timeout=settings.bedrock_read_timeout,
        max_attempts=settings.bedrock_max_attempts,
    )


PROVIDERS: dict[str, Callable[[], GenerationProvider]] = {
    "bedrock": _build_bedrock_provider,
}


def get_generation_provider(settings: Settings | None = None) -> GenerationProvider:
    """Deliberately uncached: `Settings` is a Pydantic model and therefore unhashable, so
    `@lru_cache` here would raise `TypeError` for every caller that passes settings explicitly.
    Provider reuse is the responsibility of `app.api.deps.get_generator`, which takes no arguments.
    """
    settings = settings or get_settings()
    return resolve_provider("generation", settings.llm_provider, PROVIDERS)
