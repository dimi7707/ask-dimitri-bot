.PHONY: dev up down logs test migrate ingest shell

COMPOSE := docker compose -f docker/docker-compose.yml

## Bring up the full local dev stack (API + Postgres/pgvector + LocalStack S3), following logs
dev:
	$(COMPOSE) up --build

## Same as `dev` but detached, then apply migrations so the stack is ready to use
up:
	$(COMPOSE) up --build -d
	$(MAKE) migrate
	@echo "API ready at http://localhost:8000 (health: http://localhost:8000/health)"

## Tear down the local dev stack (containers + network; the Postgres volume is kept)
down:
	$(COMPOSE) down

## Follow the logs of the running stack
logs:
	$(COMPOSE) logs -f

## Run the automated test suite. Provider tests against Postgres/LocalStack are skipped
## unless the stack is up (`make up`); every other test runs with no setup at all.
test:
	uv run pytest

## Run Alembic migrations against the local database (reads DATABASE_URL from .env)
migrate:
	uv run alembic upgrade head

## Run the standalone ingestion script against the local stack (reads .env).
## Ingests every supported document in the bucket, or specific keys:
##   make ingest ARGS="documents/cv.pdf documents/profile.pdf"
ingest:
	uv run python -m ingestion.ingest $(ARGS)

## Open a shell inside the running API container
shell:
	$(COMPOSE) exec api bash
