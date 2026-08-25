from dataclasses import dataclass

from app.integrations.embeddings.base import EmbeddingProvider
from app.integrations.vector_store.base import RetrievedChunk, VectorStoreProvider


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    best_score: float


def retrieve(
    question: str,
    *,
    embedder: EmbeddingProvider,
    vector_store: VectorStoreProvider,
    top_k: int,
) -> RetrievalResult:
    """Embed the question and return the closest chunks along with their best similarity score.

    `best_score` is what the chat route compares against SIMILARITY_THRESHOLD; it is 0.0 when
    nothing was retrieved, so an empty store can never clear the threshold.
    """
    query_embedding = embedder.embed(question)
    chunks = vector_store.similarity_search(query_embedding, top_k)
    best_score = max((chunk.score for chunk in chunks), default=0.0)
    return RetrievalResult(chunks=chunks, best_score=best_score)
