"""Shared isolation for the API tests: FastAPI's override registry and the provider cache are both
process-wide, so a test that forgets to clean up would otherwise decide what the next one sees.
"""

import pytest

from app.api import deps
from app.main import app


@pytest.fixture(autouse=True)
def isolate_provider_state():
    """Reset the dependency overrides and the cached vector store around every API test.

    Clearing on the way in as well as on the way out is deliberate: teardown-only cleanup still
    leaves a test at the mercy of whatever ran before it, which is exactly the ordering dependency
    these tests must not have.
    """
    app.dependency_overrides.clear()
    deps.reset_vector_store()
    yield
    app.dependency_overrides.clear()
    deps.reset_vector_store()
