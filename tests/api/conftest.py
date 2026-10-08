"""Shared isolation for the API tests: FastAPI's override registry and the provider caches are all
process-wide, so a test that forgets to clean up would otherwise decide what the next one sees.
"""

import pytest

from app.api import deps
from app.main import app


@pytest.fixture(autouse=True)
def isolate_provider_state():
    """Reset the dependency overrides and every cached provider around every API test.

    `reset_providers()` rather than `reset_vector_store()`: with three cached dependencies, a
    fixture that released one of them would leave the other two deciding what the next test sees —
    and the build-counter assertions would then pass or fail on suite ordering.

    Clearing on the way in as well as on the way out is deliberate: teardown-only cleanup still
    leaves a test at the mercy of whatever ran before it, which is exactly the ordering dependency
    these tests must not have.
    """
    app.dependency_overrides.clear()
    deps.reset_providers()
    yield
    app.dependency_overrides.clear()
    deps.reset_providers()
