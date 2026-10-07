# adb-002-reuse-bedrock-clients — plan

## Context

`app/api/deps.py` holds argument-less wrappers around the integration factories, so
routes depend on `Depends(...)` callables tests can override without FastAPI binding
the factories' `settings` parameter as a query param. `adb-001` already cached one of
the three:

| Dependency | Line | Cached today |
|---|---|---|
| `get_embedder` | `deps.py:26` | ✗ |
| `get_vector_store` | `deps.py:31` | ✓ `@lru_cache` + `reset_vector_store()` |
| `get_generator` | `deps.py:60` | ✗ |

`BedrockEmbeddingProvider.__init__` (`embeddings/bedrock_provider.py:9`) creates its
`boto3.client("bedrock-runtime", ...)` eagerly. `BedrockGenerationProvider`
(`generation/bedrock_provider.py:22-30`) defers `ChatBedrock` to first use, but
memoizes it on `self`, and `self` dies with the request.

Verified against `origin/main` (`410e39c`): both factories return fresh instances with
fresh clients; `Settings` is unhashable; a warm `boto3.client` build costs ~1.5 ms and
`ChatBedrock` ~9 ms, while the first client in a process costs ~140 ms. The expensive
consequence is not construction but that a new botocore client cannot reuse the
previous one's keep-alive HTTPS connection to the Bedrock endpoint.

API facts confirmed in the installed versions (langchain-aws 1.7.3, botocore 1.43.78):
`ChatBedrock` exposes a `config` field and a `client` field; boto3 clients expose
`close()`. Both are load-bearing below.

## Decisions

### Cache at the dependency layer with `@lru_cache`, mirroring `adb-001`

```python
@lru_cache
def get_embedder() -> EmbeddingProvider:
    return get_embedding_provider()

@lru_cache
def get_generator() -> GenerationProvider:
    return get_generation_provider()
```

*Alternatives rejected.* Caching the factories — `Settings` is unhashable, so
`@lru_cache` there raises `TypeError` in the existing factory tests. A module-level
singleton at import time — builds a boto3 client during import, making every test that
imports `deps` pay credential resolution. A `lifespan` hook on `app.state` — more
machinery for the same result, and it moves provider access off the `Depends` pattern
the routes and tests share. This is the same reasoning `adb-001` recorded, applied to
the siblings it deferred.

### Release through a separate `Closeable` protocol, not the capability protocols

New file `app/integrations/lifecycle.py`:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Closeable(Protocol):
    """A provider holding a resource worth releasing before the provider is discarded."""

    def close(self) -> None: ...
```

Implementations: `PgVectorStoreProvider.close()` disposes its engine;
`BedrockEmbeddingProvider.close()` closes its boto3 client;
`BedrockGenerationProvider.close()` closes the client held by its `ChatBedrock`
(`self._chat_model.client`) if one was ever built, then drops the reference.

*Why not `close()` on `VectorStoreProvider` / `EmbeddingProvider` /
`GenerationProvider`?* They are `runtime_checkable`, so `isinstance` checks method
presence — adding `close()` breaks the protocol assertions for every existing double
(`tests/api/fakes.py`, both `test_factory.py` modules) until each grows a method that
releases nothing. A separate protocol removes the `getattr(provider, "_engine", None)`
sniffing that `adb-001` flagged in task 5.7, which was the actual defect, at zero churn
to current fakes. The coupling to `ChatBedrock.client` sits inside a
`*_provider.py` file, which is the one place the architecture test permits vendor
coupling.

### One `reset_providers()`, clearing every cache even when a release fails

```python
_CACHED_PROVIDER_DEPENDENCIES = (get_embedder, get_vector_store, get_generator)

def reset_providers() -> None:
    """Release every cached provider. Every cache is cleared even if a close() raises."""
    failures = []
    for dependency in _CACHED_PROVIDER_DEPENDENCIES:
        try:
            _release(dependency)
        except Exception as error:
            failures.append(error)
    if failures:
        raise failures[0]

def _release(dependency) -> None:
    try:
        # Guard on the cache being populated, so a reset never *builds* a provider to drop it.
        if dependency.cache_info().currsize:
            provider = dependency()
            if isinstance(provider, Closeable):
                provider.close()
    finally:
        dependency.cache_clear()

def reset_vector_store() -> None:
    _release(get_vector_store)
