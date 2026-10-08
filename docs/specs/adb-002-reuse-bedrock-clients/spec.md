# adb-002-reuse-bedrock-clients — Bedrock clients are rebuilt on every request

| | |
|---|---|
| **Status** | Proposed |
| **Ticket** | [ticket.md](./ticket.md) (adb-002, detected at `eb18bb9`) |
| **Type** | bug |
| **Priority** | High, **not** deployment-blocking — revised down from the ticket's 🔴 critical; see OQ-6 |
| **Related** | `adb-001` (`openspec/changes/archive/2026-09-26-reuse-vector-store-engine/`) — same root cause, same fix, already shipped for the vector store |

## Problem

`get_embedder` and `get_generator` in `app/api/deps.py:26,60` are uncached FastAPI
dependencies. FastAPI's own dependency cache spans a single request and never spans
two, so every `POST /chat` builds a fresh `BedrockEmbeddingProvider` — whose
`__init__` eagerly creates a `boto3.client("bedrock-runtime", ...)` — and a fresh
`BedrockGenerationProvider`, whose `ChatBedrock` is then built on first use within
that request and discarded with it.

`app/integrations/generation/bedrock_provider.py:22-30` already holds a lazy cache
for exactly this cost, introduced by `eb18bb9` to avoid a ~90 s credential-resolution
hang. It memoizes **per instance**, and the instance is per request, so the cache
never serves a second question. Its docstring — "Build the Bedrock client on first
use, then reuse it" — is false across requests today.

Reproduced on `origin/main` (`410e39c`):

```text
embedder same instance?        False
embedder same boto3 client?    False
generator same instance?       False
Settings hashable?             False -> unhashable type: 'Settings'
```

**Measured cost, and why it is not the cost the ticket claims.** Construction itself
is cheap once the process is warm: the first `boto3.client` in a process costs ~140 ms
(botocore parses the service model), but botocore caches that on the default session,
so every subsequent client costs **~1.5 ms**. `ChatBedrock` construction measured
**~9 ms** on a machine with resolvable credentials. Steady-state waste is therefore
roughly **10 ms per request**, not the "critical, production-blocking" latency the
ticket's header asserts.

The cost that *does* justify this change is one the ticket does not name: a botocore
client owns a `urllib3` connection pool, so a client built per request **cannot reuse
the keep-alive HTTPS connection** the previous request established to the Bedrock
endpoint. Every one of the up to three Bedrock calls per question pays a fresh TCP+TLS
handshake to a regional endpoint, and each abandoned client holds its sockets until the
garbage collector finalizes it. That is the same shape of defect as `adb-001`, against
a managed multi-tenant endpoint instead of Aurora — so it wastes latency rather than
exhausting a quota, but it is connection churn, not merely object churn.

## Goals

- One embedding provider and one generation provider per process, reused across
  requests and across invocations of a warm Lambda execution environment.
- The Bedrock HTTPS connection pool survives between questions, so the second question
  in a container does not re-handshake.
- `_get_chat_model()`'s docstring becomes true: `ChatBedrock` is built once per
  process, not once per request.
- A single, explicit release contract for cached providers, replacing the attribute
  sniffing `adb-001` left behind — and a check that every cached provider actually
  participates in it.
- A bounded ceiling on how long one unresponsive Bedrock call can run.
- Automated proof of all of the above, and proof that `app.dependency_overrides` and
  the existing factory tests are unaffected.

## Non-goals

- Caching the factories themselves. `get_embedding_provider(settings=...)` takes a
  Pydantic `Settings`, which is **not hashable** (confirmed above); memoizing there
  raises `TypeError` in the existing factory tests. Caching belongs at the
  argument-less dependency layer, as it already does for the vector store.
- Bedrock error *handling* — catching and translating `ThrottlingException` or
  `AccessDeniedException` into an HTTP response (finding A1). **This change does,
  however, deliberately shrink the retry budget**: botocore's current default is
  `legacy` mode with **5 attempts**, and AC-9 replaces it with `standard` mode at
  **2**. A throttled or 5xx Bedrock call therefore surfaces after two attempts
  instead of five. That is a real change to failure behavior, forced by the
  arithmetic in OQ-3, and it is stated here rather than discovered in production.
- A request-level deadline across the up-to-three Bedrock calls one question makes.
  AC-9 bounds a single call, not the aggregate — see OQ-3.
