from __future__ import annotations

from pathlib import Path

from eth_account import Account
from eth_account.signers.local import LocalAccount

from treasurypilot_signer.config import Settings


class ExecutorKeyUnavailable(RuntimeError):
    """The encrypted executor key for a treasury could not be loaded."""


class ExecutorKeyNotConfigured(ExecutorKeyUnavailable):
    """No keystore is mapped for the treasury."""


class ExecutorKeys:
    def __init__(self, settings: Settings) -> None:
        self._paths = {
            key.lower(): Path(path) for key, path in settings.executor_keystore_map.items()
        }
        self._password_file = settings.executor_keystore_password_file

    def for_treasury(self, treasury_id: str) -> LocalAccount:
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
        """Fail fast at startup: a keystore must be mapped and every one must decrypt.

        Returns treasury id -> executor address; never the key.
        """
        if not self._paths:
            raise ExecutorKeyUnavailable("TP_EXECUTOR_KEYSTORE_MAP has no entries")
        for path in self._paths.values():
            if not path.is_file():
                raise ExecutorKeyUnavailable("a keystore in TP_EXECUTOR_KEYSTORE_MAP is missing")
        if self._password_file is None or not self._password_file.is_file():
            raise ExecutorKeyUnavailable("TP_EXECUTOR_KEYSTORE_PASSWORD_FILE is missing")
        return {t: self.for_treasury(t).address for t in self._paths}
