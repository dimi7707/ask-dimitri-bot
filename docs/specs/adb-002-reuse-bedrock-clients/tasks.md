# adb-002-reuse-bedrock-clients — tasks

Ordered so the suite stays green at every step. **Group 2 is the atomic slice**: the
caches and the reset that makes their tests order-independent land together, because a
cache without a reset fixture ships order-dependent tests and violates AC-7 by
construction. Groups 3–6 are additive and could be cut without invalidating group 2 —
with one exception called out in group 3, which is what lets this change claim it
retired `adb-001` task 5.7.

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

## 2. The cached dependencies and the reset that isolates them — **AC-1, AC-2, AC-3, AC-4, AC-6, AC-7, AC-11, AC-12**

- [ ] 2.1 Add `app/integrations/lifecycle.py` with the `runtime_checkable` `Closeable`
      protocol (`close() -> None`). Imports from `typing` only, so the architecture
      test keeps passing
- [ ] 2.2 Decorate `get_embedder` and `get_generator` with `@lru_cache` in
      `app/api/deps.py`, with docstrings saying what each cache buys (one client, and
      therefore one Bedrock HTTPS connection pool, per process) and noting that this is
      what finally makes `_get_chat_model()`'s "then reuse it" true across
      requests — **AC-1, AC-2**
- [ ] 2.3 Add `_release(dependency)` and `reset_providers()` over
      `_CACHED_PROVIDER_DEPENDENCIES`, clearing each cache in a `finally`, collecting
      failures across the loop, and raising a lone failure as itself or several as an
      `ExceptionGroup` — **AC-11**
- [ ] 2.4 Implement `close()` on the three providers: `PgVectorStoreProvider` disposes
      its engine; `BedrockEmbeddingProvider` closes its boto3 client;
      `BedrockGenerationProvider` closes **both** clients `ChatBedrock` owns
      (`client` and `bedrock_client`, verified present in langchain-aws 1.7.3) if a
      chat model was built, then drops the reference — **AC-11**
- [ ] 2.5 Re-express `reset_vector_store()` as `_release(get_vector_store)`, off
      `getattr(provider, "_engine", None)`, and confirm the three `adb-001` reset tests
      in `tests/api/test_deps.py` pass **unmodified** — including the one asserting a
      failed dispose still propagates
- [ ] 2.6 Point the autouse fixture in `tests/api/conftest.py` at `reset_providers()`,
      still clearing on the way in as well as out — **AC-7**
- [ ] 2.7 Make `fresh_settings` (`tests/api/test_deps.py:180`) reset providers too, so a
      provider built from the previous `Settings` cannot survive the fixture — **AC-7**
- [ ] 2.8 Leave both factories uncached and comment why (`Settings` is unhashable, so
      `lru_cache` there raises `TypeError`) — **AC-6**
- [ ] 2.9 Confirm `tests/integrations/embeddings/test_factory.py` and
      `tests/integrations/generation/test_factory.py` pass **unmodified**, especially
      the cases passing an explicit `Settings` — **AC-6**
- [ ] 2.10 Add a closeable double to `tests/api/fakes.py` that records `close()` calls,
      and one whose `close()` raises
- [ ] 2.11 Add identity tests for both dependencies: `a is b`, **plus** a build counter
      asserting the factory ran exactly once — identity alone passes vacuously if
      something memoizes a layer down — **AC-1, AC-2**
- [ ] 2.12 Add a test that two consecutive `POST /chat` requests see the identical
      embedding provider, recorded from **inside** `embed()`, **and** that exactly one
      `boto3.client` was constructed across both — identity implies client identity
      only because the client is built eagerly, which is an implementation fact, not a
      tested one — **AC-3**
- [ ] 2.13 Add a test that two consecutive `POST /chat` requests see the identical chat
      model, recorded from **inside** the generation call. Install the double by
      patching `generation.bedrock_provider.ChatBedrock`, **not** by passing
      `chat_model=` — the constructor seam skips `_get_chat_model()`'s lazy branch and
      would leave AC-4's actual claim unproven — **AC-4**
