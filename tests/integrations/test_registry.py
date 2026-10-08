import pytest

from app.integrations._registry import resolve_provider
from app.integrations.embeddings import factory as embeddings_factory
from app.integrations.generation import factory as generation_factory
from app.integrations.lifecycle import Closeable
from app.integrations.vector_store import factory as vector_store_factory


def test_resolve_provider_builds_the_registered_provider():
    provider = resolve_provider("storage", "fake", {"fake": lambda: "fake-instance"})

    assert provider == "fake-instance"


def test_resolve_provider_raises_on_unknown_provider_name():
    with pytest.raises(ValueError, match="Unknown storage provider 'does-not-exist'"):
        resolve_provider("storage", "does-not-exist", {"fake": lambda: "fake-instance"})


# --- adb-002 3.x the release contract is a requirement, not a hope -------------------------

# The registries behind the three *cached* API dependencies. Storage and document processing are
# absent on purpose: neither is an API dependency — both are reached only from `ingestion/`, which
# builds its providers once at its entry point — so neither is ever held in a cache that has to
# release it. The seam this leaves is that caching a fourth dependency means extending this dict as
# well; `tests/api/test_deps.py` catches the half of that which is visible from `deps`.
CACHED_PROVIDER_REGISTRIES = {
    "embedding": embeddings_factory.PROVIDERS,
    "generation": generation_factory.PROVIDERS,
    "vector store": vector_store_factory.PROVIDERS,
}


def every_registered_provider():
    return [
        pytest.param(capability, provider_name, build, id=f"{capability}-{provider_name}")
        for capability, registry in CACHED_PROVIDER_REGISTRIES.items()
        for provider_name, build in registry.items()
    ]


@pytest.mark.parametrize(("capability", "provider_name", "build"), every_registered_provider())
def test_every_cached_provider_declares_its_release_contract(capability, provider_name, build):
    """Every provider behind a cached dependency must declare `close()`, or the build fails.

    An `isinstance(provider, Closeable)` *check* in the release path is not a presence
    *requirement*: a provider that owns a resource and simply omits `close()` answers `False`, is
    dropped from the cache unreleased, and — with no telemetry here — says nothing. That is the same
    silent leak adb-001 described, with a quiet `False` in place of a `getattr` sniff. This
    assertion is the requirement, and the `PROVIDERS` dicts being enumerable is what makes it a gate.

    It proves *declaration*, not *diligence*: a `close()` that releases nothing still passes, and
    that is the limit of what a structural check can promise.

    The gate is unconditional by design. A future stateless provider declares `close()` as a no-op
    rather than being excluded, because a gate that decided for itself which providers own something
    releasable would have to inspect each provider's internals — and would be narrowed into
    uselessness the first time it over-fired.
    """
    provider = build()

    assert isinstance(provider, Closeable), (
        f"the {provider_name!r} {capability} provider is reachable through a cached dependency but "
        "declares no close(); releasing the cache would skip it silently and abandon its resource"
    )

    # Built a real provider to check it, so release it here rather than abandoning its client.
    provider.close()
