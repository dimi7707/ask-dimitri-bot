from typing import Callable

from app.core.config import Settings, get_settings
from app.integrations._registry import resolve_provider
from app.integrations.document_processing.base import DocumentProcessor

def _build_llamaindex_processor() -> DocumentProcessor:
    from app.integrations.document_processing.llamaindex_provider import LlamaIndexDocumentProcessor

    settings = get_settings()
    return LlamaIndexDocumentProcessor(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )


PROVIDERS: dict[str, Callable[[], DocumentProcessor]] = {
    "llamaindex": _build_llamaindex_processor,
}


def get_document_processor(settings: Settings | None = None) -> DocumentProcessor:
    settings = settings or get_settings()
    return resolve_provider("document processor", settings.document_processor, PROVIDERS)
