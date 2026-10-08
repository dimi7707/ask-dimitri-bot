# adb-002-reuse-bedrock-clients — tasks

Ordered so the suite stays green at every step. **Group 2 is the atomic slice**: the
caches and the reset that makes their tests order-independent land together, because a
cache without a reset fixture ships order-dependent tests and violates AC-7 by
construction. Groups 3–6 are additive and could be cut without invalidating group 2 —
with one exception called out in group 3, which is what lets this change claim it
retired `adb-001` task 5.7.

## 1. Baseline

> Already measured while writing this spec, on `origin/main` (`410e39c`); the numbers below
> are the values to re-confirm against, not work still to do.
>
> *Re-confirmed in the implementing PR, with one of the three taken on trust.* **1.1** was
> re-run on `origin/main` (`8d40e38`, which carries only the merged spec docs on top of
> `410e39c`): **124 passed, 8 skipped**, unchanged. **1.2**'s premise is re-proven more
> strongly than a manual probe would: removing the two decorators and shrinking the release
> tuple fails 12 of the new `tests/api/test_deps.py` tests, which is the defect expressed as
> a gate. **1.3**'s timings (~140 ms first client, ~1.5 ms thereafter, ~9 ms `ChatBedrock`)
> were **not** re-measured here — they are argumentative rather than load-bearing, since the
> case for this change rests on connection churn, not on construction cost.

- [x] 1.1 Record the suite baseline. Measured on `origin/main` (`410e39c`):
      **124 passed, 8 skipped** (132 collected) — unchanged since `adb-001`
- [x] 1.2 Reproduce the defect. Measured on `410e39c`: `get_embedding_provider()`
      twice gives different instances *and* different `_client` objects;
      `get_generation_provider()` twice gives different instances;
      `hash(Settings(_env_file=None))` raises `unhashable type: 'Settings'`
- [x] 1.3 Record the cost honestly for the plan's claims: first `boto3.client` in a
      process ~140 ms, every later one ~1.5 ms, `ChatBedrock` ~9 ms. Note that the
      per-request waste is ~10 ms and the real cost is the lost keep-alive connection

## 2. The cached dependencies and the reset that isolates them — **AC-1, AC-2, AC-3, AC-4, AC-6, AC-7, AC-11, AC-12**

- [x] 2.1 Add `app/integrations/lifecycle.py` with the `runtime_checkable` `Closeable`
      protocol (`close() -> None`). Imports from `typing` only, so the architecture
      test keeps passing
- [x] 2.2 Decorate `get_embedder` and `get_generator` with `@lru_cache` in
      `app/api/deps.py`, with docstrings saying what each cache buys (one client, and
      therefore one Bedrock HTTPS connection pool, per process) and noting that this is
      what finally makes `_get_chat_model()`'s "then reuse it" true across
      requests — **AC-1, AC-2**
- [x] 2.3 Add `_release(dependency)` and `reset_providers()` over
      `_CACHED_PROVIDER_DEPENDENCIES`, clearing each cache in a `finally`, collecting
      failures across the loop, and raising a lone failure as itself or several as an
      `ExceptionGroup` — **AC-11**
- [x] 2.4 Implement `close()` on the three providers: `PgVectorStoreProvider` disposes
      its engine; `BedrockEmbeddingProvider` closes its boto3 client;
      `BedrockGenerationProvider` closes **both** clients `ChatBedrock` owns
      (`client` and `bedrock_client`, verified present in langchain-aws 1.7.3) if a
      chat model was built, then drops the reference — **AC-11**
- [x] 2.5 Re-express `reset_vector_store()` as `_release(get_vector_store)`, off
      `getattr(provider, "_engine", None)`
- [x] 2.6 Give `EngineHoldingVectorStore` (in `tests/api/test_deps.py`) a `close()`
      that disposes its engine. **Required, not cosmetic:** it extends `FakeVectorStore`,
      which has no `close()`, so `isinstance(..., Closeable)` is `False` (verified) and
      two of the three `adb-001` reset tests would fail —
      `test_reset_vector_store_disposes_the_engine_before_dropping_the_provider` on
      `disposals == [True]`, and `test_reset_vector_store_clears_the_cache_even_if_dispose_fails`
      with DID NOT RAISE. Do **not** repair that by
      restoring the `getattr` sniff alongside the `isinstance` check; that reinstates the
      coupling this group removes. The empty-cache test
      (`test_reset_vector_store_builds_nothing_when_nothing_is_cached`) is unaffected
- [x] 2.7 Point the autouse fixture in `tests/api/conftest.py` at `reset_providers()`,
      still clearing on the way in as well as out — **AC-7**
