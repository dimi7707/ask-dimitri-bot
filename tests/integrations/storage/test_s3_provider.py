import os
import uuid

import pytest

TEST_S3_ENDPOINT_URL = os.environ.get("TEST_S3_ENDPOINT_URL", "http://localhost:45660")


def _localstack_reachable(endpoint_url: str) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"{endpoint_url}/_localstack/health", timeout=1):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _localstack_reachable(TEST_S3_ENDPOINT_URL),
    reason=f"LocalStack not reachable at {TEST_S3_ENDPOINT_URL!r}. Start it (see design.md) or run `make dev`.",
)


@pytest.fixture
def bucket_name():
    return f"askdimitri-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def provider(bucket_name):
    from app.integrations.storage.s3_provider import S3StorageProvider

    provider = S3StorageProvider(
        bucket_name=bucket_name,
        region="us-east-1",
        endpoint_url=TEST_S3_ENDPOINT_URL,
    )
    provider._client.create_bucket(Bucket=bucket_name)
    return provider


def test_upload_then_download_round_trips_bytes(provider):
    provider.upload("docs/cv.pdf", b"cv-bytes")

    assert provider.download("docs/cv.pdf") == b"cv-bytes"


def test_list_returns_keys_matching_prefix(provider):
    provider.upload("docs/cv.pdf", b"cv-bytes")
    provider.upload("docs/profile.pdf", b"profile-bytes")
    provider.upload("other/readme.txt", b"readme")

    assert sorted(provider.list(prefix="docs/")) == ["docs/cv.pdf", "docs/profile.pdf"]


def test_delete_removes_the_object(provider):
    provider.upload("docs/cv.pdf", b"cv-bytes")

    provider.delete("docs/cv.pdf")

    assert provider.list(prefix="docs/") == []