- [ ] 2.14 Test that releasing closes each provider before dropping it, that **all
      three** caches end empty when one `close()` raises, and that the failure reaches
      the caller — **AC-11**
- [ ] 2.15 Test that releasing an empty cache constructs nothing, by making the factory
      raise if called — a post-condition on `currsize` would pass
      unconditionally — **AC-12**

## 3. Make the release contract a requirement, not a hope — **AC-13**

> Not droppable. `isinstance(provider, Closeable)` is a method-*presence* check, so
> without this group a provider that omits `close()` is skipped silently and its
> resource abandoned — the exact failure `adb-001` task 5.7 described. Group 2 alone
> replaces private-attribute coupling; this group is what retires 5.7.

- [ ] 3.1 Extend `tests/integrations/test_registry.py` with an assertion parameterized
      over every entry of the three `PROVIDERS` dicts
      (`embeddings/factory.py:17`, `generation/factory.py:17`, `vector_store/factory.py`),
      failing the build if a registered provider declares no `close()`. The registries
      are enumerable, which is what makes this a gate rather than a hope — **AC-13**
- [ ] 3.2 Give the failure message enough context to act on: which provider, and that
      release would skip it silently and abandon its resource
- [ ] 3.3 Record in the test's docstring that this proves *declaration*, not
      *diligence* — a no-op `close()` still passes, and that is the limit of a
      structural check

## 4. Bound the Bedrock calls — **AC-9, AC-10**

- [ ] 4.1 Add `bedrock_connect_timeout` (`gt=0`, default 3), `bedrock_read_timeout`
      (`gt=0`, default 8) and `bedrock_max_attempts` (`ge=1`, default 2) to
      `app/core/config.py`. The bounds matter: botocore reads a `connect_timeout` of
      `0`/`None` as *no timeout*, the inverse of the intent — **AC-10**
- [ ] 4.2 Build the `botocore.config.Config` inside
      `embeddings/bedrock_provider.py` and pass it to `boto3.client` — **AC-9**
- [ ] 4.3 Pass a `Config` to `ChatBedrock(config=...)` in
      `generation/bedrock_provider.py`, and confirm it reaches **both** clients
      `ChatBedrock` builds (`langchain_aws/llms/bedrock.py:948`, `:976`) — **AC-9**
- [ ] 4.4 Read the three values from `get_settings()` inside each
      `_build_bedrock_provider()` and pass them to the provider. The registry callables
      keep taking **no** parameters: an explicit `Settings` passed to the factory
      selects which provider is built, not how it is configured — **AC-9**
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
- [ ] 4.9 Document the three variables in `.env.example` and in `README.md`'s
      environment table — `adb-001` landed its pool vars in all three places, and these
      are the two surfaces a human reads to discover configuration — **AC-10**

## 5. Verify nothing else regressed — **AC-5, AC-8**

- [ ] 5.1 Confirm the `/chat` tests injecting fakes via `app.dependency_overrides`
      still work, and add the explicit test: with an override registered, the fake
      serves the request and **no real Bedrock client is constructed** — **AC-5**
- [ ] 5.2 Confirm `classify_scope`'s unrecognized-verdict fallback behaves identically
      with a cached generator — the provider holds no verdict state, but it is the path
      most dependent on the provider, as the ticket asks
- [ ] 5.3 Give AC-8 a gate instead of a manual check: extend
      `tests/architecture/test_integration_boundaries.py` so a module under
      `ingestion/` importing `app.api.deps` fails the build. The ten existing tests in
      `tests/ingestion/test_ingest.py` all drive `ingest_document`/`ingest_all` with
      injected providers and never call `main()`, so none of them would notice if
      ingestion started resolving through the API layer — **AC-8**
- [ ] 5.4 Confirm the architecture test still passes otherwise: the new
      `botocore.config` imports are inside `*_provider.py`, and `lifecycle.py` imports
      only `typing`
- [ ] 5.5 Add an assertion that every entry of `_CACHED_PROVIDER_DEPENDENCIES` reports
      `currsize == 0` after the autouse fixture runs, so a fourth cached dependency
      added without being registered fails instead of contaminating silently — **AC-7**
