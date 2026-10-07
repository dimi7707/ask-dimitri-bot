# AskDimitri Backend

A small serverless RAG API that answers questions about Dimitri Avila's professional profile.
FastAPI runs on AWS Lambda through Mangum, retrieval is served by Postgres + pgvector, and
Amazon Bedrock provides both generation (Nova Micro) and embeddings (Titan Embeddings V2).

The project exists to practice a reusable serverless GenAI architecture, so its central rule is
strict: **no route, service or script ever imports `boto3`, `langchain` or `llama_index`
directly.** Every external dependency sits behind a protocol + factory under
`app/integrations/`, and a test (`tests/architecture/`) fails the build if that boundary is
crossed.

---

## Table of contents

- [Architecture](#architecture)
- [Local development](#local-development)
  - [Prerequisites](#prerequisites)
  - [1. Configure the environment](#1-configure-the-environment)
  - [2. Start the stack](#2-start-the-stack)
  - [3. Ingest documents](#3-ingest-documents)
  - [4. Ask a question](#4-ask-a-question)
  - [Makefile targets](#makefile-targets)
- [Running the tests](#running-the-tests)
- [Postman](#postman)
- [Configuration reference](#configuration-reference)
- [Deploying to AWS (manual console setup)](#deploying-to-aws-manual-console-setup)

---

## Architecture

```
POST /chat
   │
   ├─ 1. scope guard      classify_scope()  ── Bedrock ──▶ IN_SCOPE / OUT_OF_SCOPE
   │                      off-topic → decline, without querying the vector store
   │
   ├─ 2. retrieval        retrieve()  ── Bedrock (Titan) ──▶ question embedding
   │                                  ── pgvector ─────────▶ top_k closest chunks
   │
   ├─ 3. threshold guard  best_score < SIMILARITY_THRESHOLD
   │                      → "I don't have that information", without calling the LLM
   │
   └─ 4. generation       generate_answer()  ── Bedrock (Nova Micro) ──▶ grounded answer
```

Two guards stand between a question and a generated answer. The scope guard keeps off-topic
questions away from the vector store; the similarity threshold keeps weakly-related chunks away
from the model, so it is never handed context it could paper over with invented detail.

| Layer | Directory | Notes |
| --- | --- | --- |
| Routes | `app/api/routes/` | `health.py`, `chat.py`; providers arrive via `app/api/deps.py` |
| Services | `app/services/` | `retrieval.py`, `generation.py` — business logic, provider-agnostic |
| Prompts | `app/core/prompts.py` | System prompt, scope classifier, canned ES/EN answers |
| Integrations | `app/integrations/<domain>/` | `base.py` (protocol), `factory.py` (resolver), `*_provider.py` (the only files allowed to import an SDK) |
| Models | `app/models/` | SQLModel tables (`documents`, `document_chunks`) and Pydantic schemas |
| Ingestion | `ingestion/ingest.py` | Standalone script, not an API endpoint |

Swapping a provider means adding one `*_provider.py`, registering it in that domain's
`factory.py`, and pointing the matching env var at it — no service or route changes.

---

## Local development

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (Desktop or Engine) with Compose v2
- [uv](https://docs.astral.sh/uv/) for running tests, migrations and the ingestion script on the host
- AWS credentials with Bedrock access **only for `/chat` and ingestion** — see the note below

> **Bedrock has no local emulation.** S3 is served by LocalStack and Postgres runs in a container,
> so `/health`, storage and vector-store work fully offline. Generation and embeddings call real
> AWS, so `/chat` and `make ingest` need credentials with model access to `amazon.nova-micro-v1:0`
> and `amazon.titan-embed-text-v2:0`. Without them those two paths fail with
> `NoCredentialsError`; everything else still works.

### 1. Configure the environment

```bash
cp .env.example .env
```

`.env` drives host-run commands (`make migrate`, `make ingest`, the tests) and points at the
compose stack's **host** ports (`55432` for Postgres, `45660` for LocalStack — deliberately
non-standard so the stack never collides with a locally installed Postgres or LocalStack).

Export your AWS credentials before starting the stack so compose can pass them to the API
container:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...   # only if using temporary credentials
```

> The repo is bind-mounted into the API container, so `.env` is visible inside it too. Real
> environment variables take precedence over `.env`, so the compose settings always win — but
> anything you put in `.env` that compose does *not* set will also apply inside the container.

### 2. Start the stack

```bash
make up       # detached: API + Postgres/pgvector + LocalStack, then applies migrations
# or
make dev      # same stack in the foreground, following logs (run `make migrate` separately)
```

Then check it is alive:

```bash
curl http://localhost:8000/health
# {"status":"healthy"}
```

Interactive API docs are at <http://localhost:8000/docs>.

`make up` creates the `askdimitri-documents` bucket in LocalStack automatically
(`docker/localstack/init-s3.sh`) and applies the Alembic migrations, which install the `vector`
extension and create the `documents` / `document_chunks` tables.

### 3. Ingest documents

Upload the source documents (`.pdf`, `.docx`, `.pptx`) into the LocalStack bucket, then ingest:

```bash
# Upload (AWS CLI pointed at LocalStack)
aws --endpoint-url http://localhost:45660 s3 cp ./cv.pdf s3://askdimitri-documents/documents/cv.pdf

# Ingest everything in the bucket...
make ingest

# ...or specific keys
make ingest ARGS="documents/cv.pdf documents/profile.pdf"
```

Ingestion downloads each object, chunks it with LlamaIndex, embeds each chunk with Titan V2, and
upserts into pgvector. The `document_id` is derived deterministically from the storage key, and
prior chunks are deleted before the new ones are inserted — so re-ingesting the same key is a
reindex, never a duplicate. Unsupported extensions are skipped with a warning and persist nothing.

### 4. Ask a question

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"question": "¿Qué stack tecnológico maneja Dimitri?"}'
```

With `INCLUDE_DEBUG_CONTEXT=true` the response also carries the retrieved chunks and their
similarity scores, which is how you tune `SIMILARITY_THRESHOLD`:

```json
{
  "answer": "Dimitri trabaja principalmente con Python, FastAPI y AWS.",
  "debug_context": {
    "similarity_threshold": 0.6,
    "chunks_retrieved": [
      {"chunk_text": "...", "score": 0.82, "document_id": "..."}
    ]
  }
}
```

### Makefile targets

| Target | What it does |
| --- | --- |
| `make dev` | Builds and starts the full stack in the foreground, following logs |
| `make up` | Same, detached, then runs `make migrate` |
| `make down` | Stops and removes the containers (the Postgres volume is kept) |
| `make logs` | Follows the logs of the running stack |
| `make migrate` | Runs Alembic migrations against the local database |
| `make ingest` | Runs the ingestion script (`ARGS="key1 key2"` for specific objects) |
| `make test` | Runs the automated test suite |
| `make shell` | Opens a shell inside the running API container |

---

## Running the tests

```bash
make test
```

Unit tests use fake providers and need no Docker, network or AWS credentials. The provider tests
for S3 and pgvector run against the real containers and **skip themselves** when the stack is
down, so `make test` is always green on a clean checkout. Start the stack (`make up`) to run the
full suite — the provider tests default to the same host ports compose publishes.

Bedrock is never called from an automated test: the embedding and generation providers are tested
with the client mocked at the boundary, so the suite stays free and deterministic. Real Bedrock is
exercised manually through the Postman collection.

> **The first run is slow.** The LlamaIndex tests download tokenizer data (tiktoken/NLTK) on first
> use — expect a couple of minutes once, then ~3 seconds on every later run.

---

## Postman

Import both files from `postman/`:

- `askdimitri.postman_collection.json` — `GET /health` plus `/chat` cases: in-scope (ES), in-scope
  (EN), off-topic, ambiguous/below-threshold, a prompt-injection attempt, and an invalid body
- `askdimitri.postman_environment.json` — sets `base_url` to `http://localhost:8000`

Select the **AskDimitri Local** environment and run the collection against the local stack.

---

## Configuration reference

All settings live in `app/core/config.py` (`pydantic-settings`) and can be overridden by
environment variable. See `.env.example` for a ready-to-copy local set.

| Variable | Default | Purpose |
| --- | --- | --- |
| `BEDROCK_MODEL_ID` | `amazon.nova-micro-v1:0` | Generation model |
| `EMBEDDING_MODEL_ID` | `amazon.titan-embed-text-v2:0` | Embedding model (1024 dimensions) |
| `SIMILARITY_THRESHOLD` | `0.6` | Below this best score, the assistant declines instead of generating |
| `SIMILARITY_TOP_K` | `5` | Chunks requested from the vector store |
| `INCLUDE_DEBUG_CONTEXT` | `false` | Adds `debug_context` (chunks + scores) to `/chat` responses |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `512` / `50` | Chunking, in tokens, at ingestion time |
| `STORAGE_PROVIDER` | `s3` | Selects the storage implementation |
| `EMBEDDING_PROVIDER` | `bedrock` | Selects the embedding implementation |
| `LLM_PROVIDER` | `bedrock` | Selects the generation implementation |
| `VECTOR_STORE_PROVIDER` | `pgvector` | Selects the vector-store implementation |
| `DOCUMENT_PROCESSOR` | `llamaindex` | Selects the document-processing implementation |
| `DATABASE_URL` | local Postgres DSN | Vector store connection |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `1` / `2` | Connection-pool sizing. The defaults suit Lambda, which serves one request per container; raise them for a runtime that handles concurrency in-process (uvicorn, provisioned concurrency) |
| `AWS_REGION` | `us-east-1` | Region for Bedrock and S3 |
| `S3_BUCKET_NAME` | `askdimitri-documents` | Source-document bucket |
| `S3_ENDPOINT_URL` | unset | Set to the LocalStack endpoint locally; leave unset for real AWS |

---

## Deploying to AWS (manual console setup)

Infrastructure is provisioned **by hand in the AWS console** for now. Terraform is a later phase,
and this section is its source of truth — keep it accurate as the setup changes.

### 1. Bedrock model access

In the target region (`us-east-1` by default), open **Bedrock → Model access** and request access
to:

- `amazon.nova-micro-v1:0` (generation)
- `amazon.titan-embed-text-v2:0` (embeddings)

Access is per-region, so this must be repeated in every region the Lambda runs in.

### 2. Aurora PostgreSQL + pgvector

1. **RDS → Create database → Amazon Aurora → PostgreSQL-Compatible**, engine version 15.3 or
   later (pgvector requires 15.3+).
2. Serverless v2 is the cheapest fit for this workload; set the minimum ACU low.
3. Put the cluster in private subnets, and create a security group allowing inbound `5432` **only**
   from the Lambda's security group.
4. Connect once and enable the extension:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
5. Apply the schema by running the migrations against the cluster:
   ```bash
   DATABASE_URL="postgresql+psycopg://<user>:<pass>@<cluster-endpoint>:5432/askdimitri" \
     uv run alembic upgrade head
   ```
   Run this from somewhere with network access to the cluster (a bastion, or temporarily from a
   public subnet).
6. Store the credentials in **Secrets Manager** rather than in plaintext Lambda env vars.

### 3. S3 bucket

Create a private bucket (e.g. `askdimitri-documents`) with public access **blocked** and default
encryption on. Upload the profile documents under a `documents/` prefix. This is the same layout
`make ingest` expects locally.

### 4. ECR repository and image

```bash
aws ecr create-repository --repository-name askdimitri-backend

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

docker build --platform linux/amd64 -f docker/Dockerfile.lambda -t askdimitri-backend:latest .
docker tag askdimitri-backend:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/askdimitri-backend:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/askdimitri-backend:latest
```

`--platform linux/amd64` matters when building on an Apple Silicon Mac — Lambda rejects an arm64
image on an x86_64 function.

You can smoke-test the image locally before pushing, using the Lambda Runtime Interface Emulator
baked into the base image:

```bash
docker run --rm -p 9000:8080 askdimitri-backend:latest
curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" -d '{
  "version": "2.0", "rawPath": "/health", "rawQueryString": "",
  "headers": {"host": "localhost"},
  "requestContext": {"http": {"method": "GET", "path": "/health", "protocol": "HTTP/1.1", "sourceIp": "127.0.0.1"}},
  "isBase64Encoded": false
}'
# {"statusCode": 200, "body": "{\"status\":\"healthy\"}", ...}
```

### 5. Lambda function

1. **Lambda → Create function → Container image**, selecting the image pushed above.
2. Handler is baked into the image (`app.main.handler`); no override needed.
3. **Memory** 1024 MB or more and **timeout** 30 s — the RAG path makes two Bedrock calls plus a
   database query, and the dependencies are heavy on cold start.
4. **VPC**: attach the Lambda to the same VPC/private subnets as Aurora, with a security group the
   database accepts. Reaching Bedrock and S3 from private subnets needs either a NAT gateway or
   VPC endpoints (`com.amazonaws.<region>.bedrock-runtime` and an S3 gateway endpoint) — VPC
   endpoints are cheaper and keep the traffic off the public internet.
5. **Environment variables**: `DATABASE_URL`, `S3_BUCKET_NAME`, `AWS_REGION`, `BEDROCK_MODEL_ID`,
   `EMBEDDING_MODEL_ID`, `SIMILARITY_THRESHOLD`, `SIMILARITY_TOP_K`. Leave `S3_ENDPOINT_URL`
   **unset** so boto3 talks to real S3, and leave `INCLUDE_DEBUG_CONTEXT` unset (or `false`) in
   production — it exposes raw document chunks in the response.
6. **Execution role** — attach a policy granting:
   - `bedrock:InvokeModel` on the two model ARNs
   - `s3:GetObject` / `s3:ListBucket` on the documents bucket
   - `secretsmanager:GetSecretValue` on the database secret
   - `AWSLambdaVPCAccessExecutionRole` (managed) for the VPC attachment

### 6. API Gateway

1. **API Gateway → Create API → HTTP API** (cheaper and simpler than REST for this).
2. Add a Lambda proxy integration pointing at the function, with routes `ANY /{proxy+}` plus
   `GET /health` — Mangum handles the routing inside FastAPI.
3. Deploy to a stage and note the invoke URL. Point Postman's `base_url` at it to run the same
   collection against AWS.
4. Before exposing it publicly, add throttling on the stage. WAF and per-IP rate limiting are
   noted as future work and are not configured here.

### 7. Ingestion in production

Ingestion is a standalone script, not an endpoint. Run it from a machine with access to the
bucket and the database:

```bash
DATABASE_URL="postgresql+psycopg://..." S3_BUCKET_NAME=askdimitri-documents \
  uv run python -m ingestion.ingest --prefix documents/
```
