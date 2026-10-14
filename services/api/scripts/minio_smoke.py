"""Exercise private document upload and presigned reads against the compose MinIO."""

from __future__ import annotations

import urllib.error
import urllib.request
import uuid

from treasurypilot_api.config import get_settings
from treasurypilot_api.invoices.documents import build_document_storage


def main() -> None:
    settings = get_settings()
    storage = build_document_storage(settings)
    if storage is None or settings.s3_bucket is None:
        raise RuntimeError("MinIO document storage must be configured for this smoke test")
    key = f"ci-smoke/{uuid.uuid4().hex}"
    body = b"private invoice document smoke"
    storage.put(key, body, "application/pdf")
    try:
        signed_body = urllib.request.urlopen(storage.sign_read(key), timeout=5).read()
        assert signed_body == body
        direct_url = f"http://minio:9000/{settings.s3_bucket}/{key}"
        try:
            urllib.request.urlopen(direct_url, timeout=5)
        except urllib.error.HTTPError as error:
            assert error.code in (400, 403)
        else:
            raise AssertionError("MinIO document was publicly readable without a signature")
    finally:
        storage.delete(key)


if __name__ == "__main__":
    main()
