"""Read-only access to private invoice documents for extraction (AGT-004)."""

from io import BytesIO
from urllib.parse import urlparse

from minio import Minio

from treasurypilot_worker.config import Settings

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # the API's upload limit; a larger object is not ours


class MinioDocumentReader:
    def __init__(self, client: Minio, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> "MinioDocumentReader":
        endpoint, bucket = settings.s3_endpoint_url, settings.s3_bucket
        access, secret = settings.s3_access_key, settings.s3_secret_key
        if not (endpoint and bucket and access and secret):
            raise RuntimeError(
                "S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY and S3_SECRET_KEY are required"
            )
        url = urlparse(endpoint)
        client = Minio(
            url.netloc,
            access_key=access.get_secret_value(),
            secret_key=secret.get_secret_value(),
            secure=url.scheme == "https",
        )
        return cls(client, bucket)

    def read(self, storage_key: str) -> bytes:
        response = self._client.get_object(self._bucket, storage_key, length=MAX_DOCUMENT_BYTES + 1)
        try:
            body = BytesIO(response.read()).getvalue()
        finally:
            response.close()
            response.release_conn()
        if len(body) > MAX_DOCUMENT_BYTES:
            raise ValueError("stored document exceeds the upload limit")
        return body
