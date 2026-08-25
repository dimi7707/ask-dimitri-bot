import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core.config import Settings
from app.core.prompts import IN_SCOPE_LABEL, OUT_OF_SCOPE_LABEL, SYSTEM_PROMPT
from app.integrations.vector_store.base import RetrievedChunk
from app.main import app

SPANISH_QUESTION = "¿Qué stack maneja Dimitri?"
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


def chunk(text: str, score: float, document_id: str = "doc-1") -> RetrievedChunk:
    return RetrievedChunk(chunk_text=text, score=score, document_id=document_id)


def build_client(
    *,
    chunks: list[RetrievedChunk] | None = None,
    in_scope: bool = True,
    answer: str = GENERATED_ANSWER,
    **settings_overrides,
):
    """Wire the chat route to fake providers, returning the client and the fakes for assertions."""
    embedder = FakeEmbeddingProvider()
    vector_store = FakeVectorStore(chunks)
    generator = FakeGenerationProvider(in_scope=in_scope, answer=answer)
    settings = Settings(_env_file=None, **settings_overrides)

    app.dependency_overrides[deps.get_embedder] = lambda: embedder
    app.dependency_overrides[deps.get_vector_store] = lambda: vector_store
    app.dependency_overrides[deps.get_generator] = lambda: generator
    app.dependency_overrides[deps.get_app_settings] = lambda: settings

    return TestClient(app), embedder, vector_store, generator


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


# --- 11.1 similarity-threshold guard -------------------------------------------------------


def test_best_score_above_threshold_forwards_the_chunks_as_context():
    client, _, _, generator = build_client(
        chunks=[chunk("Python, FastAPI y AWS", 0.82), chunk("Terraform", 0.71)],
        similarity_threshold=0.6,
    )

    response = client.post("/chat", json={"question": SPANISH_QUESTION})

    assert response.status_code == 200
    assert response.json()["answer"] == GENERATED_ANSWER
    assert generator.answer_calls[0]["context"] == ["Python, FastAPI y AWS", "Terraform"]


def test_chunks_below_the_threshold_are_not_forwarded_as_context():
    client, _, _, generator = build_client(
        chunks=[chunk("relevante", 0.82), chunk("ruido", 0.31)],
        similarity_threshold=0.6,
    )

    client.post("/chat", json={"question": SPANISH_QUESTION})

    assert generator.answer_calls[0]["context"] == ["relevante"]


def test_best_score_below_threshold_answers_without_calling_generation():
    client, _, _, generator = build_client(chunks=[chunk("apenas relacionado", 0.42)], similarity_threshold=0.6)

    response = client.post("/chat", json={"question": SPANISH_QUESTION})

    assert response.status_code == 200
    assert "no tengo esa información" in response.json()["answer"].lower()
    assert generator.answer_calls == []


def test_no_retrieved_chunks_answers_that_there_is_no_information():
    client, _, _, generator = build_client(chunks=[], similarity_threshold=0.6)

    response = client.post("/chat", json={"question": SPANISH_QUESTION})

    assert "no tengo esa información" in response.json()["answer"].lower()
    assert generator.answer_calls == []


def test_the_threshold_comes_from_settings():
    client, _, _, generator = build_client(chunks=[chunk("relevante", 0.55)], similarity_threshold=0.5)

    client.post("/chat", json={"question": SPANISH_QUESTION})

    assert generator.answer_calls[0]["context"] == ["relevante"]


def test_retrieval_uses_the_configured_top_k():
    client, embedder, vector_store, _ = build_client(
        chunks=[chunk("relevante", 0.82)], similarity_top_k=3
    )

    client.post("/chat", json={"question": SPANISH_QUESTION})

    assert embedder.embedded_texts == [SPANISH_QUESTION]
    assert vector_store.searches == [([0.1, 0.2, 0.3], 3)]


# --- 11.2 off-topic rejection --------------------------------------------------------------


def test_off_topic_question_is_declined_politely():
    client, _, _, _ = build_client(in_scope=False)

    response = client.post("/chat", json={"question": "¿Cuál es la capital de Francia?"})

    assert response.status_code == 200
    assert "perfil profesional de Dimitri" in response.json()["answer"]


def test_off_topic_question_never_reaches_the_vector_store():
    client, embedder, vector_store, generator = build_client(
        in_scope=False, chunks=[chunk("no deberia consultarse", 0.99)]
    )

    client.post("/chat", json={"question": "¿Cuál es la capital de Francia?"})

    assert vector_store.searches == []
    assert embedder.embedded_texts == []
    assert generator.answer_calls == []