```

The per-dependency `finally` is what AC-11 rests on, and the loop's exception
collection extends it across the family: without collecting, one provider's failing
`close()` would abort the loop and leave the remaining caches populated — the exact
cross-test contamination the reset exists to prevent. The first failure is re-raised so
a broken release is still loud, preserving the propagation `adb-001`'s
`test_reset_vector_store_clears_the_cache_even_if_dispose_fails` asserts.

`reset_vector_store()` is kept and re-expressed over `_release`, so the `adb-001` tests
calling it by name pass unmodified. Its behavior is unchanged: disposal via
`PgVectorStoreProvider.close()` instead of the `getattr` sniff.

### Bedrock timeouts in `Settings`, applied to both clients

```python
# inside each bedrock_provider.py
config=Config(
    connect_timeout=settings_connect_timeout,   # default 3
    read_timeout=settings_read_timeout,         # default 8
    retries={"mode": "standard", "max_attempts": settings_max_attempts},  # default 2
)
```

Three new `Settings` fields — `bedrock_connect_timeout` (`gt=0`),
`bedrock_read_timeout` (`gt=0`), `bedrock_max_attempts` (`ge=1`) — threaded from each
factory into its provider, exactly as `adb-001` threaded `db_pool_size`.

*Why `Settings` and not literals?* `adb-001` shipped `pool_size=1` as a literal and its
review made it configurable, because the same image runs under uvicorn in
`docker compose` where the Lambda-shaped default is wrong. The same argument applies
here, and the bounds exist for the same reason the pool bounds do: botocore reads a
`connect_timeout` of 0 or `None` as *no timeout*, the inverse of the intent, and that is
one `.env` typo away.

*Why both clients?* The ticket configures only embeddings, but generation makes up to
two of the three Bedrock calls per question; leaving it at botocore's 60 s default is
the asymmetry with no defense.

### Prove reuse by identity, recorded from inside the request

Following `adb-001`: the identity assertions record the object *inside*
`embed()` and inside the generation call, not by reading
`deps.get_embedder()` back from the module. Reading it back bypasses FastAPI's
dependency resolution, so a future route that stopped using the cached dependency
would leave the test green while per-request construction returned.

The timeout configuration is asserted by capturing the kwargs the provider passes to
`boto3.client` / `ChatBedrock`, not by reading botocore internals off the built client —
same rationale as `adb-001`'s `create_engine` capture: an upstream rename should produce
a meaningful failure, not an `AttributeError`.

## Affected layers

Dependency direction, as the architecture test enforces it: `api` → `services` →
`integrations`; raw SDKs are reachable only from `integrations/*/[a-z]*_provider.py`.
Nothing here inverts that.

| Layer | File | Change |
|---|---|---|
| integrations (new) | `app/integrations/lifecycle.py` | `Closeable` protocol; imports only `typing` |
| integrations | `app/integrations/vector_store/pgvector_provider.py` | add `close()` disposing the engine |
| integrations | `app/integrations/embeddings/bedrock_provider.py` | `Config(...)` on the client; add `close()` |
| integrations | `app/integrations/generation/bedrock_provider.py` | `config=` on `ChatBedrock`; add `close()`; docstring now true |
| integrations | `app/integrations/embeddings/factory.py`, `generation/factory.py` | thread the three timeout settings into the providers |
| core | `app/core/config.py` | three bounded `Settings` fields |
| api | `app/api/deps.py` | `@lru_cache` on both dependencies; `reset_providers()`; `reset_vector_store()` over `_release` |
| tests | `tests/api/conftest.py` | autouse fixture calls `reset_providers()` |
| tests | `tests/api/test_deps.py` | new reuse/release/timeout tests; `fresh_settings` also resets providers |
| tests | `tests/api/fakes.py` | a closeable double recording `close()` |
| docker | `docker/docker-compose.yml` | pass the three env vars through, as `adb-001` did for the pool |
| capability spec | `openspec/specs/provider-lifecycle/spec.md` | generalize purpose; add requirements for the sibling providers and `Closeable` |

## Invariant → enforcement

| AC | Invariant | Chokepoint | Proof |
|---|---|---|---|
| AC-1 | Embedding provider built at most once per process | `@lru_cache` on `deps.get_embedder` — the single resolution path for the route | `tests/api/test_deps.py` — identity across two calls **plus** a build counter asserting the factory ran once |
| AC-2 | Generation provider built at most once per process | `@lru_cache` on `deps.get_generator` | same shape as AC-1 |
| AC-5 | A registered override always wins over the cache | FastAPI's own override resolution, which runs before the dependency is called | `tests/api/test_deps.py` — override registered, `/chat` issued, fake recorded the call and no real client was constructed |
| AC-9 | Every Bedrock client carries a bounded ceiling | The two provider constructors are the only call sites that build a Bedrock client | `tests/integrations/{embeddings,generation}/test_bedrock_provider.py` — captured kwargs assert `connect_timeout`, `read_timeout`, `max_attempts` |
| AC-10 | A ceiling-removing value is rejected, not accepted | `Settings` field constraints (`gt=0`, `ge=1`) — validation happens before any provider is built | `tests/core/test_config.py` — `ValidationError` for `0`/negative timeout and `0` attempts |
| AC-11 | A release never leaves a populated cache behind | `_release`'s `finally`, plus `reset_providers()` collecting failures across the loop | `tests/api/test_deps.py` — a double whose `close()` raises; assert all three caches empty and the error propagates |

AC-3, AC-4, AC-6, AC-7, AC-8 and AC-12 are behavioral rather than invariants; their
tests are listed in `tasks.md`.

## Gates this change adds

- **`tests/architecture/test_integration_boundaries.py` (existing, unchanged).** It
  rejects a `botocore.config` import from anywhere under `app/` or `ingestion/` that is
  not a `*_provider.py` directly inside `app/integrations/<capability>/`. It therefore
  catches the plausible mistake of building the `Config` in a factory or in `deps.py`.
  **What still passes it:** `lifecycle.py` (typing only), and any SDK import inside the
  provider files — including a careless one. It is a location gate, not a usage gate.
- **`Settings` field bounds (new).** `gt=0` / `ge=1` reject `0`, negatives, and
  non-numerics at startup. **What still passes:** a syntactically valid but useless
  ceiling — `bedrock_read_timeout=600` is accepted and silently exceeds the Lambda
  budget. Nothing enforces the relationship between these values and the 30 s timeout,
  because the Lambda timeout is not visible to the app. The aggregate-budget limitation
  in OQ-3 is therefore unenforced by construction, which is why it is a recorded
  non-goal rather than a claimed guarantee.
- **The build-counter assertions (new).** Asserting `a is b` alone passes vacuously if
  something memoizes one layer down; counting factory invocations is what makes AC-1
  and AC-2 real.

## Risks / trade-offs

- **`lru_cache` shadows `app.dependency_overrides`** → safe in principle, since FastAPI
  resolves overrides before calling the original. It is the one real risk of caching a
  dependency, so AC-5 carries it as an explicit test rather than an assumption —
  `adb-001` took the same approach and the suite confirmed it.
- **Two threads race to build the chat model** (sync route → Starlette threadpool)
  → **accepted, not guarded** (OQ-5). The loser's `ChatBedrock` is discarded: ~9 ms
  wasted once per process, no corruption, and boto3 clients are thread-safe for calls.
  A lock on every request's hot path to protect a one-time 9 ms waste is the wrong
  trade. Revisit if provider construction ever acquires side effects.
- **A failed `ChatBedrock` construction is retried per request** → **accepted**
  (OQ-4). AC-4 is scoped to the success path. On a credential-less machine the ~90 s
  block still repeats; fast-failing it needs A1's error handling to be meaningful.
- **A cached provider outlives a `Settings` change** → only matters in tests, where
  `fresh_settings` now resets providers too. In Lambda, settings are fixed per
  container.
- **`BedrockGenerationProvider.close()` depends on `ChatBedrock.client`** → verified
  present in langchain-aws 1.7.3; an upstream rename degrades it to closing nothing.
  Mitigated by keeping the access inside the provider file and asserting `close()`
  behavior in that provider's own test.
- **A third timeout triple is one more thing to configure** → the defaults are the
  Lambda-correct values, so only a non-Lambda runtime needs to touch them.

## Rollout & rollback

No data migration, no schema change, no HTTP contract change. Ships with the normal
Lambda container image build. Deploy order is irrelevant — nothing outside the process
observes the cache.

Rollback is a straight revert: dropping the two decorators restores per-request
providers, dropping the `Config` restores botocore defaults. Neither direction touches
persisted state.

Post-deploy signal: p50 latency on `POST /chat` drops by roughly the handshake time to
the Bedrock endpoint for the second and later questions in a container, and a hung
Bedrock call now surfaces as a provider-level timeout at ~22 s instead of the Lambda's
own 30 s cutoff. No new telemetry is added — observability is not in scope.

## ADR impact

This repo keeps no ADR directory, so the decision is recorded here and in the capability
spec. The architectural rule this change establishes:

> **Providers that own a releasable resource declare it by implementing `Closeable`.**
> Cached-provider release goes through that protocol — never by reaching for a private
> attribute. Caching stays at the argument-less dependency layer; factories remain
> uncached because they accept an unhashable `Settings`.

The first clause is new (and retires `adb-001` task 5.7); the second restates the rule
`adb-001` established. Both land in `openspec/specs/provider-lifecycle/spec.md` per
OQ-7, which is the capability-level contract and the right home for a rule that outlives
this change.
