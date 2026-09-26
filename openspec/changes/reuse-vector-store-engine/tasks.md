## 1. Baseline

- [x] 1.1 Run the full suite and record the passing count as the baseline to compare against (measured: **116 passed**; the ticket's "108" was stale)
- [x] 1.2 Reproduce the defect from the ticket: confirm that two calls to `get_vector_store_provider()` return different instances and different `_engine` objects

## 2. Cache the provider at the dependency layer

- [x] 2.1 Add `from functools import lru_cache` and decorate `get_vector_store` with `@lru_cache` in `app/api/deps.py`
- [x] 2.2 Leave `app/integrations/vector_store/factory.py` uncached, and note in a comment why (`Settings` is unhashable, so `lru_cache` there raises `TypeError`)
- [x] 2.3 Confirm `tests/integrations/vector_store/test_factory.py` still passes unmodified, especially the cases passing an explicit `Settings`

## 3. Configure the engine for the Lambda runtime

- [x] 3.1 Pass `pool_pre_ping=True`, `pool_size=1`, and `max_overflow=2` to `create_engine` in `PgVectorStoreProvider.__init__`
- [x] 3.2 Verify `tests/integrations/vector_store/test_pgvector_provider.py` still passes with the new pool arguments

## 4. Tests proving reuse

- [ ] 4.1 Add a test asserting `get_vector_store()` returns the identical instance on two consecutive calls (`a is b`)
- [ ] 4.2 Add a test asserting two consecutive `POST /chat` requests are served by the same `provider._engine` object
- [ ] 4.3 Add a test asserting the pgvector provider's engine is created with `pool_pre_ping=True` (and the configured pool sizing)
- [ ] 4.4 Add a fixture that calls `get_vector_store.cache_clear()` wherever a test needs a fresh provider, so the cache does not leak state between tests

## 5. Verify nothing else regressed

- [ ] 5.1 Confirm the `/chat` tests that inject fakes via `app.dependency_overrides` still work — the cache must not shadow registered overrides
- [ ] 5.2 Confirm `ingestion/ingest.py` needs no change: it already builds its providers once in `main()` and passes them down
- [ ] 5.3 Run the full suite and confirm it is green at the baseline count plus the new tests
- [ ] 5.4 Update the `adb-001` ticket's acceptance criteria checkboxes and close it
