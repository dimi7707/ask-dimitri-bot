## Context

Greenfield project (no existing code, no existing OpenSpec specs, no git history). The system is a single Lambda running a FastAPI app (via Mangum) that answers questions about Dimitri's professional profile using a RAG pipeline: LlamaIndex for document processing, LangChain for retrieval/generation orchestration, Amazon Bedrock for embeddings (Titan V2) and generation (Nova Micro), and Postgres+pgvector (Aurora in prod, Docker locally) as the vector store. Source documents live in S3 (LocalStack locally).

The project's explicit purpose is to *learn and practice* a serverless GenAI architecture on AWS so the pattern is reusable in future commercial work. That learning goal directly motivates the central architectural decision below: every external service/library integration must sit behind a generic abstraction, so swapping a provider later (e.g. Bedrock → another model host, pgvector → a managed vector DB, LlamaIndex/LangChain → another orchestration library) is a localized change.

## Goals / Non-Goals

**Goals:**
- Ship a working `/chat` + `/health` API, runnable locally via Docker Compose (`make dev`) and deployable as a container-image Lambda.
- Enforce a hard boundary: application/business code (routes, services) never imports an AWS SDK or AI-framework symbol directly. All such access goes through a small set of factory-resolved provider interfaces.
- Implement the RAG safety behaviors already decided in the spec: similarity-threshold hallucination guard, off-topic rejection, bilingual responses, idempotent reindexing, optional debug context.
- Follow TDD for all business logic (services, providers, routes): tests define the contract before implementation.

**Non-Goals:**
- Terraform/IaC (explicitly deferred to a later phase; this change provisions nothing beyond local Docker Compose).
- WAF / per-IP rate limiting (documented as a future enhancement in the spec, not implemented here).
- Frontend integration (Astro) — out of scope per the spec document.
- Final content of the two profile PDFs — ingestion *mechanism* is in scope, the documents themselves are not.
- Building a general-purpose plugin system for arbitrary future providers — only the providers actually named in the spec (S3, Bedrock generation, Bedrock embeddings, pgvector, LlamaIndex-based processing) get an abstraction; no speculative extensibility beyond that.

## Decisions

### 1. Integration abstraction: Protocol + Factory per external dependency

Every external dependency gets its own small package under `app/integrations/<domain>/`:

```
app/integrations/
  storage/           # raw document storage (S3 / LocalStack)
    base.py          # StorageProvider protocol: upload, download, list, delete
    s3_provider.py   # boto3-based implementation (endpoint_url swaps for LocalStack)
    factory.py       # get_storage_provider() -> StorageProvider
  embeddings/        # text -> vector
    base.py          # EmbeddingProvider protocol: embed(text) -> list[float]
    bedrock_provider.py
    factory.py        # get_embedding_provider() -> EmbeddingProvider
  generation/        # prompt+context -> answer
    base.py          # GenerationProvider protocol: generate(system_prompt, question, context) -> str
    bedrock_provider.py  # wraps LangChain's ChatBedrock
    factory.py         # get_generation_provider() -> GenerationProvider
  vector_store/      # similarity search + persistence
    base.py          # VectorStoreProvider protocol: upsert_chunks, delete_by_document_id, similarity_search
    pgvector_provider.py  # SQLModel + pgvector.sqlalchemy.Vector
    factory.py           # get_vector_store_provider() -> VectorStoreProvider
  document_processing/  # file -> chunks
    base.py          # DocumentProcessor protocol: load_and_chunk(path) -> list[Chunk]
    llamaindex_provider.py
    factory.py         # get_document_processor() -> DocumentProcessor
```

Routes and services (`app/api/`, `app/services/`) import only from `app/integrations/<domain>/base.py` (the protocol) and `factory.py` (the resolver) — never the concrete `*_provider.py` modules, and never `boto3`, `langchain`, `llama_index`, or `psycopg`/`sqlalchemy` engine internals directly.

Each `factory.py` resolves the concrete implementation from a settings value (e.g. `STORAGE_PROVIDER=s3`, `LLM_PROVIDER=bedrock`, `VECTOR_STORE_PROVIDER=pgvector`, `EMBEDDING_PROVIDER=bedrock`, `DOCUMENT_PROCESSOR=llamaindex`), defaulting to the current implementation. This is the same env-driven-swap pattern the spec already applies to `BEDROCK_MODEL_ID` (section 7), extended to the provider itself, not just its model id — a future provider swap becomes "add a new `*_provider.py` implementing the same protocol + one new factory branch," not a change scattered across services.

**Alternatives considered:**
- *Direct SDK calls in services, revisit later if needed* — rejected: explicit user requirement, and retrofitting abstraction after code exists is exactly the "painful" scenario the user wants to avoid.
- *Single monolithic `AWSGateway` class covering all AWS services* — rejected: mixes unrelated concerns (storage vs. inference vs. embeddings) behind one interface, harder to test/mock in isolation, and doesn't cleanly cover the non-AWS integrations (LlamaIndex, LangChain).
- *Dependency-injection framework (e.g. `dependency-injector`)* — rejected as unnecessary complexity for a single-Lambda, single-developer experimental project; plain factory functions + `typing.Protocol` give the same swappability with far less machinery.

### 2. Provider interfaces are Protocols, not ABCs

Use `typing.Protocol` (structural typing) for `base.py` contracts instead of `abc.ABC`. Fakes used in tests don't need to inherit from anything — any object with the right methods satisfies the type. Keeps unit tests free of AWS/LangChain/LlamaIndex imports entirely.

