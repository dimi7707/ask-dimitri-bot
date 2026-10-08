"""FastAPI dependencies resolving the configured providers.

Thin wrappers around the factories so routes depend on `Depends(...)` callables that tests can
override, without FastAPI trying to bind the factories' own `settings` argument as a query param.

Taking no arguments also makes these wrappers the right place to cache a provider that owns a
connection pool: FastAPI's own dependency cache spans a single request, so an uncached wrapper
builds a new provider — and a new pool, to Postgres or to the Bedrock endpoint — per request. All
three provider dependencies are cached here for that reason; the factories stay uncached because
they accept an unhashable `Settings`.

Releasing is the other half of caching, and it goes through `app.integrations.lifecycle.Closeable` —
never by reaching for a provider's private attributes. `reset_providers()` is the entry point;
`reset_vector_store()` is the narrower one `adb-001` introduced, kept so its callers still work.
"""

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.integrations.embeddings.base import EmbeddingProvider
from app.integrations.embeddings.factory import get_embedding_provider
from app.integrations.generation.base import GenerationProvider
from app.integrations.generation.factory import get_generation_provider
from app.integrations.lifecycle import Closeable
from app.integrations.vector_store.base import VectorStoreProvider
from app.integrations.vector_store.factory import get_vector_store_provider


def get_app_settings() -> Settings:
    return get_settings()


@lru_cache
def get_embedder() -> EmbeddingProvider:
    """One provider per process, so its boto3 client — and its HTTPS connection pool — is reused.

    A client per request cannot reuse the keep-alive connection the previous request established to
    the Bedrock endpoint, so every embedding call pays a fresh TCP+TLS handshake and the abandoned
    client holds its sockets until the garbage collector finalizes it. Call `reset_providers()` —
    not `cache_clear()` — to drop the provider.
    """
    return get_embedding_provider()


@lru_cache
def get_vector_store() -> VectorStoreProvider:
    """One provider per process, so its SQLAlchemy engine and pool survive across requests.

    On Lambda the cache spans invocations of a warm execution environment, which is the point: an
    engine per request pays a full TCP+TLS handshake per question and exhausts Aurora's
    `max_connections`. Call `reset_providers()` — not `cache_clear()` — to drop the provider.
    """
    return get_vector_store_provider()


@lru_cache
def get_generator() -> GenerationProvider:
    """One provider per process, which is what finally makes the provider's own lazy cache real.

    `BedrockGenerationProvider._get_chat_model()` memoizes its `ChatBedrock` on the instance and
    promises to "reuse it" — a promise that was false across requests while the instance died with
    the request. Cached here, the chat model and both of its clients are built once per process.
    Call `reset_providers()` — not `cache_clear()` — to drop the provider.
    """
    return get_generation_provider()


# The release surface. Every cached provider dependency belongs here: a reset that walked some of
# them would be worse than none, because the gap is only visible as a test that fails depending on
# what ran before it. `tests/api/test_deps.py` asserts this tuple holds *every* cached dependency in
# the module, since iterating a tuple can never notice something missing from the tuple.
_CACHED_PROVIDER_DEPENDENCIES = (get_embedder, get_vector_store, get_generator)


def reset_providers() -> None:
    """Release every cached provider and empty every cache, then report any failure.

    Failures are collected rather than raised as they happen: letting the first one abort the loop
    would leave the remaining caches populated, which is the cross-test contamination this exists to
    prevent. A lone failure is re-raised as itself so callers can still match on its type; several
    are raised together, because picking one would make the tuple's ordering decide silently which
    error a caller gets to see.
    """
    failures: list[BaseException] = []
    for dependency in _CACHED_PROVIDER_DEPENDENCIES:
        try:
            _release(dependency)
        except Exception as error:
            failures.append(error)

    if len(failures) == 1:
        raise failures[0]
    if failures:
        raise ExceptionGroup("releasing cached providers failed", failures)


def reset_vector_store() -> None:
    """Release just the cached vector store provider. Kept for the callers `adb-001` left behind."""
    _release(get_vector_store)


def _release(dependency) -> None:
    """Close the provider this dependency has cached, if any, then clear the cache regardless."""
    try:
        # Guard on the cache being populated, so a reset never *builds* a provider just to drop it:
        # on a cold Lambda that would resolve credentials and open a pool for nothing.
        if dependency.cache_info().currsize:
            provider = dependency()
            if isinstance(provider, Closeable):
                provider.close()
    finally:
        # Clear even if closing blew up: this is the only isolation the API tests have, so a failed
        # release must not leave the stale provider behind for everything that runs next.
        dependency.cache_clear()