- Normalizing `message.content` when it is not a string (finding M1).
- The ingestion path's **provider lifecycle**. `ingestion/ingest.py:17` imports the
  embedding factory directly and builds its providers once in `main()`, so it never
  resolves the API dependency and gains nothing from the caches. This change must
  **verify** that, not alter it (AC-8).

  **But ingestion does inherit the client ceiling, and that is a behavior change on
  this path.** The `Config` lands in `_build_bedrock_provider()`, which is the same
  factory `ingest.py:130` calls, so the batch job moves from botocore's 60 s read
  timeout and 5 legacy attempts to 8 s and 2 — numbers justified by a 30 s Lambda
  budget that does not apply to a batch job. Accepted, because each ingestion Bedrock
  call is a single short `embed()` of one chunk, for which 8 s is generous; the real
  exposure is the reduced retry budget across a long run, where a transient throttle
  now fails a chunk after two attempts. Recorded as a risk in `plan.md` rather than
  discovered during a large ingest. If it bites, the fix is ingestion-specific values,
  not reverting the ceiling.
- The storage and document-processing providers. Neither is an API dependency — both
  are reached only from `ingestion/` — so neither is rebuilt per request. (The
  ticket's evidence snippet samples `get_storage_provider`, which illustrates the
  shared factory pattern but is not itself on the request path.)

## Acceptance criteria

> **A note on naming.** Several criteria below name Python symbols
> (`get_embedder`, `app.dependency_overrides`). That is a deliberate continuation of
> the precedent in `openspec/specs/provider-lifecycle/spec.md:10-13`, which phrases the
> same capability over "the `get_vector_store` API dependency". The observable behavior
> in every case is *what a second request gets*; the symbol names the seam where it is
> observable in this codebase.

> **The sequential guard.** AC-1, AC-2 and AC-4 are stated over *sequential*
> resolution. OQ-5 deliberately accepts a race in which two concurrent first requests
> each construct a provider, so these criteria would be false as unguarded universals
> on a threadpool runtime. The accepted allowance is bounded: **at most one extra
> construction per cache, and only on the first concurrent resolution**; steady state
> is one provider per process either way.

- **AC-1** *(invariant)* — WHILE no override is registered for the embedding
  dependency, the provider cache has not been released, and resolutions are not
  concurrent first resolutions (OQ-5), repeated resolutions of `get_embedder` SHALL
  return the identical provider object, and the system SHALL NOT construct a second
  embedding provider for a second request.
- **AC-2** *(invariant)* — WHILE no override is registered for the generation
  dependency, the provider cache has not been released, and resolutions are not
  concurrent first resolutions (OQ-5), repeated resolutions of `get_generator` SHALL
  return the identical provider object, and the system SHALL NOT construct a second
  generation provider for a second request.
- **AC-3** — WHEN a client sends two consecutive `POST /chat` requests handled by the
  same process, THEN the embedding provider observed from inside the embedding call
  SHALL be the identical object on both requests, and the **embedding provider** SHALL
  have constructed exactly **one** `boto3` client across both. (The generation path
  constructs two more — see OQ-3 — which this criterion does not count.)
- **AC-4** — WHEN a client sends two consecutive `POST /chat` requests handled by the
  same process, **the chat model was constructed successfully on the first**, and the
  requests are sequential (OQ-5), THEN the chat model observed from inside the
  generation call SHALL be the identical object on both requests, so the Bedrock HTTPS
  connection established by the first question remains available to the second.
- **AC-5** *(invariant)* — WHILE an override for a provider dependency is registered
  in `app.dependency_overrides`, the system SHALL serve the request from the override
  and SHALL NOT return the cached provider, and no real Bedrock client SHALL be
  constructed **for that dependency**. Dependencies left un-overridden stay on the real
  resolution path by design — that is what keeps the cache under test live.
- **AC-6** — The embedding and generation factories SHALL continue to accept an
  optional explicit `Settings` argument and SHALL NOT be memoized.
- **AC-7** — WHEN an API test runs, THEN it SHALL observe no provider cached by a
  previously-run test, so no test's outcome depends on suite ordering.
- **AC-8** — WHEN the standalone ingestion script runs, THEN it SHALL build its own
  providers at its entry point and SHALL NOT resolve them through the API dependency
  layer.
