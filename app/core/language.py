"""Question language detection, used to pick the language of the canned (non-LLM) answers.

Context-grounded answers get their language from the system prompt instead; this only has to
choose between the two languages the assistant supports, so a marker-word heuristic is enough
and keeps the threshold/off-topic short-circuits free of an extra model call.
"""

import re

SPANISH = "es"
ENGLISH = "en"

# Characters that essentially never appear in an English question.
SPANISH_ONLY_CHARACTERS = frozenset("áéíóúüñ¿¡")

SPANISH_MARKERS = frozenset(
    {
        "que", "qué", "cual", "cuál", "cuales", "cuáles", "donde", "dónde", "como", "cómo",
        "quien", "quién", "cuando", "cuándo", "cuanto", "cuánto", "es", "son", "está", "esta",
        "el", "la", "los", "las", "del", "de", "con", "para", "por", "sus", "su", "y", "o",
        "tiene", "trabaja", "trabajo", "trabajado", "sabe", "maneja", "experiencia", "habilidades",
        "empresa", "empresas", "estudios", "proyectos", "cuentame", "cuéntame", "dime", "sobre",
    }
)

ENGLISH_MARKERS = frozenset(
    {
        "what", "which", "where", "how", "who", "when", "whose", "is", "are", "was", "were",
        "the", "of", "with", "for", "and", "or", "his", "her", "their", "does", "do", "did",
        "have", "has", "had", "can", "tell", "me", "about", "work", "works", "worked", "working",
        "experience", "skills", "company", "companies", "studies", "projects", "he", "she",
    }
)

_WORD_PATTERN = re.compile(r"[a-záéíóúüñ]+")


def detect_language(text: str) -> str:
    """Return "es" or "en" for `text`, defaulting to Spanish when neither language shows a signal."""
    lowered = text.lower()
    if SPANISH_ONLY_CHARACTERS.intersection(lowered):
        return SPANISH

    words = set(_WORD_PATTERN.findall(lowered))
    english_hits = len(words & ENGLISH_MARKERS)
    spanish_hits = len(words & SPANISH_MARKERS)
    return ENGLISH if english_hits > spanish_hits else SPANISH
