# adb-002-reuse-bedrock-clients — tasks

Ordered so the suite stays green at every step. The thin end-to-end slice is group 2:
the two decorators alone satisfy the ticket's headline criteria, and every later group
is additive. Groups 3–5 can be dropped without invalidating group 2, which is the
property that makes this safe to ship in pieces if the review asks for that.

## 1. Baseline

- [ ] 1.1 Record the suite baseline. Measured on `origin/main` (`410e39c`):
      **124 passed, 8 skipped** (132 collected) — unchanged since `adb-001`
- [ ] 1.2 Reproduce the defect. Measured on `410e39c`: `get_embedding_provider()`
      twice gives different instances *and* different `_client` objects;
      `get_generation_provider()` twice gives different instances;
      `hash(Settings(_env_file=None))` raises `unhashable type: 'Settings'`
- [ ] 1.3 Record the cost honestly for the plan's claims: first `boto3.client` in a
      process ~140 ms, every later one ~1.5 ms, `ChatBedrock` ~9 ms. Note that the
      per-request waste is ~10 ms and the real cost is the lost keep-alive connection

## 2. Cache the two dependencies — **AC-1, AC-2, AC-3, AC-4, AC-6**

- [ ] 2.1 Decorate `get_embedder` with `@lru_cache` in `app/api/deps.py`, with a
      docstring saying what the cache buys (one boto3 client, and therefore one
      Bedrock HTTPS connection pool, per process) — **AC-1**
- [ ] 2.2 Decorate `get_generator` with `@lru_cache`, noting that this is what finally
      makes `_get_chat_model()`'s "then reuse it" true across requests — **AC-2**
- [ ] 2.3 Leave both factories uncached and comment why (`Settings` is unhashable, so
      `lru_cache` there raises `TypeError`) — **AC-6**
- [ ] 2.4 Confirm `tests/integrations/embeddings/test_factory.py` and
      `tests/integrations/generation/test_factory.py` pass **unmodified**, especially
      the cases passing an explicit `Settings` — **AC-6**
- [ ] 2.5 Add identity tests for both dependencies: `a is b`, **plus** a build counter
      asserting the factory ran exactly once — identity alone passes vacuously if
      something memoizes a layer down — **AC-1, AC-2**
- [ ] 2.6 Add a test that two consecutive `POST /chat` requests see the identical
      embedding provider, recorded from **inside** `embed()` — **AC-3**
- [ ] 2.7 Add a test that two consecutive `POST /chat` requests see the identical chat
      model, recorded from **inside** the generation call. Use a double standing in for
      `ChatBedrock` so the test needs no credentials — **AC-4**

## 3. The release contract — **AC-11, AC-12, AC-7**

- [ ] 3.1 Add `app/integrations/lifecycle.py` with the `runtime_checkable`
      `Closeable` protocol. Imports from `typing` only, so the architecture test keeps
      passing
- [ ] 3.2 Implement `PgVectorStoreProvider.close()` disposing the engine, and switch
      `reset_vector_store()` off `getattr(provider, "_engine", None)` onto `Closeable`.
      This retires `adb-001` task 5.7 — **AC-11**
- [ ] 3.3 Implement `BedrockEmbeddingProvider.close()` (closes its boto3 client) and
      `BedrockGenerationProvider.close()` (closes `self._chat_model.client` if one was
      built, then drops the reference) — **AC-11**
- [ ] 3.4 Add `reset_providers()` walking all three caches, collecting failures and
      re-raising the first, so one failing `close()` cannot leave the other caches
      populated — **AC-11**
- [ ] 3.5 Keep `reset_vector_store()` as a thin call to `_release(get_vector_store)`,
      and confirm the three `adb-001` reset tests in `tests/api/test_deps.py` pass
      **unmodified** — including the one asserting the error propagates
- [ ] 3.6 Add a closeable double to `tests/api/fakes.py` that records `close()` calls,
      and one whose `close()` raises
- [ ] 3.7 Test that releasing closes each provider before dropping it, that **all
      three** caches end empty when one `close()` raises, and that the first error
      propagates — **AC-11**
- [ ] 3.8 Test that releasing an empty cache constructs nothing, by making the factory
      raise if called — a post-condition on `currsize` would pass unconditionally — **AC-12**
- [ ] 3.9 Point the autouse fixture in `tests/api/conftest.py` at `reset_providers()`,
      still clearing on the way in as well as out — **AC-7**
- [ ] 3.10 Make `fresh_settings` in `tests/api/test_deps.py` reset providers too, so a
      provider built from the previous `Settings` cannot survive the fixture — **AC-7**

## 4. Bound the Bedrock calls — **AC-9, AC-10**

- [ ] 4.1 Add `bedrock_connect_timeout` (`gt=0`, default 3), `bedrock_read_timeout`
      (`gt=0`, default 8) and `bedrock_max_attempts` (`ge=1`, default 2) to
      `app/core/config.py`. The bounds matter: botocore reads a `connect_timeout` of
      `0`/`None` as *no timeout*, the inverse of the intent — **AC-10**
