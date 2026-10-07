# adb-002-reuse-bedrock-clients — Bedrock clients are rebuilt on every request

| | |
|---|---|
| **Status** | Proposed |
| **Ticket** | [ticket.md](./ticket.md) (adb-002, detected at `eb18bb9`) |
| **Type** | bug |
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

```
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
- Automated proof of all of the above, and proof that `app.dependency_overrides` and
  the existing factory tests are unaffected.

## Non-goals

- Caching the factories themselves. `get_embedding_provider(settings=...)` takes a
  Pydantic `Settings`, which is **not hashable** (confirmed above); memoizing there
  raises `TypeError` in the existing factory tests. Caching belongs at the
  argument-less dependency layer, as it already does for the vector store.
- Bedrock error handling — `ThrottlingException`, `AccessDeniedException` (finding A1).
- Normalizing `message.content` when it is not a string (finding M1).
- The ingestion path. `ingestion/ingest.py:17` imports the embedding factory directly
  and builds its providers once in `main()`, so it never resolves the API dependency.
  This change must **verify** that, not alter it.
- The storage and document-processing providers. Neither is an API dependency — both
  are reached only from `ingestion/` — so neither is rebuilt per request. (The
  ticket's evidence snippet samples `get_storage_provider`, which illustrates the
  shared factory pattern but is not itself on the request path.)

## Acceptance criteria

- **AC-1** *(invariant)* — The system SHALL resolve the embedding provider at most
  once per process: repeated resolutions of the `get_embedder` API dependency SHALL
  return the identical provider object.
- **AC-2** *(invariant)* — The system SHALL resolve the generation provider at most
  once per process: repeated resolutions of the `get_generator` API dependency SHALL
  return the identical provider object.
- **AC-3** — WHEN a client sends two consecutive `POST /chat` requests handled by the
  same process, THEN the embedding provider observed from inside the embedding call
  SHALL be the identical object on both requests, and no second `boto3` client SHALL
  be created for the second request.
- **AC-4** — WHEN a client sends two consecutive `POST /chat` requests handled by the
  same process, THEN the chat model observed from inside the generation call SHALL be
  the identical object on both requests, so the Bedrock HTTPS connection established
  by the first question remains available to the second.
- **AC-5** *(invariant)* — WHILE an override for a provider dependency is registered
  in `app.dependency_overrides`, the system SHALL serve the request from the override
  and SHALL NOT return the cached provider, and no real Bedrock client SHALL be
  constructed for that request.
- **AC-6** — The embedding and generation factories SHALL continue to accept an
  optional explicit `Settings` argument and SHALL NOT be memoized; the existing tests
  in `tests/integrations/embeddings/test_factory.py` and
  `tests/integrations/generation/test_factory.py` SHALL pass unmodified.
- **AC-7** — WHEN an API test runs, THEN it SHALL observe no provider cached by a
  previously-run test, so no test's outcome depends on suite ordering.
- **AC-8** — WHEN the standalone ingestion script runs, THEN it SHALL continue to
  build its own providers at its entry point, unaffected by the API dependency cache.

*Bounds for a timeout ceiling (AC-9) and a release/`close()` contract depend on
OQ-3 and OQ-1 and are added once those are decided.*

## Open questions

Raised by the blindspot pass. **No plan is written while any of these is open.**

### OQ-1 — Does this change land the `close()` contract that `adb-001` deferred *to it*?

`adb-001`'s own task list closes with a deferred item (task 5.7) that names this
ticket as its home:

> `reset_vector_store()` finds the engine via `getattr(provider, "_engine", None)`, so
> a second vector-store implementation holding its resource under another name
> silently reintroduces the leak. A `close()` on the `VectorStoreProvider` protocol is
> the honest fix; deferred to `adb-002`, which is where sibling providers arrive.

The sibling providers now arrive. A botocore client has a real `close()`, and the
cached embedding provider holds one for the life of the process. Deciding this by
accident means either three bespoke `getattr`-sniffing reset helpers, or a release
contract on the protocols.

**Status:** open.

### OQ-2 — What is the reset surface for the two new caches?

`tests/api/conftest.py:20` resets only the vector store, because it was the only
cached dependency. Two more caches make that fixture incomplete: a test that resolves
the real embedding provider leaves a live boto3 client cached for every test that runs
after it, and `tests/api/test_deps.py:187` already has a `fresh_settings` fixture that
drops the memoized `Settings` — which would now leave providers built from the *old*
settings in place. The shape chosen here is what AC-7 is proven against.

**Status:** open.

### OQ-3 — Are the botocore timeouts in this change, and with which numbers?

The ticket offers them as "optional but recommended". The configuration it proposes
does not fit the runtime it cites:
`Config(connect_timeout=5, read_timeout=25, retries={"mode": "standard"})` — standard
mode defaults to **3 attempts**, so the worst case is ~75 s of read timeout against a
**30 s** Lambda budget. A ceiling that exceeds the enclosing timeout is not a ceiling.
If timeouts are in scope, the numbers must multiply out to less than the Lambda
timeout, and the asymmetry needs a decision too: the ticket configures only the
embedding client, while generation is the path that makes up to two Bedrock calls.

**Status:** open.

### OQ-4 — Does the spec claim the ~90 s hang is paid once per process?

The ticket's final acceptance criterion says construction is paid "once per process".
That holds only when construction **succeeds**. `_get_chat_model()` assigns
`self._chat_model` after `ChatBedrock(...)` returns, so if credential resolution
raises, the attribute stays `None` and the next request retries — on a machine with no
credentials the ~90 s block repeats per request *after* this fix, exactly as before.
Either the spec scopes the claim to the success path, or this change also has to decide
what a failed construction does.

**Status:** open.

### OQ-5 — Is a shared cached provider safe under the threadpool runtime?

`def chat` (`app/api/routes/chat.py:18`) is a **sync** route, so Starlette dispatches
it to a threadpool and several requests touch one cached provider concurrently. This
is not hypothetical for this repo: `adb-001` sized the connection pool from `Settings`
specifically because `docker compose` runs the same image under uvicorn with
concurrent requests. `_get_chat_model()` is a check-then-set with no lock, so two
threads can both observe `None` and both build a `ChatBedrock`; `lru_cache` can
likewise run the factory twice under a race.

**Status:** open.

### OQ-6 — Does the ticket's priority survive the measurement?

The ticket is labelled 🔴 critical / production-blocking, inherited from `adb-001`,
which genuinely took the service down by exhausting Aurora's `max_connections`. The
measured construction waste here is ~10 ms per request on a path that spends hundreds
of milliseconds per Bedrock call, and the ticket's own impact table concedes it "does
not bring down the service". The connection-churn argument above is the real one, and
it is a latency argument.

**Status:** open.

### OQ-7 — Does `openspec/specs/provider-lifecycle/spec.md` get updated?

`adb-001` created a `provider-lifecycle` capability whose stated purpose is "how
integration providers and their underlying connection resources are created, cached,
and reused" — and every requirement under it currently says *vector store*. After this
change that capability spec describes one third of the actual behavior. This spec lives
in `docs/specs/` by request, which does not by itself update the capability spec.

**Status:** open.

## Constraints from the repo's own rules

- **Providers are the only place raw SDKs may be imported.**
  `tests/architecture/test_integration_boundaries.py` fails the build if any module
  under `app/` or `ingestion/` imports `boto3`, `botocore`, `langchain`, or
  `llama_index` unless it is a `*_provider.py` file directly under an
  `integrations/<capability>/` package. Any `botocore.config.Config` from OQ-3 must
  therefore live inside `bedrock_provider.py`.
- **Caching belongs to the dependency layer, not the factory** — established by
  `adb-001` and documented in `app/api/deps.py:6-8` and
  `openspec/specs/provider-lifecycle/spec.md` ("Provider factories accept explicit
  settings and remain uncached").
- **Provider contracts are `Protocol`s** (`app/integrations/*/base.py`), structural and
  `runtime_checkable`; the test doubles in `tests/api/fakes.py` satisfy them by shape.
- This repo has no `CLAUDE.md`, no `AGENTS.md`, no `docs/architecture.md`, and no ADR
  directory. The authorities above are the architecture test, `openspec/specs/`, and
  the `adb-001` archived change.
