from fastapi import APIRouter, Depends

from app.api.deps import get_app_settings, get_embedder, get_generator, get_vector_store
from app.core.config import Settings
from app.core.language import detect_language
from app.core.prompts import NO_INFORMATION_ANSWER, OFF_TOPIC_ANSWER
from app.integrations.embeddings.base import EmbeddingProvider
from app.integrations.generation.base import GenerationProvider
from app.integrations.vector_store.base import VectorStoreProvider
from app.models.schemas import ChatRequest, ChatResponse, DebugChunk, DebugContext
from app.services.generation import classify_scope, generate_answer
from app.services.retrieval import RetrievalResult, retrieve

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
def chat(
    request: ChatRequest,
    settings: Settings = Depends(get_app_settings),
    embedder: EmbeddingProvider = Depends(get_embedder),
    vector_store: VectorStoreProvider = Depends(get_vector_store),
    generator: GenerationProvider = Depends(get_generator),
) -> ChatResponse:
    """Answer a question about Dimitri's professional profile from the ingested documents.

    Two guards run before any context reaches the model: off-topic questions are declined
    without retrieval, and retrievals whose best score misses SIMILARITY_THRESHOLD are answered
    as "no information" without a generation call, so the model can never fill the gap itself.
    """
    question = request.question
    language = detect_language(question)

    if not classify_scope(question, provider=generator):
        return ChatResponse(answer=OFF_TOPIC_ANSWER[language])

    retrieval = retrieve(
        question,
        embedder=embedder,
        vector_store=vector_store,
        top_k=settings.similarity_top_k,
    )
    debug_context = _build_debug_context(retrieval, settings)

    if retrieval.best_score < settings.similarity_threshold:
        return ChatResponse(answer=NO_INFORMATION_ANSWER[language], debug_context=debug_context)

    relevant_chunks = [
        chunk for chunk in retrieval.chunks if chunk.score >= settings.similarity_threshold
    ]
    answer = generate_answer(question, relevant_chunks, provider=generator)
    return ChatResponse(answer=answer, debug_context=debug_context)


def _build_debug_context(retrieval: RetrievalResult, settings: Settings) -> DebugContext | None:
    if not settings.include_debug_context:
        return None
    return DebugContext(
        similarity_threshold=settings.similarity_threshold,
        chunks_retrieved=[DebugChunk.from_retrieved(chunk) for chunk in retrieval.chunks],
    )
