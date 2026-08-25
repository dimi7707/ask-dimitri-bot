from app.core.config import Settings


def test_settings_defaults_match_spec_values():
    settings = Settings(_env_file=None)

    assert settings.bedrock_model_id == "amazon.nova-micro-v1:0"
    assert settings.embedding_model_id == "amazon.titan-embed-text-v2:0"
    assert settings.similarity_threshold == 0.6
    assert settings.include_debug_context is False
    assert settings.chunk_size == 512
    assert settings.chunk_overlap == 50


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

    settings = Settings(_env_file=None)

    assert settings.similarity_threshold == 0.75
    assert settings.include_debug_context is True
    assert settings.bedrock_model_id == "anthropic.claude-haiku-v1"
