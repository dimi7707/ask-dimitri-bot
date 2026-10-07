## Why

Every `POST /chat` builds a brand-new SQLAlchemy engine, and therefore a brand-new Postgres
connection pool: `get_vector_store()` in `app/api/deps.py` is an uncached FastAPI dependency, and
FastAPI's `use_cache=True` only dedupes dependencies *within* a single request, never *across*
requests. Locally this is invisible, but on Lambda against Aurora Serverless v2 it pays a full
TCP+TLS+auth handshake on every question, leaks pools until the GC collects them, and exhausts
Aurora's low `max_connections` at minimum ACU under moderate concurrency. It is a
production-only failure, which is exactly what makes it blocking for deployment
(ticket `adb-001`, detected at commit `eb18bb9`).

## What Changes

- Cache the vector store provider at module level in `app/api/deps.py` with `@lru_cache`, so a
  single engine lives for the lifetime of the Lambda execution environment and is reused across
  invocations.
- Configure `PgVectorStoreProvider`'s engine for a Lambda runtime: `pool_pre_ping=True` (a frozen
  container's connection may have been closed by Aurora), `pool_size=1` (one container serves one
  request at a time), `max_overflow=2`.
- Add regression tests proving provider identity across calls, engine identity across two
  consecutive `POST /chat` requests, and that the engine is built with `pool_pre_ping=True`.
- Explicitly **not** caching `get_vector_store_provider()` itself: it accepts a Pydantic `Settings`
  object, which is unhashable, so `@lru_cache` there would raise `TypeError` in the existing
  factory tests that pass settings explicitly.

No breaking changes: the public HTTP contract, the factory signature, and
`app.dependency_overrides` in tests all keep working unchanged.

## Capabilities

### New Capabilities
- `provider-lifecycle`: How integration providers and their underlying connection resources are
  created, cached, and reused across requests and Lambda invocations — one engine per process,
  many sessions — including the connection-pool settings required for a serverless runtime and the
  guarantee that dependency overrides in tests still bypass the cache.

### Modified Capabilities
<!-- No existing spec's requirements change: rag-chat-api's endpoint behavior, document-ingestion,
     health-check, and local-dev-environment all keep their current observable contracts. -->

## Impact

- **Code**: `app/api/deps.py` (add `@lru_cache` to `get_vector_store`, plus `reset_vector_store()`
  disposing the engine before dropping it), `app/integrations/vector_store/pgvector_provider.py`
  (`create_engine` pool arguments), `app/core/config.py` and
  `app/integrations/vector_store/factory.py` (pool sizing read from `Settings` and threaded into
  the provider).
- **Unchanged by design**: the factory stays *uncached* — it must, because of the unhashable
  `Settings` argument — and `ingestion/ingest.py` needs no change, since it already builds its
  providers once in `main()` and passes them down.
- **Tests**: new tests for provider and engine reuse; existing
  `tests/integrations/vector_store/test_factory.py` must keep passing without modification, and the
  full suite must stay green (baseline: 108 passing, 8 skipped).
- **Infrastructure**: reduces open connections against Aurora Serverless v2 and removes per-request
  connection handshake latency; unblocks Lambda deployment.
- **Follow-up, out of scope**: Secrets Manager integration for the database password (M4) and
  connection-error handling (finding A1, separate ticket). `pool_size` needs revisiting if
  provisioned concurrency or in-process concurrency is added later.
