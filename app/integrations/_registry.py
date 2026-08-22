from typing import Callable, TypeVar

T = TypeVar("T")


def resolve_provider(domain: str, provider_name: str, providers: dict[str, Callable[[], T]]) -> T:
    """Look up and build the provider registered under `provider_name` for `domain`.

    Shared by every app/integrations/<domain>/factory.py so each factory stays a
    thin, domain-specific registry instead of duplicating dispatch/error logic.
    """
    try:
        build = providers[provider_name]
    except KeyError as exc:
        available = ", ".join(sorted(providers)) or "none registered"
        raise ValueError(
            f"Unknown {domain} provider {provider_name!r}. Available: {available}"
        ) from exc
    return build()
