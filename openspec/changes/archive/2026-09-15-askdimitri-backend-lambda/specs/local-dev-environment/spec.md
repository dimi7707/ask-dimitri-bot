## ADDED Requirements

### Requirement: One-command local environment
The system SHALL provide a `Makefile` with a `dev` target that brings up the full local development stack — the API container, a Postgres+pgvector container, and a LocalStack container providing S3 — with a single command.

#### Scenario: Starting the local stack
- **WHEN** a developer runs `make dev` from the repository root
- **THEN** the API becomes reachable at `http://localhost:8000`, a Postgres instance with the pgvector extension is running and reachable by the API container, and a LocalStack S3 endpoint is running and reachable by the API container

### Requirement: Local storage is LocalStack, not real S3
In the local development environment, the storage provider SHALL be configured to talk to LocalStack's S3 endpoint rather than real AWS S3, requiring no AWS credentials or network access to function.

#### Scenario: Document upload/download works fully offline against LocalStack
- **WHEN** the API or ingestion script performs a storage operation (upload, download, or list) while running under `make dev`
- **THEN** the operation is served by the LocalStack container and succeeds without any request reaching real AWS S3

### Requirement: Makefile convenience targets
The system SHALL provide Makefile targets for the other recurring local development operations: running the test suite, running database migrations, running the ingestion script, and tearing down the local stack.

#### Scenario: Running tests via Makefile
- **WHEN** a developer runs `make test`
- **THEN** the project's automated test suite executes without requiring any manual environment setup beyond `make dev` having been run previously

#### Scenario: Tearing down the local stack
- **WHEN** a developer runs `make down`
- **THEN** all containers started by `make dev` are stopped and removed
