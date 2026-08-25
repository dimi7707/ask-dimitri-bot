import pytest

from app.core.language import detect_language


@pytest.mark.parametrize(
    "question",
    [
        "¿Qué stack maneja Dimitri?",
        "Cuentame sobre su experiencia laboral",
        "Dimitri trabaja con Python y AWS",
    ],
)
def test_detect_language_recognizes_spanish(question):
    assert detect_language(question) == "es"


@pytest.mark.parametrize(
    "question",
    [
        "What stack does Dimitri work with?",
        "Tell me about his professional experience",
        "Which companies has he worked for?",
    ],
)
def test_detect_language_recognizes_english(question):
    assert detect_language(question) == "en"


def test_detect_language_defaults_to_spanish_when_there_is_no_signal():
    assert detect_language("") == "es"
    assert detect_language("Python AWS FastAPI") == "es"
