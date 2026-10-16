from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from eth_account import Account
from eth_account.signers.local import LocalAccount

from treasurypilot_signer.config import Settings
from treasurypilot_signer.kms import (
    ExecutorSigner,
    KmsAccount,
    KmsClient,
    KmsSigningError,
    build_kms_client,
)


class ExecutorKeyUnavailable(RuntimeError):
    """The encrypted executor key for a treasury could not be loaded."""


class ExecutorKeyNotConfigured(ExecutorKeyUnavailable):
    """No keystore is mapped for the treasury."""


class ExecutorKeys:
    """Resolves the executor signer per treasury from the configured backend.

    ``keystore`` (default) decrypts a local encrypted JSON keystore; ``kms`` signs through AWS KMS
    and never holds private key material.
    """

    def __init__(
        self, settings: Settings, *, kms_client_factory: Callable[[], KmsClient] | None = None
    ) -> None:
        self._backend = settings.executor_key_backend
        self._settings = settings
        self._paths = {
            key.lower(): Path(path) for key, path in settings.executor_keystore_map.items()
        }
        self._kms_keys = {k.lower(): v for k, v in settings.executor_kms_key_map.items()}
        self._password_file = settings.executor_keystore_password_file
        self._kms_client_factory = kms_client_factory
        self._kms_client: KmsClient | None = None
        self._kms_accounts: dict[str, KmsAccount] = {}

    @property
    def configured(self) -> bool:
        return bool(self._kms_keys if self._backend == "kms" else self._paths)

    def for_treasury(self, treasury_id: str) -> ExecutorSigner:
        if self._backend == "kms":
            return self._kms_for_treasury(treasury_id.lower())
        return self._keystore_for_treasury(treasury_id)

    def _kms_for_treasury(self, treasury_id: str) -> KmsAccount:
        account = self._kms_accounts.get(treasury_id)
        if account is not None:
            return account
        key_id = self._kms_keys.get(treasury_id)
        if key_id is None:
            raise ExecutorKeyNotConfigured
        try:
            if self._kms_client is None:
                factory = self._kms_client_factory or self._default_kms_client
                self._kms_client = factory()
            account = KmsAccount(
                self._kms_client,
                key_id,
                max_attempts=self._settings.kms_max_attempts,
            )
        except KmsSigningError as error:
            raise ExecutorKeyUnavailable(str(error)) from error
        self._kms_accounts[treasury_id] = account
        return account

    def _default_kms_client(self) -> KmsClient:
        return build_kms_client(
            region=self._settings.kms_region,
            endpoint_url=self._settings.kms_endpoint_url,
            timeout_seconds=self._settings.kms_timeout_seconds,
        )

    def _keystore_for_treasury(self, treasury_id: str) -> LocalAccount:
        path = self._paths.get(treasury_id.lower())
        if path is None:
            raise ExecutorKeyNotConfigured
        if self._password_file is None:
            raise ExecutorKeyUnavailable("TP_EXECUTOR_KEYSTORE_PASSWORD_FILE is not set")
        try:
            private_key = Account.decrypt(path.read_text(), self._password_file.read_text().strip())
            account: LocalAccount = Account.from_key(private_key)
            return account
        except (OSError, ValueError) as error:
            # Do not forward decoder errors; some implementations include key material.
            raise ExecutorKeyUnavailable from error

    def validate(self) -> dict[str, str]:
        """Fail fast at startup: every mapped key must load.

        Returns treasury id -> executor address; never the key.
        """
        if self._backend == "kms":
            if not self._kms_keys:
                raise ExecutorKeyUnavailable("TP_EXECUTOR_KMS_KEY_MAP has no entries")
            return {t: self._kms_for_treasury(t).address for t in self._kms_keys}
        if not self._paths:
            raise ExecutorKeyUnavailable("TP_EXECUTOR_KEYSTORE_MAP has no entries")
        for path in self._paths.values():
            if not path.is_file():
                raise ExecutorKeyUnavailable("a keystore in TP_EXECUTOR_KEYSTORE_MAP is missing")
        if self._password_file is None or not self._password_file.is_file():
            raise ExecutorKeyUnavailable("TP_EXECUTOR_KEYSTORE_PASSWORD_FILE is missing")
        return {t: self._keystore_for_treasury(t).address for t in self._paths}


class SentinelKey:
    """The pause-only key: a separate keystore from the executor's."""

    def __init__(self, settings: Settings) -> None:
        self._path = settings.sentinel_keystore_path
        self._password_file = settings.sentinel_keystore_password_file

    def load(self) -> LocalAccount:
        if self._path is None or self._password_file is None:
            raise ExecutorKeyNotConfigured
        try:
            private_key = Account.decrypt(
                self._path.read_text(), self._password_file.read_text().strip()
            )
            account: LocalAccount = Account.from_key(private_key)
            return account
        except (OSError, ValueError) as error:
            # Do not forward decoder errors; some implementations include key material.
            raise ExecutorKeyUnavailable from error
