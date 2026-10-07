from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Generation / embeddings (Bedrock) — swappable via env var without code changes.
    bedrock_model_id: str = "amazon.nova-micro-v1:0"
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"

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
