from pydantic import BaseModel, Field, field_validator

from app.integrations.vector_store.base import RetrievedChunk


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, description="Question about Dimitri's professional profile")

    @field_validator("question")
    @classmethod
    def _reject_blank_question(cls, value: str) -> str:
        """Reject whitespace-only questions at validation time, before any provider is called."""
        question = value.strip()
        if not question:
            raise ValueError("question must not be blank")
        return question


class DebugChunk(BaseModel):
    chunk_text: str
    score: float
    document_id: str

    @classmethod
    def from_retrieved(cls, chunk: RetrievedChunk) -> "DebugChunk":
        return cls(chunk_text=chunk.chunk_text, score=chunk.score, document_id=chunk.document_id)


class DebugContext(BaseModel):
    """Retrieval diagnostics, returned only when INCLUDE_DEBUG_CONTEXT is enabled."""

    similarity_threshold: float
    chunks_retrieved: list[DebugChunk]


class ChatResponse(BaseModel):
    answer: str
    # Serialized with exclude_none, so the field is absent (not null) when debugging is off.
    debug_context: DebugContext | None = None
