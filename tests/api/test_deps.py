"""Provider lifecycle: one provider per process, reused across requests.

The defect these cover (adb-001, then adb-002): the provider dependencies were uncached, so every
`POST /chat` built a new SQLAlchemy engine — and a new Postgres connection pool — plus a new boto3
client and a new `ChatBedrock`, each with its own HTTPS connection pool to the Bedrock endpoint.
FastAPI's own dependency cache only spans a single request, so nothing prevented it.
"""

import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api import deps
from app.core.config import Settings, get_settings
from app.integrations.embeddings import bedrock_provider as embeddings_bedrock_provider
from app.integrations.embeddings import factory as embeddings_factory
from app.integrations.embeddings.bedrock_provider import BedrockEmbeddingProvider
from app.integrations.generation import bedrock_provider as generation_bedrock_provider
from app.integrations.generation import factory as generation_factory
from app.integrations.vector_store import factory as vector_store_factory
from app.integrations.vector_store import pgvector_provider
from app.integrations.vector_store.base import RetrievedChunk, VectorStoreProvider
from app.main import app
from tests.api.fakes import (
    ClosingProvider,
    FailingToCloseProvider,
    FakeEmbeddingProvider,
    FakeGenerationProvider,
    FakeVectorStore,
    chunk,
)

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

    def close(self) -> None:
        """Dispose like the real provider does, because the release path keys on `Closeable`.

        `FakeVectorStore` declares no `close()`, so without this the double is not `Closeable` and a
        reset would skip its dispose entirely — leaving the reset tests below asserting nothing. The
        repair is this method, never an `_engine` sniff back in `deps._release`: reaching for a
        private attribute is exactly the coupling `Closeable` exists to remove.
        """
        self._engine.dispose()

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


@pytest.fixture
def fresh_settings():
    """`get_settings` is `lru_cache`d, so an env-var test has to drop the memoized Settings.

    The providers go with it: they are cached too, so a provider built from the previous `Settings`
    would otherwise survive this fixture and answer for the settings the test is about to change.
    """
    get_settings.cache_clear()
    deps.reset_providers()
    yield
    get_settings.cache_clear()
    deps.reset_providers()


def test_pool_sizing_flows_from_the_environment_to_the_engine(monkeypatch, fresh_settings):
    """The end-to-end path the spec scenario describes: env var -> Settings -> factory -> engine."""
    captured = capture_engine_kwargs(monkeypatch)
    monkeypatch.setenv("DB_POOL_SIZE", "4")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "6")

    vector_store_factory.get_vector_store_provider()

    assert captured["pool_size"] == 4
    assert captured["max_overflow"] == 6


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


def test_reset_vector_store_builds_nothing_when_nothing_is_cached(monkeypatch):
    """Resetting an empty cache must not resolve a provider — on a cold Lambda that would connect."""

    def must_not_be_called():
        raise AssertionError("reset constructed a provider instead of short-circuiting")

    monkeypatch.setattr(deps, "get_vector_store_provider", must_not_be_called)

    deps.reset_vector_store()  # the fixture already reset it; a second reset must not raise

    assert deps.get_vector_store.cache_info().currsize == 0


def test_reset_vector_store_clears_the_cache_even_if_dispose_fails(monkeypatch):
    """A failed dispose must not leave the stale provider behind for everything that runs next."""
    monkeypatch.setattr(deps, "get_vector_store_provider", EngineHoldingVectorStore)
    provider = deps.get_vector_store()

    def failing_dispose():
        raise RuntimeError("socket refused to close")

    monkeypatch.setattr(provider._engine, "dispose", failing_dispose)

    with pytest.raises(RuntimeError):
        deps.reset_vector_store()

    assert deps.get_vector_store.cache_info().currsize == 0
    assert deps.get_vector_store() is not provider


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


# --- adb-002 2.x the Bedrock provider dependencies cache too -------------------------------

