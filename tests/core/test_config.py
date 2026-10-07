import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_defaults_match_spec_values():
    settings = Settings(_env_file=None)

    assert settings.bedrock_model_id == "amazon.nova-micro-v1:0"
    assert settings.embedding_model_id == "amazon.titan-embed-text-v2:0"
    assert settings.similarity_threshold == 0.6
    assert settings.include_debug_context is False
    assert settings.chunk_size == 512
    assert settings.chunk_overlap == 50
    # Lambda serves one request per container at a time; the overflow is headroom, not concurrency.
    assert settings.db_pool_size == 1
    assert settings.db_max_overflow == 2


def test_settings_defaults_select_current_providers():
    settings = Settings(_env_file=None)

    assert settings.storage_provider == "s3"
    assert settings.embedding_provider == "bedrock"
    assert settings.llm_provider == "bedrock"
    assert settings.vector_store_provider == "pgvector"
    assert settings.document_processor == "llamaindex"


def test_settings_honors_environment_variable_overrides(monkeypatch):
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.75")
    monkeypatch.setenv("INCLUDE_DEBUG_CONTEXT", "true")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-haiku-v1")
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "10")

    settings = Settings(_env_file=None)

    assert settings.similarity_threshold == 0.75
    assert settings.include_debug_context is True
    assert settings.bedrock_model_id == "anthropic.claude-haiku-v1"
    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 10


@pytest.mark.parametrize(
    ("variable", "value"),
    [("DB_POOL_SIZE", "0"), ("DB_MAX_OVERFLOW", "-1")],
)
def test_settings_rejects_pool_values_sqlalchemy_reads_as_unbounded(monkeypatch, variable, value):
    """SQLAlchemy treats pool_size=0 and max_overflow=-1 as *no limit* — the inverse of the intent."""
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