- [ ] 4.2 Build the `botocore.config.Config` inside
      `embeddings/bedrock_provider.py` and pass it to `boto3.client` — **AC-9**
- [ ] 4.3 Pass a `Config` to `ChatBedrock(config=...)` in
      `generation/bedrock_provider.py` (field confirmed present in langchain-aws
      1.7.3) — **AC-9**
- [ ] 4.4 Thread the three values from each factory into its provider, mirroring how
      `adb-001` threads `db_pool_size` — **AC-9**
- [ ] 4.5 Assert the configuration by capturing the kwargs passed to `boto3.client`
      and to `ChatBedrock`, not by reading botocore internals off the built client —
      an upstream rename must fail meaningfully, not as `AttributeError` — **AC-9**
- [ ] 4.6 Test the env-var → `Settings` → factory → client path end to end for at
      least one of the three values, so the halves are not covered in isolation —
      **AC-9**
- [ ] 4.7 Test that `Settings` rejects a `0`/negative timeout and a `0` attempt count
      with `ValidationError` in `tests/core/test_config.py` — **AC-10**
- [ ] 4.8 Pass the three variables through `docker/docker-compose.yml`, as `adb-001`
      did for the pool settings, so the uvicorn runtime can widen them

## 5. Verify nothing else regressed — **AC-5, AC-8**

- [ ] 5.1 Confirm the `/chat` tests injecting fakes via `app.dependency_overrides`
      still work, and add the explicit test: with an override registered, the fake
      serves the request and **no real Bedrock client is constructed** — **AC-5**
- [ ] 5.2 Confirm `classify_scope`'s unrecognized-verdict fallback behaves identically
      with a cached generator — the provider holds no verdict state, but it is the path
      most dependent on the provider, as the ticket asks
- [ ] 5.3 Confirm `ingestion/ingest.py` needs no change: it imports the factories
      directly and builds its providers once in `main()`, so it never resolves the API
      dependency — **AC-8**
- [ ] 5.4 Confirm `tests/architecture/test_integration_boundaries.py` passes: the new
      `botocore.config` import is inside `*_provider.py`, and `lifecycle.py` imports
      only `typing`
- [ ] 5.5 Verify each new test fails against the unfixed code — remove the decorators
      and the `Config` and confirm the expected failures — so they guard the regression
      instead of passing vacuously
- [ ] 5.6 Run the full suite: green at **124 baseline + the new tests**, 8 skipped

## 6. Keep the written record true

- [ ] 6.1 Extend `openspec/specs/provider-lifecycle/spec.md` per OQ-7: generalize the
      purpose line off "vector store", add requirements for the embedding and
      generation providers, the `Closeable` release contract, and the Bedrock ceiling
- [ ] 6.2 Update `app/api/deps.py`'s module docstring: it currently explains the cache
      in terms of "a provider that owns connections", which was accurate when the
      vector store was the only cached one
- [ ] 6.3 Tick the `adb-002` acceptance criteria and close the ticket. Also record the
      priority revision (High, not deployment-blocking) in the tracker and the second
      brain, since `ticket.md` is preserved verbatim and keeps the original 🔴 label
- [ ] 6.4 Note on `adb-001` task 5.7 that the deferred `close()` contract shipped here

---

## Definition of done

**This spec PR** (docs only): `spec.md`, `plan.md` and `tasks.md` reviewed and merged.
No implementation code, and therefore **no test, lint, or build run belongs to this
PR** — the baseline in 1.1 is a measurement, not a gate.

**The implementing PR**: every task above checked; every AC covered by a named test;
full suite green at 124 + new tests with 8 skipped; the architecture test passing; the
capability spec updated.

## AC coverage

| AC | Task | Test that proves it |
|---|---|---|
| AC-1 embedder once per process | 2.1, 2.5 | `test_deps.py` — identity + factory build counter |
| AC-2 generator once per process | 2.2, 2.5 | `test_deps.py` — identity + factory build counter |
| AC-3 two requests, one embedder | 2.6 | `test_deps.py` — identity recorded inside `embed()` |
| AC-4 two requests, one chat model | 2.7 | `test_deps.py` — identity recorded inside the generation call |
| AC-5 override beats the cache | 5.1 | `test_deps.py` — fake served it, no real client built |
| AC-6 factories uncached, tests untouched | 2.3, 2.4 | existing `test_factory.py` modules, unmodified |
| AC-7 no cross-test contamination | 3.9, 3.10 | `conftest.py` autouse fixture + `fresh_settings` |
| AC-8 ingestion unaffected | 5.3 | existing `tests/ingestion/test_ingest.py` |
| AC-9 bounded Bedrock client | 4.2–4.6 | `test_bedrock_provider.py` (both) — captured kwargs; env-var path end to end |
| AC-10 ceiling-removing values rejected | 4.1, 4.7 | `tests/core/test_config.py` — `ValidationError` cases |
| AC-11 release closes, then always clears | 3.2–3.4, 3.7 | `test_deps.py` — raising `close()`, all caches empty, error propagates |
| AC-12 empty release builds nothing | 3.8 | `test_deps.py` — factory raises if called |
