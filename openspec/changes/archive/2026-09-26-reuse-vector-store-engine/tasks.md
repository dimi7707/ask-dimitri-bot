## 1. Baseline

- [x] 1.1 Run the full suite and record the passing count as the baseline to compare against (measured: **108 passed, 8 skipped** — 116 collected; the ticket's "108" was the passing count, not stale after all)
- [x] 1.2 Reproduce the defect from the ticket: confirm that two calls to `get_vector_store_provider()` return different instances and different `_engine` objects

## 2. Cache the provider at the dependency layer

- [x] 2.1 Add `from functools import lru_cache` and decorate `get_vector_store` with `@lru_cache` in `app/api/deps.py`
- [x] 2.2 Leave `app/integrations/vector_store/factory.py` uncached, and note in a comment why (`Settings` is unhashable, so `lru_cache` there raises `TypeError`)
- [x] 2.3 Confirm `tests/integrations/vector_store/test_factory.py` still passes unmodified, especially the cases passing an explicit `Settings`
- [x] 2.4 (review follow-up) Add `deps.reset_vector_store()`, which disposes the engine before dropping it, so clearing the cache releases the pool instead of leaving it to the garbage collector

## 3. Configure the engine for the Lambda runtime

- [x] 3.1 Pass `pool_pre_ping=True`, `pool_size=1`, and `max_overflow=2` to `create_engine` in `PgVectorStoreProvider.__init__`
- [x] 3.2 Verify `tests/integrations/vector_store/test_pgvector_provider.py` still passes with the new pool arguments
- [x] 3.3 (review follow-up) Promote the pool sizing to `Settings.db_pool_size` / `Settings.db_max_overflow`, defaulting to 1 and 2, so a non-Lambda runtime sizes it up without a code change

## 4. Tests proving reuse

- [x] 4.1 Add a test asserting `get_vector_store()` returns the identical instance on two consecutive calls (`a is b`)
- [x] 4.2 Add a test asserting two consecutive `POST /chat` requests are served by the same `provider._engine` object — recorded *inside* `similarity_search`, so the assertion observes the request path instead of reading the identity back from the module and bypassing FastAPI's resolution
- [x] 4.3 Add a test asserting the pgvector provider's engine is created with `pool_pre_ping=True` (and the configured pool sizing), by capturing the kwargs passed to `create_engine` rather than reading SQLAlchemy's private `pool._pre_ping` / `pool._max_overflow`
- [x] 4.4 Add an autouse fixture in `tests/api/conftest.py` resetting the provider cache around every API test — on the way in as well as out, so no test inherits the previous one's provider
- [x] 4.5 Confirm each new test actually fails against the unfixed code, so it guards the regression rather than passing vacuously (verified: 7 failures with `@lru_cache` removed)
- [x] 4.6 (review follow-up) Move the shared test doubles into `tests/api/fakes.py` so `test_deps.py` stops importing from `test_chat.py`, and have `EngineHoldingVectorStore` extend `FakeVectorStore` instead of redeclaring its stubs

## 5. Verify nothing else regressed

- [x] 5.1 Confirm the `/chat` tests that inject fakes via `app.dependency_overrides` still work — the cache must not shadow registered overrides
- [x] 5.2 Confirm `ingestion/ingest.py` needs no change: it already builds its providers once in `main()` and passes them down
- [x] 5.3 Run the full suite and confirm it is green at the baseline count plus the new tests (**120 passed, 8 skipped** = 108 baseline + 12 new; 128 collected)
- [x] 5.4 Update the `adb-001` ticket's acceptance criteria checkboxes and close it
- [x] 5.5 (review follow-up) Correct the `design.md` rationale for deferring `get_embedder` / `get_generator`: the Bedrock chat model is lazy only *per instance*, and the instance is per request, so `adb-002` must cover the embedding provider too
