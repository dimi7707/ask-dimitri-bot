from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.generation.base import GenerationProvider

def _build_bedrock_provider() -> GenerationProvider:
    from app.integrations.generation.bedrock_provider import BedrockGenerationProvider

    settings = get_settings()
    return BedrockGenerationProvider(
        model_id=settings.bedrock_model_id,
        region=settings.aws_region,
    )


PROVIDERS: dict[str, Callable[[], GenerationProvider]] = {
    "bedrock": _build_bedrock_provider,
}


def get_generation_provider(settings: Settings | None = None) -> GenerationProvider:
    settings = settings or get_settings()
    return resolve_provider("generation", settings.llm_provider, PROVIDERS)
