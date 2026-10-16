from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from fastapi import UploadFile
from PIL import Image
from pypdf import PdfWriter

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.invoices.documents import build_document_storage, read_document


def _png() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (1, 1), color="white").save(stream, format="PNG")
    return stream.getvalue()


def _pdf(page_count: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_upload_accepts_private_pdf_and_detects_pages() -> None:
    body, mime, pages = asyncio.run(
        read_document(UploadFile(file=BytesIO(_pdf(2)), filename="invoice.pdf"))
    )
    assert body.startswith(b"%PDF-")
    assert mime == "application/pdf"
    assert pages == 2


def test_upload_accepts_valid_png_from_content_signature() -> None:
    body, mime, pages = asyncio.run(
        read_document(UploadFile(file=BytesIO(_png()), filename="invoice.png"))
    )
    assert body.startswith(b"\x89PNG\r\n\x1a\n")
    assert mime == "image/png"
    assert pages == 1


def test_upload_rejects_executable_renamed_as_pdf() -> None:
    with pytest.raises(AuthFailure) as error:
        asyncio.run(
            read_document(UploadFile(file=BytesIO(b"MZ" + b"x" * 512), filename="invoice.pdf"))
        )
    assert error.value.status == 415
    assert error.value.code == "UNSUPPORTED_DOCUMENT_TYPE"


def test_upload_rejects_oversized_document_before_parsing() -> None:
    body = b"%PDF-" + b"x" * (10 * 1024 * 1024)
    with pytest.raises(AuthFailure) as error:
        asyncio.run(read_document(UploadFile(file=BytesIO(body), filename="invoice.pdf")))
    assert error.value.status == 413
    assert error.value.code == "DOCUMENT_TOO_LARGE"


def test_upload_rejects_more_than_twenty_pdf_pages() -> None:
    with pytest.raises(AuthFailure) as error:
        asyncio.run(read_document(UploadFile(file=BytesIO(_pdf(21)), filename="invoice.pdf")))
    assert error.value.status == 413
    assert error.value.code == "DOCUMENT_TOO_MANY_PAGES"


def test_partial_s3_config_disables_uploads_instead_of_failing_startup() -> None:
    settings = Settings(_env_file=None, s3_endpoint_url="http://minio:9000", s3_bucket="bucket")  # type: ignore[call-arg]
    assert build_document_storage(settings) is None


def test_presigned_urls_use_the_public_endpoint() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        s3_endpoint_url="http://minio:9000",
        s3_public_endpoint_url="http://localhost:9000",
        s3_bucket="bucket",
        s3_access_key="key",
        s3_secret_key="secret",
    )
    storage = build_document_storage(settings)
    assert storage is not None
    assert storage.sign_read("k").startswith("http://localhost:9000/bucket/k?")


def test_presigned_urls_sign_for_a_public_https_host() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        s3_endpoint_url="http://minio:9000",
        s3_public_endpoint_url="https://files.demo.example.com",
        s3_bucket="bucket",
        s3_access_key="key",
        s3_secret_key="secret",
    )
    storage = build_document_storage(settings)
    assert storage is not None
    assert storage.sign_read("k").startswith("https://files.demo.example.com/bucket/k?")
