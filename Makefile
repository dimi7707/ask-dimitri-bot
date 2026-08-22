.PHONY: dev down test migrate ingest

## Bring up the full local dev stack (API + Postgres/pgvector + LocalStack S3)
dev:
	docker compose -f docker/docker-compose.yml up --build

## Tear down the local dev stack
down:
	docker compose -f docker/docker-compose.yml down

## Run the automated test suite
test:
	uv run pytest

## Run Alembic migrations against the local database
migrate:
	uv run alembic upgrade head

## Run the standalone ingestion script against the local stack
ingest:
	uv run python -m ingestion.ingest
