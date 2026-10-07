# 🔍 PR Review — `main...adb-001-reuse-vector-store-engine`

**PR:** [#1 — Adb 001 reuse vector store engine](https://github.com/dimi7707/ask-dimitri-bot/pull/1)
**Files reviewed:** 10 (3 source, 1 test, 6 spec/docs) — +563 / −1
**Test suite at review time:** ✅ 115 passed, 8 skipped

> **Status: all six findings addressed on this branch.** The suite is now at 120 passed, 8 skipped,
> and the 12 lifecycle guards were re-verified against the unfixed code (7 fail with `@lru_cache`
> removed). What changed per finding is recorded at the bottom of this file.

---

## Summary of the change

`get_vector_store` in `app/api/deps.py` is now `@lru_cache`-decorated, so one `PgVectorStoreProvider`
— and therefore one SQLAlchemy engine and connection pool — lives for the whole process instead of
being rebuilt on every request. The pgvector engine also gets `pool_pre_ping=True`, `pool_size=1`,
`max_overflow=2` for the Lambda freeze/thaw cycle against Aurora.

The diagnosis is correct and the chosen layer is the right one: `deps.get_vector_store` takes no
arguments, so it is safe to memoize, while `get_vector_store_provider(settings=...)` must stay
uncached because `Settings` is a Pydantic model and unhashable. The alternatives (module-level
singleton, `lifespan` + `app.state`, `NullPool`) are considered and rejected with sound reasoning in
`design.md`. The one real risk — the cache shadowing `app.dependency_overrides` — is covered by an
explicit test.

**No critical or blocking defect was found.** Everything below is hardening.

---

## 📄 `app/api/deps.py`

### 🟡 MINOR — Error handling / resource lifecycle
**Problem:** `cache_clear()` is documented as the supported way to get a fresh provider, but it drops
the provider reference without disposing its engine. The abandoned pool's connections are only
released when the garbage collector finalizes them.

❌ Current:
```python
@lru_cache
def get_vector_store() -> VectorStoreProvider:
    """...Tests that need a fresh provider call `get_vector_store.cache_clear()`."""
    return get_vector_store_provider()
```

✅ Suggested — give callers a reset that actually releases the pool:
```python
def reset_vector_store() -> None:
    """Dispose the cached provider's engine before dropping it, so its pool is released."""
    cached = get_vector_store.cache_info()
    if cached.currsize:
        engine = getattr(get_vector_store(), "_engine", None)
        if engine is not None:
            engine.dispose()
    get_vector_store.cache_clear()
```

💡 **Why:** harmless in tests today because `create_engine` is lazy and the test doubles never open a
socket. It stops being harmless the moment anything clears the cache in a process that has served
real traffic — exactly the connection leak this PR exists to remove.

### 🟡 MINOR — Consistency of the dependency layer
**Problem:** `get_embedder` and `get_generator` are still uncached, so a new provider is built per
request. `BedrockEmbeddingProvider.__init__` creates its `boto3` client eagerly, which means a new
`bedrock-runtime` client (credential resolution + botocore model parsing) on every `POST /chat`.

`design.md` scopes this out, which is reasonable — but the stated rationale is not quite right:

> `get_embedder` and `get_generator` are out of scope for this change; the Bedrock chat client is
> already built lazily

The chat client is lazy *per provider instance*. Since the instance itself is rebuilt per request,
the laziness never pays off across requests — `ChatBedrock` is still constructed once per request,
and the embedding client is not lazy at all.

💡 **Why:** the scoping decision stands (`adb-002` tracks it), but the justification in the design
doc would mislead whoever picks up `adb-002`. Worth correcting the sentence, or at least confirming
`adb-002` covers the embedding provider too and not just generation.

---

## 📄 `app/integrations/vector_store/factory.py`

✅ No problems found. The docstring explaining why this layer stays uncached is the right call —
it is precisely the comment that stops someone from "helpfully" adding `@lru_cache` here later.

---

## 📄 `app/integrations/vector_store/pgvector_provider.py`

### 🟡 MINOR — Hardcoding / runtime assumption
**Problem:** `pool_size=1` and `max_overflow=2` are inline literals, while every other tunable in the
project (`similarity_threshold`, `similarity_top_k`, `chunk_size`, `chunk_overlap`…) lives in
`Settings`. The sizing encodes the Lambda execution model, but the same code runs under `uvicorn` in
`docker compose`, where `def chat` (a sync route) is dispatched to Starlette's threadpool and several
requests can check out connections at once. Beyond 3 concurrent requests the 4th blocks for
`pool_timeout` (30 s by default) and then raises `QueuePool limit of size 1 overflow 2 reached`.

❌ Current:
```python
self._engine = create_engine(
    database_url,
    pool_pre_ping=True,
    pool_size=1,
    max_overflow=2,
)
```

✅ Suggested:
```python
# app/core/config.py
db_pool_size: int = 1
db_max_overflow: int = 2

# pgvector_provider.py
def __init__(self, database_url: str, pool_size: int = 1, max_overflow: int = 2):
    self._engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )
```

💡 **Why:** `design.md` already lists "`pool_size=1` becomes wrong if the runtime changes" as a risk
and asks for it to be revisited rather than silently inherited. Moving it to `Settings` makes the
revisit a `.env` change instead of a code change, and lets local dev differ from Lambda without
diverging from the deployed image. Low practical impact today (local dev is single-user), hence
minor.

> **Out of scope, flagged for awareness:** `similarity_search` (unchanged by this PR) reads
> `chunk.chunk_text` and `chunk.document_id` *after* the `with self._session()` block has closed the
> session. It works today because a plain `SELECT` with no commit leaves attributes loaded on the
> detached instances — but it is one `commit()` or one `expire_on_commit` change away from
> `DetachedInstanceError`. Building the result list inside the `with` block would remove the trap.

---

## 📄 `tests/api/test_deps.py`

### 🟠 IMPORTANT — Test coverage: the headline test does not assert what its name claims
**Problem:** `test_two_consecutive_chat_requests_share_one_provider_and_engine` never verifies that
either HTTP request was actually served by the cached provider. Both identity assertions come from
calling `deps.get_vector_store()` directly, which bypasses FastAPI's dependency resolution entirely.
The only thing asserted about the requests themselves is `status_code == 200`, and
`EngineHoldingVectorStore` records nothing.

❌ Current:
```python
first = client.post("/chat", json={"question": "¿Qué stack maneja Dimitri?"})
provider_after_first = deps.get_vector_store()
second = client.post("/chat", json={"question": "¿Y qué bases de datos usa?"})
provider_after_second = deps.get_vector_store()

assert first.status_code == 200
assert second.status_code == 200
assert provider_after_first is provider_after_second
assert provider_after_first._engine is provider_after_second._engine
```

✅ Suggested — let the double record the engine that each request actually used:
```python
class EngineHoldingVectorStore:
    def __init__(self):
        self._engine = create_engine(PROBE_DATABASE_URL)
        self.engines_used: list = []   # shared list, or a module-level collector

    def similarity_search(self, query_embedding, top_k):
        ENGINES_SEEN.append(self._engine)
        return [RetrievedChunk(...)]


def test_two_consecutive_chat_requests_share_one_provider_and_engine(monkeypatch):
    client = build_chat_client(monkeypatch)

    assert client.post("/chat", json={"question": "..."}).status_code == 200
    assert client.post("/chat", json={"question": "..."}).status_code == 200

    assert len(ENGINES_SEEN) == 2, "both requests must have reached the vector store"
    assert ENGINES_SEEN[0] is ENGINES_SEEN[1]
```

💡 **Why:** as written, the test guards the cache (`deps.get_vector_store()` would return distinct
objects against the unfixed code, so it does fail pre-fix — task 4.5 holds). What it does *not*
guard is the request path: if `/chat` later stopped resolving through the cached dependency — a new
route, a `Depends(get_vector_store_provider)`, a `use_cache=False` — this test would stay green while
the production defect came back. This is the PR's central guarantee, so it deserves an assertion that
observes the requests rather than the module.

### 🟡 MINOR — DRY: shared test doubles imported across test modules
**Problem:** the new module imports fakes from a sibling *test* module, in two separate
function-level imports, and `EngineHoldingVectorStore` re-declares the same four no-op protocol stubs
that `FakeVectorStore` already has.

❌ Current:
```python
def build_chat_client(monkeypatch):
    from tests.api.test_chat import FakeEmbeddingProvider, FakeGenerationProvider
    ...

def test_registered_override_wins_over_the_cached_provider(monkeypatch):
    from tests.api.test_chat import FakeVectorStore, chunk
```

✅ Suggested: move `FakeEmbeddingProvider`, `FakeVectorStore`, `FakeGenerationProvider` and `chunk`
into `tests/api/conftest.py` (the repo currently has no `conftest.py` at all) or `tests/fakes.py`,
and have `EngineHoldingVectorStore` subclass `FakeVectorStore`, overriding only `__init__`.

💡 **Why:** a test module importing another test module makes `test_chat.py` a de-facto public
fixture API — renaming a fake there now breaks an unrelated file, and the function-level imports
exist only to dodge that coupling. Collecting them in `conftest.py` is the idiomatic fix and removes
the duplicated stubs.

### 🟡 MINOR — Coupling to SQLAlchemy internals
**Problem:** the pool assertions read `pool._pre_ping` and `pool._max_overflow`, both private.

The inline comment already acknowledges this and it is genuinely the only observable surface for
`pre_ping`, so this is not a blocker — but a SQLAlchemy upgrade that renames either attribute turns
these into `AttributeError` rather than a meaningful failure. An alternative that stays public is to
capture the kwargs passed to `create_engine`:

```python
def test_pgvector_engine_is_configured_for_a_frozen_container(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        pgvector_provider, "create_engine",
        lambda url, **kwargs: captured.update(kwargs) or create_engine(url),
    )
    PgVectorStoreProvider(database_url=PROBE_DATABASE_URL)

    assert captured == {"pool_pre_ping": True, "pool_size": 1, "max_overflow": 2}
```

💡 **Why:** asserts the same contract against the project's own call site instead of SQLAlchemy's
internals. (`pool.size()` is public and fine to keep either way.)

---

## 📄 OpenSpec documents

`proposal.md`, `design.md`, `specs/provider-lifecycle/spec.md`, the archived delta spec and
`.openspec.yaml` are all coherent with the implementation: every requirement in the spec maps to a
test, and the four scenarios match the four test sections. Good traceability.

### 🟡 MINOR — Documentation accuracy in `tasks.md`
**Problem:** the recorded counts conflate *passed* with *collected*.

❌ Current:
```
1.1 ... (measured: **116 passed**; the ticket's "108" was stale)
5.3 ... confirm it is green at the baseline count plus the new tests (**123 passed** = 116 baseline + 7 new)
```

✅ Actual output on this branch: `115 passed, 8 skipped` (123 collected).

💡 **Why:** 116 and 123 are the *collected* totals; the passing totals are 108 and 115, with 8 skips
in both. In an SDD repo the task log is the durable record of the verification, so the numbers should
say what the runner said — otherwise the next person chasing a count mismatch loses time on a
discrepancy that was never real.

---

## 📋 Final verdict

| Severity | Count |
|---|---|
| 🔴 Critical | 0 |
| 🟠 Important | 1 |
| 🟡 Minor | 5 |
| **Total** | **6** |

**Fix priority**

1. 🟠 Make `test_two_consecutive_chat_requests_share_one_provider_and_engine` observe the request
   path (record the engine inside `similarity_search`) — it is the regression guard for the PR's
   core guarantee.
2. 🟡 Move the shared fakes into `tests/api/conftest.py` and drop the cross-test-module imports.
3. 🟡 Dispose the engine when the provider cache is cleared.
4. 🟡 Promote `pool_size` / `max_overflow` to `Settings`.
5. 🟡 Correct the `design.md` sentence about the "already lazy" Bedrock client, and confirm `adb-002`
   covers the embedding provider.
6. 🟡 Fix the passed/collected counts in `tasks.md`.

**Verdict: ✅ READY TO MERGE** — the fix is correct, well-reasoned, covered by tests that fail against
the unfixed code, and the suite is green. None of the findings block the merge; item 1 is worth doing
before merge if it is cheap, the rest are fine as follow-ups.

---

## ✅ Resolution

All six were fixed on the branch rather than deferred.

| # | Finding | What changed |
|---|---|---|
| 1 | 🟠 Reuse test didn't observe the request path | `EngineHoldingVectorStore.similarity_search` now records the engine it was called with, and `test_two_consecutive_chat_requests_share_one_engine` asserts on those two recordings instead of reading the identity back from the module. A second test pins that engine to the cached provider's. |
| 2 | 🟡 Fakes imported across test modules | Moved to `tests/api/fakes.py`; `EngineHoldingVectorStore` now extends `FakeVectorStore` instead of redeclaring its stubs. New `tests/api/conftest.py` holds the autouse isolation fixture, clearing overrides and the provider cache on the way in *and* out, so no test inherits the previous one's state. |
| 3 | 🟡 `cache_clear()` abandoned the pool | Added `deps.reset_vector_store()`, which disposes the engine before dropping it. The docstring on `get_vector_store` now points at it instead of at `cache_clear()`. |
| 4 | 🟡 Pool sizing hardcoded | `Settings.db_pool_size` / `Settings.db_max_overflow` (defaults 1 and 2), threaded through the factory into `PgVectorStoreProvider.__init__`. Documented in `README.md` and `.env.example`, covered in `tests/core/test_config.py`. |
| 5 | 🟡 `design.md` rationale on the "already lazy" Bedrock client | Corrected: the laziness is per instance and the instance is per request, so `ChatBedrock` is still built on every call and `BedrockEmbeddingProvider` creates its `boto3` client eagerly. `adb-002` is now stated to cover both siblings. |
| 6 | 🟡 passed/collected counts in `tasks.md` | Corrected to `108 passed, 8 skipped` baseline → `120 passed, 8 skipped` (128 collected). The ticket's "108" turned out to be right; it was the passing count, not a stale one. |

Also folded in: the pool-sizing and cache-reset behaviours were added to
`openspec/specs/provider-lifecycle/spec.md` as requirements, so the spec still describes what the
code does. The pre-existing `DetachedInstanceError` risk in `similarity_search` was left alone — it
predates this PR and is out of its scope.
