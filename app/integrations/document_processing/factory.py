from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.document_processing.base import DocumentProcessor

PROVIDERS: dict[str, Callable[[], DocumentProcessor]] = {}


def get_document_processor(settings: Settings | None = None) -> DocumentProcessor:
    settings = settings or get_settings()
    return resolve_provider("document processor", settings.document_processor, PROVIDERS)
