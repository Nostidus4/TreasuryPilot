from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from eth_hash.auto import keccak
from fastapi.testclient import TestClient

from treasurypilot_api.audit.events import AuditEvent
from treasurypilot_api.compliance.screening import (
    FixtureScreeningProvider,
    ProviderResult,
    ScreeningProviderError,
    ScreeningRecord,
    ScreeningService,
    normalize_address,
)
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.main import create_app
from treasurypilot_api.mandate.governance import GovernanceCall
from treasurypilot_api.mandate.models import (
    GovernanceTxPurpose,
    OobMethod,
    PayeeStatus,
    ScreeningResult,
)
from treasurypilot_api.mandate.payees import (
    NotAwaitingOwner,
    OobAlreadyVerified,
    PayeeContext,
    PayeeExists,
    PayeeRecord,
    ScreeningSummary,
    check_registration_gates,
    effective_payee_status,
)
from treasurypilot_api.mandate.vendors import (
    VendorHasPayees,
    VendorRecord,
    VendorRefExists,
    VendorUpdate,
    normalize_vendor_ref,
)

ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000111")
TREASURY_ID = uuid.UUID("00000000-0000-4000-8000-000000000222")
USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000333")
CHAIN_ID = 11155111
SAFE = bytes.fromhex("11" * 20)
MODULE = bytes.fromhex("22" * 20)
CLEAN = "0x" + "ab" * 20
LISTED = "0x000000000000000000000000000000000000dEaD"


class FakeGovernanceService:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    async def create(self, **fields: object) -> dict[str, object]:
        tx_id = uuid.uuid4()
        self.created.append(fields)
        calls = cast(list[GovernanceCall], fields["calls"])
        return {
            "id": tx_id,
            "purpose": cast(GovernanceTxPurpose, fields["purpose"]).value,
            "decodedCalls": [call.as_json() for call in calls],
            "status": "Collecting",
        }


class MemoryScreeningRepository:
    def __init__(self) -> None:
        self.rows: list[ScreeningRecord] = []

    async def latest(
        self, *, organization_id: uuid.UUID, address: bytes, chain_id: int, provider: str
    ) -> ScreeningRecord | None:
        matches = [
            r
            for r in self.rows
            if (r.organization_id, r.address, r.chain_id, r.provider)
            == (organization_id, address, chain_id, provider)
        ]
        return matches[-1] if matches else None

    async def record(self, **fields: object) -> ScreeningRecord:
        row = ScreeningRecord(id=uuid.uuid4(), **fields)  # type: ignore[arg-type]
        self.rows.append(row)
        return row


class DownProvider:
    name = "fixture-test"

    async def screen(self, *, address: bytes, chain_id: int) -> ProviderResult:
        raise ScreeningProviderError("outage")


