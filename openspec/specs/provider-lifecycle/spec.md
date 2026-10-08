# provider-lifecycle Specification

## Purpose

How integration providers and their underlying connection resources are created, cached, released, and reused across requests and Lambda invocations — one provider per process, many calls — including the connection-pool settings a serverless runtime requires, the ceiling on a single outbound call, the release contract every cached provider declares, and the guarantee that dependency overrides in tests still bypass the cache.

Every provider reached through an API dependency is in scope: the vector store, the embedding provider, and the generation provider. The storage and document-processing providers are not — they are reached only from the standalone ingestion entry point, which builds its own providers and is covered below.

## Requirements

### Requirement: Vector store provider is created once per process
The system SHALL resolve the vector store provider at most once per process, absent a registered
override and a release of the cache. Repeated resolutions of the `get_vector_store` API dependency
SHALL return the same provider instance, so that the underlying SQLAlchemy engine — and therefore
its connection pool — is created once and reused for the lifetime of the process (a warm Lambda
execution environment included).

#### Scenario: Two dependency resolutions return the same provider
- **WHEN** `get_vector_store()` is called twice within the same process
- **THEN** both calls return the identical provider object (`a is b`)

#### Scenario: Two consecutive chat requests share one engine
- **WHEN** a client sends two consecutive `POST /chat` requests handled by the same process
- **THEN** the engine observed from inside the vector store call is the identical object on both
  requests, and no additional engine is created for the second request

#### Scenario: A warm invocation creates no new connection pool
- **WHEN** a Lambda execution environment that has already served a `POST /chat` request receives
  another one
- **THEN** the existing connection pool is reused and no new TCP/TLS handshake to Postgres is
  performed to obtain an already-pooled connection

### Requirement: Embedding and generation providers are created once per process
The system SHALL resolve the embedding provider and the generation provider at most once per
process, absent a registered override and a release of the cache. Repeated resolutions of the
`get_embedder` and `get_generator` API dependencies SHALL return the same provider instance, so that
each provider's boto3 client — and therefore its HTTPS connection pool to the Bedrock endpoint — is
created once and reused for the lifetime of the process.

A shared cached provider is reached concurrently on a threadpool runtime, where two first
resolutions can race and each construct a provider. That allowance is bounded and accepted: at most
one extra construction per cache, only on the first concurrent resolution, with the loser's object
simply discarded. Steady state is one provider per process either way, which is why the scenarios
below are stated over sequential resolution.

#### Scenario: Two dependency resolutions return the same provider
- **WHEN** `get_embedder()` or `get_generator()` is called twice sequentially within the same
  process
- **THEN** both calls return the identical provider object (`a is b`), and the factory behind it
  runs exactly once

#### Scenario: Two consecutive chat requests share one embedding client
- **WHEN** a client sends two consecutive `POST /chat` requests handled by the same process
- **THEN** the embedding provider observed from inside the embedding call is the identical object on
  both requests, and the embedding provider has constructed exactly one boto3 client across both, so
  the HTTPS connection established by the first question remains available to the second

#### Scenario: Two consecutive chat requests share one chat model
- **WHEN** a client sends two consecutive `POST /chat` requests handled by the same process, and the
  chat model was constructed successfully on the first
- **THEN** the chat model observed from inside the generation call is the identical object on both
  requests, and no additional chat model is created for the second request

#### Scenario: A failed chat model construction is not memoized
- **WHEN** constructing the chat model raises, for example because credentials cannot be resolved
- **THEN** nothing is cached for it, and the next request attempts the construction again rather
  than being served a pinned failure for the life of the execution environment

### Requirement: Dropping a cached provider releases its resource
Discarding a cached provider SHALL release the resource it owns first — an engine's pooled
connections, a boto3 client's HTTPS connection pool — so those are released at that moment rather
than whenever the garbage collector finalizes the abandoned object.

Release SHALL go through an explicit contract that the provider declares, never by reading a
provider's private attributes: a release path that reaches for a known attribute name silently skips
any future provider that holds its resource under a different one.

#### Scenario: Reset releases each provider before dropping it
- **WHEN** the cached providers are reset
- **THEN** each one's release operation is invoked, and the next resolution builds a new provider

#### Scenario: Reset with an empty cache is a no-op
- **WHEN** the caches are reset while holding no provider
- **THEN** the reset succeeds without constructing a provider and without raising — on a cold
  execution environment, constructing one just to release it would resolve credentials and open a
  pool for nothing

#### Scenario: A failed release still drops every provider
- **WHEN** releasing one provider raises
- **THEN** every cache is cleared regardless, so no stale provider is handed to the next caller, and
  the failure is reported to the caller rather than the reset completing silently

### Requirement: Every provider behind a cached dependency declares its release contract
Every provider reachable through a cached API dependency SHALL declare a release operation,
regardless of whether it currently owns a releasable resource, and one that does not SHALL fail the
build rather than being skipped silently at release time.

The requirement is unconditional by design. A check for the operation's presence is not a
requirement that it exist: a provider that owns a resource and omits it is simply skipped, which is
the same silent leak as reading a private attribute. A stateless provider declares the operation as
a no-op — the ceremony is the point, because it is what makes an omission visible. This proves
declaration, not diligence: a release operation that releases nothing still satisfies it, and that
is the limit of what a structural check can promise.

#### Scenario: A registered provider without a release operation fails the build
- **WHEN** a provider registered for a cached capability declares no release operation
- **THEN** the test suite fails, naming the provider, rather than the omission surfacing as an
  abandoned resource at runtime

