<!--
Conventions for implementation (see design.md and the project's implementation-quality skill):
- TDD: for every task that produces business logic, write the failing test(s) first (Red),
  implement the minimum to pass (Green), then refactor without breaking tests (Refactor).
- No route/service ever imports boto3, langchain, llama_index, or a DB engine directly —
  only app/integrations/<domain>/base.py (protocol) and factory.py (resolver).
- One git commit per completed task, authored as the project owner, message format:
  "tipo de ajuste: breve descripción" (e.g. "feat: add health check endpoint").
-->

## 1. Project Bootstrap

- [x] 1.1 Initialize git repository at the current directory root (no nested project folder) and add a Python `.gitignore` (venv, `__pycache__`, `.env`, `.terraform`, etc.)
- [x] 1.2 Initialize `pyproject.toml` via `uv` with project metadata and base dependencies (fastapi, mangum, uvicorn)
- [x] 1.3 Create the base repo structure from design.md: `app/`, `app/api/routes/`, `app/core/`, `app/services/`, `app/models/`, `app/integrations/`, `ingestion/`, `docker/`, `postman/`, `infra/terraform/` (placeholder `.gitkeep`)
- [x] 1.4 Add `Makefile` skeleton with `dev`, `test`, `down`, `migrate`, `ingest` targets (implemented incrementally as their dependencies land)

## 2. Core App Skeleton & Config

- [x] 2.1 Add `pydantic-settings`-based `app/core/config.py` with a `Settings` class covering all env vars from the spec (`BEDROCK_MODEL_ID`, `EMBEDDING_MODEL_ID`, `SIMILARITY_THRESHOLD`, `INCLUDE_DEBUG_CONTEXT`, provider selectors, DB DSN, storage endpoint) with sane local-dev defaults
- [x] 2.2 Write a unit test asserting `Settings` loads defaults and honors environment variable overrides
- [x] 2.3 Create `app/main.py` with a minimal FastAPI app instance and the Mangum handler (`handler = Mangum(app)`)

## 3. Integration Abstraction Layer (Protocols + Factories)

- [x] 3.1 Write unit tests for a `StorageProvider` protocol contract (upload/download/list/delete) using an in-memory fake, and add `app/integrations/storage/base.py` + `factory.py` to satisfy them
- [x] 3.2 Write unit tests for an `EmbeddingProvider` protocol contract (`embed(text) -> list[float]`) using a fake, and add `app/integrations/embeddings/base.py` + `factory.py`
- [x] 3.3 Write unit tests for a `GenerationProvider` protocol contract (`generate(system_prompt, question, context) -> str`) using a fake, and add `app/integrations/generation/base.py` + `factory.py`
- [x] 3.4 Write unit tests for a `VectorStoreProvider` protocol contract (`upsert_chunks`, `delete_by_document_id`, `similarity_search`) using a fake, and add `app/integrations/vector_store/base.py` + `factory.py`
- [x] 3.5 Write unit tests for a `DocumentProcessor` protocol contract (`load_and_chunk(path) -> list[Chunk]`) using a fake, and add `app/integrations/document_processing/base.py` + `factory.py`
- [x] 3.6 Confirm (via a lint/import-check test or manual grep) that no module outside `app/integrations/*/**_provider.py` imports `boto3`, `langchain`, or `llama_index`

## 4. Health Check (spec: `health-check`)

- [x] 4.1 Write a test for `GET /health` asserting HTTP 200 and a healthy-status body with all dependencies mocked/unavailable
- [x] 4.2 Implement `app/api/routes/health.py` and wire it into `app/main.py` to pass the test

## 5. Vector Store Provider & Data Model

- [x] 5.1 Add SQLModel models for `documents` and `document_chunks` per the confirmed schema (section 9 of the spec doc), including `pgvector.sqlalchemy.Vector(1024)` for `embedding`
- [x] 5.2 Add Alembic setup and initial migration creating both tables with the `vector_cosine_ops` index strategy (no HNSW yet, per design)
- [x] 5.3 Write tests for `pgvector_provider` (`upsert_chunks`, `delete_by_document_id`, `similarity_search`) against a real Postgres+pgvector test container
- [x] 5.4 Implement `app/integrations/vector_store/pgvector_provider.py` to pass those tests
- [x] 5.5 Wire `VECTOR_STORE_PROVIDER=pgvector` as the default in the factory

## 6. Storage Provider (S3 / LocalStack)

- [ ] 6.1 Write tests for `s3_provider` (upload/download/list/delete) against a LocalStack S3 endpoint
- [ ] 6.2 Implement `app/integrations/storage/s3_provider.py` (boto3-based, endpoint URL from `Settings`) to pass those tests
- [ ] 6.3 Wire `STORAGE_PROVIDER=s3` as the default in the factory

## 7. Embedding & Generation Providers (Bedrock)

- [ ] 7.1 Write tests for `bedrock_embedding_provider` with the Bedrock client mocked at the boundary, covering a successful embed call and an error path
- [ ] 7.2 Implement `app/integrations/embeddings/bedrock_provider.py` (Titan Embeddings V2, model id from `Settings.EMBEDDING_MODEL_ID`) to pass those tests
- [ ] 7.3 Write tests for `bedrock_generation_provider` with LangChain's `ChatBedrock` mocked at the boundary, covering a successful generation call and an error path
- [ ] 7.4 Implement `app/integrations/generation/bedrock_provider.py` (Nova Micro, model id from `Settings.BEDROCK_MODEL_ID`) to pass those tests
- [ ] 7.5 Wire `EMBEDDING_PROVIDER=bedrock` and `LLM_PROVIDER=bedrock` as defaults in their factories

## 8. Document Processing Provider (LlamaIndex)

- [ ] 8.1 Write tests for `llamaindex_provider.load_and_chunk` covering `.pdf`, `.docx`, `.pptx` inputs and rejection of unsupported extensions
- [ ] 8.2 Implement `app/integrations/document_processing/llamaindex_provider.py` to pass those tests
- [ ] 8.3 Wire `DOCUMENT_PROCESSOR=llamaindex` as the default in the factory

## 9. Document Ingestion (spec: `document-ingestion`)

- [ ] 9.1 Write tests for the ingestion flow (using fakes for storage/processing/embedding/vector-store providers) covering: successful ingest creates `documents` + `document_chunks`, unsupported file type fails cleanly, re-ingesting a `document_id` deletes prior chunks before inserting new ones, ingesting one document leaves other documents' chunks untouched
- [ ] 9.2 Implement `ingestion/ingest.py` orchestrating the four providers to pass those tests
- [ ] 9.3 Wire `make ingest` to run the script against the local stack

## 10. Retrieval & Generation Services

- [ ] 10.1 Write tests for `app/services/retrieval.py` covering: embeds the question, calls vector-store similarity search, returns chunks plus the best score
- [ ] 10.2 Implement `app/services/retrieval.py` to pass those tests
- [ ] 10.3 Write tests for `app/services/generation.py` covering: builds the system prompt with retrieved context, calls the generation provider, returns the answer text
- [ ] 10.4 Implement `app/services/generation.py` and `app/core/prompts.py` (system prompt template covering off-topic rejection, bilingual instruction, prompt-injection resilience) to pass those tests

## 11. Chat API Endpoint (spec: `rag-chat-api`)

- [ ] 11.1 Write tests for the similarity-threshold guard: above-threshold best score forwards context to generation, below-threshold best score short-circuits to a no-information response without calling the generation provider
- [ ] 11.2 Write tests for off-topic question handling declining without invoking the vector-store provider
- [ ] 11.3 Write tests for response language matching the question's language (ES and EN cases)
- [ ] 11.4 Write tests for prompt-injection resilience: embedded instructions in the question and in a retrieved chunk are not followed
- [ ] 11.5 Write tests for the `debug_context` field: present with scores when `INCLUDE_DEBUG_CONTEXT=true`, absent when `false`/unset
- [ ] 11.6 Write tests for the request/response contract: valid question returns 200 with `answer`; missing `question` returns 422 with no provider calls made
- [ ] 11.7 Implement `app/models/schemas.py` (Pydantic request/response models) and `app/api/routes/chat.py` orchestrating retrieval + threshold guard + generation to pass all of the above
- [ ] 11.8 Wire the chat route into `app/main.py`

## 12. Local Dev Environment (spec: `local-dev-environment`)

- [ ] 12.1 Write `docker/Dockerfile` for the API (dev-mode: uvicorn with reload)
- [ ] 12.2 Write `docker/docker-compose.yml` wiring the API, LocalStack (S3 only), and Postgres+pgvector containers together with the env vars from `Settings`
- [ ] 12.3 Complete `Makefile`: `make dev` brings up the full stack per docker-compose, `make down` tears it down, `make migrate` runs Alembic migrations against the local DB, `make test` runs the automated test suite
- [ ] 12.4 Manually verify `make dev` then `curl http://localhost:8000/health` returns a healthy response, and that storage operations succeed against LocalStack without reaching real AWS

## 13. Postman Collection

- [ ] 13.1 Create `postman/askdimitri.postman_collection.json` with `GET /health` and `POST /chat` requests
- [ ] 13.2 Add `/chat` test-case requests: in-scope question, off-topic question, ambiguous/low-similarity question, English question
- [ ] 13.3 Create `postman/askdimitri.postman_environment.json` with a `base_url` variable defaulting to `http://localhost:8000`

## 14. Lambda Packaging & Docs

- [ ] 14.1 Add a production-mode Lambda container image `docker/Dockerfile.lambda` (or a build stage) exposing the Mangum `handler`
- [ ] 14.2 Document manual AWS console setup steps (API Gateway, Lambda from container image, Aurora PostgreSQL+pgvector, Bedrock model access for Nova Micro + Titan V2) in `README.md`, to serve as the source of truth for the later Terraform phase
- [ ] 14.3 Document the full local dev workflow (`make dev`, `make ingest`, `make test`, Postman usage) in `README.md`
