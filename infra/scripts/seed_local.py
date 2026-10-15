"""Seed the local demo dataset after `deploy-local` (DEV-006).

Everything is keyed by deterministic UUIDs and upserted by id, so running twice leaves one
dataset; chain-linked columns (module/Safe/asset addresses) follow the latest deployment
manifest, because Deploy.s.sol uses `new Safe()` and addresses change per deploy. The mandate is
immutable (DB trigger), so its expiry is not refreshed. All seeded names and the tUSDC asset
carry a TEST label.
shortcut: rows are written with SQL, not the HTTP API (it needs SIWE + MFA step-up sessions),
upgrade when a service-account API client exists.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from eth_utils import keccak
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from treasurypilot_api.treasury.config import PlatformConfiguration
from treasurypilot_api.treasury.sync import asset_id, sync_platform_configuration

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAIN_ID = 31337
NS = uuid.UUID("5eed0000-0000-4000-8000-000000000053")
# Anvil accounts 0-9 (public test mnemonic): owner, executor, approver, guardian, payee, ...
ANVIL = [
    "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
    "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
    "0x976EA74026E726554dB657fA54763abd0C3a0aa9",
    "0x14dC79964da2C08b23698B3D3cc7Ca32193d9955",
    "0x23618e81E3f5cdF7f54C3d65f7FBc0aBf5B21E8f",
]
USERS = {  # email -> (display name, roles)
    "owner@seed.treasurypilot.test": ("Olivia Owner (TEST)", ["Owner", "OrgAdmin"]),
    "approver@seed.treasurypilot.test": ("Aaron Approver (TEST)", ["Approver"]),
    "finance@seed.treasurypilot.test": ("Fiona Finance (TEST)", ["Finance", "Operator"]),
    "auditor@seed.treasurypilot.test": ("Arlo Auditor (TEST)", ["Auditor"]),
}
BASE_UNITS = 10**6  # tUSDC has 6 decimals


def sid(name: str) -> uuid.UUID:
    return uuid.uuid5(NS, name)


def b(address: str) -> bytes:
    return bytes.fromhex(address.removeprefix("0x"))


def rpc(url: str, method: str, params: list[object]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(f"{method} failed: {payload['error']}")
    return payload["result"]


def is_deployed(manifest_path: Path, rpc_url: str) -> bool:
    """True when the manifest exists and its module still has code (Anvil not restarted)."""
    try:
        module = json.loads(manifest_path.read_text())["module"]
        return rpc(rpc_url, "eth_getCode", [module, "latest"]) not in ("0x", "")
    except (OSError, KeyError, ValueError, RuntimeError):
        return False


def write_platform_config(
    manifest: dict[str, Any], rpc_url: str, out_dir: Path, serve_rpc_url: str
) -> None:
    """Write the API's chain config + deployment manifest for the local Anvil chain."""

    def deployment(field: str, version: str) -> dict[str, str]:
        code = bytes.fromhex(rpc(rpc_url, "eth_getCode", [manifest[field], "latest"])[2:])
        if not code:
            raise RuntimeError(f"{field} has no code on {rpc_url}; run `make deploy-local` first")
        return {
            "address": manifest[field],
            "codeHash": "0x" + keccak(code).hex(),
            "version": version,
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    chains = {
        "chains": [
            {
                "chainId": CHAIN_ID,
                "name": "Local Anvil (TEST)",
                "isTestnet": True,
                "confirmations": 0,
                "explorerUrl": "http://localhost:8545",
                # shortcut: one node listed twice (the trailing slash only makes the failover URLs
                # distinct), upgrade with a 2nd node.
                "rpcUrls": [serve_rpc_url, serve_rpc_url + "/"],
                "assets": [
                    {
                        "address": manifest["testToken"],
                        "symbol": "tUSDC",
                        "decimals": 6,
                        "issuerLabel": "TEST token (local Anvil)",
                        "isTest": True,
                    }
                ],
            }
        ]
    }
    deployments = {
        "chainId": CHAIN_ID,
        "deployments": {
            "SAFE_SINGLETON_L1": deployment("safeSingleton", "1.4.1"),
            "SAFE_PROXY_FACTORY": deployment("safeProxyFactory", "1.4.1"),
            "SAFE_MULTISEND_CALL_ONLY": deployment("multiSend", "1.4.1"),
            "TREASURY_MODULE_IMPLEMENTATION": deployment("implementation", "1.0.0"),
            "TREASURY_MODULE_FACTORY": deployment("factory", "1.0.0"),
            # shortcut: Deploy.s.sol sets no fallback handler; the Safe singleton stands in so the
            # seeded snapshots can be COMPLETE. A live coverage refresh will report PARTIAL.
            "SAFE_FALLBACK_HANDLER": deployment("safeSingleton", "1.4.1"),
        },
    }
    (out_dir / "chains.json").write_text(json.dumps(chains, indent=2) + "\n")
    (out_dir / f"{CHAIN_ID}.json").write_text(json.dumps(deployments, indent=2) + "\n")


async def _run(c: AsyncConnection, sql: str, **params: object) -> None:
    await c.execute(text(sql), params)


async def seed_database(
    c: AsyncConnection, manifest: dict[str, Any], now: datetime
) -> dict[str, str]:
    """Insert the demo dataset; safe to call repeatedly. Returns magic-link tokens by email."""
    org, treasury = sid("org"), sid("treasury")
    owner_user = sid("user:owner@seed.treasurypilot.test")
    token = asset_id(CHAIN_ID, manifest["testToken"])
    expires = datetime.fromtimestamp(int(manifest["mandateExpiresAt"]), UTC)
    valid_from = expires - timedelta(days=30)
    executor, approver, guardian, payee_addr = ANVIL[1], ANVIL[2], ANVIL[3], ANVIL[4]
    sentinel = ANVIL[6]

    for email, (name, _roles) in USERS.items():
        uid = sid(f"user:{email}")
        await _run(
            c,
            "INSERT INTO users (id, email, display_name) VALUES (:id, :email, :name) "
            "ON CONFLICT DO NOTHING",
            id=uid, email=email, name=name,
        )  # fmt: skip
    await _run(
        c,
        "INSERT INTO organizations (id, name, legal_name, country, created_by) "
        "VALUES (:id, 'TreasuryPilot Demo (TEST)', 'Demo Treasury Ltd (TEST)', 'GB', :u) "
        "ON CONFLICT DO NOTHING",
        id=org, u=owner_user,
    )  # fmt: skip
    for email, (_, roles) in USERS.items():
        await _run(
            c,
            "INSERT INTO memberships (id, org_id, user_id, roles, manual_roles, "
            "role_sources_initialized, created_by) "
            "VALUES (:id, :org, :u, :roles, :roles, true, :owner) ON CONFLICT DO NOTHING",
            id=sid(f"member:{email}"), org=org, u=sid(f"user:{email}"), roles=roles, owner=owner_user,
        )  # fmt: skip

    await _run(
        c,
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address, status, coverage, "
        "created_by) VALUES (:id, :org, :chain, :asset, :module, 'Ready', 'COMPLETE', :u) "
        "ON CONFLICT (id) DO UPDATE SET asset_id = EXCLUDED.asset_id, "
        "module_address = EXCLUDED.module_address",
        id=treasury, org=org, chain=CHAIN_ID, asset=token, module=b(manifest["module"]), u=owner_user,
    )  # fmt: skip
    wallets = (
        ("safeT", "SOURCE", "T - Source Safe (TEST)"),
        ("safeO1", "OPERATIONAL", "O1 - Operational Safe (TEST)"),
        ("safeO2", "OPERATIONAL", "O2 - Operational Safe (TEST)"),
    )
    wallet_ids = {}
    for field, role, label in wallets:
        wallet_ids[field] = sid(f"wallet:{field}")
        await _run(
            c,
            "INSERT INTO treasury_wallets (id, org_id, treasury_id, chain_id, role, label, "
            "safe_address, owners, threshold, created_by) "
            "VALUES (:id, :org, :t, :chain, :role, :label, :addr, CAST(:owners AS jsonb), 1, :u) "
            "ON CONFLICT (id) DO UPDATE SET safe_address = EXCLUDED.safe_address, "
            "owners = EXCLUDED.owners",
            id=wallet_ids[field], org=org, t=treasury, chain=CHAIN_ID, role=role, label=label,
            addr=b(manifest[field]), owners=json.dumps([manifest["demoOwner"]]), u=owner_user,
        )  # fmt: skip

    def units(amount: int) -> str:
        return str(amount * BASE_UNITS)

    def wallet(field: str) -> str:
        return str(manifest[field]).lower()

    # MandateConfig shape (the API rejects unknown keys); values mirror Deploy.s.sol `_setup`.
    has_pool = int(manifest.get("aavePool") or "0x0", 16) != 0
    config = {
        "validFrom": int(valid_from.timestamp()),
        "expiresAt": int(expires.timestamp()),
        "payeeCoolingSeconds": 300,
        "executor": executor,
        "guardian": guardian,
        "limits": {
            "PAY": {"perRequest": units(2000), "daily": units(10000)},
            "REFILL": {"perRequest": units(2500), "daily": units(12000)},
        },
        "supplyLimits": {
            "perRequest": units(5000) if has_pool else "0",
            "daily": units(20000) if has_pool else "0",
        },
        "buffers": [
            {"wallet": wallet("safeT"), "minimum": units(1000)},
            {"wallet": wallet("safeO1"), "minimum": units(10), "target": units(150)},
            {"wallet": wallet("safeO2"), "minimum": units(10), "target": units(150)},
        ],
        "approvalMaxAge": 14 * 86400,
        "approvers": [approver],
    }
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    await _run(
        c,
        "INSERT INTO mandate_versions (id, org_id, treasury_id, version, onchain_version, status, "
        "config, config_hash, valid_from, expires_at, created_by, activated_at) "
        "VALUES (:id, :org, :t, 1, 1, 'Active', CAST(:config AS jsonb), :hash, :vf, :exp, :u, :vf) "
        "ON CONFLICT DO NOTHING",  # a DB trigger makes mandate config immutable, so no refresh
        id=sid("mandate:1"), org=org, t=treasury, config=json.dumps(config),
        hash=hashlib.sha256(canonical.encode()).digest(), vf=valid_from, exp=expires, u=owner_user,
    )  # fmt: skip
    # shortcut: Deploy.s.sol makes the module guardian an EOA (Anvil #3), not a Guardian Safe, so
    # that "EOA stand-in" fills guardian_safe until a real Guardian Safe is deployed.
    await _run(
        c,
        "INSERT INTO guardian_setups (id, org_id, treasury_id, guardian_safe, human_owners, "
        "sentinel_address, status, created_by) "
        "VALUES (:id, :org, :t, :g, :humans, :s, 'Active', :u) "
        "ON CONFLICT (id) DO UPDATE SET human_owners = EXCLUDED.human_owners",
        id=sid("guardian"), org=org, t=treasury, g=b(guardian), humans=[b(manifest["demoOwner"])],
        s=b(sentinel), u=owner_user,
    )  # fmt: skip
    await _run(
        c,
        "INSERT INTO treasury_fee_policies (id, org_id, treasury_id, preset, max_fee_multiplier_bps, "
        "tip_percentile, resend_after_s, bump_bps, per_plan_threshold_wei, daily_budget_wei, "
        "reference_eth_price, accepted_by, accepted_at, version, created_by) "
        "VALUES (:id, :org, :t, 'NORMAL', 20000, 50, 120, 1250, 10000000000000000, "
        "100000000000000000, 3000, :u, :now, 1, :u) ON CONFLICT DO NOTHING",
        id=sid("fee-policy"), org=org, t=treasury, u=owner_user, now=now,
    )  # fmt: skip

    for field in wallet_ids:  # fresh COMPLETE snapshot per Safe (valid for 12 min, see service.py)
        await _run(
            c,
            "INSERT INTO safe_config_snapshots (id, org_id, wallet_id, block_number, block_hash, "
            "owners, threshold, modules, guard, fallback_handler, module_implementations, "
            "observed_at) VALUES (:id, :org, :w, 1, :bh, CAST(:owners AS jsonb), 1, :mods, NULL, "
            ":fh, CAST(:impls AS jsonb), :now) "
            "ON CONFLICT (id) DO UPDATE SET modules = EXCLUDED.modules, "
            "fallback_handler = EXCLUDED.fallback_handler, "
            "module_implementations = EXCLUDED.module_implementations, "
            "observed_at = EXCLUDED.observed_at",
            id=sid(f"snapshot:{field}"), org=org, w=wallet_ids[field],
            bh=hashlib.sha256(field.encode()).digest(), owners=json.dumps([manifest["demoOwner"]]),
            mods=[b(manifest["module"])], fh=b(manifest["safeSingleton"]), now=now,
            impls=json.dumps({manifest["module"].lower(): manifest["implementation"].lower()}),
        )  # fmt: skip

    payees = (  # (key, vendor, address, status, active_from)
        ("acme", "Acme Supplies (TEST)", payee_addr, "Active", now - timedelta(days=1)),
        ("globex", "Globex Services (TEST)", ANVIL[5], "Active", now - timedelta(days=1)),
        # Still cooling: the 24h window keeps the demo state stable between reruns.
        ("initech", "Initech Consulting (TEST)", ANVIL[7], "Cooling", now + timedelta(days=1)),
    )
    payee_ids = {}
    for key, vendor_name, address, status, active_from in payees:
        vendor, payee = sid(f"vendor:{key}"), sid(f"payee:{key}")
        payee_ids[key] = (vendor, payee)
        await _run(
            c,
            "INSERT INTO vendors (id, org_id, name, normalized_ref, country, created_by) "
            "VALUES (:id, :org, :name, :ref, 'GB', :u) ON CONFLICT DO NOTHING",
            id=vendor, org=org, name=vendor_name, ref=key, u=owner_user,
        )  # fmt: skip
        await _run(
            c,
            "INSERT INTO payees (id, org_id, treasury_id, vendor_id, label, address, status, "
            "active_from, oob_verified_by, oob_verified_at, oob_method, oob_note, created_by) "
            "VALUES (:id, :org, :t, :v, :label, :addr, :status, :af, :u, :ova, 'OTHER', "
            "'Seeded TEST payee', :u) ON CONFLICT DO NOTHING",
            id=payee, org=org, t=treasury, v=vendor, label=f"{vendor_name} main", addr=b(address),
            status=status, af=active_from, u=owner_user, ova=now - timedelta(days=1),
        )  # fmt: skip

    invoices = (  # (no, payee, status, amount tUSDC, wallet)
        ("INV-TEST-001", "acme", "Draft", 120, "safeO1"),
        ("INV-TEST-002", "acme", "AwaitingApproval", 450, "safeO1"),
        ("INV-TEST-003", "globex", "Approved", 800, "safeO2"),
        ("INV-TEST-004", "globex", "Paid", 250, "safeO2"),
        ("INV-TEST-005", "initech", "Rejected", 90, "safeO1"),
    )
    for number, (invoice_no, key, status, amount, wallet_key) in enumerate(invoices, start=1):
        request = sid(f"request:{invoice_no}")
        vendor, payee = payee_ids[key]
        issued = (now - timedelta(days=10 - number)).date()
        fingerprint = (
            None
            if status in ("Draft", "Rejected")
            else hashlib.sha256(invoice_no.encode()).digest()
        )
        await _run(
            c,
            "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
            "invoice_no, issue_date, due_at, amount, asset_id, paying_wallet_id, fingerprint, "
            "status, created_by, last_edited_by, note, tags) "
            "VALUES (:id, :org, :t, :chain, :v, :p, :no, :issued, :due, :amount, :asset, :w, :fp, "
            ":status, :u, :u, 'Seeded TEST invoice', ARRAY['TEST']) "
            "ON CONFLICT (id) DO UPDATE SET asset_id = EXCLUDED.asset_id",
            id=request, org=org, t=treasury, chain=CHAIN_ID, v=vendor, p=payee, no=invoice_no,
            issued=issued, due=issued + timedelta(days=30), amount=amount * BASE_UNITS, asset=token,
            w=wallet_ids[wallet_key], fp=fingerprint, status=status, u=owner_user,
        )  # fmt: skip
        snapshot = {"invoiceNo": invoice_no, "amount": str(amount * BASE_UNITS), "test": True}
        await _run(
            c,
            "INSERT INTO request_revisions (id, request_id, revision, snapshot, edited_by) "
            "VALUES (:id, :r, 1, CAST(:s AS jsonb), :u) ON CONFLICT DO NOTHING",
            id=sid(f"revision:{invoice_no}"), r=request, s=json.dumps(snapshot), u=owner_user,
        )  # fmt: skip
        await _run(
            c,
            'INSERT INTO request_status_events (id, request_id, "to", actor_type, actor_id, reason) '
            "VALUES (:id, :r, :to, 'USER', :u, 'Seeded TEST data') ON CONFLICT DO NOTHING",
            id=sid(f"event:{invoice_no}"), r=request, to=status, u=owner_user,
        )  # fmt: skip

    # Fresh login links on every run; older unused ones are retired (like replace_magic_link).
    tokens: dict[str, str] = {}
    for email in USERS:
        await _run(
            c,
            "UPDATE magic_links SET used_at = :now WHERE email = :email AND used_at IS NULL",
            now=now, email=email,
        )  # fmt: skip
        tokens[email] = secrets.token_urlsafe(32)
        await _run(
            c,
            "INSERT INTO magic_links (id, email, token_hash, created_at, expires_at) "
            "VALUES (:id, :email, :hash, :now, :exp)",
            id=uuid.uuid4(), email=email, hash=hashlib.sha256(tokens[email].encode()).digest(),
            now=now, exp=now + timedelta(hours=12),
        )  # fmt: skip
    return tokens


def database_url() -> str:
    if url := os.environ.get("DATABASE_URL"):
        return url.replace("@postgres:", "@127.0.0.1:")
    user, password, db = (
        os.environ[k] for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    )
    return f"postgresql+asyncpg://{quote(user)}:{quote(password)}@127.0.0.1:5432/{db}"


async def main_async(args: argparse.Namespace) -> None:
    manifest = json.loads(Path(args.manifest).read_text())
    config_dir = Path(args.config_dir)
    # The sync below reads decimals() from this host, so it needs host-reachable RPC URLs; the
    # file is rewritten afterwards with the container-reachable ones the API will load.
    write_platform_config(manifest, args.rpc_url, config_dir, args.rpc_url)
    configuration = PlatformConfiguration.load(config_dir / "chains.json", config_dir)
    now = datetime.now(UTC)
    engine = create_async_engine(database_url())
    try:
        # sync_platform_configuration commits itself, so it cannot run inside session.begin().
        async with AsyncSession(engine) as session:
            await sync_platform_configuration(session, configuration)
        async with engine.begin() as connection:
            tokens = await seed_database(connection, manifest, now)
        write_platform_config(manifest, args.rpc_url, config_dir, args.api_rpc_url)
    finally:
        await engine.dispose()
    print("Seeded TEST dataset (safe to re-run). Addresses:")
    for field in ("safeT", "safeO1", "safeO2", "module", "testToken"):
        print(f"  {field:9} {manifest[field]}")
    print(f"  guardian  {ANVIL[3]} (EOA stand-in, not a Safe; sentinel {ANVIL[6]})")
    print("Login links (valid 12h):")
    for email, token in tokens.items():
        print(f"  {email}: {args.web_url}?{urlencode({'token': token})}")
    print(
        "Safe snapshots are fresh for 12 minutes; re-run `make seed` to refresh coverage.\n"
        f"Host API: TP_PLATFORM_CHAIN_CONFIG_PATH={config_dir}/chains.json "
        f"TP_DEPLOYMENTS_DIR={config_dir} (and --api-rpc-url http://127.0.0.1:8545)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(REPO_ROOT / "deployments" / "31337.json"))
    parser.add_argument("--rpc-url", default="http://127.0.0.1:8545")
    parser.add_argument("--api-rpc-url", default="http://anvil:8545", help="as seen by the API")
    parser.add_argument(
        "--check-deployed", action="store_true", help="exit 0 if the manifest is live on the RPC"
    )
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "deployments" / "local"))
    parser.add_argument("--web-url", default="http://localhost:5173/auth/verify")
    args = parser.parse_args()
    if args.check_deployed:
        raise SystemExit(0 if is_deployed(Path(args.manifest), args.rpc_url) else 1)
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
