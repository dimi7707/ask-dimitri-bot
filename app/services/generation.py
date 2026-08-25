from app.core.prompts import OUT_OF_SCOPE_LABEL, SCOPE_CLASSIFIER_PROMPT, SYSTEM_PROMPT
from app.integrations.generation.base import GenerationProvider
from app.integrations.vector_store.base import RetrievedChunk


def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    provider: GenerationProvider,
) -> str:
    """Answer `question` grounded in `chunks`, which the provider passes as delimited context."""
    return provider.generate(
        system_prompt=SYSTEM_PROMPT,
        question=question,
        context=[chunk.chunk_text for chunk in chunks],
    )


def classify_scope(question: str, *, provider: GenerationProvider) -> bool:
    """Return whether `question` is about Dimitri's professional profile.

    Runs before retrieval so off-topic questions are declined without touching the vector store.
    An unrecognized classifier answer is treated as in-scope: the similarity threshold still
    guards the response, so ambiguity should not cost a legitimate question its answer.
    """
    verdict = provider.generate(system_prompt=SCOPE_CLASSIFIER_PROMPT, question=question, context=[])
    return verdict.strip().upper() != OUT_OF_SCOPE_LABEL