### 3. Config centralized via `pydantic-settings`

`app/core/config.py` defines one `Settings(BaseSettings)` reading all environment variables (`BEDROCK_MODEL_ID`, `EMBEDDING_MODEL_ID`, `SIMILARITY_THRESHOLD`, `INCLUDE_DEBUG_CONTEXT`, `*_PROVIDER` selectors, DB DSN, S3/LocalStack endpoint, etc.). Factories and providers receive config through this single settings object — no `os.environ` reads scattered in provider code.

### 4. Lambda packaging: container image, not zip

`docker/Dockerfile` builds a container image for Lambda (via the AWS base image or a Mangum-compatible custom image). Rationale: LlamaIndex + LangChain + boto3 are heavy dependencies that are awkward to fit in a zip-based Lambda layer; a container image also matches "everything dockerized" from the spec and lets the exact same image run locally via `docker compose` and in Lambda.

### 5. Local dev topology

`docker/docker-compose.yml` runs three services: LocalStack (S3 only), Postgres+pgvector, and the API (running the FastAPI app directly with `uvicorn`, not through Mangum, for hot reload). Bedrock has no local emulation, so local dev calls real Bedrock with the low-cost Nova Micro / Titan V2 models, as already decided in the spec. `make dev` builds/starts this stack; other Makefile targets wrap common operations (`make test`, `make migrate`, `make ingest`, `make down`).

### 6. Testing strategy (TDD, per `implementation-quality` skill)

- **Unit tests** for services and route handlers use fake providers (plain Python objects satisfying the Protocol) — no network, no Docker required. These drive the Red→Green→Refactor cycle for business logic (threshold guard, off-topic handling, reindex-dedup logic).
- **Provider tests** (one per `*_provider.py`) verify the adapter against the real dependency where feasible in CI without cost/flakiness: `s3_provider` against LocalStack, `pgvector_provider` against a throwaway Postgres+pgvector container. `bedrock_provider` (generation + embeddings) is tested with the boto3/LangChain client mocked at the boundary — real Bedrock is only exercised manually through the Postman collection, never in automated tests, to avoid cost and nondeterminism.
- Every capability spec's scenarios (see `specs/`) map to at least one test.

## Risks / Trade-offs

- **Abstraction overhead for a single-developer experimental project** → Mitigation: keep each Protocol to only the methods actually called today (no speculative methods); the abstraction cost is a handful of small files, paid back the first time any provider changes.
- **Provider-specific tuning (e.g. Bedrock retry/backoff, `top_k` similarity search) could get hidden or awkward behind a generic interface** → Mitigation: providers accept their config via the shared `Settings` object and may expose provider-specific constructor kwargs; the protocol only constrains the call signature used by application code, not internal tuning.
- **Similarity threshold (0.6) may be too conservative and reject legitimate questions phrased differently from the source documents** → Mitigation: already env-configurable (`SIMILARITY_THRESHOLD`); `debug_context` in the response makes retrieval scores visible for tuning during manual testing.
- **Lambda cold starts with heavy dependencies (LlamaIndex, LangChain, boto3)** → Mitigation: container-image packaging (faster cold-start init than large zips with many files) and lazy-importing heavy libraries only inside the specific `*_provider.py` that needs them, so unrelated code paths don't pay the import cost.
- **No IaC yet — AWS resources created manually in console** → Mitigation: explicitly deferred per spec; document manual setup steps in the README so Terraform (later phase) has a clear source of truth to codify.
- **PII in ingested documents (CV, profile PDFs)** → Open question below; until resolved, the ingestion pipeline treats all ingested text as verbatim-quotable by the bot, per whatever documents Dimitri chooses to provide.

## Migration Plan

Greenfield build, sequenced to keep every step testable before the next depends on it:
1. Project skeleton: `pyproject.toml` (uv), `Makefile`, `app/core/config.py`, empty FastAPI app + Mangum handler, `GET /health`.
2. Integration layer: protocols + factories + fakes for all five domains, with unit tests against the fakes only.
3. Concrete providers: `s3_provider` (LocalStack), `pgvector_provider` (SQLModel models + Alembic migration for `documents`/`document_chunks`), `bedrock_provider` (embeddings + generation), `llamaindex_provider`.
4. `docker/docker-compose.yml` + `make dev` wiring LocalStack + Postgres + API together.
5. Ingestion script (`ingestion/ingest.py`) using the storage/document-processing/embedding/vector-store providers, with delete-by-`document_id`-before-reinsert reindexing.
6. Retrieval + generation services, then the `POST /chat` route (threshold guard, off-topic/system prompt, bilingual behavior, `debug_context`).
7. Postman collection + environment, exercised manually end-to-end.
8. Dockerfile for the Lambda container image; manual AWS console provisioning (API Gateway, Lambda, Aurora, Bedrock model access) documented in README.

Rollback: nothing is in production yet, so rollback is simply not deploying/discarding the Lambda container image; no data migration to reverse.

## Open Questions

- **PII policy**: which personal details from ingested documents the bot is allowed to repeat verbatim vs. redact — not yet decided (spec item, section 6). Needs a decision before ingesting the real CV/profile PDFs; does not block building the pipeline itself.
- **Prompt-injection mitigation depth**: spec calls for resilience to injection from user input and from ingested documents, but doesn't specify beyond system-prompt hardening. This change implements system-prompt-level mitigation only; a dedicated guard/library is out of scope unless the user asks for it.
- **HNSW index timing**: spec defers adding an HNSW index until data volume grows; this change ships without it, consistent with that decision.
