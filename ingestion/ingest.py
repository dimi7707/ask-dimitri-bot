"""Standalone ingestion: object storage -> chunks -> embeddings -> vector store.

Run via `make ingest` (all documents under the configured prefix) or
`uv run python -m ingestion.ingest <key> [<key> ...]` for specific objects.
"""

import argparse
import logging
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.integrations.document_processing.base import UnsupportedDocumentTypeError
from app.integrations.document_processing.factory import get_document_processor
from app.integrations.embeddings.factory import get_embedding_provider
from app.integrations.storage.factory import get_storage_provider
from app.integrations.vector_store.base import EmbeddedChunk
from app.integrations.vector_store.factory import get_vector_store_provider

logger = logging.getLogger(__name__)

# Fixed namespace so the same storage key always maps to the same document_id — that is what
# makes re-ingesting a document a reindex rather than a duplicate insert.
DOCUMENT_ID_NAMESPACE = uuid.UUID("6f5a0c1e-9b3d-4f2a-8c7e-1d0b4a9f3e21")


@dataclass
class IngestionResult:
    key: str
    document_id: str
    chunks_ingested: int


def document_id_for(key: str) -> str:
    return str(uuid.uuid5(DOCUMENT_ID_NAMESPACE, key))


def ingest_document(
    key: str,
    *,
    storage,
    processor,
    embedder,
    vector_store,
    version: str | None = None,
) -> IngestionResult:
    """Ingest a single stored object, replacing any chunks from a previous run.

    Raises UnsupportedDocumentTypeError (before anything is persisted) for unsupported file types.
    """
    filename = Path(key).name
    chunks = _load_and_chunk(key, storage=storage, processor=processor)
    embedded_chunks = [
        EmbeddedChunk(
            chunk_text=chunk.chunk_text,
            embedding=embedder.embed(chunk.chunk_text),
            chunk_index=chunk.chunk_index,
            metadata=chunk.metadata,
        )
        for chunk in chunks
    ]

    document_id = document_id_for(key)
    vector_store.upsert_document(
        document_id=document_id,
        filename=filename,
        doc_type=Path(key).suffix.lower().lstrip("."),
        version=version or _default_version(),
    )
    # Explicit delete-before-insert: reindexing must never leave chunks from the previous run.
    vector_store.delete_by_document_id(document_id)
    vector_store.upsert_chunks(document_id, embedded_chunks)

    return IngestionResult(key=key, document_id=document_id, chunks_ingested=len(embedded_chunks))


def ingest_all(
    *,
    storage,
    processor,
    embedder,
    vector_store,
    prefix: str = "",
    version: str | None = None,
) -> list[IngestionResult]:
    """Ingest every supported object under `prefix`, skipping unsupported file types."""
    results = []
    for key in storage.list(prefix=prefix):
        try:
            results.append(
                ingest_document(
                    key,
                    storage=storage,
                    processor=processor,
                    embedder=embedder,
                    vector_store=vector_store,
                    version=version,
                )
            )
        except UnsupportedDocumentTypeError as exc:
            logger.warning("Skipping %s: %s", key, exc)
    return results


def _load_and_chunk(key: str, *, storage, processor):
    """Materialize the stored object under its original name so chunk metadata keeps that name."""
    with tempfile.TemporaryDirectory() as temp_dir:
        local_path = Path(temp_dir) / Path(key).name
        local_path.write_bytes(storage.download(key))
        return processor.load_and_chunk(str(local_path))


def _default_version() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keys", nargs="*", help="storage keys to ingest (default: everything under --prefix)")
    parser.add_argument("--prefix", default="", help="storage key prefix to ingest when no keys are given")
    parser.add_argument("--version", default=None, help="version label recorded on the documents row")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    providers = {
        "storage": get_storage_provider(),
        "processor": get_document_processor(),
        "embedder": get_embedding_provider(),
        "vector_store": get_vector_store_provider(),
    }

    if args.keys:
        results = [ingest_document(key, version=args.version, **providers) for key in args.keys]
    else:
        results = ingest_all(prefix=args.prefix, version=args.version, **providers)

    for result in results:
        logger.info("Ingested %s as %s (%d chunks)", result.key, result.document_id, result.chunks_ingested)
    logger.info("Ingested %d document(s)", len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
