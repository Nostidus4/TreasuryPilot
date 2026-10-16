"""Provider registry: the one place a new ERP adapter (QuickBooks, NetSuite) is wired in."""

from __future__ import annotations

from collections.abc import Mapping

from treasurypilot_api.config import Settings
from treasurypilot_api.integrations.erp.http import HttpClient, UrllibHttpClient
from treasurypilot_api.integrations.erp.netsuite import NetSuiteProvider
from treasurypilot_api.integrations.erp.provider import ErpProvider
from treasurypilot_api.integrations.erp.quickbooks import QuickBooksProvider
from treasurypilot_api.integrations.erp.xero import XeroProvider


def build_providers(
    settings: Settings, http: HttpClient | None = None
) -> Mapping[str, ErpProvider]:
    """Only providers with credentials configured are returned; the rest are simply off."""

    client = http or UrllibHttpClient()
    providers: dict[str, ErpProvider] = {}
    if settings.xero_client_id and settings.xero_client_secret is not None:
        providers["xero"] = XeroProvider(
            client,
            client_id=settings.xero_client_id,
            client_secret=settings.xero_client_secret.get_secret_value(),
        )
    if settings.quickbooks_client_id and settings.quickbooks_client_secret is not None:
        providers["quickbooks"] = QuickBooksProvider(
            client,
            client_id=settings.quickbooks_client_id,
            client_secret=settings.quickbooks_client_secret.get_secret_value(),
            sandbox=settings.quickbooks_sandbox,
        )
    if (
        settings.netsuite_account_id
        and settings.netsuite_client_id
        and settings.netsuite_client_secret is not None
    ):
        providers["netsuite"] = NetSuiteProvider(
            client,
            account_id=settings.netsuite_account_id,
            client_id=settings.netsuite_client_id,
            client_secret=settings.netsuite_client_secret.get_secret_value(),
        )
    return providers