- **AC-9** — WHEN the embedding provider or the generation provider constructs a
  Bedrock client, THEN **every** client it constructs SHALL carry a connect timeout, a
  read timeout, and a maximum attempt count under botocore's **`standard`** retry mode,
  defaulting to **3 s**, **8 s**, and **2 attempts** — so one unresponsive Bedrock call
  cannot consume more than ~22 s of the Lambda's 30 s budget. This applies to the
  embedding provider's client and to **both** clients `ChatBedrock` creates (see OQ-3).
  The retry mode is part of the contract: `max_attempts` without `standard` mode leaves
  legacy backoff semantics in place and changes what the arithmetic means.

  *Not marked `(invariant)`.* An invariant needs one chokepoint, and this has two — the
  two provider constructors. The repo's own rule says an invariant enforced in two
  places is enforced in neither, and the architecture test structurally forbids the
  shared config-builder module that would make it one place (any
  `app/integrations/bedrock_config.py` importing `botocore.config` fails the build). So
  this is behavioral over the two named providers, and the **recorded limitation** is
  that a future third Bedrock client — a new provider, a reranker, a control-plane call
  — can land unbounded with a green suite. AC-13's registry gate covers release
  declaration, not ceilings.
- **AC-10** *(invariant)* — The timeout and attempt values SHALL be configurable per
  runtime without a code change, and configuration SHALL reject values that remove the
  ceiling (a non-positive timeout or an attempt count below 1), rather than silently
  accepting an unbounded client.
- **AC-11** *(invariant)* — WHEN the cached providers are released, THEN every cached
  provider that exposes a release operation SHALL have it invoked before its cache
  entry is dropped; **every** cache entry SHALL be dropped even if a release raises;
  and the release SHALL report at least one failure to its caller rather than
  completing silently.
- **AC-12** — IF a release is requested while nothing is cached, THEN the system SHALL
  succeed without constructing a provider — on a cold Lambda, constructing one just to
  release it would resolve credentials for nothing.
- **AC-13** *(invariant)* — **Every** provider reachable through a cached API
  dependency SHALL declare a release operation, regardless of whether it currently owns
  a releasable resource, and one that does not SHALL fail the build rather than be
  skipped silently at release time. The qualifier is deliberately absent: a gate that
  tried to decide which providers "own something releasable" would have to inspect each
  provider's internals, and the first stateless provider would be fixed by narrowing
  the gate rather than by declaring. A stateless provider declares `close()` as a no-op
  — the ceremony is the point, because it is what makes the omission visible.

## Open questions

All raised by the blindspot pass and resolved with the requester before planning.

### OQ-1 — Does this change land the `close()` contract that `adb-001` deferred *to it*? — **Closed**

`adb-001`'s task 5.7 names this ticket as the home for the deferred fix:

> `reset_vector_store()` finds the engine via `getattr(provider, "_engine", None)`, so
> a second vector-store implementation holding its resource under another name
> silently reintroduces the leak. A `close()` on the `VectorStoreProvider` protocol is
> the honest fix; deferred to `adb-002`, which is where sibling providers arrive.

**Decision: land it as a separate `Closeable` protocol**, not as a method on the three
capability protocols. `PgVectorStoreProvider.close()` disposes its engine; the Bedrock
providers close their clients. The release path tests `isinstance(provider, Closeable)`
instead of sniffing `_engine`.

*Rationale:* the capability protocols are `runtime_checkable`, so adding `close()` to
them would make `isinstance` fail for every double that is explicitly protocol-checked
— `tests/integrations/embeddings/test_factory.py:14`,
`generation/test_factory.py:14`, `vector_store/test_factory.py:32`, and
`tests/api/test_deps.py:51` — until each grows a method that releases nothing. A
separate protocol leaves all four valid.

**One fake does change, and not for protocol reasons.** `EngineHoldingVectorStore`
(`tests/api/test_deps.py:34-47`) extends `FakeVectorStore` (`tests/api/fakes.py:23`),
which has **no** `close()` — verified: `isinstance(FakeVectorStore(), Closeable)` is
`False`. Since the release path keys on `Closeable`, that double must gain a `close()`
that disposes its engine, or `reset_vector_store()` would silently skip the dispose and
two of the three `adb-001` reset tests would fail. See `plan.md`; it is a task, not an
afterthought.

**Correction after review.** `isinstance` against a `runtime_checkable` Protocol is a
method-*presence* test, so a provider that owns a resource and simply omits `close()`
returns `False` and is dropped unreleased — the identical silent leak `adb-001`
described, with `getattr` swapped for a quiet `False`. A presence *check* is not a
presence *requirement*. AC-13 therefore adds the requirement, enforced over the
enumerable `PROVIDERS` registries, and this change retires `adb-001` task 5.7 only
because AC-13 exists — not because `Closeable` exists. Drives AC-11, AC-13.

