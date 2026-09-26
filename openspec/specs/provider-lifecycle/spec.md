# provider-lifecycle Specification

## Purpose

How integration providers and their underlying connection resources are created, cached, and reused across requests and Lambda invocations — one engine per process, many sessions — including the connection-pool settings a serverless runtime requires and the guarantee that dependency overrides in tests still bypass the cache.

## Requirements

### Requirement: Vector store provider is created once per process
The system SHALL resolve the vector store provider at most once per process. Repeated resolutions of
the `get_vector_store` API dependency SHALL return the same provider instance, so that the
underlying SQLAlchemy engine — and therefore its connection pool — is created once and reused for
the lifetime of the process (a warm Lambda execution environment included).

#### Scenario: Two dependency resolutions return the same provider
- **WHEN** `get_vector_store()` is called twice within the same process
- **THEN** both calls return the identical provider object (`a is b`)

#### Scenario: Two consecutive chat requests share one engine
- **WHEN** a client sends two consecutive `POST /chat` requests handled by the same process
- **THEN** both requests are served by the same provider instance and the same SQLAlchemy engine
  object, and no additional engine is created for the second request

#### Scenario: A warm invocation creates no new connection pool
- **WHEN** a Lambda execution environment that has already served a `POST /chat` request receives
  another one
- **THEN** the existing connection pool is reused and no new TCP/TLS handshake to Postgres is
  performed to obtain an already-pooled connection

### Requirement: Provider factories accept explicit settings and remain uncached
The vector store factory SHALL continue to accept an optional `Settings` argument and SHALL NOT be
memoized, because `Settings` is a Pydantic model and is not hashable. Caching SHALL be applied only
at the API dependency layer, whose functions take no arguments.

#### Scenario: Factory called with explicit settings succeeds
- **WHEN** `get_vector_store_provider(settings=<explicit Settings instance>)` is called
- **THEN** it returns a provider without raising `TypeError`, and the provider reflects the supplied
  settings rather than the process-wide settings

#### Scenario: Factory is not memoized
- **WHEN** the vector store factory is called directly twice with no arguments
- **THEN** the call succeeds both times and the factory itself imposes no caching contract; provider
  reuse is guaranteed by the dependency layer, not by the factory

### Requirement: Database engine is configured for a serverless runtime
The system SHALL create the pgvector provider's SQLAlchemy engine with `pool_pre_ping` enabled, so
that a connection closed by the database while the execution environment was frozen is discarded
and replaced instead of being handed to the caller. The engine SHALL be configured with a pool sized
for a runtime that serves one request per process at a time.

#### Scenario: Engine enables pre-ping
- **WHEN** the pgvector provider is constructed
- **THEN** its engine is created with `pool_pre_ping=True`

#### Scenario: Pool is sized for single-request-per-container concurrency
- **WHEN** the pgvector provider is constructed
- **THEN** its engine is created with `pool_size=1` and `max_overflow=2`

#### Scenario: A stale connection after idle time does not fail the request
- **WHEN** the first `POST /chat` request arrives after an idle period long enough for the database
  to have closed the pooled connection
- **THEN** the dead connection is detected and replaced before use, and the request is served
  successfully rather than failing on a closed connection

### Requirement: Provider caching does not defeat dependency overrides in tests
Caching the provider dependency SHALL NOT prevent tests from substituting fakes. When a test
registers an override for the vector store dependency, the system SHALL use the override and SHALL
NOT return the cached real provider.

#### Scenario: Registered override wins over the cache
- **WHEN** a test registers an override for the vector store dependency and then issues a
  `POST /chat` request
- **THEN** the request is served by the injected fake provider, and no real database engine is
  created or used for that request

#### Scenario: Ingestion keeps building its own providers
- **WHEN** the standalone ingestion script runs
- **THEN** it constructs its providers once at entry point and passes them down explicitly,
  unaffected by the API dependency cache