- [ ] 5.6 Verify each new test fails against the unfixed code — remove the decorators
      and the `Config` and confirm the expected failures — so they guard the regression
      instead of passing vacuously
- [ ] 5.7 Run the full suite: green at **124 baseline + the new tests**, 8 skipped

## 6. Keep the written record true

- [ ] 6.1 Extend `openspec/specs/provider-lifecycle/spec.md` per OQ-7: generalize the
      purpose line off "vector store", add requirements for the embedding and
      generation providers, the `Closeable` + AC-13 release contract, and the Bedrock
      ceiling. Use whatever guarded phrasing AC-1/AC-2 ended up with, so the capability
      spec does not keep the old unguarded "at most once per process" universal
- [ ] 6.2 **Narrow** that spec's scenario at `:52-55` — "the provider reflects the
      supplied settings rather than the process-wide settings" is false of the code
      (`_build_*_provider()` takes no arguments and calls `get_settings()`); correct it
      rather than copying it onto the sibling providers
- [ ] 6.3 Update `app/api/deps.py`'s module docstring: it currently explains the cache
      in terms of "a provider that owns connections", which was accurate when the
      vector store was the only cached one
- [ ] 6.4 Correct `README.md:316` — it says the RAG path makes **two** Bedrock calls;
      it makes three (`chat.py:34`, `:39`, `:51`), and this change's whole timeout
      arithmetic is built on that count
- [ ] 6.5 Tick the `adb-002` acceptance criteria and close the ticket. Also record the
      priority revision (High, not deployment-blocking) and the retry-budget reduction
      in the tracker and the second brain, since `ticket.md` is preserved verbatim
- [ ] 6.6 Note on `adb-001` task 5.7 that the deferred contract shipped here — citing
      AC-13, not `Closeable` alone, as what closed it

---

## Definition of done

**This spec PR** (docs only): `spec.md`, `plan.md` and `tasks.md` reviewed and merged.
No implementation code, and therefore **no test, lint, or build run belongs to this
PR** — the baseline in 1.1 is a measurement, not a gate.

**The implementing PR**: every task above checked; every AC covered by a named test;
full suite green at 124 + new tests with 8 skipped; the architecture test passing; the
capability spec updated and corrected.

## AC coverage

| AC | Task | Test that proves it |
|---|---|---|
| AC-1 embedder once per process | 2.2, 2.11 | `test_deps.py` — identity + factory build counter |
| AC-2 generator once per process | 2.2, 2.11 | `test_deps.py` — identity + factory build counter |
| AC-3 two requests, one embedder and one client | 2.12 | `test_deps.py` — identity inside `embed()` + `boto3.client` construction counter |
| AC-4 two requests, one chat model | 2.13 | `test_deps.py` — identity inside the generation call, double patched at the module symbol |
| AC-5 override beats the cache | 5.1 | `test_deps.py` — fake served it, no real client built |
| AC-6 factories uncached | 2.8, 2.9 | existing `test_factory.py` modules, unmodified |
| AC-7 no cross-test contamination | 2.6, 2.7, 5.5 | `conftest.py` fixture + the `currsize == 0` registration assertion in 5.5 |
| AC-8 ingestion does not use the API deps | 5.3 | `tests/architecture/test_integration_boundaries.py` — new import rule |
| AC-9 every Bedrock client bounded | 4.2–4.6, 3.1 | `test_bedrock_provider.py` (both) for the values; `test_registry.py` for the universal |
| AC-10 ceiling-removing values rejected | 4.1, 4.7 | `tests/core/test_config.py` — `ValidationError` cases |
| AC-11 release closes, always clears, never silent | 2.3, 2.4, 2.14 | `test_deps.py` — raising `close()`, all caches empty, failure reaches the caller |
| AC-12 empty release builds nothing | 2.15 | `test_deps.py` — factory raises if called |
| AC-13 every provider declares its release contract | 3.1–3.3 | `tests/integrations/test_registry.py` — parameterized over the `PROVIDERS` dicts |