### Requirement: Provider factories accept explicit settings and remain uncached
Every provider factory SHALL continue to accept an optional `Settings` argument and SHALL NOT be
memoized, because `Settings` is a Pydantic model and is not hashable. Caching SHALL be applied only
at the API dependency layer, whose functions take no arguments.

An explicit `Settings` passed to a factory selects **which provider is built** — it supplies the
registry key — and not how that provider is configured. The registry callables take no arguments and
read the process-wide settings themselves.

#### Scenario: Factory called with explicit settings succeeds
- **WHEN** a provider factory is called with an explicit `Settings` instance
- **THEN** it returns a provider without raising `TypeError`, and the provider selected is the one
  the supplied settings name

#### Scenario: Configuration comes from the process-wide settings, not the supplied instance
- **WHEN** a provider factory is called with an explicit `Settings` instance whose configuration
  values differ from the process-wide ones
- **THEN** the provider that is built is the one the supplied settings select, but its configuration
  — pool sizing, call ceiling — comes from the process-wide settings, because the registry callable
  reads those itself

#### Scenario: Factory is not memoized
- **WHEN** a provider factory is called directly twice with no arguments
- **THEN** the call succeeds both times and the factory itself imposes no caching contract; provider
  reuse is guaranteed by the dependency layer, not by the factory

### Requirement: Database engine is configured for a serverless runtime
The system SHALL create the pgvector provider's SQLAlchemy engine with `pool_pre_ping` enabled, so
that a connection closed by the database while the execution environment was frozen is discarded
and replaced instead of being handed to the caller. The pool size SHALL default to a runtime that
serves one request per process at a time, and SHALL be configurable, so that a runtime handling
concurrency in-process can size the pool up instead of queueing requests behind a single connection.

#### Scenario: Engine enables pre-ping
- **WHEN** the pgvector provider is constructed
- **THEN** its engine is created with `pool_pre_ping=True`

#### Scenario: Pool defaults to single-request-per-container concurrency
- **WHEN** the pgvector provider is constructed without explicit pool arguments
- **THEN** its engine is created with `pool_size=1` and `max_overflow=2`

#### Scenario: Pool sizing is configurable per runtime
- **WHEN** `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` are set in the environment
- **THEN** the provider built by the factory creates its engine with those values instead of the
  defaults, without any code change

#### Scenario: Pool sizing rejects values SQLAlchemy reads as unbounded
- **WHEN** `DB_POOL_SIZE` is 0 or `DB_MAX_OVERFLOW` is negative
- **THEN** settings validation fails, rather than silently configuring an unbounded pool

#### Scenario: A stale connection after idle time does not fail the request
- **WHEN** the first `POST /chat` request arrives after an idle period long enough for the database
  to have closed the pooled connection
- **THEN** the dead connection is detected and replaced before use, and the request is served
  successfully rather than failing on a closed connection

### Requirement: Outbound Bedrock calls are bounded
Every Bedrock client the embedding and generation providers construct SHALL carry a connect timeout,
a read timeout, and a total attempt count under botocore's `standard` retry mode, so that one
unresponsive call cannot consume the whole enclosing runtime timeout. This applies to the embedding
provider's client and to **both** clients the chat model creates, including the control-plane one.

The values SHALL be configurable per runtime without a code change, and configuration SHALL reject
values that remove the ceiling — a non-positive timeout or an attempt count below one — rather than
silently accepting an unbounded client. The attempt count SHALL bound **total** calls, including the
initial request, not retries after it.

Two consequences are stated rather than discovered. First, a ceiling that fits inside the runtime
timeout necessarily retries less than botocore's default, so a throttled call surfaces sooner than
it did. Second, the ceiling is per call and does not bound the aggregate of the several calls one
request makes; the runtime timeout remains the backstop for that.

This is behavioral over the two named providers rather than an invariant, because there are two
construction sites and no single chokepoint: a shared configuration module is structurally
forbidden by the rule that only provider files may import a raw SDK. The recorded limitation is that
a future third Bedrock client could be introduced unbounded with the suite green.

#### Scenario: A client is built with a bounded ceiling
- **WHEN** either provider constructs a Bedrock client
- **THEN** that client is configured with the connect timeout, read timeout and total attempt count
  the settings specify, under `standard` retry mode

#### Scenario: The ceiling is configurable from the environment
- **WHEN** the Bedrock timeout or attempt-count variables are set in the environment
- **THEN** the client built by the factory uses those values instead of the defaults, without any
  code change

#### Scenario: A ceiling-removing value is rejected
- **WHEN** a Bedrock timeout is set to zero or a negative number, or the attempt count is set below
  one
- **THEN** settings validation fails before any provider is built, rather than silently configuring
  an unbounded client

### Requirement: Provider caching does not defeat dependency overrides in tests
Caching a provider dependency SHALL NOT prevent tests from substituting fakes. When a test registers
an override for a provider dependency, the system SHALL use the override and SHALL NOT return the
cached real provider, and no real client SHALL be constructed for that dependency. Dependencies left
un-overridden stay on the real resolution path by design, which is what keeps a cache under test
live.

#### Scenario: Registered override wins over the cache
- **WHEN** a test registers an override for a provider dependency and then issues a `POST /chat`
  request
- **THEN** the request is served by the injected fake provider, and no real database engine or
  Bedrock client is created or used for that dependency

#### Scenario: No test observes a provider cached by a previously-run test
- **WHEN** an API test runs
- **THEN** every provider cache is empty on entry, so no test's outcome depends on suite ordering

#### Scenario: Ingestion keeps building its own providers
- **WHEN** the standalone ingestion script runs
- **THEN** it constructs its providers once at entry point and passes them down explicitly,
  unaffected by the API dependency cache