### OQ-2 — What is the reset surface for the two new caches? — **Closed**

`tests/api/conftest.py:20` resets only the vector store, because it was the only cached
dependency. Two more caches make that fixture incomplete, and the `fresh_settings`
fixture at `tests/api/test_deps.py:180` would leave providers built from the *old*
`Settings` in place.

**Decision: one `reset_providers()` in `deps.py`** that walks all three caches, closes
whatever is `Closeable`, and clears each entry in a `finally`. The autouse fixture in
`tests/api/conftest.py` and `fresh_settings` both call it. `reset_vector_store()` is
**kept**, re-expressed over the same mechanism, so the `adb-001` tests keep calling it
by name — though two of them need a one-line change to their double, per OQ-1 above.

*Rationale:* three separate functions put the burden on every future caller to remember
all of them, and the conftest fixture is exactly the place where forgetting one is
invisible. Deleting `reset_vector_store()` would be cleaner long-term but edits tests
the ticket asks to leave alone. Drives AC-7, AC-11, AC-12.

### OQ-3 — Are the botocore timeouts in this change, and with which numbers? — **Closed**

The ticket offers them as "optional but recommended", but the configuration it proposes
does not fit the runtime it cites: `read_timeout=25` with
`retries={"mode": "standard"}` is **3 attempts**, so the worst case is ~75 s against a
**30 s** Lambda budget. A ceiling above the enclosing timeout is not a ceiling.

**Decision: in scope, on every Bedrock client this code constructs**, with
`connect_timeout=3, read_timeout=8, retries={"mode": "standard", "max_attempts": 2}` —
~22 s worst case per call, inside the 30 s budget.

*Rationale:* botocore's default read timeout is 60 s, so today a single hung call
consumes the whole Lambda; any correct ceiling is strictly better, and the constructor
is being touched anyway. Configuring only the embedding client, as the ticket wrote it,
would leave the busier path at the default — generation makes two of the three calls.

**The retry budget is being spent to buy the ceiling, and that is a real trade.**
botocore's current default is `legacy` mode with **5 attempts**; this change moves to
`standard` mode with **2**. Five attempts cannot coexist with a ceiling inside 30 s
(5 × 11 s = 55 s), so bounding the call necessarily means retrying less. The
consequence is that a throttled Bedrock call now reaches the caller after 2 attempts
where it previously retried 5 times, which is recorded in *Non-goals* rather than left
implicit. If throttling resilience should outweigh the tight ceiling, the alternative
is `read_timeout=6, max_attempts=3` (~27 s worst case) — still inside the budget, one
more attempt, each attempt given less time.

**Two clients, not one.** Verified in langchain-aws 1.7.3: `ChatBedrock` builds
`self.client` for `bedrock-runtime` **and** `self.bedrock_client` for the `bedrock`
control plane (`langchain_aws/llms/bedrock.py:948`, `:976`), assigning both when not
supplied. Both receive the config, so AC-9 holds for both — but only because the
config is passed, which is why AC-9 says "every client it constructs".

**Recorded limitation:** a per-call ceiling does not bound the aggregate. Three calls at
~22 s each still exceed 30 s, so the Lambda timeout remains the backstop for the
pathological case. A request-level deadline is the real fix and belongs with A1; it is
named as a non-goal above rather than left to be discovered.

### OQ-4 — Does the spec claim the ~90 s hang is paid once per process? — **Closed**

`_get_chat_model()` assigns `self._chat_model` only after `ChatBedrock(...)` returns,
so if credential resolution raises, the attribute stays `None` and the next request
retries. On a machine with no credentials the ~90 s block repeats per request *after*
this fix, exactly as before — the ticket's final acceptance criterion is true only on
the success path.

**Decision: scope the claim to the success path** (AC-4 now says so explicitly) and
record the failure behavior as a known limitation pointing at A1.

*Rationale:* memoizing the failure would make request 2 onward fail fast, which is
better behavior, but it changes error semantics without A1's error handling to give the
failure a meaningful shape — and a transient credential failure would then be pinned
for the life of the container. Constructing eagerly instead would reintroduce precisely
the provider-resolution hang `eb18bb9` removed on purpose.

### OQ-5 — Is a shared cached provider safe under the threadpool runtime? — **Closed**

