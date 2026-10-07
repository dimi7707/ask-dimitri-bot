## Context

`app/api/deps.py` exposes thin, argument-less wrappers around the integration factories so routes can
depend on `Depends(...)` callables that tests may override. `get_vector_store()` currently forwards
straight to `get_vector_store_provider()`, which builds a `PgVectorStoreProvider`, whose `__init__`
calls `create_engine(database_url)` with no pool arguments.

A SQLAlchemy engine is not a connection — it is the factory that owns a pool of reusable TCP
connections. The canonical rule is **one engine per process, many sessions**. This project currently
has one engine per request, because FastAPI's dependency cache (`use_cache=True`) deduplicates a
dependency *within* one request and never *between* requests.

Verified against the current tree at commit `eb18bb9`:

```
misma instancia? False
mismo engine?   False
```

The consequences split by environment. Local Docker hides the defect entirely — a local Postgres
absorbs the extra pools, and the handshake latency disappears into Bedrock's. On Lambda against
Aurora Serverless v2 at minimum ACU, each request pays a full TCP+TLS+auth handshake, every
abandoned pool holds connections open until garbage collection, and Aurora's low `max_connections`
is exhausted under moderate concurrency. This is the classic Lambda + SQLAlchemy failure: green in
development, broken in production.

Two constraints shape the design:

1. `get_vector_store_provider(settings=...)` takes a Pydantic `Settings` object, and `Settings` is
   **not hashable** (confirmed: `unhashable type: 'Settings'`). Memoizing the factory would raise
   `TypeError` in `tests/integrations/vector_store/test_factory.py`, which passes settings
   explicitly today.
2. The `/chat` tests rely on `app.dependency_overrides` to inject fakes. Any cache must not shadow
   those overrides.

## Goals / Non-Goals

**Goals:**
- One SQLAlchemy engine, and therefore one connection pool, per process — reused across Lambda
  invocations in a warm execution environment.
- An engine configured to survive the freeze/thaw cycle of a Lambda container against Aurora.
- Automated proof of both, plus proof that the existing suite and the test override mechanism are
  unaffected.

**Non-Goals:**
- Caching the provider factories themselves — ruled out by the unhashable `Settings` argument.
- Changing the ingestion path. `ingestion/ingest.py` already builds its providers once in `main()`
  and passes them into each call, so it needs no change; the work is to verify this, not alter it.
- Secrets Manager integration for the database password (tracked as M4).
- Connection-error handling and retry semantics (tracked separately as finding A1).
- Any change to the `POST /chat` HTTP contract.

## Decisions

**Cache at the dependency layer with `@lru_cache`, not at the factory.**
`app/api/deps.py` holds argument-less functions, which makes them trivially safe to memoize:

```python
@lru_cache
def get_vector_store() -> VectorStoreProvider:
    return get_vector_store_provider()
```

*Alternatives considered.* (a) `@lru_cache` on the factory — rejected: unhashable `Settings`
argument breaks existing tests. (b) A module-level singleton assigned at import time — rejected: it
would build an engine during module import, which runs before `Settings` is necessarily usable and
makes importing `deps.py` a side-effecting operation for every test. (c) A FastAPI `lifespan` hook
storing the provider on `app.state` — rejected as more machinery for the same result, and it would
move provider access away from the `Depends` pattern the routes and tests already share. `lru_cache`
keeps the existing shape and defers construction to first use.

**Scope the cache to the vector store dependency only.**
`get_embedder` and `get_generator` are out of scope for this change. Narrowing it keeps the blast
radius to the resource that actually holds connections: a Bedrock client is stateless HTTP, so
rebuilding one wastes setup work but never exhausts a pool the way an abandoned engine does.

The deferral is a cost trade-off, not an absence of cost. `BedrockGenerationProvider` builds its
chat model lazily (commit `eb18bb9`), but that laziness is *per provider instance*, and the instance
itself is rebuilt per request — so `ChatBedrock` is still constructed on every `POST /chat`.
`BedrockEmbeddingProvider` is worse: it creates its `boto3` client eagerly in `__init__`, so every
request pays credential resolution and botocore model parsing. `adb-002` covers **both** siblings
under the same root cause, and the fix there is the same one-line `@lru_cache`.

