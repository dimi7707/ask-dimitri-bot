import boto3


class S3StorageProvider:
    def __init__(self, bucket_name: str, region: str, endpoint_url: str | None = None):
        self._bucket_name = bucket_name
        client_kwargs = {"region_name": region, "endpoint_url": endpoint_url}
        if endpoint_url is not None:
            # LocalStack ignores credential *values* but boto3 still refuses to sign
            # requests without some — keeps local dev/test free of manual AWS setup.
            client_kwargs["aws_access_key_id"] = "test"
            client_kwargs["aws_secret_access_key"] = "test"
        self._client = boto3.client("s3", **client_kwargs)

    def upload(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket_name, Key=key, Body=data)

    def download(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket_name, Key=key)
        return response["Body"].read()

    def list(self, prefix: str = "") -> list[str]:
        response = self._client.list_objects_v2(Bucket=self._bucket_name, Prefix=prefix)
        return [obj["Key"] for obj in response.get("Contents", [])]

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket_name, Key=key)