`def chat` (`app/api/routes/chat.py:18`) is a **sync** route, so Starlette dispatches it
to a threadpool and several requests touch one cached provider concurrently — not
hypothetical here, since `adb-001` sized the connection pool from `Settings` precisely
because `docker compose` runs this image under uvicorn. `_get_chat_model()` is a
check-then-set with no lock, and `lru_cache` can likewise run the factory twice under a
race.

**Decision: accept the race and document it as a trade-off** in `plan.md`. No lock.

*Rationale:* losing the race builds one extra `ChatBedrock` that is immediately
discarded — ~9 ms of waste, once, with no corruption, because the loser's object is
simply dropped. boto3 clients are thread-safe for making calls, so sharing the cached
client across threadpool threads is correct. A lock on every request's hot path to
protect a one-time 9 ms waste is the wrong trade.

### OQ-6 — Does the ticket's priority survive the measurement? — **Closed**

The ticket is labelled 🔴 critical / production-blocking, inherited from `adb-001`,
which genuinely took the service down by exhausting Aurora's `max_connections`. Measured
construction waste here is ~10 ms per request on a path spending hundreds of
milliseconds per Bedrock call, and the ticket's own impact table concedes it "does not
bring down the service".

**Decision: revise to High, not deployment-blocking**, re-justified on connection churn
and latency rather than resource exhaustion. Recorded in the header table above.
`ticket.md` is preserved verbatim and keeps its original label; the tracker and the
second brain should be updated to match this spec.

*Rationale:* a spec that asserts a severity its own measurement contradicts teaches the
next reader to distrust its numbers. The bug is still worth fixing — the fix is small
and the churn argument is real — it just does not block a deploy.

### OQ-7 — Does `openspec/specs/provider-lifecycle/spec.md` get updated? — **Closed**

`adb-001` created a `provider-lifecycle` capability whose stated purpose is "how
integration providers and their underlying connection resources are created, cached, and
reused" — and every requirement under it currently says *vector store*. After this
change that capability spec describes one third of the actual behavior.

**Decision: extend it in the implementing PR** — generalize its purpose line and add
requirements covering the embedding and generation providers, the `Closeable` contract,
and the Bedrock ceiling. The `spec.md` / `plan.md` / `tasks.md` for this change live in
`docs/specs/` as requested; `openspec/specs/` remains the capability-level contract.

**Also correct, do not duplicate.** That capability spec currently asserts a scenario
the code does not satisfy: "the provider reflects the supplied settings rather than the
process-wide settings" (`openspec/specs/provider-lifecycle/spec.md:52-55`). The
`_build_*_provider()` callables in the registries take no arguments and read
`get_settings()` directly, so an explicit `Settings` selects the *registry key* only.
That scenario must be narrowed, not copied onto the sibling providers.

*Rationale:* leaving it untouched would park an active document that states something
false about the system. Migrating the capability into `docs/` entirely is the coherent
end state but exceeds this ticket and deserves its own chore.

> **Note on spec homes.** This change's artifacts live in `docs/specs/` by explicit
> request, while `adb-001` lives in `openspec/changes/archive/`. The two directories
> coexist for now; `docs/specs/README.md` records how they relate.

## Constraints from the repo's own rules

- **Providers are the only place raw SDKs may be imported.**
  `tests/architecture/test_integration_boundaries.py` fails the build if any module
  under `app/` or `ingestion/` imports `boto3`, `botocore`, `langchain`, or
  `llama_index` unless it is a `*_provider.py` file directly under an
  `integrations/<capability>/` package. The `botocore.config.Config` from AC-9 must
  therefore live inside the `bedrock_provider.py` files, and the `Closeable` protocol
  must not import a vendor SDK. **This also forbids** a single shared config-builder
  module, which is why AC-9 is behavioral over two construction sites rather than an
  invariant with one chokepoint — see AC-9's note and `plan.md`.
- **Caching belongs to the dependency layer, not the factory** — established by
  `adb-001` and documented in `app/api/deps.py:6-8` and
  `openspec/specs/provider-lifecycle/spec.md` ("Provider factories accept explicit
  settings and remain uncached").
- **Provider contracts are `Protocol`s** (`app/integrations/*/base.py`), structural and
  `runtime_checkable`; the test doubles in `tests/api/fakes.py` satisfy them by shape,
  which is what OQ-1 protects.
- This repo has no `CLAUDE.md`, no `AGENTS.md`, no `docs/architecture.md`, and no ADR
  directory. The authorities above are the architecture test, `openspec/specs/`, and
  the `adb-001` archived change.
