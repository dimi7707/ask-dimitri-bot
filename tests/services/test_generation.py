from app.core.prompts import SCOPE_CLASSIFIER_PROMPT, SYSTEM_PROMPT
from app.integrations.vector_store.base import RetrievedChunk
from app.services.generation import classify_scope, generate_answer

QUESTION = "¿Qué stack maneja Dimitri?"


class FakeGenerationProvider:
    def __init__(self, answer: str = "Dimitri trabaja con Python y AWS."):
        self._answer = answer
        self.calls: list[dict] = []

    def generate(self, system_prompt: str, question: str, context: list[str]) -> str:
        self.calls.append({"system_prompt": system_prompt, "question": question, "context": context})
        return self._answer


def _chunk(text: str) -> RetrievedChunk:
    return RetrievedChunk(chunk_text=text, score=0.9, document_id="doc-1")


def test_generate_answer_returns_the_provider_answer():
    provider = FakeGenerationProvider(answer="Trabaja con Python, FastAPI y AWS.")

    answer = generate_answer(QUESTION, [_chunk("Python, FastAPI y AWS")], provider=provider)

    assert answer == "Trabaja con Python, FastAPI y AWS."


def test_generate_answer_uses_the_shared_system_prompt():
    provider = FakeGenerationProvider()

    generate_answer(QUESTION, [_chunk("Python")], provider=provider)

    assert provider.calls[0]["system_prompt"] == SYSTEM_PROMPT
    assert provider.calls[0]["question"] == QUESTION


def test_generate_answer_passes_the_retrieved_chunk_texts_as_context_in_order():
    provider = FakeGenerationProvider()
    chunks = [_chunk("mas relevante"), _chunk("menos relevante")]

    generate_answer(QUESTION, chunks, provider=provider)

    assert provider.calls[0]["context"] == ["mas relevante", "menos relevante"]


def test_generate_answer_without_chunks_passes_an_empty_context():
    provider = FakeGenerationProvider()

    generate_answer(QUESTION, [], provider=provider)

    assert provider.calls[0]["context"] == []


def test_classify_scope_accepts_a_question_the_classifier_marks_in_scope():
    provider = FakeGenerationProvider(answer="IN_SCOPE")

    assert classify_scope(QUESTION, provider=provider) is True
    assert provider.calls[0]["system_prompt"] == SCOPE_CLASSIFIER_PROMPT


def test_classify_scope_rejects_a_question_the_classifier_marks_out_of_scope():
    provider = FakeGenerationProvider(answer="OUT_OF_SCOPE")

    assert classify_scope("¿Cuál es la capital de Francia?", provider=provider) is False


def test_classify_scope_tolerates_surrounding_whitespace_and_casing():
    provider = FakeGenerationProvider(answer="  out_of_scope\n")

    assert classify_scope("¿Cuál es la capital de Francia?", provider=provider) is False


def test_classify_scope_never_sends_document_context_to_the_classifier():
    provider = FakeGenerationProvider(answer="IN_SCOPE")

    classify_scope(QUESTION, provider=provider)

    assert provider.calls[0]["context"] == []


def test_classify_scope_falls_back_to_in_scope_on_an_unexpected_classifier_answer():
    """The similarity threshold is the real backstop, so ambiguity must not silently drop a valid question."""
    provider = FakeGenerationProvider(answer="no estoy seguro")

    assert classify_scope(QUESTION, provider=provider) is True
