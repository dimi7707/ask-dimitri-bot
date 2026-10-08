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

- `ChatBedrock` exposes a `config` field (`langchain_aws/llms/bedrock.py:763`).
- `ChatBedrock` builds **two** boto3 clients, not one: `self.client` for
  `bedrock-runtime` (`:948`) and `self.bedrock_client` for the `bedrock` control plane
  (`:976`), both assigned when not supplied, both receiving the effective config.
- boto3 clients expose `close()`.
- botocore's default retry config is `legacy` mode with **5 attempts**; its default
  read timeout is 60 s.

All four are load-bearing below.

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

### Release through a separate `Closeable` protocol, **plus** a requirement that providers implement it

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
`BedrockGenerationProvider.close()` closes **both** clients its `ChatBedrock` owns —
`self._chat_model.client` and `self._chat_model.bedrock_client` — if a chat model was
ever built, then drops the reference.

*Why not `close()` on `VectorStoreProvider` / `EmbeddingProvider` /
`GenerationProvider`?* They are `runtime_checkable`, so `isinstance` checks method
presence — adding `close()` breaks the four doubles that are explicitly
protocol-asserted (`tests/integrations/{embeddings,generation,vector_store}/test_factory.py`
and `tests/api/test_deps.py::test_engine_holding_vector_store_satisfies_the_protocol`) until each grows a method that releases nothing. The
doubles in `tests/api/fakes.py` are satisfied structurally and never
`isinstance`-checked, so they are unaffected either way. A separate protocol removes
the `getattr(provider, "_engine", None)` coupling at zero churn to current fakes.

**`isinstance` alone does not retire `adb-001` task 5.7, so AC-13 does.** A
`runtime_checkable` Protocol check is method *presence*: a provider that owns a resource
and omits `close()` returns `False`, is dropped from the cache unreleased, and — since
this change adds no telemetry — says nothing. That is the same silent leak task 5.7
described, with `getattr` swapped for a quiet `False`. The honest fix is a presence
*requirement*, not a presence *check*:

```python
# tests/integrations/test_registry.py (extending the existing registry test)
@pytest.mark.parametrize("provider_name,build", _every_registered_provider())
def test_every_cached_provider_declares_its_release_contract(provider_name, build):
    assert isinstance(build(), Closeable), (
        f"{provider_name} is reachable through a cached dependency but declares no "
        "close(); release would skip it silently and abandon its resource"
    )
```

The three `PROVIDERS` dicts in `embeddings/factory.py:17`, `generation/factory.py:17`
and `vector_store/factory.py` are an **enumerable** registry, which is what makes this
a real gate rather than a hope. The coupling to `ChatBedrock`'s attributes sits inside a
`*_provider.py` file, the one place the architecture test permits vendor coupling.

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
        raise failures[0] if len(failures) == 1 else ExceptionGroup("provider release failed", failures)

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
cross-test contamination the reset exists to prevent.

**Every failure is reported, not just the first.** A bare `raise failures[0]` would
discard the rest, and with no telemetry in this change they would vanish entirely while
the tuple's ordering silently decided which error a caller saw. A single failure is
re-raised as itself, so `adb-001`'s
`test_reset_vector_store_clears_the_cache_even_if_dispose_fails` — which asserts
`pytest.raises(RuntimeError)` — keeps passing unmodified; multiple failures are raised
as an `ExceptionGroup` (Python 3.12, which this project targets).

`reset_vector_store()` is kept and re-expressed over `_release`. Its behavior is
unchanged for real providers: disposal via `PgVectorStoreProvider.close()` instead of
the `getattr` sniff.

**Two `adb-001` reset tests need a one-line change to their double, and the spec says
so rather than promising they are untouched.** The reset tests do not exercise
`PgVectorStoreProvider`; they use `EngineHoldingVectorStore`
(`EngineHoldingVectorStore` in `tests/api/test_deps.py`), which extends `FakeVectorStore`
(`tests/api/fakes.py:23`) and holds an `_engine` but declares no `close()` — verified:
`isinstance(FakeVectorStore(), Closeable)` is `False`. Keying the release on `Closeable`
would therefore skip the dispose for that double, so
`test_reset_vector_store_disposes_the_engine_before_dropping_the_provider`
would fail on `disposals == [True]` and
`test_reset_vector_store_clears_the_cache_even_if_dispose_fails` would fail
with DID NOT RAISE. The fix is to give `EngineHoldingVectorStore` a `close()` that
disposes its engine — which is what the production provider does, so the double becomes
*more* faithful, not less. The third reset test (`test_reset_vector_store_builds_nothing_when_nothing_is_cached`) is
genuinely unaffected.

