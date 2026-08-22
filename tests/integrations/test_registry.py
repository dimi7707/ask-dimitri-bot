import pytest

from app.integrations._registry import resolve_provider


def test_resolve_provider_builds_the_registered_provider():
    provider = resolve_provider("storage", "fake", {"fake": lambda: "fake-instance"})

    assert provider == "fake-instance"


def test_resolve_provider_raises_on_unknown_provider_name():
    with pytest.raises(ValueError, match="Unknown storage provider 'does-not-exist'"):
        resolve_provider("storage", "does-not-exist", {"fake": lambda: "fake-instance"})