class MemoryStore:
    """Vendor and payee repositories over one dict, recording audit events."""

    def __init__(self, screenings: MemoryScreeningRepository) -> None:
        self.vendors: dict[uuid.UUID, VendorRecord] = {}
        self.payees: dict[uuid.UUID, PayeeRecord] = {}
        self.audit: list[AuditEvent] = []
        self.module_address: bytes | None = MODULE
        self.screenings = screenings

    def _log(self, action: str, entity_type: str, entity_id: uuid.UUID, **data: object) -> None:
        self.audit.append(AuditEvent(ORG_ID, USER_ID, action, entity_type, entity_id, data))

    # vendors
    async def list_vendors(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID | None = None
    ) -> tuple[VendorRecord, ...]:
        return tuple(v for v in self.vendors.values() if v.org_id == organization_id)

    async def get_vendor(
        self, *, organization_id: uuid.UUID, vendor_id: uuid.UUID
    ) -> VendorRecord | None:
        vendor = self.vendors.get(vendor_id)
        return vendor if vendor and vendor.org_id == organization_id else None

    async def create_vendor(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        country: str | None,
        normalized_ref: str,
        tax_id: bytes | None,
        contact: bytes | None,
        notes: str | None,
    ) -> VendorRecord:
        if any(
            v.org_id == organization_id and v.normalized_ref == normalized_ref
            for v in self.vendors.values()
        ):
            raise VendorRefExists
        row = VendorRecord(
            uuid.uuid4(), organization_id, name, normalized_ref,
            tax_id is not None, contact is not None, notes, datetime.now(UTC), country,
        )  # fmt: skip
        self.vendors[row.id] = row
        self._log("vendor.created", "vendor", row.id)
        return row

    async def update_vendor(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        vendor_id: uuid.UUID,
        update: VendorUpdate,
        changed: tuple[str, ...],
    ) -> VendorRecord | None:
        vendor = await self.get_vendor(organization_id=organization_id, vendor_id=vendor_id)
        if vendor is None:
            return None
        vendor = replace(
            vendor,
            name=update.name or vendor.name,
            country=update.country if "country" in changed else vendor.country,
            has_tax_id=(vendor.has_tax_id or update.tax_id is not None) and not update.clear_tax_id,
        )
        self.vendors[vendor_id] = vendor
        self._log("vendor.updated", "vendor", vendor_id, fields=list(changed))
        return vendor

    async def delete_vendor(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, vendor_id: uuid.UUID
    ) -> bool:
        if await self.get_vendor(organization_id=organization_id, vendor_id=vendor_id) is None:
            return False
        if any(p.vendor_id == vendor_id for p in self.payees.values()):
            raise VendorHasPayees
        del self.vendors[vendor_id]
        return True

    # payees
    async def get_context(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> PayeeContext | None:
        if (organization_id, treasury_id) != (ORG_ID, TREASURY_ID):
            return None
        return PayeeContext(
            chain_id=CHAIN_ID,
            wallet_addresses=frozenset({SAFE}),
            module_address=self.module_address,
        )

    async def vendor_exists(self, *, organization_id: uuid.UUID, vendor_id: uuid.UUID) -> bool:
        return (
            await self.get_vendor(organization_id=organization_id, vendor_id=vendor_id) is not None
        )

    async def propose(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        vendor_id: uuid.UUID,
        user_id: uuid.UUID,
        label: str,
        address: bytes,
    ) -> PayeeRecord:
        dead = {PayeeStatus.DEACTIVATED.value, PayeeStatus.SCREENING_FAILED.value}
        if any(p.address == address and p.status not in dead for p in self.payees.values()):
            raise PayeeExists
        row = PayeeRecord(
            id=uuid.uuid4(), treasury_id=treasury_id, vendor_id=vendor_id, label=label,
            address=address, status=PayeeStatus.SCREENING.value, oob_method=None, oob_note=None,
            oob_verified_by=None, oob_verified_at=None, registration_tx_id=None,
            active_from=None, proposed_by=user_id, created_at=datetime.now(UTC),
        )  # fmt: skip
        self.payees[row.id] = row
        self._log("payee.proposed", "payee", row.id)
        return row

    def _with_screening(self, row: PayeeRecord) -> PayeeRecord:
        stored = [s for s in self.screenings.rows if s.payee_id == row.id]
        if not stored:
            return row
        s = stored[-1]
        return replace(
            row,
            screening=ScreeningSummary(
                s.result, s.source_ref, s.provider, s.checked_at, s.ttl_until
            ),
        )

    async def finish_screening(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        payee_id: uuid.UUID,
        user_id: uuid.UUID,
        result: ScreeningResult,
        provider: str,
    ) -> PayeeRecord | None:
        row = self.payees.get(payee_id)
        if row is None:
            return None
        clear = result == ScreeningResult.CLEAR
        row = replace(
            row,
            status=(PayeeStatus.AWAITING_OWNER if clear else PayeeStatus.SCREENING_FAILED).value,
        )
        self.payees[payee_id] = row
        self._log("payee.screening_clear" if clear else "payee.screening_failed", "payee", payee_id)
        return self._with_screening(row)

    async def list_payees(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> tuple[PayeeRecord, ...] | None:
        if (organization_id, treasury_id) != (ORG_ID, TREASURY_ID):
            return None
        return tuple(self._with_screening(p) for p in self.payees.values())

    async def get_payee(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID, payee_id: uuid.UUID
    ) -> PayeeRecord | None:
        row = self.payees.get(payee_id)
        if row is None or (organization_id, treasury_id) != (ORG_ID, TREASURY_ID):
            return None
        return self._with_screening(row)

    async def register_with_tx(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        payee_id: uuid.UUID,
        create_tx: Callable[[], Awaitable[tuple[uuid.UUID, dict[str, object]]]],
    ) -> dict[str, object] | None:
        row = self.payees.get(payee_id)
        if (
            row is None
            or row.status != PayeeStatus.AWAITING_OWNER.value
            or row.registration_tx_id is not None
        ):
            return None
        tx_id, governance_tx = await create_tx()
        self.payees[payee_id] = replace(row, registration_tx_id=tx_id)
        return governance_tx

    async def record_deactivation_requested(
        self,
        *,
        organization_id: uuid.UUID,
        payee_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
        governance_tx_id: object,
    ) -> None:
        self._log(
            "payee.deactivation_requested",
            "payee",
            payee_id,
            reason=reason,
            governanceTxId=str(governance_tx_id),
        )

    async def verify_oob(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        payee_id: uuid.UUID,
        user_id: uuid.UUID,
        method: OobMethod,
        note: str,
        at: datetime,
    ) -> PayeeRecord | None:
        row = await self.get_payee(
            organization_id=organization_id, treasury_id=treasury_id, payee_id=payee_id
        )
        if row is None:
            return None
        if row.status != PayeeStatus.AWAITING_OWNER.value:
            raise NotAwaitingOwner
        if row.oob_verified_at is not None:
            raise OobAlreadyVerified
        row = replace(
            row, oob_method=method.value, oob_note=note, oob_verified_by=user_id, oob_verified_at=at
        )
        self.payees[payee_id] = row
        self._log("payee.oob_verified", "payee", payee_id, method=method)
        return row


class FakeCipher:
    def encrypt(self, plaintext: str) -> bytes:
        return plaintext[::-1].encode()

    def decrypt(self, ciphertext: bytes) -> str:
        return ciphertext.decode()[::-1]


def _member_access(organization_id: uuid.UUID, roles: frozenset[str]) -> MemberAccess:
    access = SessionAccess(
        user=UserRecord(USER_ID, "member@example.test", None, "active"),
        session_id=uuid.UUID("00000000-0000-4000-8000-000000000444"),
    )
    return MemberAccess(access=access, organization_id=organization_id, roles=roles)


def make_client(
    *,
    provider: object | None = None,
    roles: frozenset[str] = frozenset({"Owner"}),
    cipher: bool = True,
    governance_service: object | None = None,
) -> tuple[TestClient, MemoryStore]:
    screenings = MemoryScreeningRepository()
    store = MemoryStore(screenings)
    fixture = FixtureScreeningProvider({normalize_address(LISTED): "TEST DATA"})
    service = ScreeningService(screenings, provider or fixture)  # type: ignore[arg-type]
    app = create_app(
        settings=Settings(environment="local"),
        vendor_repository=cast(object, store),
        payee_repository=cast(object, store),
        screening_service=service,
        governance_service=cast(object, governance_service) if governance_service else None,
        field_cipher=FakeCipher() if cipher else None,
    )

    async def member_override(organization_id: uuid.UUID) -> MemberAccess:
        return _member_access(organization_id, roles)

    app.dependency_overrides[require_member] = member_override
    return TestClient(app), store


VENDORS = f"/v1/orgs/{ORG_ID}/vendors"
PAYEES = f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/payees"


def new_vendor(client: TestClient, name: str = "Acme Supplies") -> str:
    response = client.post(VENDORS, json={"name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["vendor"]["id"])


# ------------------------------------------------------------------ vendors


def test_vendor_crud_and_normalized_ref() -> None:
    client, store = make_client()
    with client:
        created = client.post(
            VENDORS,
            json={"name": "  Acme   Supplies ", "country": "gb", "taxId": "VN123"},
        )
        vendor_id = created.json()["vendor"]["id"]
        patched = client.patch(f"{VENDORS}/{vendor_id}", json={"name": "Acme Ltd", "country": "ca"})
        fetched = client.get(f"{VENDORS}/{vendor_id}")
        listed = client.get(VENDORS)
        deleted = client.delete(f"{VENDORS}/{vendor_id}")
        missing = client.get(f"{VENDORS}/{vendor_id}")

    assert created.status_code == 201
    assert created.json()["vendor"]["normalizedRef"] == "acme supplies"
    assert created.json()["vendor"]["country"] == "GB"
    assert created.json()["vendor"]["hasTaxId"] is True
    assert "taxId" not in created.json()["vendor"]
    assert patched.json()["vendor"]["name"] == "Acme Ltd"
    assert patched.json()["vendor"]["country"] == "CA"
    assert patched.json()["vendor"]["normalizedRef"] == "acme supplies"
    assert fetched.status_code == 200 and len(listed.json()["items"]) == 1
    assert deleted.status_code == 204 and missing.status_code == 404
    assert missing.json()["code"] == "VENDOR_NOT_FOUND"
    assert [e.action for e in store.audit] == ["vendor.created", "vendor.updated"]


def test_second_vendor_with_same_normalized_ref_is_rejected() -> None:
    client, _ = make_client()
    with client:
        new_vendor(client, "Acme Supplies")
        duplicate = client.post(VENDORS, json={"name": "ACME   supplies"})
        by_code = client.post(VENDORS, json={"name": "Other", "supplierCode": "acme supplies"})

    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "VENDOR_REF_EXISTS"
    assert by_code.json()["code"] == "VENDOR_REF_EXISTS"


def test_vendor_permissions_and_confidential_fields_fail_closed() -> None:
    finance, _ = make_client(roles=frozenset({"Finance"}))
    no_cipher, _ = make_client(cipher=False)
    with finance:
        assert finance.get(VENDORS).status_code == 200
        assert finance.post(VENDORS, json={"name": "X"}).status_code == 403
    with no_cipher:
        refused = no_cipher.post(VENDORS, json={"name": "X", "taxId": "123"})
        plain = no_cipher.post(VENDORS, json={"name": "X"})
    assert refused.status_code == 503 and refused.json()["code"] == "ENCRYPTION_UNAVAILABLE"
    assert plain.status_code == 201


def test_vendor_with_payees_cannot_be_deleted() -> None:
    client, _ = make_client()
    with client:
        vendor_id = new_vendor(client)
        client.post(PAYEES, json={"vendorId": vendor_id, "label": "Main", "address": CLEAN})
        response = client.delete(f"{VENDORS}/{vendor_id}")
    assert response.status_code == 409 and response.json()["code"] == "VENDOR_HAS_PAYEES"


def test_normalize_vendor_ref() -> None:
    assert normalize_vendor_ref("  ÄCME\tCorp ") == normalize_vendor_ref("äcme corp")
    assert normalize_vendor_ref("ＡＢＣ") == "abc"


# ------------------------------------------------------------------ payees


def test_clear_proposal_awaits_owner_and_is_audited() -> None:
    client, store = make_client()
    with client:
        vendor_id = new_vendor(client)
        response = client.post(
            PAYEES, json={"vendorId": vendor_id, "label": "Main account", "address": CLEAN}
        )

    assert response.status_code == 201
    payee = response.json()["payee"]
    assert payee["status"] == "AwaitingOwner"
    assert payee["address"] == CLEAN
    assert payee["screening"]["result"] == "CLEAR"
    assert [e.action for e in store.audit if e.entity_type == "payee"] == [
        "payee.proposed",
        "payee.screening_clear",
    ]
    assert response.headers["location"].endswith(payee["id"])


def test_screening_hit_returns_code_and_payee_cannot_proceed() -> None:
    client, store = make_client()
    with client:
        vendor_id = new_vendor(client)
        response = client.post(
            PAYEES, json={"vendorId": vendor_id, "label": "Bad", "address": LISTED}
        )
        payee_id = next(iter(store.payees))
        verify = client.post(
            f"{PAYEES}/{payee_id}/verify-oob", json={"method": "PHONE", "note": "called"}
        )
        registration = client.post(f"{PAYEES}/{payee_id}/registration-tx")

    assert response.status_code == 422
    assert response.json()["code"] == "SCREENING_HIT"
    assert store.payees[payee_id].status == "ScreeningFailed"
    assert verify.status_code == 409 and verify.json()["code"] == "NOT_AWAITING_OWNER"
    assert registration.status_code == 409
    assert registration.json()["code"] == "SCREENING_NOT_CLEAR"
    assert "payee.screening_failed" in [e.action for e in store.audit]


def test_provider_error_blocks_registration() -> None:
    client, store = make_client(provider=DownProvider())
    with client:
        vendor_id = new_vendor(client)
        response = client.post(
            PAYEES, json={"vendorId": vendor_id, "label": "Main", "address": CLEAN}
        )
        payee_id = next(iter(store.payees))
        registration = client.post(f"{PAYEES}/{payee_id}/registration-tx")

    assert response.status_code == 503 and response.json()["code"] == "DATA_MISSING"
    assert store.payees[payee_id].status == "ScreeningFailed"
    assert registration.json()["code"] == "SCREENING_NOT_CLEAR"
    assert store.screenings.rows[-1].result == ScreeningResult.ERROR


def test_duplicate_address_is_rejected_but_failed_one_can_be_reproposed() -> None:
    client, _ = make_client()
    with client:
        vendor_id = new_vendor(client)
        body = {"vendorId": vendor_id, "label": "Main", "address": CLEAN}
        first = client.post(PAYEES, json=body)
        again = client.post(PAYEES, json={**body, "address": CLEAN.upper().replace("0X", "0x")})
        client.post(PAYEES, json={**body, "address": LISTED})
        listed_again = client.post(PAYEES, json={**body, "address": LISTED})

    assert first.status_code == 201
    assert again.status_code == 409 and again.json()["code"] == "PAYEE_EXISTS"
    assert listed_again.json()["code"] == "SCREENING_HIT"  # not PAYEE_EXISTS


@pytest.mark.parametrize(
    ("address", "code"),
    [("0x1234", "ADDRESS_INVALID"), ("0x" + "11" * 20, "ADDRESS_IS_TREASURY_WALLET")],
)
def test_invalid_and_treasury_addresses_are_rejected(address: str, code: str) -> None:
    client, store = make_client()
    with client:
        vendor_id = new_vendor(client)
        response = client.post(
            PAYEES, json={"vendorId": vendor_id, "label": "x", "address": address}
        )
    assert response.status_code == 422 and response.json()["code"] == code
    assert store.payees == {}


def test_unknown_vendor_and_foreign_tenant() -> None:
    client, _ = make_client()
    with client:
        unknown = client.post(
            PAYEES, json={"vendorId": str(uuid.uuid4()), "label": "x", "address": CLEAN}
        )
        foreign = client.get(f"/v1/orgs/{uuid.uuid4()}/treasuries/{TREASURY_ID}/payees")
    assert unknown.status_code == 404 and unknown.json()["code"] == "VENDOR_NOT_FOUND"
    assert foreign.status_code == 404


def test_proposing_requires_operator_admin_or_owner_and_screening() -> None:
    finance, _ = make_client(roles=frozenset({"Finance"}))
    operator, _ = make_client(roles=frozenset({"Operator"}))
    with finance:
        denied = finance.post(
            PAYEES, json={"vendorId": str(uuid.uuid4()), "label": "x", "address": CLEAN}
        )
    with operator:
        vendor_id = new_vendor(operator)
        allowed = operator.post(
            PAYEES, json={"vendorId": vendor_id, "label": "x", "address": CLEAN}
        )
    assert denied.status_code == 403
    assert allowed.status_code == 201

    unscreened = create_app(
        settings=Settings(environment="local"),
        vendor_repository=cast(object, MemoryStore(MemoryScreeningRepository())),
        payee_repository=cast(object, MemoryStore(MemoryScreeningRepository())),
    )

    async def member(organization_id: uuid.UUID) -> MemberAccess:
        return _member_access(organization_id, frozenset({"Owner"}))

    unscreened.dependency_overrides[require_member] = member
    with TestClient(unscreened) as client:
        response = client.post(
            PAYEES, json={"vendorId": str(uuid.uuid4()), "label": "x", "address": CLEAN}
        )
    assert response.status_code == 503 and response.json()["code"] == "SCREENING_UNAVAILABLE"


def test_registration_refused_until_oob_recorded_owner_only_and_audited() -> None:
    governance = FakeGovernanceService()
    owner, store = make_client(governance_service=governance)
    operator, _ = make_client(roles=frozenset({"Operator"}))
    with owner:
        vendor_id = new_vendor(owner)
        payee_id = owner.post(
            PAYEES, json={"vendorId": vendor_id, "label": "Main", "address": CLEAN}
        ).json()["payee"]["id"]
        before = owner.post(f"{PAYEES}/{payee_id}/registration-tx")
        blank = owner.post(f"{PAYEES}/{payee_id}/verify-oob", json={"method": "PHONE", "note": " "})
        bad_method = owner.post(
            f"{PAYEES}/{payee_id}/verify-oob", json={"method": "EMAIL", "note": "x"}
        )
        verified = owner.post(
            f"{PAYEES}/{payee_id}/verify-oob",
            json={"method": "PHONE", "note": "Called CFO on file"},
        )
        again = owner.post(
            f"{PAYEES}/{payee_id}/verify-oob", json={"method": "PHONE", "note": "again"}
        )
        after = owner.post(f"{PAYEES}/{payee_id}/registration-tx")
    with operator:
        denied = operator.post(
            f"{PAYEES}/{payee_id}/verify-oob", json={"method": "PHONE", "note": "x"}
        )
        denied_tx = operator.post(f"{PAYEES}/{payee_id}/registration-tx")

    assert before.status_code == 409 and before.json()["code"] == "OOB_NOT_VERIFIED"
    assert blank.status_code == 422 and bad_method.status_code == 422
    assert verified.status_code == 200
    assert verified.json()["payee"]["oobMethod"] == "PHONE"
    assert verified.json()["payee"]["oobVerifiedBy"] == str(USER_ID)
    assert again.status_code == 409 and again.json()["code"] == "OOB_ALREADY_VERIFIED"
    assert after.status_code == 201
    tx = after.json()["governanceTx"]
    assert tx["purpose"] == "PAYEE_ADD"
    assert tx["decodedCalls"][0]["to"] == "0x" + MODULE.hex()
    assert tx["decodedCalls"][0]["data"].startswith("0x" + keccak(b"addPayee(address)").hex()[:8])
    assert store.payees[uuid.UUID(payee_id)].registration_tx_id == uuid.UUID(tx["id"])
    assert governance.created[-1]["entity_type"] == "payee"
    assert governance.created[-1]["entity_id"] == uuid.UUID(payee_id)
    assert denied.status_code == 403 and denied_tx.status_code == 403
    assert [e.action for e in store.audit if e.action == "payee.oob_verified"] == [
        "payee.oob_verified"
    ]


def test_registration_gates_screening_expiry() -> None:
    now = datetime(2026, 10, 14, tzinfo=UTC)
    payee = PayeeRecord(
        id=uuid.uuid4(), treasury_id=TREASURY_ID, vendor_id=uuid.uuid4(), label="x",
        address=bytes(20), status="AwaitingOwner", oob_method="PHONE", oob_note="n",
        oob_verified_by=USER_ID, oob_verified_at=now, registration_tx_id=None, active_from=None,
        proposed_by=USER_ID, created_at=now,
        screening=ScreeningSummary(ScreeningResult.CLEAR, None, "p", now, now + timedelta(hours=1)),
    )  # fmt: skip
    assert check_registration_gates(payee, now=now) is None
    expired = check_registration_gates(payee, now=now + timedelta(hours=2))
    assert expired is not None and expired.code == "SCREENING_EXPIRED"
    unscreened = check_registration_gates(replace(payee, screening=None), now=now)
    assert unscreened is not None and unscreened.code == "SCREENING_NOT_CLEAR"


def test_cooling_becomes_active_after_active_from_without_another_event() -> None:
    active_from = datetime(2026, 10, 15, 12, tzinfo=UTC)
    assert (
        effective_payee_status("Cooling", active_from, now=active_from - timedelta(seconds=1))
        == "Cooling"
    )
    assert effective_payee_status("Cooling", active_from, now=active_from) == "Active"


def test_deactivation_builds_governance_transaction_for_registered_payee() -> None:
    governance = FakeGovernanceService()
    owner, store = make_client(governance_service=governance)
    with owner:
        vendor_id = new_vendor(owner)
        payee = owner.post(
            PAYEES, json={"vendorId": vendor_id, "label": "Main account", "address": CLEAN}
        ).json()["payee"]
        payee_id = uuid.UUID(payee["id"])
        store.payees[payee_id] = replace(store.payees[payee_id], status=PayeeStatus.ACTIVE.value)

        response = owner.post(
            f"{PAYEES}/{payee_id}/deactivation-tx", json={"reason": "Vendor requested"}
        )

    assert response.status_code == 201, response.text
    tx = response.json()["governanceTx"]
    assert tx["purpose"] == "PAYEE_DEACTIVATE"
    call = tx["decodedCalls"][0]
    assert call["to"] == "0x" + MODULE.hex()
    assert call["data"].startswith("0x" + keccak(b"deactivatePayee(address)").hex()[:8])
    assert call["data"][-40:].lower() == CLEAN[2:]
    assert governance.created[-1]["entity_type"] == "payee"
    assert governance.created[-1]["entity_id"] == payee_id
    assert [(e.action, e.data["reason"]) for e in store.audit if "deactivation" in e.action] == [
        ("payee.deactivation_requested", "Vendor requested")
    ]


def test_replacement_without_module_leaves_no_stray_payee_row() -> None:
    owner, store = make_client(governance_service=FakeGovernanceService())
    with owner:
        vendor_id = new_vendor(owner)
        old = owner.post(
            PAYEES, json={"vendorId": vendor_id, "label": "Main account", "address": CLEAN}
        ).json()["payee"]
        old_id = uuid.UUID(old["id"])
        store.payees[old_id] = replace(store.payees[old_id], status=PayeeStatus.ACTIVE.value)
        store.module_address = None

        response = owner.post(
            f"{PAYEES}/{old_id}/replace-address",
            json={"address": "0x" + "cd" * 20, "reason": "Vendor bank account changed"},
        )

    assert response.status_code == 409 and response.json()["code"] == "MODULE_NOT_READY"
    assert list(store.payees) == [old_id]


def test_registration_tx_is_created_once() -> None:
    governance = FakeGovernanceService()
    owner, _ = make_client(governance_service=governance)
    with owner:
        vendor_id = new_vendor(owner)
        payee_id = owner.post(
            PAYEES, json={"vendorId": vendor_id, "label": "Main", "address": CLEAN}
        ).json()["payee"]["id"]
        owner.post(f"{PAYEES}/{payee_id}/verify-oob", json={"method": "PHONE", "note": "ok"})
        first = owner.post(f"{PAYEES}/{payee_id}/registration-tx")
        second = owner.post(f"{PAYEES}/{payee_id}/registration-tx")

    assert first.status_code == 201
    assert second.status_code == 409 and second.json()["code"] == "REGISTRATION_TX_EXISTS"
    assert len(governance.created) == 1


def test_replacing_address_creates_new_payee_and_deactivation_governance_tx() -> None:
    governance = FakeGovernanceService()
    owner, store = make_client(governance_service=governance)
    replacement = "0x" + "cd" * 20
    with owner:
        vendor_id = new_vendor(owner)
        old = owner.post(
            PAYEES, json={"vendorId": vendor_id, "label": "Main account", "address": CLEAN}
        ).json()["payee"]
        old_id = uuid.UUID(old["id"])
        store.payees[old_id] = replace(
            store.payees[old_id], status=PayeeStatus.ACTIVE.value, active_from=datetime.now(UTC)
        )

        response = owner.post(
            f"{PAYEES}/{old_id}/replace-address",
            json={"address": replacement, "reason": "Vendor bank account changed"},
        )
        new = response.json()["payee"]
        new_id = uuid.UUID(new["id"])
        verified = owner.post(
            f"{PAYEES}/{new_id}/verify-oob", json={"method": "PHONE", "note": "confirmed"}
        )
        registered = owner.post(f"{PAYEES}/{new_id}/registration-tx")

    assert response.status_code == 201, response.text
    assert new_id != old_id
    assert new["address"] == replacement
    assert new["status"] == "AwaitingOwner"
    assert response.json()["deactivationGovernanceTx"]["purpose"] == "PAYEE_DEACTIVATE"
    assert store.payees[old_id].status == PayeeStatus.ACTIVE.value
    assert verified.status_code == 200
    assert registered.status_code == 201
    assert registered.json()["governanceTx"]["purpose"] == "PAYEE_ADD"
    assert (
        registered.json()["governanceTx"]["decodedCalls"][0]["data"][-40:].lower()
        == replacement[2:]
    )


def test_list_and_get_payee() -> None:
    client, _ = make_client(roles=frozenset({"Auditor"}))
    # Read access for any member: seed through the store directly.
    with client:
        listed = client.get(PAYEES)
        missing = client.get(f"{PAYEES}/{uuid.uuid4()}")
    assert listed.status_code == 200 and listed.json() == {"items": []}
    assert missing.status_code == 404 and missing.json()["code"] == "PAYEE_NOT_FOUND"


def test_payee_openapi_contract_is_fully_typed() -> None:
    client, _ = make_client()
    with client:
        spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    base = "/v1/orgs/{organization_id}/treasuries/{treasury_id}/payees/{payee_id}"
    for suffix, model in (
        ("registration-tx", "PayeeTxResponse"),
        ("deactivation-tx", "PayeeTxResponse"),
        ("replace-address", "ReplacePayeeAddressResponse"),
    ):
        ok = spec["paths"][f"{base}/{suffix}"]["post"]["responses"]["201"]
        assert ok["content"]["application/json"]["schema"]["$ref"].endswith(f"/{model}")
    assert set(schemas["PayeeTxResponse"]["required"]) == {"governanceTx"}
    status = schemas["PayeeStatus"]["enum"]
    assert status == [s.value for s in PayeeStatus]
    assert schemas["ScreeningResult"]["enum"] == ["CLEAR", "HIT", "ERROR"]


def test_screening_hit_payee_is_listed_as_failed_for_the_web() -> None:
    # The web gets 422 SCREENING_HIT from the POST, then relies on the extensions and list.
    client, _ = make_client()
    with client:
        vendor_id = new_vendor(client)
        response = client.post(
            PAYEES, json={"vendorId": vendor_id, "label": "Bad", "address": LISTED}
        )
        items = client.get(PAYEES).json()["items"]
    body = response.json()
    assert response.status_code == 422 and body["code"] == "SCREENING_HIT"
    assert body["payeeId"] == items[0]["id"]
    assert [(i["status"], i["screening"]["result"]) for i in items] == [("ScreeningFailed", "HIT")]


def test_provider_error_payee_is_listed_as_failed_for_the_web() -> None:
    client, _ = make_client(provider=DownProvider())
    with client:
        vendor_id = new_vendor(client)
        response = client.post(
            PAYEES, json={"vendorId": vendor_id, "label": "Main", "address": CLEAN}
        )
        items = client.get(PAYEES).json()["items"]
    body = response.json()
    assert response.status_code == 503 and body["code"] == "DATA_MISSING"
    assert body["payeeId"] == items[0]["id"]
    assert [(i["status"], i["screening"]["result"]) for i in items] == [
        ("ScreeningFailed", "ERROR")
    ]