- [x] 2.8 Make the `fresh_settings` fixture in `tests/api/test_deps.py` reset providers too, so a
      provider built from the previous `Settings` cannot survive the fixture — **AC-7**
- [x] 2.9 Leave both factories uncached and comment why (`Settings` is unhashable, so
      `lru_cache` there raises `TypeError`) — **AC-6**
- [x] 2.10 Confirm `tests/integrations/embeddings/test_factory.py` and
      `tests/integrations/generation/test_factory.py` pass **unmodified**, especially
      the cases passing an explicit `Settings` — **AC-6**
- [x] 2.11 Add a closeable double to `tests/api/fakes.py` that records `close()` calls,
      and one whose `close()` raises
- [x] 2.12 Add identity tests for both dependencies: `a is b`, **plus** a build counter
      asserting the factory ran exactly once — identity alone passes vacuously if
      something memoizes a layer down — **AC-1, AC-2**
- [x] 2.13 Add a test that two consecutive `POST /chat` requests see the identical
      embedding provider, recorded from **inside** `embed()`, **and** that the embedding
      provider constructed exactly one `boto3.client` across both — identity implies
      client identity only because the client is built eagerly, which is an
      implementation fact, not a tested one. Scope the counter to
      `embeddings.bedrock_provider.boto3`; the generation path builds two more
      clients — **AC-3**
- [x] 2.14 Add a test that two consecutive `POST /chat` requests see the identical chat
      model, recorded from **inside** the generation call. Install the double by
      patching `generation.bedrock_provider.ChatBedrock`, **not** by passing
      `chat_model=` — the constructor seam skips `_get_chat_model()`'s lazy branch and
      would leave AC-4's actual claim unproven — **AC-4**
- [x] 2.15 Test that releasing closes each provider before dropping it, that **all
      three** caches end empty when one `close()` raises, and that the failure reaches
      the caller — **AC-11**
- [x] 2.16 Test that releasing an empty cache constructs nothing, by making the factory
      raise if called — a post-condition on `currsize` would pass
      unconditionally — **AC-12**

## 3. Make the release contract a requirement, not a hope — **AC-13**

> Not droppable. `isinstance(provider, Closeable)` is a method-*presence* check, so
> without this group a provider that omits `close()` is skipped silently and its
> resource abandoned — the exact failure `adb-001` task 5.7 described. Group 2 alone
> replaces private-attribute coupling; this group is what retires 5.7.

- [x] 3.1 Extend `tests/integrations/test_registry.py` with an assertion parameterized
      over every entry of the three `PROVIDERS` dicts
      (`embeddings/factory.py:17`, `generation/factory.py:17`, `vector_store/factory.py`),
      failing the build if a registered provider declares no `close()`. The registries
      are enumerable, which is what makes this a gate rather than a hope — **AC-13**
- [x] 3.2 Give the failure message enough context to act on: which provider, and that
      release would skip it silently and abandon its resource
- [x] 3.3 Record in the test's docstring that this proves *declaration*, not
      *diligence* — a no-op `close()` still passes, and that is the limit of a
      structural check. Also record that the gate is unconditional **by design**: a
      future stateless provider declares `close()` as a no-op rather than being
      excluded, because a gate that decided for itself which providers own something
      releasable would be narrowed into uselessness the first time it over-fired

## 4. Bound the Bedrock calls — **AC-9, AC-10**

- [x] 4.1 Add `bedrock_connect_timeout` (`gt=0`, default 3), `bedrock_read_timeout`
      (`gt=0`, default 8) and `bedrock_max_attempts` (`ge=1`, default 2) to
      `app/core/config.py`. The bounds matter: botocore reads a `connect_timeout` of
      `0`/`None` as *no timeout*, the inverse of the intent — **AC-10**
- [x] 4.2 Build the `botocore.config.Config` inside
      `embeddings/bedrock_provider.py` and pass it to `boto3.client`. Include
      `"mode": "standard"` explicitly — `max_attempts` alone validates fine and leaves
      botocore's `legacy` backoff semantics in place, which is not what AC-9's
      arithmetic assumes — **AC-9**
- [x] 4.2b Make the three values **required** parameters on both provider
      constructors, so the defaults exist only in `Settings` and cannot drift. This
      changes both signatures: update the direct constructions in
      `tests/integrations/embeddings/test_bedrock_provider.py:26-28` and
      `generation/test_bedrock_provider.py:31-33`
