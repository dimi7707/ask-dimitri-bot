import uuid
from contextlib import contextmanager

from sqlalchemy import create_engine, delete, select
from sqlmodel import Session

from app.integrations.vector_store.base import EmbeddedChunk, RetrievedChunk
from app.models.documents import Document, DocumentChunk


class PgVectorStoreProvider:
    def __init__(self, database_url: str, pool_size: int = 1, max_overflow: int = 2):
        """Pool sizing is caller-supplied because it describes the runtime, not the store.

        The defaults describe Lambda — one request per container at a time, the overflow being
        headroom rather than concurrency. A runtime that serves requests concurrently in one process
        passes larger values (see `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`), otherwise requests queue
        behind `pool_timeout` instead of running.
        """
        self._engine = create_engine(
            database_url,
            # A Lambda container freezes between invocations and Aurora may close the connection on
            # its own, so ping before handing a pooled connection to the caller.
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )

    def close(self) -> None:
        """Dispose the engine, releasing its pooled connections now instead of at GC time.

        This is the `Closeable` half of the provider's lifecycle: the cache calls it before dropping
        the provider, which is the only moment a replaced pool can be released deterministically.
        """
        self._engine.dispose()

    @contextmanager
    def _session(self):
        with Session(self._engine) as session:
            yield session

    def upsert_document(self, document_id: str, filename: str, doc_type: str, version: str) -> None:
        document_uuid = uuid.UUID(document_id)
        with self._session() as session:
            document = session.get(Document, document_uuid)
            if document is None:
                document = Document(id=document_uuid, filename=filename, doc_type=doc_type, version=version)
            else:
                document.filename = filename
                document.doc_type = doc_type
                document.version = version
            session.add(document)
            session.commit()

    def upsert_chunks(self, document_id: str, chunks: list[EmbeddedChunk]) -> None:
        document_uuid = uuid.UUID(document_id)
        with self._session() as session:
            session.exec(delete(DocumentChunk).where(DocumentChunk.document_id == document_uuid))
            for chunk in chunks:
                session.add(
                    DocumentChunk(
                        document_id=document_uuid,
                        chunk_text=chunk.chunk_text,
                        embedding=chunk.embedding,
                        chunk_index=chunk.chunk_index,
                        metadata_=chunk.metadata,
                    )
                )
            session.commit()

    def delete_by_document_id(self, document_id: str) -> None:
        document_uuid = uuid.UUID(document_id)
        with self._session() as session:
            session.exec(delete(DocumentChunk).where(DocumentChunk.document_id == document_uuid))
            session.commit()

    def similarity_search(self, query_embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        statement = select(DocumentChunk, distance.label("distance")).order_by(distance).limit(top_k)

        with self._session() as session:
            rows = session.exec(statement).all()

        return [
            RetrievedChunk(
                chunk_text=chunk.chunk_text,
                score=1.0 - distance_value,
                document_id=str(chunk.document_id),
            )
            for chunk, distance_value in rows
        ]
