from pathlib import Path

from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter

from app.integrations.document_processing.base import DocumentChunk, UnsupportedDocumentTypeError

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx"})

# Metadata worth carrying into document_chunks.metadata; anything else LlamaIndex attaches
# (file size, timestamps, internal ids) is noise for retrieval.
KEPT_METADATA_KEYS = ("file_name", "page_label")


class LlamaIndexDocumentProcessor:
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self._splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def load_and_chunk(self, path: str) -> list[DocumentChunk]:
        self._reject_unsupported_extension(path)
        documents = SimpleDirectoryReader(input_files=[path]).load_data()
        nodes = self._splitter.get_nodes_from_documents(documents)
        return [
            DocumentChunk(
                chunk_text=node.get_content(),
                chunk_index=index,
                metadata=self._kept_metadata(node.metadata),
            )
            for index, node in enumerate(nodes)
        ]

    def _reject_unsupported_extension(self, path: str) -> None:
        extension = Path(path).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise UnsupportedDocumentTypeError(
                f"Cannot process {path!r}: unsupported extension {extension!r}. Supported: {supported}"
            )

    def _kept_metadata(self, metadata: dict) -> dict:
        return {key: metadata[key] for key in KEPT_METADATA_KEYS if key in metadata}
