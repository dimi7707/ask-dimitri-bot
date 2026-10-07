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
from app.integrations.vector_store import pgvector_provider
from app.integrations.vector_store.base import RetrievedChunk, VectorStoreProvider
from app.main import app
from tests.api.fakes import FakeEmbeddingProvider, FakeGenerationProvider, FakeVectorStore, chunk

PROBE_DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/askdimitri"

# Every engine that served a request, in order, recorded by the double below. The engine identity a
# request actually used is the property under test, and it is only observable from inside the call.
ENGINES_THAT_SERVED_A_REQUEST: list = []


@pytest.fixture(autouse=True)
def forget_engines_seen():
    ENGINES_THAT_SERVED_A_REQUEST.clear()
    yield
    ENGINES_THAT_SERVED_A_REQUEST.clear()


class EngineHoldingVectorStore(FakeVectorStore):
    """Stands in for the pgvector provider: owns an engine, needs no reachable database.

    `create_engine` is lazy, so this builds a real engine object — the thing whose identity the
    reuse assertions are about — without opening a connection.
    """

    def __init__(self):
        super().__init__([RetrievedChunk(chunk_text="Dimitri trabaja con Python", score=0.9, document_id="doc-1")])
        self._engine = create_engine(PROBE_DATABASE_URL)

    def similarity_search(self, query_embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        ENGINES_THAT_SERVED_A_REQUEST.append(self._engine)
        return super().similarity_search(query_embedding, top_k)


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


def test_two_consecutive_chat_requests_share_one_engine(monkeypatch):
    """The regression guard proper: assert on what the requests used, not on what the module returns.

    Reading the identity back through `deps.get_vector_store()` would bypass FastAPI's dependency
    resolution entirely, so a future route that stopped using the cached dependency would leave this
    test green while the per-request engine came back.
    """
    client = build_chat_client(monkeypatch)

    first = client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})
    second = client.post("/chat", json={"question": "¿Y qué bases de datos usa?"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(ENGINES_THAT_SERVED_A_REQUEST) == 2, "both requests must have reached the vector store"
    assert ENGINES_THAT_SERVED_A_REQUEST[0] is ENGINES_THAT_SERVED_A_REQUEST[1]


def test_the_engine_serving_requests_is_the_cached_providers_engine(monkeypatch):
    client = build_chat_client(monkeypatch)

    client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})

    assert ENGINES_THAT_SERVED_A_REQUEST == [deps.get_vector_store()._engine]


# --- 4.3 the engine is configured for a frozen container ----------------------------------


def capture_engine_kwargs(monkeypatch) -> dict:
    """Record what the provider passes to `create_engine`, asserting on our own call site.

    The alternative is reading `pool._pre_ping` and `pool._max_overflow`, which are SQLAlchemy
    internals: a rename upstream would turn these tests into `AttributeError` rather than a
    meaningful failure.
    """
    captured: dict = {}

    def recording_create_engine(url, **kwargs):
        captured.update(kwargs)
        return create_engine(url)

    monkeypatch.setattr(pgvector_provider, "create_engine", recording_create_engine)
    return captured


def test_pgvector_engine_pre_pings_before_handing_out_a_connection(monkeypatch):
    captured = capture_engine_kwargs(monkeypatch)

    pgvector_provider.PgVectorStoreProvider(database_url=PROBE_DATABASE_URL)

    # Pre-ping is what makes the first request after an idle period survive a connection Aurora
    # closed while the execution environment was frozen.
    assert captured["pool_pre_ping"] is True


def test_pgvector_engine_pool_defaults_to_one_request_per_container(monkeypatch):
    captured = capture_engine_kwargs(monkeypatch)

    pgvector_provider.PgVectorStoreProvider(database_url=PROBE_DATABASE_URL)

    assert captured["pool_size"] == 1
    assert captured["max_overflow"] == 2


def test_pgvector_engine_pool_sizing_is_caller_supplied(monkeypatch):
    """A runtime that serves requests concurrently in one process must be able to size the pool up."""
    captured = capture_engine_kwargs(monkeypatch)

    pgvector_provider.PgVectorStoreProvider(database_url=PROBE_DATABASE_URL, pool_size=5, max_overflow=10)

    assert captured["pool_size"] == 5
    assert captured["max_overflow"] == 10


def test_factory_sizes_the_pool_from_settings(monkeypatch):
    captured = capture_engine_kwargs(monkeypatch)
    monkeypatch.setattr(
        vector_store_factory,
        "get_settings",
        lambda: Settings(_env_file=None, db_pool_size=7, db_max_overflow=3),
    )

    vector_store_factory.get_vector_store_provider()

    assert captured["pool_size"] == 7
    assert captured["max_overflow"] == 3


# --- 4.4 resetting the cache releases the pool ---------------------------------------------


def test_reset_vector_store_disposes_the_engine_before_dropping_the_provider(monkeypatch):
    monkeypatch.setattr(deps, "get_vector_store_provider", EngineHoldingVectorStore)
    provider = deps.get_vector_store()
    disposals = []
    monkeypatch.setattr(provider._engine, "dispose", lambda: disposals.append(True))

    deps.reset_vector_store()

    assert disposals == [True], "the pool was abandoned instead of released"
    assert deps.get_vector_store() is not provider


def test_reset_vector_store_is_safe_when_nothing_is_cached():
    deps.reset_vector_store()  # the fixture already reset it; a second reset must not raise

    assert deps.get_vector_store.cache_info().currsize == 0


# --- 5.1 the cache must not shadow test overrides ------------------------------------------


def test_registered_override_wins_over_the_cached_provider(monkeypatch):
    """The real risk of caching a dependency: FastAPI must still prefer a registered override."""
    monkeypatch.setattr(deps, "get_vector_store_provider", EngineHoldingVectorStore)
    cached_provider = deps.get_vector_store()

    injected = FakeVectorStore([chunk("Python, FastAPI y AWS", 0.82)])
    client = build_chat_client(monkeypatch)
    app.dependency_overrides[deps.get_vector_store] = lambda: injected

    response = client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})

    assert response.status_code == 200
    assert injected.searches, "the override was never used; the cache shadowed it"
    assert not ENGINES_THAT_SERVED_A_REQUEST, "an engine-holding provider served the request"
    assert deps.get_vector_store() is cached_provider
