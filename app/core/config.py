from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Generation / embeddings (Bedrock) — swappable via env var without code changes.
    bedrock_model_id: str = "amazon.nova-micro-v1:0"
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"

    # Ceiling on a single Bedrock call, applied to every client the providers build. The defaults
    # are sized for Lambda's 30 s timeout: 2 attempts x (3 s connect + 8 s read) is ~22 s worst
    # case, where botocore's own defaults (60 s read, legacy mode's 5 attempts) let one hung call
    # consume the whole budget. The tighter ceiling costs retries, which is the deliberate trade.
    # Bounded because botocore reads a timeout of 0 or None as *no timeout* — the inverse of the
    # intent here, and one `.env` typo away.
    bedrock_connect_timeout: float = Field(default=3, gt=0)
    bedrock_read_timeout: float = Field(default=8, gt=0)
    bedrock_max_attempts: int = Field(default=2, ge=1)

    # RAG retrieval tuning.
    similarity_threshold: float = 0.6
    similarity_top_k: int = 5
    include_debug_context: bool = False

    # Document chunking (tokens), applied at ingestion time.
    chunk_size: int = 512
    chunk_overlap: int = 50

    # Provider selectors resolved by app/integrations/*/factory.py.
    storage_provider: str = "s3"
    embedding_provider: str = "bedrock"
    llm_provider: str = "bedrock"
    vector_store_provider: str = "pgvector"
    document_processor: str = "llamaindex"

    # Vector store. The pool defaults match Lambda, which serves one request per container at a
    # time; a runtime that handles concurrency in-process (uvicorn, provisioned concurrency) should
    # raise them via env vars rather than queueing requests behind a single connection.
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/askdimitri"
    # Bounded because SQLAlchemy reads the low end as "no limit": a `pool_size` of 0 and a
    # `max_overflow` of -1 both mean *unbounded* connections, which is the inverse of the intent
    # here and is one `.env` typo away.
    db_pool_size: int = Field(default=1, ge=1)
    db_max_overflow: int = Field(default=2, ge=0)

    # Object storage (S3 in prod, LocalStack locally via s3_endpoint_url).
    aws_region: str = "us-east-1"
    s3_bucket_name: str = "askdimitri-documents"
    s3_endpoint_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