This is called out loudly because the tempting repair when those two go red is to put
the `getattr(provider, "_engine", None)` sniff back alongside the `isinstance` check,
which reinstates exactly the coupling OQ-1 exists to remove.

### Bedrock timeouts in `Settings`, applied to every client, at the cost of retries

```python
# inside each bedrock_provider.py
config=Config(
    connect_timeout=connect_timeout,   # default 3
    read_timeout=read_timeout,         # default 8
    retries={"mode": "standard", "total_max_attempts": max_attempts},  # default 2
)
```

**Correction, found at implementation time: the key is `total_max_attempts`, not
`max_attempts`.** This sketch originally named the latter, and botocore's two keys differ by
exactly one: `max_attempts` in a client `Config` counts retries *after* the initial request, so
botocore rewrites it as `total_max_attempts = value + 1` (`botocore/args.py:600-620`). Passing
`2` there would permit **three** calls at ~11 s each — ~33 s, outside the 30 s Lambda budget, which
is the very shape of defect OQ-3 rejected in the ticket's proposal. `total_max_attempts` includes
the initial request and is what botocore's own documentation prefers
(`botocore/config.py:147-161`). Both provider tests assert the resolved `retries` dict rather than
just the count, because the wrong key validates without complaint.

Three new `Settings` fields — `bedrock_connect_timeout` (`gt=0`),
`bedrock_read_timeout` (`gt=0`), `bedrock_max_attempts` (`ge=1`). The retry **mode** is
a literal `"standard"` in the provider, not a fourth setting: it is the semantics the
attempt count is expressed in, not a per-runtime tunable, and `max_attempts` without it
silently keeps legacy backoff.

**The defaults live in `Settings` only.** The three provider parameters are
**required**, not defaulted, so 3 / 8 / 2 are written in exactly one place and cannot
drift. That makes the provider constructors' signatures change, which the existing
provider tests construct directly
(`tests/integrations/embeddings/test_bedrock_provider.py:26-28`,
`generation/test_bedrock_provider.py:31-33`) — so those two files must be updated, and
they are listed in *Affected layers* and in `tasks.md` rather than discovered at
implementation time. Defaulting them on the provider instead would duplicate the
numbers and let a `Settings` default and a provider default disagree, with only one of
the three covered by the end-to-end task.

