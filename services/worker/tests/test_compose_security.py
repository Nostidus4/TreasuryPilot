from pathlib import Path


def _service_block(compose: str, service: str, next_service: str) -> str:
    return compose.split(f"  {service}:\n", 1)[1].split(f"  {next_service}:\n", 1)[0]


def test_ai_worker_environment_is_an_explicit_non_signing_allowlist() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    compose = (repository_root / "infra" / "compose.yaml").read_text()
    ai_worker = _service_block(compose, "worker-ai", "worker-webhooks")

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
        "PROMETHEUS_MULTIPROC_DIR",
        "SENTRY_DSN",
        "TP_ENVIRONMENT",
        "TP_METRICS_PORT",
        "TP_REDIS_URL",
    }
    assert "POLICY_KEYSTORE" not in ai_worker
    assert "secrets:" not in ai_worker
    assert "TP_SIGNER_SHARED_SECRET" not in ai_worker
    assert "${POSTGRES_USER}" not in ai_worker
    assert "${POSTGRES_PASSWORD}" not in ai_worker


def test_only_the_core_worker_mounts_the_policy_keystore() -> None:
    compose = (Path(__file__).resolve().parents[3] / "infra" / "compose.yaml").read_text()
    core_worker = _service_block(compose, "worker", "worker-ai")

    assert "TP_ATTESTATION_PRIVATE_KEY" not in compose
    assert "secrets: [policy_keystore, policy_keystore_password]" in core_worker
    assert "FIELD_ENCRYPTION_KEY" not in core_worker
    assert "public" not in core_worker
    assert "TP_POLICY_KEYSTORE_PATH: /run/secrets/policy_keystore" in core_worker
    assert compose.count("policy_keystore_password]") == 1
    assert "FIELD_ENCRYPTION_KEY" not in _service_block(compose, "worker-ai", "worker-webhooks")


def test_webhook_worker_has_egress_and_field_key_but_no_core_secrets() -> None:
    compose = (Path(__file__).resolve().parents[3] / "infra" / "compose.yaml").read_text()
    webhook_worker = _service_block(compose, "worker-webhooks", "beat")

    assert "--queues=webhooks" in webhook_worker
    assert "networks: [public, internal]" in webhook_worker
    assert "TP_FIELD_ENCRYPTION_KEY:" in webhook_worker
    assert "TP_TELEGRAM_BOT_TOKEN:" in webhook_worker  # Telegram needs the same egress
    assert "<<: *app-environment" not in webhook_worker
    for forbidden in ("POLICY_KEYSTORE", "TP_SIGNER_SHARED_SECRET", "S3_", "policy_keystore"):
        assert forbidden not in webhook_worker


def test_email_credentials_live_only_in_the_egress_worker() -> None:
    compose = (Path(__file__).resolve().parents[3] / "infra" / "compose.yaml").read_text()
    webhook_worker = _service_block(compose, "worker-webhooks", "beat")

    for name in ("TP_RESEND_API_KEY", "TP_RESEND_FROM_EMAIL", "TP_SESSION_SECRET"):
        assert f"{name}:" in webhook_worker
        assert compose.count(f"\n      {name}:") == 1  # not in the core, AI or beat services
