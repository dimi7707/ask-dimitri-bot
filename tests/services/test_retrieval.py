from app.integrations.vector_store.base import RetrievedChunk
from app.services.retrieval import retrieve

QUESTION = "¿Qué stack maneja Dimitri?"


class FakeEmbeddingProvider:
    def __init__(self, vector: list[float] | None = None):
        self.vector = vector or [0.1, 0.2, 0.3]
        self.embedded_texts: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.embedded_texts.append(text)
        return self.vector


class FakeVectorStore:
    def __init__(self, chunks: list[RetrievedChunk] | None = None):
        self._chunks = chunks or []
        self.searches: list[tuple[list[float], int]] = []

    def upsert_document(self, document_id, filename, doc_type, version) -> None: ...

    def upsert_chunks(self, document_id, chunks) -> None: ...

    def delete_by_document_id(self, document_id) -> None: ...

    def similarity_search(self, query_embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        self.searches.append((query_embedding, top_k))
        return self._chunks


def _chunk(text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(chunk_text=text, score=score, document_id="doc-1")


def test_retrieve_embeds_the_question_and_searches_with_that_vector():
    embedder = FakeEmbeddingProvider(vector=[0.4, 0.5, 0.6])
    vector_store = FakeVectorStore()

    retrieve(QUESTION, embedder=embedder, vector_store=vector_store, top_k=5)

    assert embedder.embedded_texts == [QUESTION]
    assert vector_store.searches == [([0.4, 0.5, 0.6], 5)]


def test_retrieve_returns_the_chunks_in_the_order_the_store_returned_them():
    chunks = [_chunk("mas relevante", 0.9), _chunk("menos relevante", 0.7)]

    result = retrieve(
        QUESTION, embedder=FakeEmbeddingProvider(), vector_store=FakeVectorStore(chunks), top_k=5
    )

    assert [chunk.chunk_text for chunk in result.chunks] == ["mas relevante", "menos relevante"]


def test_retrieve_reports_the_best_score_among_the_retrieved_chunks():
    chunks = [_chunk("a", 0.72), _chunk("b", 0.81), _chunk("c", 0.65)]

    result = retrieve(
        QUESTION, embedder=FakeEmbeddingProvider(), vector_store=FakeVectorStore(chunks), top_k=5
    )

    assert result.best_score == 0.81


def test_retrieve_reports_a_zero_best_score_when_nothing_is_retrieved():
    result = retrieve(QUESTION, embedder=FakeEmbeddingProvider(), vector_store=FakeVectorStore(), top_k=5)

    assert result.chunks == []
    assert result.best_score == 0.0


def test_retrieve_honors_the_requested_top_k():
    vector_store = FakeVectorStore()

    retrieve(QUESTION, embedder=FakeEmbeddingProvider(), vector_store=vector_store, top_k=3)

    assert vector_store.searches[0][1] == 3
