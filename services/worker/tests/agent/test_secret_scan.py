import pytest

from treasurypilot_worker.agent import AiError, AiInputRejected, SecretScanner

# Secret-shaped test values are assembled at runtime so that no literal in this file
# looks like a real credential to secret scanners on the repository.
HEX64 = "4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
MNEMONIC = (
    "legal winner thank year wave sausage worth useful legal winner thank yellow abandon ability"
)
XPRV = (
    "xp"
    + "rv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi"
)


def _secret_cases() -> list[tuple[str, str]]:
    return [
        # A. Crypto keys and signatures.
        ("hex_key", f"key {HEX64} end"),
        ("hex_key", f"0x{HEX64}"),
        ("hex_key", "sig 0x" + HEX64 + HEX64 + "1b"),
        ("bip39_mnemonic", MNEMONIC),
        (
            "bip39_mnemonic",
            "1. legal 2. winner 3. thank 4. year 5. wave 6. sausage "
            "7. worth 8. useful 9. legal 10. winner 11. thank 12. yellow",
        ),
        (
            "bip39_mnemonic",
            "Legal, Winner, Thank, Year, Wave, Sausage,\nWorth, Useful, "
            "Legal, Winner, Thank, Yellow",
        ),
        ("extended_private_key", f"backup {XPRV}"),
        (
            "keystore_json",
            '{"crypto": {"cipher": "aes-128-ctr", "ciphertext": "ab", "kdf": "scrypt"}}',
        ),
        ("private_key_block", "-----BEGIN " + "PRIVATE KEY-----\nMIIE..."),
        ("private_key_block", "-----BEGIN OPENSSH " + "PRIVATE KEY-----"),
        ("private_key_block", "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----"),
        # B. Service tokens.
        ("anthropic_key", "sk-" + "ant-api03-" + "a1B2" * 10),
        ("sk_api_key", "sk-" + "proj-" + "a1B2" * 10),
        ("aws_access_key_id", "AKIA" + "IOSFODNN7EXAMPLE"),
        ("aws_access_key_id", "ASIA" + "IOSFODNN7EXAMPLE"),
        ("gcp_service_account", '{"type": "service_account", "project_id": "p"}'),
        ("gcp_service_account", '{"private_key_id": "abc"}'),
        ("google_api_key", "AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q"),
        ("github_token", "gh" + "p_" + "A1b2C3d4E5" * 4),
        ("github_token", "github" + "_pat_" + "11ABCDEFG0" * 3),
        ("gitlab_token", "gl" + "pat-" + "A1b2C3d4E5f6G7h8I9j0"),
        ("slack_token", "xo" + "xb-" + "1234567890-abcdefghij"),
        ("slack_webhook", "hooks.slack.com/services/" + "T000/B000/XXXX"),
        ("stripe_key", "sk" + "_live_" + "A1b2C3d4E5f6G7h8"),
        ("stripe_key", "wh" + "sec_" + "A1b2C3d4E5f6G7h8"),
        ("sendgrid_key", "SG" + ".A1b2C3d4E5f6G7h8I9." + "j0K1l2M3n4O5p6Q7r8"),
        ("npm_token", "np" + "m_" + "A1b2C3d4E5f6G7h8I9j0" + "K1l2M3n4O5p6Q7r8"),
        ("pypi_token", "py" + "pi-" + "AgEIcHlwaS5vcmc" * 4),
        ("telegram_bot_token", "123456789:" + "AAH" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q"),
        (
            "jwt",
            "eyJ"
            + "hbGciOiJIUzI1NiJ9."
            + "eyJ"
            + "zdWIiOiIxMjM0NTY3ODkwIn0."
            + "dozjgNryP4J3jVmNHl0w5N",
        ),
        # C. Credentials in URLs and configuration.
        ("url_credentials", "postgresql://app:" + "s3cretpw@db:5432/tp"),
        ("url_credentials", "redis://:" + "s3cretpw@cache:6379/0"),
        ("rpc_url_key", "eth-mainnet.g.alchemy.com/v2/" + "A1b2C3d4E5f6G7h8I9j0"),
        ("rpc_url_key", "mainnet.infura.io/v3/" + "0123456789abcdef0123456789abcdef"),
        ("authorization_header", "Authorization: " + "Bearer abc.def.ghi123"),
        ("authorization_header", "authorization: " + "Basic dXNlcjpwYXNz"),
        ("secret_assignment", "ANTHROPIC_API_" + "KEY" + "=" + "x" * 16),
        ("secret_assignment", 'db_password: "' + 'hunter2hunter2"'),
        ("secret_assignment", "EXECUTOR_PRIVATE_KEY = " + "abcdefgh"),
        ("secret_assignment", "wallet mnemonic: " + "something-long"),
    ]


# Ids are pattern names, so secret-shaped values stay out of test names and CI logs.
@pytest.mark.parametrize(
    ("pattern", "text"), _secret_cases(), ids=[pattern for pattern, _ in _secret_cases()]
)
def test_secret_shaped_input_is_found(pattern: str, text: str) -> None:
    assert SecretScanner().find(f"Invoice INV-7\n{text}\nThanks") == pattern


@pytest.mark.parametrize(
    "text",
    [
        "Invoice INV-2026-0042 from Acme Ltd. Total 1,250.00 USDC, due 2026-11-01, net 30.",
        "Pay to 0x52908400098527886E0F7030069857D2E4169EE7 (registered payee).",
        "Contact billing@acme.example for questions.",
        "IBAN DE89 3704 0044 0532 0130 00, card ending 4242.",
        "Reference 123e4567-e89b-12d3-a456-426614174000, digest d41d8cd98f00b204e9800998ecf8427e.",
        "Please transfer the total amount to this account and make payment this month.",
        "Token: USDC on Base. Key terms: 2/10 net 30.",
        "See https://acme.example/terms for the terms.",
    ],
)
def test_ordinary_invoice_text_passes(text: str) -> None:
    assert SecretScanner().find(text) is None


def test_seed_phrase_as_json_array_is_found() -> None:
    words = MNEMONIC.split()[:12]
    text = "[" + ", ".join(f'"{word}"' for word in words) + "]"

    assert SecretScanner().find(text) == "bip39_mnemonic"


def test_eleven_mnemonic_words_are_not_a_seed_phrase() -> None:
    eleven = " ".join(MNEMONIC.split()[:11])

    assert SecretScanner().find(f"{eleven} invoice") is None


def test_known_secret_value_is_found_verbatim() -> None:
    value = "zz-" + "opaque-value-without-any-pattern"
    scanner = SecretScanner(known_secrets=[value])

    assert scanner.find(f"note {value} end") == "known_secret"


def test_known_secrets_come_from_secret_named_environment_variables() -> None:
    secret = "opaque" + "-value-0123456789"
    scanner = SecretScanner.from_environ(
        {
            "ANTHROPIC_API_KEY": secret,
            "DB_PASSWORD": "short",
            "TP_AI_CONFIG_PATH": "/app/config/ai.yaml-long-path",
        }
    )

    assert scanner.find(f"x {secret} y") == "known_secret"
    assert scanner.find("short") is None
    assert scanner.find("/app/config/ai.yaml-long-path") is None


def test_check_rejects_without_leaking_the_value() -> None:
    value = "sk-" + "ant-api03-" + "a1B2" * 10

    with pytest.raises(AiInputRejected) as raised:
        SecretScanner().check(f"pay with {value}", source="invoice:INV-7")

    error = raised.value
    assert isinstance(error, AiError)
    assert error.pattern == "anthropic_key"
    assert error.source == "invoice:INV-7"
    assert value not in str(error)
    assert value not in repr(error)
    assert error.__cause__ is None


def test_check_accepts_clean_text() -> None:
    SecretScanner().check("Invoice INV-7, total 100 USDC", source="invoice:INV-7")
