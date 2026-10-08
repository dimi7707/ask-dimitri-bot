"""The release half of a provider's lifecycle, kept apart from the capability protocols.

A cached provider outlives the request that built it, so something has to release the resource it
owns — a connection pool, an HTTPS keep-alive pool — at the moment the cache drops it rather than
whenever the garbage collector gets around to the abandoned object.

`Closeable` is deliberately *not* a method on `EmbeddingProvider` / `GenerationProvider` /
`VectorStoreProvider`. Those are `runtime_checkable`, so `isinstance` there is a method-presence
check: adding `close()` would make every explicitly protocol-asserted test double fail until it grew
a method that releases nothing. A separate protocol keeps the capability contracts about capability.

Declaring it is not optional for a provider reachable through a cached dependency, and the
requirement is a build-time gate rather than a convention — see
`tests/integrations/test_registry.py`. An `isinstance` check alone would quietly answer `False` for a
provider that owns a resource and forgot `close()`, which is the same silent leak that reaching for
a private `_engine` attribute used to cause.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Closeable(Protocol):
    """A provider that holds a resource worth releasing before the provider is discarded."""

    def close(self) -> None: ...