- [x] 4.3 Pass a `Config` to `ChatBedrock(config=...)` in
      `generation/bedrock_provider.py`, and confirm it reaches **both** clients
      `ChatBedrock` builds (`langchain_aws/llms/bedrock.py:948`, `:976`) — **AC-9**
- [x] 4.4 Read the three values from `get_settings()` inside each
      `_build_bedrock_provider()` and pass them to the provider. The registry callables
      keep taking **no** parameters: an explicit `Settings` passed to the factory
      selects which provider is built, not how it is configured — **AC-9**
- [x] 4.5 Assert the configuration by capturing the kwargs passed to `boto3.client`
      and to `ChatBedrock`, not by reading botocore internals off the built client —
      an upstream rename must fail meaningfully, not as `AttributeError` — **AC-9**
- [x] 4.6 Test the env-var → `Settings` → factory → client path end to end for at
      least one of the three values, so the halves are not covered in isolation —
      **AC-9**
- [x] 4.7 Test that `Settings` rejects a `0`/negative timeout and a `0` attempt count
      with `ValidationError` in `tests/core/test_config.py` — **AC-10**
- [x] 4.8 Pass the three variables through `docker/docker-compose.yml`, as `adb-001`
      did for the pool settings, so the uvicorn runtime can widen them
- [x] 4.9 Document the three variables in `.env.example` and in `README.md`'s
      environment table — `adb-001` landed its pool vars in all three places, and these
      are the two surfaces a human reads to discover configuration — **AC-10**

## 5. Verify nothing else regressed — **AC-5, AC-7, AC-8**

- [x] 5.1 Confirm the `/chat` tests injecting fakes via `app.dependency_overrides`
      still work, and add the explicit test: with an override registered, the fake
      serves the request and **no real Bedrock client is constructed** — **AC-5**
- [x] 5.2 Confirm `classify_scope`'s unrecognized-verdict fallback behaves identically
      with a cached generator — the provider holds no verdict state, but it is the path
      most dependent on the provider, as the ticket asks
- [x] 5.3 Give AC-8 a gate instead of a manual check: extend
      `tests/architecture/test_integration_boundaries.py` so a module under
      `ingestion/` importing `app.api.deps` fails the build. The ten existing tests in
      `tests/ingestion/test_ingest.py` all drive `ingest_document`/`ingest_all` with
      injected providers and never call `main()`, so none of them would notice if
      ingestion started resolving through the API layer — **AC-8**
- [x] 5.4 Confirm the architecture test still passes otherwise: the new
      `botocore.config` imports are inside `*_provider.py`, and `lifecycle.py` imports
      only `typing`
- [x] 5.5 Add **two** assertions, because one of them only looks like it covers the
      other: (a) every entry of `_CACHED_PROVIDER_DEPENDENCIES` reports
      `currsize == 0` after the autouse fixture runs; and (b) the set of
      `functools.lru_cache`-wrapped callables in the `deps` module **equals**
      `_CACHED_PROVIDER_DEPENDENCIES`. Only (b) catches a fourth cached dependency
      nobody registered — iterating the tuple can never notice something missing from
      the tuple, which is the failure this task exists for — **AC-7**
- [x] 5.6 Verify each new test fails against the unfixed code — remove the decorators
      and the `Config` and confirm the expected failures — so they guard the regression
      instead of passing vacuously
- [x] 5.7 Run the full suite: green at **124 baseline + the new tests**, 8 skipped

## 6. Keep the written record true

- [x] 6.1 Extend `openspec/specs/provider-lifecycle/spec.md` per OQ-7: generalize the
      purpose line off "vector store", add requirements for the embedding and
      generation providers, the `Closeable` + AC-13 release contract, and the Bedrock
      ceiling. Use whatever guarded phrasing AC-1/AC-2 ended up with, so the capability
      spec does not keep the old unguarded "at most once per process" universal
- [x] 6.2 **Narrow** that spec's scenario at `:52-55` — "the provider reflects the
      supplied settings rather than the process-wide settings" is false of the code
      (`_build_*_provider()` takes no arguments and calls `get_settings()`); correct it
      rather than copying it onto the sibling providers
- [x] 6.3 Update `app/api/deps.py`'s module docstring: it currently explains the cache
      in terms of "a provider that owns connections", which was accurate when the
      vector store was the only cached one
- [x] 6.4 Correct `README.md:316` — it says the RAG path makes **two** Bedrock calls;
      it makes three (`chat.py:34`, `:39`, `:51`), and this change's whole timeout
      arithmetic is built on that count