**Which `Settings` instance feeds them.** The process-wide one, via `get_settings()`
inside each `_build_bedrock_provider()`. This is explicit because the alternative is a
plausible misreading: `_build_bedrock_provider()` takes **no parameters** today
(`embeddings/factory.py:7`, `generation/factory.py:7`), and the `settings` argument on
`get_embedding_provider` / `get_generation_provider` is used only to pick the registry
key (`:22-24` in each). So an explicit `Settings` passed to the factory selects *which
provider* is built, not *how it is configured* — exactly as `adb-001`'s pool settings
behave, and why `test_factory_sizes_the_pool_from_settings` in `tests/api/test_deps.py` monkeypatches
`vector_store_factory.get_settings` rather than passing settings in. **The registry
callables do not gain a parameter in this change.** `openspec/specs/provider-lifecycle/spec.md:52-55`
currently claims the opposite ("the provider reflects the supplied settings rather than
the process-wide settings"); task 6.1 narrows that scenario instead of copying it onto
the siblings.

*Why `Settings` and not literals?* `adb-001` shipped `pool_size=1` as a literal and its
review made it configurable, because the same image runs under uvicorn in
`docker compose` where the Lambda-shaped default is wrong. The bounds exist for the same
reason the pool bounds do: botocore reads a `connect_timeout` of 0 or `None` as *no
timeout*, the inverse of the intent, and that is one `.env` typo away.

*Why every client?* The ticket configures only embeddings, but generation makes two of
the three Bedrock calls per question, and `ChatBedrock` builds two clients of its own.
Leaving any of them at botocore's 60 s default is an asymmetry with no defense.

**The retry reduction is deliberate and is the price of the ceiling.** botocore defaults
to `legacy` mode with 5 attempts; this sets `standard` mode with 2. Five attempts cannot
fit inside 30 s (5 × 11 s = 55 s), so a real per-call ceiling necessarily retries less —
a throttled call surfaces after 2 attempts instead of 5. `spec.md`'s *Non-goals* states
this rather than leaving it to be found in production. If throttling resilience should
win, `read_timeout=6, max_attempts=3` (~27 s) is the alternative recorded in OQ-3.

### Prove reuse by identity, recorded from inside the request

Following `adb-001`: the identity assertions record the object *inside* `embed()` and
inside the generation call, not by reading `deps.get_embedder()` back from the module.
Reading it back bypasses FastAPI's dependency resolution, so a future route that stopped
using the cached dependency would leave the test green while per-request construction
returned.

Identity alone is not enough, and the same reasoning applies to clients as to providers:
AC-1/AC-2 count factory invocations, and AC-3 counts `boto3.client` constructions.
Provider identity implies client identity only because `BedrockEmbeddingProvider` builds
its client eagerly — an implementation fact, not a tested one, and a refactor to a lazy
per-call client would keep an identity-only test green while reintroducing the very
handshake churn this change exists to remove.

For AC-4 the double is installed by patching the module symbol
`generation.bedrock_provider.ChatBedrock`, **not** by passing
`BedrockGenerationProvider(chat_model=...)`. The constructor seam already exists
(`bedrock_provider.py:8-11`) and the existing provider tests use it
(`tests/integrations/generation/test_bedrock_provider.py:31-33`), but injecting there
skips `_get_chat_model()`'s lazy branch entirely — the test would prove the provider is
reused (already AC-2) and leave AC-4's actual claim unproven.

The timeout configuration is asserted by capturing the kwargs the provider passes to
`boto3.client` / `ChatBedrock`, not by reading botocore internals off the built client —
same rationale as `adb-001`'s `create_engine` capture: an upstream rename should produce
a meaningful failure, not an `AttributeError`. The residual: `ChatBedrock` also exposes
its own **`timeout`** and **`max_retries`** fields (`langchain_aws/llms/bedrock.py:766`,
`:771` — verified; there are no `read_timeout`/`connect_timeout` fields), which
`_get_effective_config()` (`:908-927`) **merges over** `config`. So a later change
setting `timeout` or `max_retries` would satisfy the kwargs capture while moving the
effective ceiling — and `max_retries` moves the *attempt count* AC-9 bounds, not just
the timeouts. Accepted — asserting the built client's private config trades one blind
spot for a more brittle one.

## Affected layers

Dependency direction, as the architecture test enforces it: `api` → `services` →
`integrations`; raw SDKs are reachable only from `integrations/*/[a-z]*_provider.py`.
Nothing here inverts that.

| Layer | File | Change |
|---|---|---|
| integrations (new) | `app/integrations/lifecycle.py` | `Closeable` protocol; imports only `typing` |
| integrations | `app/integrations/vector_store/pgvector_provider.py` | add `close()` disposing the engine |
| integrations | `app/integrations/embeddings/bedrock_provider.py` | `Config(...)` on the client; add `close()` |
| integrations | `app/integrations/generation/bedrock_provider.py` | `config=` on `ChatBedrock`; `close()` for both its clients; docstring now true |
| integrations | `app/integrations/embeddings/factory.py`, `generation/factory.py` | read the three timeout settings from `get_settings()` and pass them to the provider |
| core | `app/core/config.py` | three bounded `Settings` fields |
| api | `app/api/deps.py` | `@lru_cache` on both dependencies; `reset_providers()`; `reset_vector_store()` over `_release`; module docstring updated (it currently explains the cache in terms of "a provider that owns connections") |
| tests | `tests/api/conftest.py` | autouse fixture calls `reset_providers()` |
| tests | `tests/api/test_deps.py` | new reuse/release tests; `fresh_settings` also resets providers; `EngineHoldingVectorStore` gains `close()` so the `adb-001` reset tests still exercise the dispose |
| tests | `tests/api/fakes.py` | a closeable double recording `close()`, and one whose `close()` raises |
| tests | `tests/integrations/embeddings/test_bedrock_provider.py` | captured-kwargs assertions for the `Config`; `close()` behavior; **constructor calls updated** for the three now-required parameters |
| tests | `tests/integrations/generation/test_bedrock_provider.py` | captured-kwargs assertions; `close()` closes both clients; **constructor calls updated** likewise |
| tests | `tests/integrations/test_registry.py` | AC-13: every registered provider declares `Closeable` |
| tests | `tests/core/test_config.py` | `ValidationError` for ceiling-removing values |
| tests | `tests/architecture/test_integration_boundaries.py` | AC-8: `ingestion/` must not import `app.api.deps` |
| docker | `docker/docker-compose.yml` | pass the three env vars through, as `adb-001` did for the pool |
| config docs | `.env.example` | document the three `BEDROCK_*` vars — `adb-001` landed its pool vars here too |
| docs | `README.md` | add the three vars to the environment table; correct "two Bedrock calls" to three (`README.md:316`) |
| capability spec | `openspec/specs/provider-lifecycle/spec.md` | generalize purpose; add sibling-provider, `Closeable` and ceiling requirements; narrow the false settings scenario at `:52-55` |

## Invariant → enforcement

| AC | Invariant | Chokepoint | Proof |
|---|---|---|---|
| AC-1 | Embedding provider built at most once per process, absent an override or a release | `@lru_cache` on `deps.get_embedder` — the single resolution path for the route | `tests/api/test_deps.py` — identity across two calls **plus** a build counter asserting the factory ran once |
| AC-2 | Generation provider built at most once per process, same conditions | `@lru_cache` on `deps.get_generator` | same shape as AC-1 |
| AC-5 | A registered override always wins over the cache | FastAPI's own override resolution, which runs before the dependency is called | `tests/api/test_deps.py` — override registered, `/chat` issued, fake recorded the call and no real client was constructed |
| AC-10 | A ceiling-removing value is rejected, not accepted | `Settings` field constraints (`gt=0`, `ge=1`) — validation happens before any provider is built | `tests/core/test_config.py` — `ValidationError` for `0`/negative timeout and `0` attempts |
| AC-11 | A release never leaves a populated cache behind, and never fails silently | `_release`'s `finally`, plus `reset_providers()` collecting failures across the loop and raising them | `tests/api/test_deps.py` — a double whose `close()` raises; assert all three caches empty and the error surfaces |
| AC-13 | Every provider behind a cached dependency declares its release contract | The three `PROVIDERS` registries are the single enumerable list of providers that exist | `tests/integrations/test_registry.py` — parameterized `isinstance(..., Closeable)` over every registered provider |

AC-3, AC-4, AC-6, AC-7, AC-8, AC-9 and AC-12 are behavioral rather than invariants;
their tests are listed in `tasks.md`. **AC-9 is deliberately in that list**: its two
construction sites are two chokepoints, the repo's rule rejects that as enforcement,
and the architecture test forbids collapsing them into one module. AC-9's own note in
`spec.md` records the consequence — a third Bedrock client can land unbounded.

## Gates this change adds

- **`tests/architecture/test_integration_boundaries.py` (existing, extended).** As it
  stands it rejects a `botocore.config` import from anywhere under `app/` or
  `ingestion/` that is not a `*_provider.py` directly inside
  `app/integrations/<capability>/`. **What still passes it:** a new
  `other_provider.py` building an unbounded client — it is a *location* gate, not a
  *usage* gate, which is exactly why AC-9's chokepoint is the registry assertion and
  not this. It also structurally **forbids** a shared `Config` builder module (any
  `app/integrations/bedrock_config.py` importing `botocore.config` fails the build),
  which is why no such module appears above. This change extends it with one rule:
  `ingestion/` must not import `app.api.deps`, giving AC-8 a gate instead of a manual
  check.
- **The registry assertion (new).** Parameterized over the `PROVIDERS` dicts, it fails
  the build when a provider reachable through a cached dependency declares no
  `close()`. **What still passes it:** a provider that implements `close()` as a no-op
  while holding a resource. That is a weaker promise than "no leaks", and it is the
  strongest promise an enumerable registry can make without inspecting each provider's
  internals.
- **`Settings` field bounds (new).** `gt=0` / `ge=1` reject `0`, negatives, and
  non-numerics at startup. **What still passes:** a syntactically valid but useless
  ceiling — `bedrock_read_timeout=600` is accepted and silently exceeds the Lambda
  budget. Nothing enforces the relationship between these values and the 30 s timeout,
  because the Lambda timeout is not visible to the app. The aggregate-budget limitation
  in OQ-3 is therefore unenforced by construction, which is why it is a recorded
  non-goal rather than a claimed guarantee.
- **The build-counter assertions (new).** Asserting `a is b` alone passes vacuously if
  something memoizes one layer down; counting factory invocations is what makes AC-1
  and AC-2 real, and counting `boto3.client` constructions is what makes AC-3 real.
  **Precondition:** these counters are order-dependent until the reset fixture exists,
  which is why `tasks.md` lands the reset in the same group as the caches.

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
- **The ingestion batch job inherits the ceiling it was not sized for** → the `Config`
  lands in `_build_bedrock_provider()`, the same factory `ingestion/ingest.py:130`
  calls, so the batch job also moves to 8 s / 2 attempts. **Accepted**: each ingestion
  call is a single short `embed()` of one chunk, for which 8 s is generous. The real
  exposure is the retry budget over a long run — a transient throttle now fails a chunk
  after two attempts instead of five. If a large ingest starts failing, the fix is
  ingestion-specific values, not reverting the ceiling. Recorded in `spec.md`'s
  *Non-goals* so the behavior change on a declared-out-of-scope path is stated.
- **Fewer retries against a throttle-prone endpoint** → **accepted deliberately**, and
  recorded in `spec.md`'s *Non-goals*: 2 attempts instead of botocore's default 5 is
  what buys a ceiling inside 30 s. If `/chat` starts surfacing `ThrottlingException`,
  the recorded alternative is `read_timeout=6, max_attempts=3`.
- **A cached provider outlives a `Settings` change** → only matters in tests, where
  `fresh_settings` now resets providers too. In Lambda, settings are fixed per
  container.
- **`close()` depends on `ChatBedrock`'s `client` and `bedrock_client` attributes** →
  both verified present in langchain-aws 1.7.3; an upstream rename degrades `close()`
  to releasing less than it should. Mitigated by keeping the access inside the provider
  file and asserting in that provider's own test that both clients are closed.
- **A provider can satisfy `Closeable` with a no-op `close()`** → the registry gate
  proves declaration, not diligence. Accepted as the limit of a structural check.
- **A third timeout triple is one more thing to configure** → the defaults are the
  Lambda-correct values, so only a non-Lambda runtime needs to touch them.

## Rollout & rollback

No data migration, no schema change, no HTTP contract change. Ships with the normal
Lambda container image build. Deploy order is irrelevant — nothing outside the process
observes the cache.

Rollback is a straight revert: dropping the two decorators restores per-request
providers, dropping the `Config` restores botocore defaults — including the 5-attempt
retry budget, which is worth knowing if the revert is motivated by throttling.

Post-deploy signal: p50 latency on `POST /chat` drops by roughly the handshake time to
the Bedrock endpoint for the second and later questions in a container, and a hung
Bedrock call now surfaces as a provider-level timeout at ~22 s instead of the Lambda's
own 30 s cutoff. No new telemetry is added — observability is not in scope, which is
also why a silently-skipped release would be invisible, and therefore why AC-13 is a
build-time gate rather than a runtime warning.

## ADR impact

This repo keeps no ADR directory, so the decision is recorded here and in the capability
spec. The architectural rule this change establishes:

> **Providers that own a releasable resource declare it by implementing `Closeable`,
> and every provider reachable through a cached dependency is checked for that
> declaration at build time.** Cached-provider release goes through that protocol —
> never by reaching for a private attribute. Caching stays at the argument-less
> dependency layer; factories remain uncached because they accept an unhashable
> `Settings`, and an explicit `Settings` selects which provider is built, not how it is
> configured.

The first clause is new (and retires `adb-001` task 5.7, via AC-13 rather than via
`Closeable` alone); the second restates the rule `adb-001` established; the third
corrects what `openspec/specs/provider-lifecycle/spec.md:52-55` currently asserts. All
three land in that capability spec per OQ-7, which is the capability-level contract and
the right home for a rule that outlives this change.
