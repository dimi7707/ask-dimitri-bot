"""Test doubles for the API's provider dependencies, shared by every module under `tests/api`.

They live here rather than in a test module so that importing a fake never drags in someone else's
tests: a test module that imports from another test module makes that module's internals a de-facto
public API, where a rename breaks an unrelated file.
"""

from app.core.prompts import IN_SCOPE_LABEL, OUT_OF_SCOPE_LABEL, SYSTEM_PROMPT
from app.integrations.vector_store.base import RetrievedChunk

GENERATED_ANSWER = "Dimitri trabaja con Python, FastAPI y AWS."


class FakeEmbeddingProvider:
    def __init__(self):
        self.embedded_texts: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.embedded_texts.append(text)
        return [0.1, 0.2, 0.3]


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


class FakeGenerationProvider:
    """Answers the scope-classifier call and the answer call, recording both."""

    def __init__(self, *, in_scope: bool = True, answer: str = GENERATED_ANSWER):
        self._scope_verdict = IN_SCOPE_LABEL if in_scope else OUT_OF_SCOPE_LABEL
        self._answer = answer
        self.calls: list[dict] = []

    def generate(self, system_prompt: str, question: str, context: list[str]) -> str:
        self.calls.append({"system_prompt": system_prompt, "question": question, "context": context})
        return self._answer if system_prompt == SYSTEM_PROMPT else self._scope_verdict

    @property
    def answer_calls(self) -> list[dict]:
        return [call for call in self.calls if call["system_prompt"] == SYSTEM_PROMPT]


class ClosingProvider:
    """A cached provider whose only interesting behavior is recording that it was released.

    It satisfies no capability protocol on purpose: the release path keys on `Closeable` alone, so a
    double that implements nothing else is the narrowest thing that can prove the release happened.
    """

    def __init__(self):
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FailingToCloseProvider(ClosingProvider):
    """Releases badly — the case that decides whether a failed release still empties the caches."""

    def close(self) -> None:
        super().close()
        raise RuntimeError("client refused to close")


def chunk(text: str, score: float, document_id: str = "doc-1") -> RetrievedChunk:
    return RetrievedChunk(chunk_text=text, score=score, document_id=document_id)
