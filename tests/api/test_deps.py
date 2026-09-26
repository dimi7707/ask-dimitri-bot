"""Provider lifecycle: one engine per process, reused across requests.

The defect these cover (adb-001): `get_vector_store` was an uncached dependency, so every
`POST /chat` built a new SQLAlchemy engine and therefore a new Postgres connection pool. FastAPI's
own dependency cache only spans a single request, so nothing prevented it.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api import deps
from app.core.config import Settings
from app.integrations.vector_store import factory as vector_store_factory
from app.integrations.vector_store.base import RetrievedChunk, VectorStoreProvider
from app.main import app

PROBE_DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/askdimitri"


@pytest.fixture(autouse=True)
def fresh_vector_store_cache():
    """Isolate the module-level provider cache, which otherwise outlives a single test."""
    deps.get_vector_store.cache_clear()
    yield
    deps.get_vector_store.cache_clear()
    app.dependency_overrides.clear()


class EngineHoldingVectorStore:
    """Stands in for the pgvector provider: owns an engine, needs no reachable database.

    `create_engine` is lazy, so this builds a real engine object — the thing whose identity the
    reuse assertions are about — without opening a connection.
    """

    def __init__(self):
        self._engine = create_engine(PROBE_DATABASE_URL)

    def upsert_document(self, document_id, filename, doc_type, version) -> None: ...

    def upsert_chunks(self, document_id, chunks) -> None: ...

    def delete_by_document_id(self, document_id) -> None: ...

    def similarity_search(self, query_embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        return [RetrievedChunk(chunk_text="Dimitri trabaja con Python", score=0.9, document_id="doc-1")]


def test_engine_holding_vector_store_satisfies_the_protocol():
    assert isinstance(EngineHoldingVectorStore(), VectorStoreProvider)


# --- 4.1 the dependency caches the provider ------------------------------------------------


def test_get_vector_store_returns_the_same_provider_across_calls(monkeypatch):
    builds = []

    def build_provider():
        provider = EngineHoldingVectorStore()
        builds.append(provider)
        return provider

    monkeypatch.setattr(deps, "get_vector_store_provider", build_provider)

    first, second = deps.get_vector_store(), deps.get_vector_store()

    assert first is second
    assert len(builds) == 1, "the factory ran more than once, so the provider is not cached"


def test_cached_provider_keeps_one_engine(monkeypatch):
    monkeypatch.setattr(deps, "get_vector_store_provider", EngineHoldingVectorStore)

    first, second = deps.get_vector_store(), deps.get_vector_store()

    assert first._engine is second._engine


# --- 4.2 two requests share one engine ----------------------------------------------------


def build_chat_client(monkeypatch):
    """Wire /chat to fake embedding and generation, but leave the real vector store dependency.

    Overriding `get_vector_store` here would defeat the purpose: the cache under test lives in that
    dependency, so it has to stay on the real resolution path.
    """
    from tests.api.test_chat import FakeEmbeddingProvider, FakeGenerationProvider

    monkeypatch.setitem(vector_store_factory.PROVIDERS, "engine-holding", EngineHoldingVectorStore)
    monkeypatch.setattr(
        vector_store_factory,
        "get_settings",
        lambda: Settings(_env_file=None, vector_store_provider="engine-holding"),
    )

    app.dependency_overrides[deps.get_embedder] = lambda: FakeEmbeddingProvider()
    app.dependency_overrides[deps.get_generator] = lambda: FakeGenerationProvider()
    app.dependency_overrides[deps.get_app_settings] = lambda: Settings(_env_file=None, similarity_threshold=0.6)

    return TestClient(app)


def test_two_consecutive_chat_requests_share_one_provider_and_engine(monkeypatch):
    client = build_chat_client(monkeypatch)

    first = client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})
    provider_after_first = deps.get_vector_store()
    second = client.post("/chat", json={"question": "¿Y qué bases de datos usa?"})
    provider_after_second = deps.get_vector_store()

    assert first.status_code == 200
    assert second.status_code == 200
    assert provider_after_first is provider_after_second
    assert provider_after_first._engine is provider_after_second._engine


# --- 4.3 the engine is configured for a frozen container ----------------------------------


def test_pgvector_engine_pre_pings_before_handing_out_a_connection():
    from app.integrations.vector_store.pgvector_provider import PgVectorStoreProvider

    pool = PgVectorStoreProvider(database_url=PROBE_DATABASE_URL)._engine.pool

    # `_pre_ping` is a SQLAlchemy internal, but it is the only place the setting is observable, and
    # it is what makes the first request after an idle period survive a connection Aurora closed.
    assert pool._pre_ping is True


def test_pgvector_engine_pool_is_sized_for_one_request_per_container():
    from app.integrations.vector_store.pgvector_provider import PgVectorStoreProvider

    pool = PgVectorStoreProvider(database_url=PROBE_DATABASE_URL)._engine.pool

    assert pool.size() == 1
    assert pool._max_overflow == 2


# --- 5.1 the cache must not shadow test overrides ------------------------------------------


def test_registered_override_wins_over_the_cached_provider(monkeypatch):
    """The real risk of caching a dependency: FastAPI must still prefer a registered override."""
    monkeypatch.setattr(deps, "get_vector_store_provider", EngineHoldingVectorStore)
    cached_provider = deps.get_vector_store()

    from tests.api.test_chat import FakeVectorStore, chunk

    injected = FakeVectorStore([chunk("Python, FastAPI y AWS", 0.82)])
    client = build_chat_client(monkeypatch)
    app.dependency_overrides[deps.get_vector_store] = lambda: injected

    response = client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})

    assert response.status_code == 200
    assert injected.searches, "the override was never used; the cache shadowed it"
    assert not hasattr(injected, "_engine")
    assert deps.get_vector_store() is cached_provider