# What each recorder holds, in order. As with the engines above, the property under test is what a
# request actually used, which is only observable from inside the call.
EMBEDDERS_THAT_SERVED_A_REQUEST: list = []
EMBEDDING_CLIENTS_BUILT: list = []
CHAT_MODELS_THAT_SERVED_A_CALL: list = []
CHAT_MODELS_BUILT: list = []

# Doubles as the chat model's answer *and* as an unrecognized classifier verdict, which is what lets
# one double drive both generation calls a request makes.
CHAT_MODEL_ANSWER = "Dimitri trabaja con Python, FastAPI y AWS."


@pytest.fixture(autouse=True)
def forget_bedrock_objects_seen():
    for recorder in (
        EMBEDDERS_THAT_SERVED_A_REQUEST,
        EMBEDDING_CLIENTS_BUILT,
        CHAT_MODELS_THAT_SERVED_A_CALL,
        CHAT_MODELS_BUILT,
    ):
        recorder.clear()
    yield
    for recorder in (
        EMBEDDERS_THAT_SERVED_A_REQUEST,
        EMBEDDING_CLIENTS_BUILT,
        CHAT_MODELS_THAT_SERVED_A_CALL,
        CHAT_MODELS_BUILT,
    ):
        recorder.clear()


class RecordingBedrockClient:
    """Enough of a `bedrock-runtime` client for `embed()` to return a vector and for a release."""

    def __init__(self):
        self.closed = 0

    def invoke_model(self, **kwargs):
        return {"body": io.BytesIO(json.dumps({"embedding": [0.1, 0.2, 0.3]}).encode())}

    def close(self) -> None:
        self.closed += 1


class CountingBoto3:
    """Stands in for the `boto3` module inside the embedding provider, counting client builds.

    Scoped to that one module deliberately: `ChatBedrock` builds two clients of its own on the
    generation path, which the embedding-client count is not about.
    """

    @staticmethod
    def client(service_name, **kwargs):
        client = RecordingBedrockClient()
        EMBEDDING_CLIENTS_BUILT.append((service_name, kwargs, client))
        return client


class RecordingBedrockEmbeddingProvider(BedrockEmbeddingProvider):
    """The real provider, plus a record of which instance served each `embed()` call.

    Subclassing rather than reimplementing keeps the constructor — and therefore whatever the real
    provider requires — in one place, so this double cannot drift from the thing under test.
    """

    def embed(self, text: str) -> list[float]:
        EMBEDDERS_THAT_SERVED_A_REQUEST.append(self)
        return super().embed(text)