- [x] 6.5 Tick the `adb-002` acceptance criteria and close the ticket. Also record the
      priority revision (High, not deployment-blocking) and the retry-budget reduction
      in the tracker and the second brain, since `ticket.md` is preserved verbatim

      *As shipped:* the criteria are recorded as met in a closure note in `ticket.md`'s
      editorial preamble — one table mapping each criterion to the test that proves it —
      rather than by ticking the boxes, because that file's own header says nothing below
      the marker is edited, and this ticket is its own system of record. The priority
      revision and the retry-budget reduction are in that note too. **The second brain
      (`my-2nd-brain`) is a separate repository and is deliberately left untouched here;
      it is the one remaining out-of-repo follow-up.** There is no external tracker — the
      ticket was pasted, which is why `ticket.md` is the record.
- [x] 6.6 Note on `adb-001` task 5.7 that the deferred contract shipped here — citing
      AC-13, not `Closeable` alone, as what closed it

---

## Definition of done

**This spec PR** (docs only): `spec.md`, `plan.md` and `tasks.md` reviewed and merged.
No implementation code, and therefore **no test, lint, or build run belongs to this
PR** — the baseline in 1.1 is a measurement, not a gate.

**The implementing PR**: every task above checked; every AC covered by a named test;
full suite green at 124 + new tests with 8 skipped; the architecture test passing; the
capability spec updated and corrected.

*Met.* **163 passed, 8 skipped** — the 124 baseline plus 39 new tests, with the architecture
test green and `openspec/specs/provider-lifecycle/spec.md` both extended and corrected. Each
new gate was verified to fail against the unfixed code rather than trusted to pass meaningfully:
removing the two `@lru_cache` decorators and shrinking the release tuple fails 12 of the new
`test_deps.py` tests; deleting `BedrockEmbeddingProvider.close()` fails the registry gate naming
the provider; dropping the `Config` fails the 7 ceiling tests; adding an `app.api.deps` import to
`ingestion/ingest.py` fails the new architecture rule.

**One divergence from this plan, recorded where it was found.** Group 4's `Config` uses
`retries["total_max_attempts"]`, not the `retries["max_attempts"]` that `plan.md` and `spec.md`
originally wrote. In a botocore client `Config` the latter counts retries *after* the initial
request — botocore rewrites it as `total_max_attempts = value + 1` — so a `2` there would have
permitted **three** calls at ~11 s, about 33 s, outside the 30 s budget AC-9 exists to fit inside.
That is the same defect OQ-3 rejected in the ticket's own proposal, and implementing the sketch
literally would have reintroduced it. `spec.md` AC-9 and OQ-3 and `plan.md` carry the correction,
and both provider tests assert the resolved `retries` dict, because the wrong key validates
silently.

## AC coverage

| AC | Task | Test that proves it |
|---|---|---|
| AC-1 embedder once per process (sequential) | 2.2, 2.12 | `test_deps.py` — identity + factory build counter |
| AC-2 generator once per process (sequential) | 2.2, 2.12 | `test_deps.py` — identity + factory build counter |
| AC-3 two requests, one embedder and one embedding client | 2.13 | `test_deps.py` — identity inside `embed()` + a `boto3.client` counter scoped to `embeddings.bedrock_provider` |
| AC-4 two requests, one chat model | 2.14 | `test_deps.py` — identity inside the generation call, double patched at the module symbol |
| AC-5 override beats the cache, per dependency | 5.1 | `test_deps.py` — fake served it, no real client built for that dependency |
| AC-6 factories uncached | 2.9, 2.10 | existing `test_factory.py` modules, unmodified |
| AC-7 no cross-test contamination | 2.7, 2.8, 5.5 | `conftest.py` fixture + both assertions in 5.5 — the set-equality one is what actually catches an unregistered cache |
| AC-8 ingestion does not use the API deps | 5.3 | `tests/architecture/test_integration_boundaries.py` — new import rule |
| AC-9 the two providers' clients are bounded | 4.1–4.6 | `test_bedrock_provider.py` (both) — captured kwargs incl. `standard` mode; one env-var path end to end. **Behavioral, not an invariant** — a third Bedrock client is not prevented; see AC-9's note |
| AC-10 ceiling-removing values rejected | 4.1, 4.7 | `tests/core/test_config.py` — `ValidationError` cases |
| AC-11 release closes, always clears, never silent | 2.3, 2.4, 2.6, 2.15 | `test_deps.py` — raising `close()`, all caches empty, failure reaches the caller |
| AC-12 empty release builds nothing | 2.16 | `test_deps.py` — factory raises if called |
| AC-13 every provider declares its release contract | 3.1–3.3 | `tests/integrations/test_registry.py` — parameterized over the `PROVIDERS` dicts |
