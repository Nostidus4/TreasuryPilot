from pathlib import Path


def _service_block(compose: str, service: str, next_service: str) -> str:
    return compose.split(f"  {service}:\n", 1)[1].split(f"  {next_service}:\n", 1)[0]


def test_ai_worker_environment_is_an_explicit_non_signing_allowlist() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    compose = (repository_root / "infra" / "compose.yaml").read_text()
    ai_worker = _service_block(compose, "worker-ai", "beat")

    environment = ai_worker.split("    environment:\n", 1)[1].split("    depends_on:\n", 1)[0]
    configured_names = {
        line.strip().split(":", 1)[0]
        for line in environment.splitlines()
        if line.startswith("      ") and not line.lstrip().startswith("#")
    }

    assert configured_names == {
        "ANTHROPIC_API_KEY",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_REGION",
        "DATABASE_URL",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "TP_ENVIRONMENT",
        "TP_REDIS_URL",
    }
    assert "TP_ATTESTATION_PRIVATE_KEY" not in ai_worker
    assert "TP_SIGNER_SHARED_SECRET" not in ai_worker
    assert "${POSTGRES_USER}" not in ai_worker
    assert "${POSTGRES_PASSWORD}" not in ai_worker
