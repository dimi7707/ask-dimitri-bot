from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.generation.base import GenerationProvider

PROVIDERS: dict[str, Callable[[], GenerationProvider]] = {}


def get_generation_provider(settings: Settings | None = None) -> GenerationProvider:
    settings = settings or get_settings()
    return resolve_provider("generation", settings.llm_provider, PROVIDERS)