class RecordingChatModel:
    """Stands in for `ChatBedrock`: records which instance served each call, and owns two clients.

    Two, because the real one does (`client` for `bedrock-runtime`, `bedrock_client` for the
    `bedrock` control plane), and the provider's `close()` has to release both.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.client = RecordingBedrockClient()
        self.bedrock_client = RecordingBedrockClient()

    def invoke(self, messages):
        CHAT_MODELS_THAT_SERVED_A_CALL.append(self)
        return SimpleNamespace(content=CHAT_MODEL_ANSWER)


def build_chat_client_with_the_real_embedder(monkeypatch) -> TestClient:
    """Wire /chat to fakes except the embedding dependency, which stays on the real path.

    Overriding `get_embedder` here would defeat the purpose — the cache under test lives in that
    dependency. `boto3` is replaced inside the provider module instead, so the real factory, the
    real provider and the real cache all run while no AWS call is ever made.
    """
    monkeypatch.setattr(embeddings_bedrock_provider, "boto3", CountingBoto3)
    monkeypatch.setattr(
        embeddings_bedrock_provider, "BedrockEmbeddingProvider", RecordingBedrockEmbeddingProvider
    )
    # `_build_bedrock_provider` imports the class at call time and reads settings itself, so pinning
    # these two keeps the test independent of whatever a developer's `.env` selects.
    monkeypatch.setattr(embeddings_factory, "get_settings", lambda: Settings(_env_file=None))

    app.dependency_overrides[deps.get_vector_store] = lambda: FakeVectorStore(
        [chunk("Python, FastAPI y AWS", 0.82)]
    )
    app.dependency_overrides[deps.get_generator] = lambda: FakeGenerationProvider()
    app.dependency_overrides[deps.get_app_settings] = lambda: Settings(_env_file=None, similarity_threshold=0.6)

    return TestClient(app)


def build_chat_client_with_the_real_generator(monkeypatch) -> TestClient:
    """Wire /chat to fakes except the generation dependency, which stays on the real path.

    The double is installed at the module symbol `ChatBedrock` rather than through the provider's
    `chat_model=` argument: that argument skips `_get_chat_model()`'s lazy branch, which is the
    thing whose per-process reuse is in question.
    """

    def build_chat_model(**kwargs):
        chat_model = RecordingChatModel(**kwargs)
        CHAT_MODELS_BUILT.append(chat_model)
        return chat_model

    monkeypatch.setattr(generation_bedrock_provider, "ChatBedrock", build_chat_model)
    monkeypatch.setattr(generation_factory, "get_settings", lambda: Settings(_env_file=None))

    app.dependency_overrides[deps.get_embedder] = lambda: FakeEmbeddingProvider()
    app.dependency_overrides[deps.get_vector_store] = lambda: FakeVectorStore(
        [chunk("Python, FastAPI y AWS", 0.82)]
    )
    app.dependency_overrides[deps.get_app_settings] = lambda: Settings(_env_file=None, similarity_threshold=0.6)

    return TestClient(app)


def test_get_embedder_returns_the_same_provider_across_calls(monkeypatch):
    builds = []

    def build_provider():
        provider = FakeEmbeddingProvider()
        builds.append(provider)
        return provider

    monkeypatch.setattr(deps, "get_embedding_provider", build_provider)

    first, second = deps.get_embedder(), deps.get_embedder()

    assert first is second
    # Identity alone passes vacuously if something memoizes a layer down; the counter is what makes
    # this an assertion about the cache rather than about the factory's internals.
    assert len(builds) == 1, "the factory ran more than once, so the provider is not cached"


def test_get_generator_returns_the_same_provider_across_calls(monkeypatch):
    builds = []

    def build_provider():
        provider = FakeGenerationProvider()
        builds.append(provider)
        return provider

    monkeypatch.setattr(deps, "get_generation_provider", build_provider)

    first, second = deps.get_generator(), deps.get_generator()

    assert first is second
    assert len(builds) == 1, "the factory ran more than once, so the provider is not cached"


def test_two_consecutive_chat_requests_share_one_embedding_provider(monkeypatch):
    client = build_chat_client_with_the_real_embedder(monkeypatch)

    first = client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})
    second = client.post("/chat", json={"question": "¿Y qué bases de datos usa?"})

    assert (first.status_code, second.status_code) == (200, 200)
    assert len(EMBEDDERS_THAT_SERVED_A_REQUEST) == 2, "both requests must have reached the embedder"
    assert EMBEDDERS_THAT_SERVED_A_REQUEST[0] is EMBEDDERS_THAT_SERVED_A_REQUEST[1]


def test_two_consecutive_chat_requests_build_one_embedding_client(monkeypatch):
    """The cost this change is actually about: one client means one HTTPS connection pool.

    Provider identity implies client identity only because the client is built eagerly in
    `__init__` — an implementation fact, not a tested one. A refactor to a per-call client would
    leave the identity test above green while every embedding call went back to handshaking.
    """
    client = build_chat_client_with_the_real_embedder(monkeypatch)

    client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})
    client.post("/chat", json={"question": "¿Y qué bases de datos usa?"})

    assert len(EMBEDDING_CLIENTS_BUILT) == 1, "the second request built its own Bedrock client"
    assert EMBEDDING_CLIENTS_BUILT[0][0] == "bedrock-runtime"


def test_two_consecutive_chat_requests_share_one_chat_model(monkeypatch):
    """`_get_chat_model()`'s "then reuse it" becomes true across requests, not just within one.

    Scoped to the success path: a `ChatBedrock` whose construction raises is not memoized, so a
    credential failure still retries per request (adb-002 OQ-4).
    """
    client = build_chat_client_with_the_real_generator(monkeypatch)

    first = client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})
    second = client.post("/chat", json={"question": "¿Y qué bases de datos usa?"})

    assert (first.status_code, second.status_code) == (200, 200)
    # Two calls per request: the scope classifier, then the answer.
    assert len(CHAT_MODELS_THAT_SERVED_A_CALL) == 4
    assert all(served is CHAT_MODELS_THAT_SERVED_A_CALL[0] for served in CHAT_MODELS_THAT_SERVED_A_CALL)
    assert len(CHAT_MODELS_BUILT) == 1, "the second request built its own chat model"


def test_an_unrecognized_classifier_verdict_still_answers_with_a_cached_generator(monkeypatch):
    """The path most dependent on the provider, asserted rather than assumed.

    `classify_scope` reads a verdict off the model and falls back to in-scope when it recognizes
    neither label. `CHAT_MODEL_ANSWER` is such an unrecognized verdict, so both requests take the
    fallback — which is what shows a provider shared between two requests pins no verdict state.
    """
    client = build_chat_client_with_the_real_generator(monkeypatch)

    first = client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})
    second = client.post("/chat", json={"question": "¿Y qué bases de datos usa?"})

    assert first.json()["answer"] == CHAT_MODEL_ANSWER
    assert second.json()["answer"] == CHAT_MODEL_ANSWER


# --- adb-002 2.x releasing the whole family ------------------------------------------------


def provider_cache_sizes() -> list[int]:
    return [dependency.cache_info().currsize for dependency in deps._CACHED_PROVIDER_DEPENDENCIES]


def cache_a_double_in_every_dependency(monkeypatch, *, embedder, vector_store, generator) -> dict:
    """Point all three factories at doubles and populate all three caches.

    Returns the cached provider keyed by its dependency, so a test can assert per dependency without
    depending on the order `_CACHED_PROVIDER_DEPENDENCIES` happens to list them in.
    """
    monkeypatch.setattr(deps, "get_embedding_provider", embedder)
    monkeypatch.setattr(deps, "get_vector_store_provider", vector_store)
    monkeypatch.setattr(deps, "get_generation_provider", generator)
    return {dependency: dependency() for dependency in deps._CACHED_PROVIDER_DEPENDENCIES}


def test_reset_providers_closes_every_cached_provider_before_dropping_it(monkeypatch):
    cached = cache_a_double_in_every_dependency(
        monkeypatch, embedder=ClosingProvider, vector_store=ClosingProvider, generator=ClosingProvider
    )

    deps.reset_providers()

    assert [provider.close_calls for provider in cached.values()] == [1, 1, 1]
    assert provider_cache_sizes() == [0, 0, 0]


def test_reset_providers_empties_every_cache_even_when_one_close_fails(monkeypatch):
    """One bad release must not strand the other two caches — that is the contamination to prevent.

    It also pins that the failure reaches the caller: a lone failure is re-raised as itself, so a
    caller can still match on its type instead of unwrapping a group.
    """
    cached = cache_a_double_in_every_dependency(
        monkeypatch,
        embedder=ClosingProvider,
        vector_store=FailingToCloseProvider,
        generator=ClosingProvider,
    )

    with pytest.raises(RuntimeError, match="client refused to close"):
        deps.reset_providers()

    assert provider_cache_sizes() == [0, 0, 0], "a failed release left a stale provider behind"
    assert [provider.close_calls for provider in cached.values()] == [1, 1, 1], (
        "the loop stopped at the failing release instead of continuing past it"
    )


def test_reset_providers_reports_every_failure_not_just_the_first(monkeypatch):
    """With no telemetry in this change, a discarded error vanishes — and the tuple's ordering would
    silently decide which one a caller saw."""
    cache_a_double_in_every_dependency(
        monkeypatch,
        embedder=FailingToCloseProvider,
        vector_store=FailingToCloseProvider,
        generator=FailingToCloseProvider,
    )

    with pytest.raises(ExceptionGroup) as raised:
        deps.reset_providers()

    assert len(raised.value.exceptions) == 3
    assert provider_cache_sizes() == [0, 0, 0]


def test_reset_providers_builds_nothing_when_nothing_is_cached(monkeypatch):
    """Resetting empty caches must not resolve a provider — on a cold Lambda that would connect.

    The factory raises rather than the test asserting on `currsize` afterwards: an empty cache is
    the post-condition either way, so only a factory that refuses to run can tell the difference.
    """

    def must_not_be_called():
        raise AssertionError("reset constructed a provider instead of short-circuiting")

    for factory_name in ("get_embedding_provider", "get_vector_store_provider", "get_generation_provider"):
        monkeypatch.setattr(deps, factory_name, must_not_be_called)

    deps.reset_providers()  # the autouse fixture already reset them; a second reset must not raise

    assert provider_cache_sizes() == [0, 0, 0]


# --- adb-002 5.1 an override still beats each cache ----------------------------------------


def test_registered_override_wins_over_the_cached_embedder(monkeypatch):
    """The real risk of caching a dependency, re-asserted for the embedder: the override must win."""
    client = build_chat_client_with_the_real_embedder(monkeypatch)
    cached_provider = deps.get_embedder()
    EMBEDDING_CLIENTS_BUILT.clear()  # the cache's own client is not what this test is counting

    injected = FakeEmbeddingProvider()
    app.dependency_overrides[deps.get_embedder] = lambda: injected

    response = client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})

    assert response.status_code == 200
    assert injected.embedded_texts, "the override was never used; the cache shadowed it"
    assert not EMBEDDING_CLIENTS_BUILT, "the overridden dependency still built a real Bedrock client"
    assert not EMBEDDERS_THAT_SERVED_A_REQUEST, "a real embedding provider served the request"
    assert deps.get_embedder() is cached_provider


def test_registered_override_wins_over_the_cached_generator(monkeypatch):
    client = build_chat_client_with_the_real_generator(monkeypatch)
    cached_provider = deps.get_generator()

    injected = FakeGenerationProvider()
    app.dependency_overrides[deps.get_generator] = lambda: injected

    response = client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})

    assert response.status_code == 200
    assert injected.calls, "the override was never used; the cache shadowed it"
    assert not CHAT_MODELS_BUILT, "the overridden dependency still built a real chat model"
    assert not CHAT_MODELS_THAT_SERVED_A_CALL, "a real chat model served the request"
    assert deps.get_generator() is cached_provider


# --- adb-002 5.5 every cache in the module is registered for release -----------------------


def test_the_autouse_fixture_leaves_every_provider_cache_empty():
    assert provider_cache_sizes() == [0, 0, 0]


def test_every_cached_dependency_in_deps_is_registered_for_release():
    """What the assertion above cannot catch: a cache missing from the tuple.

    Iterating `_CACHED_PROVIDER_DEPENDENCIES` can never notice something absent from it, so a fourth
    cached dependency added without registering it would be released by nothing — and the only
    symptom would be an API test that passes or fails depending on what ran before it.

    Detection duck-types on `cache_clear` because that is the contract `deps._release` actually
    calls; `__module__` filters out `get_settings`, which is `lru_cache`d but merely imported here.
    """
    cached_in_module = {
        name
        for name, value in vars(deps).items()
        if hasattr(value, "cache_clear") and getattr(value, "__module__", None) == deps.__name__
    }
    registered = {dependency.__name__ for dependency in deps._CACHED_PROVIDER_DEPENDENCIES}

    assert cached_in_module == registered
