## Why

Dimitri wants a hands-on way to learn and practice a serverless, AWS-based generative AI architecture (Lambda + FastAPI + RAG + Bedrock) so the pattern can be reused later in commercial projects. The vehicle for this is a small experimental API that answers questions about his own professional profile, using documents he provides (CV, technical profile, preferences). No frontend exists yet; the API is tested directly via Postman.

## What Changes

- Add a FastAPI application packaged for AWS Lambda via Mangum, exposing a `POST /chat` endpoint and a `GET /health` endpoint.
- Add a RAG pipeline: LlamaIndex for document ingestion/chunking/embeddings, LangChain for retrieval + generation orchestration, Amazon Bedrock (Nova Micro) for generation and Titan Embeddings V2 for embeddings.
- Add a vector store layer backed by Postgres + pgvector (local Docker) / Aurora PostgreSQL + pgvector (production), with `documents` and `document_chunks` tables managed via SQLModel + Alembic.
- Add a similarity-threshold guard (`SIMILARITY_THRESHOLD`, default `0.6`) so low-relevance retrieval results never reach the LLM as context, preventing hallucinated answers.
- Add off-topic rejection and bilingual (ES/EN) response behavior via system prompt design, plus baseline resilience to prompt injection from user input and ingested documents.
- Add a standalone ingestion script (`ingestion/ingest.py`) that reads source documents from S3 (LocalStack in dev), chunks and embeds them, and upserts into pgvector, deleting prior chunks by `document_id` before reinsertion to avoid duplicates on reindex.
- Add a **service abstraction layer**: all AWS SDK and AI-framework integrations (S3, Bedrock, LlamaIndex, LangChain) are accessed exclusively through generic factory interfaces defined in the codebase — no direct SDK/library references outside those factories — so a future provider swap only requires changing the factory's internal implementation.
- Add local development tooling: Docker Compose stack (LocalStack for S3, Postgres+pgvector container, API container) and a `Makefile` exposing simplified commands (e.g. `make dev` to bring up the full local environment).
- Add a versioned Postman collection + environment (`postman/`) covering the `/chat` and `/health` endpoints with representative test cases (in-scope, off-topic, ambiguous, English).
- Response schema includes an optional `debug_context` field (retrieved chunks + similarity scores), gated by `INCLUDE_DEBUG_CONTEXT`, for tuning the similarity threshold during development.

## Capabilities

### New Capabilities
- `rag-chat-api`: The `POST /chat` endpoint and its RAG behavior — retrieval over pgvector, similarity-threshold hallucination guard, off-topic rejection, bilingual responses, prompt-injection resilience, and the optional `debug_context` payload.
- `document-ingestion`: The standalone ingestion pipeline that turns source documents (CV, profile PDFs) stored in S3 into chunked, embedded rows in the vector store, with idempotent reindexing by `document_id`.
- `health-check`: The `GET /health` endpoint used to verify the Lambda/API Gateway wiring independently of the RAG pipeline.
- `local-dev-environment`: The Dockerized local stack (LocalStack S3, Postgres+pgvector, API container) and the `Makefile` targets that orchestrate it for day-to-day development.

### Modified Capabilities
(none — this is a new project with no pre-existing specs)

## Impact

- **New repo structure** (at the current directory root, no nested project folder): `app/` (FastAPI app, API routes, core config/prompts, services, models/schemas), `ingestion/` (ingest script), `infra/terraform/` (placeholder, implemented in a later phase), `docker/` (Dockerfile, docker-compose.yml), `postman/` (collection + environment), `pyproject.toml` (uv-managed), `Makefile`.
- **New dependencies**: FastAPI, Mangum, LangChain, LlamaIndex, boto3, SQLModel, Alembic, `pgvector` (Python + Postgres extension), Amazon Bedrock (`ChatBedrock`), uv as package manager.
- **External systems**: Amazon Bedrock (Nova Micro generation, Titan Embeddings V2), Aurora PostgreSQL/pgvector (prod) or Dockerized Postgres/pgvector (dev), S3 (prod) / LocalStack (dev), API Gateway + Lambda.
- **Out of scope for this change**: the Astro frontend, Terraform IaC (deferred to a later phase), WAF/per-IP rate limiting (documented as a future enhancement, not implemented now), and final content of the two profile PDFs.
