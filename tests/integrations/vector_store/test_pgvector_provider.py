import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from app.integrations.vector_store.base import EmbeddedChunk
from app.models.documents import EMBEDDING_DIMENSIONS

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:55432/askdimitri",
)


def _database_reachable(url: str) -> bool:
    try:
        engine = create_engine(url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _database_reachable(TEST_DATABASE_URL),
    reason=(
        "Postgres+pgvector test database not reachable at "
        f"{TEST_DATABASE_URL!r}. Start it (see design.md) or run `make dev`."
    ),
)


def _vector(*leading_values: float) -> list[float]:
    """Pad a few meaningful dimensions out to the real 1024-dim embedding width.

    Cosine similarity is unaffected by the trailing zeros since they're
    identical (zero) on both sides of every comparison in these tests.
    """
    return list(leading_values) + [0.0] * (EMBEDDING_DIMENSIONS - len(leading_values))


@pytest.fixture
def provider():
    from app.integrations.vector_store.pgvector_provider import PgVectorStoreProvider

    provider = PgVectorStoreProvider(database_url=TEST_DATABASE_URL)
    yield provider

    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE document_chunks, documents CASCADE"))


def test_upsert_document_then_chunks_makes_them_searchable(provider):
    document_id = str(uuid.uuid4())
    provider.upsert_document(document_id, filename="cv.pdf", doc_type="cv", version="v1")
    provider.upsert_chunks(
        document_id,
        [EmbeddedChunk(chunk_text="Dimitri trabaja con Python", embedding=_vector(1.0, 0.0, 0.0), chunk_index=0)],
    )

    results = provider.similarity_search(query_embedding=_vector(1.0, 0.0, 0.0), top_k=5)

    assert len(results) == 1
    assert results[0].chunk_text == "Dimitri trabaja con Python"
    assert results[0].document_id == document_id
    assert results[0].score == pytest.approx(1.0)


def test_similarity_search_ranks_closer_vectors_first(provider):
    document_id = str(uuid.uuid4())
    provider.upsert_document(document_id, filename="cv.pdf", doc_type="cv", version="v1")
    provider.upsert_chunks(
        document_id,
        [
            EmbeddedChunk(chunk_text="closer chunk", embedding=_vector(1.0, 0.0, 0.0), chunk_index=0),
            EmbeddedChunk(chunk_text="farther chunk", embedding=_vector(0.0, 1.0, 0.0), chunk_index=1),
        ],
    )

    results = provider.similarity_search(query_embedding=_vector(0.9, 0.1, 0.0), top_k=5)

    assert [chunk.chunk_text for chunk in results] == ["closer chunk", "farther chunk"]


def test_similarity_search_respects_top_k(provider):
    document_id = str(uuid.uuid4())
    provider.upsert_document(document_id, filename="cv.pdf", doc_type="cv", version="v1")
    provider.upsert_chunks(
        document_id,
        [
            EmbeddedChunk(chunk_text="chunk one", embedding=_vector(1.0, 0.0, 0.0), chunk_index=0),
            EmbeddedChunk(chunk_text="chunk two", embedding=_vector(0.9, 0.1, 0.0), chunk_index=1),
            EmbeddedChunk(chunk_text="chunk three", embedding=_vector(0.8, 0.2, 0.0), chunk_index=2),
        ],
    )

    results = provider.similarity_search(query_embedding=_vector(1.0, 0.0, 0.0), top_k=2)

    assert len(results) == 2


def test_delete_by_document_id_removes_only_that_documents_chunks(provider):
    document_a = str(uuid.uuid4())
    document_b = str(uuid.uuid4())
    provider.upsert_document(document_a, filename="a.pdf", doc_type="cv", version="v1")
    provider.upsert_document(document_b, filename="b.pdf", doc_type="cv", version="v1")
    provider.upsert_chunks(
        document_a, [EmbeddedChunk(chunk_text="from a", embedding=_vector(1.0, 0.0, 0.0), chunk_index=0)]
    )
    provider.upsert_chunks(
        document_b, [EmbeddedChunk(chunk_text="from b", embedding=_vector(1.0, 0.0, 0.0), chunk_index=0)]
    )

    provider.delete_by_document_id(document_a)
    results = provider.similarity_search(query_embedding=_vector(1.0, 0.0, 0.0), top_k=10)

    assert [chunk.chunk_text for chunk in results] == ["from b"]


def test_upsert_chunks_reindex_replaces_prior_chunks_for_the_same_document(provider):
    document_id = str(uuid.uuid4())
    provider.upsert_document(document_id, filename="cv.pdf", doc_type="cv", version="v1")
    provider.upsert_chunks(
        document_id, [EmbeddedChunk(chunk_text="old chunk", embedding=_vector(1.0, 0.0, 0.0), chunk_index=0)]
    )

    provider.upsert_chunks(
        document_id, [EmbeddedChunk(chunk_text="new chunk", embedding=_vector(1.0, 0.0, 0.0), chunk_index=0)]
    )
    results = provider.similarity_search(query_embedding=_vector(1.0, 0.0, 0.0), top_k=10)

    assert [chunk.chunk_text for chunk in results] == ["new chunk"]