**Configure the pool for one-request-per-container, but let the runtime override it.**

```python
create_engine(
    database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,      # default 1
    max_overflow=settings.db_max_overflow,  # default 2
)
```

`pool_pre_ping` is the load-bearing setting: between invocations the Lambda container is *frozen*,
and Aurora may close the connection on its own. Without a pre-use ping, the first request after an
idle stretch fails on a dead connection. A `pool_size` of 1 matches the execution model — one
container serves one request at a time — and `max_overflow=2` leaves headroom rather than
hard-failing on an unexpected concurrent checkout.

The sizing is a `Settings` field rather than a literal because the same image also runs under
`uvicorn` in `docker compose`, where `def chat` is a sync route dispatched to Starlette's threadpool
and several requests can check out connections at once. At the defaults the fourth concurrent
request would block for `pool_timeout` (30 s) and then raise `QueuePool limit of size 1 overflow 2
reached`. Keeping it in `Settings` — where `similarity_threshold`, `chunk_size` and every other
tunable already live — makes that a `.env` change instead of a code change, which is also what the
"`pool_size=1` becomes wrong if the runtime changes" risk below asks for.

*Alternative considered:* `NullPool`, which opens a connection per checkout and closes it after. It
eliminates stale-connection risk but reinstates the per-request handshake cost this change exists to
remove. A small pre-pinged pool gets the reuse and handles staleness.

**Prove reuse by object identity, observed from inside the request.**
Tests assert `a is b` on the engine, because identity is the property the design actually
guarantees. The identity is recorded *inside* `similarity_search` rather than read back from
`deps.get_vector_store()`: reading it back from the module bypasses FastAPI's dependency resolution,
so a future route that stopped using the cached dependency would leave the test green while the
per-request engine came back.

The pool settings are asserted by capturing the kwargs the provider passes to `create_engine`, not
by reading `pool._pre_ping` and `pool._max_overflow`. Both of those are SQLAlchemy internals, where
an upstream rename produces an `AttributeError` instead of a meaningful failure; the capture asserts
the same contract against this project's own call site.

## Risks / Trade-offs

**`lru_cache` could shadow `app.dependency_overrides` and silently break the `/chat` tests** → In
principle safe: FastAPI resolves overrides *before* calling the original dependency, so a cached
original is never consulted when an override is registered. This is the one real risk in the change,
so it gets confirmed by a green suite rather than assumed — the spec carries it as an explicit
scenario.

**Cached provider leaks state between tests that exercise the real provider** → an autouse fixture
in `tests/api/conftest.py` resets it around every API test, on the way in as well as on the way out,
so no test inherits the previous one's provider. The reset goes through `deps.reset_vector_store()`
rather than `cache_clear()` directly: clearing alone drops the engine without disposing it, leaving
the pool holding its connections until garbage collection — the very leak this change removes.

**`pool_size=1` becomes wrong if the runtime changes** → Adding provisioned concurrency, or moving
to a Lambda that handles concurrency in-process, invalidates the sizing assumption. Recorded here
and in the ticket so the setting is revisited rather than inherited silently.

**A cached engine holds a connection open across a long idle period** → `pool_pre_ping` covers
correctness; the cost is one extra round trip per checkout, which is negligible next to the
handshake it replaces.

## Migration Plan

No data migration and no schema change. The change is two edits plus tests, deployed with the normal
Lambda container image build. Rollback is a straight revert: dropping `@lru_cache` restores
per-request engines, and dropping the pool arguments restores SQLAlchemy defaults. Neither direction
touches persisted state, so no coordination with the database is required.

Post-deploy, the signal that it worked is the absence of the old symptom: connection count against
Aurora stays flat under repeated questions instead of climbing with request volume.

## Open Questions

None blocking. The two deferred items — Secrets Manager (M4) and connection-error handling (A1) —
are tracked as separate work and do not gate this change.
