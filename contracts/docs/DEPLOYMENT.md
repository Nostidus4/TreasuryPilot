# Local and Sepolia deployments

The local path deploys the module implementation, immutable factory and test
token at versioned CREATE2 addresses, then makes Safe T/O1/O2, one module clone,
the fixed Safe MultiSend bytecode, and a clearly labelled local EAS double. Module
CREATE2 salts are scoped to Safe T, so prior factory activity cannot change a
predicted clone address. All
three Safes have a 1-of-1 demo owner. Safe T creates its module and enables it in
the same owner-authorized MultiSend transaction; O1 and O2 enable that clone in
their own owner transactions. The Forge script writes only
`deployments/predictions/31337.json`. The Python publisher checks the actual mined
runtime hashes, module identity, owners, enablement, asset decimals and EAS schema
at one RPC block before atomically publishing `deployments/31337.json`.

The Anvil deployment uses tUSDC and disables Aave (`aavePool = 0`, supply limits
zero). Lending unit tests create their own MockAavePool; pinned fork tests use
the real pool. The Sepolia profile retains Aave's test USDC per ADR-019.

Install the Python workspace with `uv sync --frozen`. On Windows, install Foundry
and run `./infra/scripts/deploy-local.ps1`. Its fixed
Anvil keys are public development identities and must never be funded or reused
on a public network. On other hosts, `make deploy-local` starts its own Anvil.
For an existing Anvil on port 8545, set `DEMO_OWNER`, `DEMO_EXECUTOR`,
`DEMO_APPROVER`, `DEMO_GUARDIAN`, `DEMO_PAYEE` and `DEMO_RECEIPT_ATTESTER` to
development accounts and run:

```sh
cd contracts
FOUNDRY_PROFILE=deploy forge script script/Deploy.s.sol:Deploy \
  --rpc-url http://127.0.0.1:8545 --private-key "$ANVIL_PRIVATE_KEY" --broadcast
../.venv/bin/python ../infra/scripts/publish_manifest.py \
  --prediction ../deployments/predictions/31337.json \
  --manifest ../deployments/31337.json --rpc-url http://127.0.0.1:8545
```

The broadcast signer must equal `DEMO_OWNER`: the Safe approved-hash signature
depends on that sender. A mismatch fails before creating any contracts. The
receipt attester must be nonzero and distinct from the owner, executor, approver
and guardian. It is recorded as `easAttester`; the committed Sepolia value stays
null until a real dedicated receipt identity is configured.

The Sepolia branch uses the committed USDC, Aave V3 pool and EAS addresses. It
deploys tUSDC as a separately labelled test asset; the module is configured to
the actual Sepolia USDC reserve. CREATE2 uses the canonical `0x4e59…` deployer
with versioned salts. The Sepolia manifest has null implementation/Safe fields
until the deployment is broadcast and its RPC state verified. Dry runs never
write the published manifest. After a successful Sepolia deployment, run the
publisher with prediction `deployments/predictions/11155111.json` and manifest
`deployments/11155111.json`, using the same RPC.

After publication, verify the project-owned Sepolia implementation, factory and
tUSDC source on Etherscan with `make verify-sepolia`. Set `SEPOLIA_RPC_URL` (or
`ETH_RPC_URL`) and `ETHERSCAN_API_KEY` first. The command requires a `deployed`
manifest, confirms the RPC chain and all three runtime code hashes, and verifies
the factory with its mined implementation constructor argument. Canonical Safe
contracts are already published separately; the module address is an EIP-1167
clone and is validated against the implementation by the publisher rather than
submitted as standalone Solidity source.

Sepolia uses these canonical Safe 1.4.1 deployments, pinned in
[safe-deployments](https://github.com/safe-global/safe-deployments/tree/7b1fb6d615ab2d2999550ec9166554b180e813e5/src/assets/v1.4.1):

| Contract | Sepolia address |
| --- | --- |
| Safe singleton | `0x41675C099F32341bf84BFc5382aF534df5C7461a` |
| SafeProxyFactory | `0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67` |
| MultiSend | `0x38869bf66a61cF6bDB996A6aE40D5853Fd43B526` |

The script verifies their published runtime hashes. The publisher checks each
proxy's `masterCopy` as well as owner, threshold and module enablement. Canonical
factory salts 1/2 and the owner initializer determine T/O1 on Sepolia. Anvil uses
salt 3 for O2 as a multi-wallet fixture. Repeated Sepolia
runs reuse those Safes and the existing module without resetting governance,
counters or payee cooling. Changing the owner creates another set of Safes.
The manifest records `operationalWalletCount`: 1 on Sepolia, 2 on Anvil. Sepolia
records the unused `safeO2` as the zero address after verified publication.
The publisher compares the complete operational list, reviewed decimals and
count, and any previously pinned aToken before changing the manifest.
Locally deployed singleton/factory/MultiSend copies are used only on Anvil. The
canonical Sepolia bytecode supports recognition by Safe tooling; opening the
deployed Safes in SafeWallet remains a public deployment acceptance check.

Publication also compares the predicted asset, pool, EAS, registry and canonical
Safe infrastructure with the reviewed Sepolia manifest before changing it.
Configure the dedicated `easAttester` in that manifest before public deployment
to pin the expected signer. If already configured, publication rejects a different
attester. The demo mandate expires 30 days after initialization; its actual
`mandateExpiresAt` is recorded. Rerunning deployment does not renew it. The Safe T
owner must renew it through `configureMandate` (including the configured limits
and roles) before the expiry if the demo needs to continue.

`RegisterReceiptSchema.s.sol` is idempotent and writes the scalar UID to
`deployments/predictions/11155111.schema.json`. After its broadcast, use
`publish_manifest.py --schema-only` with that prediction and the existing Sepolia
manifest. This checks the exact registered schema and preserves deployment
addresses, metadata and status. Both publication modes fail without changing the
manifest if the RPC configuration or mined state does not match.

Do not use local mock EAS addresses as production addresses. Verify public-network
contracts after deployment using the published compiler settings and verify the
receipt from its actual successful `PaymentExecuted` transaction before calling
the Python attestation helper. On Sepolia, ADR-018 requires the PAY block at or
below the RPC's `finalized` tag and its receipt block hash to match the canonical
block. Extra confirmation depth defaults to zero; `--confirmations 0` does not
disable finality. Anvil requires the canonical receipt match without consensus
finality. RPC finality failures stop submission so the caller can retry later.

The product's `Paid` state after three confirmations is an earlier workflow
milestone. It does not authorize an EAS receipt before Sepolia finality. This
helper deliberately enforces that later ADR-018 requirement.

### Trusted receipts and retries

EAS accepts attestations from anyone for this public schema. Consumers must read
`getAttestation(uid)` and require `attester == manifest.easAttester`, the expected
schema, recipient, nonrevocable/unexpired record and exact payload. A schema match
alone is insufficient. The helper derives the keystore address and refuses to
send if it differs from `easAttester`.

Only `requestId`, payee, amount and the actual successful PAY transaction are
checked against the module and its logs. `invoiceHash`, `approvalHash`, `planHash`
and `policyVersion` are trusted backend assertions; this helper does not prove
those four metadata hashes on chain. EAS preserves the attester's assertion, not
an independent verification of that metadata.

Use `ETH_RPC_URL` for keyed provider URLs. Both Python CLIs accept it; their
`cast` children receive the URL in the environment, not process arguments:

```sh
# Set ETH_RPC_URL through your local environment/secret configuration.
.venv/bin/python infra/scripts/attest_receipt.py \
  --receipt receipt.json --manifest deployments/11155111.json --broadcast \
  --keystore receipt-wallet.json --password-file receipt-password.txt \
  --journal receipts/CHAIN-MODULE-REQUEST.json
```

Keep one persistent journal path for every `(chain, module, requestId)`; create
its parent directory first. The helper locks that path, binds it to the complete
payload and saves submission intent before sending. A confirmed retry verifies
and returns the recorded UID without another transaction. An ambiguous timeout
or interrupted send blocks further submissions. Reconcile the attester's
transaction and its UID, then verify it and recover the same journal with:

```sh
.venv/bin/python infra/scripts/attest_receipt.py \
  --receipt receipt.json --manifest deployments/11155111.json \
  --existing-uid "$RECONCILED_UID" --journal receipts/CHAIN-MODULE-REQUEST.json
```

Recovery does not send and checks the on-chain record against the trusted signer
and complete payload. It cannot replace a different confirmed UID. After a hard
process crash, remove a stale `.lock` only after confirming no worker is active
and reconciling the transaction. Never clear an uncertain journal to retry blindly.
EAS itself permits duplicate attestations, and another journal path bypasses this
local guard. A production worker needs a shared database uniqueness constraint
on `(chain, module, requestId)` and transaction reconciliation; REC-005 remains
separate worker integration work.

### Pinned Aave fork

`FOUNDRY_PROFILE=fork forge test` runs seven cases and verifies the
reserve-to-aToken mapping. Four LINK cases at Sepolia block 11,890,000 cover D2/D3
and borrow/repay without a supply cap. Two six-decimal USDC cases at block
8,000,000 cover real supply/withdraw accounting and withdraw/refill/PAY.
The seventh case at 11,890,000 confirms a USDC cap failure with complete rollback:
the cap is 2,000,000,000 USDC while nominal aToken supply is
4,536,900,878.408670 USDC. The module and committed Sepolia asset remain USDC per
ADR-019; live D2 is expected to fail while this cap is full. Recheck reserve
capacity before a public demo. Historical success is not proof of current headroom.

At both USDC pins `ATOKEN_REVISION()` returns 1 and the EIP-1967 implementation is
[`0x48424f2779be0f03cdf6f02e17a591a9bf7af89f`](https://sepolia.etherscan.io/address/0x48424f2779be0f03cdf6f02e17a591a9bf7af89f#code).
This records the deployed identity rather than inferring a release version from
the revision alone. The supply check accepts a nonzero scaled delta between
`floor(amount * RAY / index)` and half-up `rayDiv(amount, index)`, covering both
rounding modes while requiring an exact underlying debit and zero residual
allowance. A mock with index 1.5 RAY verifies floor and nearest behavior and
rejects values outside that band. Only test Safe balances
are placed in the token storage for the fork. The pool, aToken, reserve accounting
and interest model all execute their real deployed bytecode.

CI caches `~/.foundry/cache/rpc` with the Foundry version, Sepolia chain and both
block pins in the key, then compares two runs. Cached historical state reduces
provider calls; block headers and uncached state can still require network access.
Local deployment fork evidence pins Anvil's hardfork to Cancun to match the
project's EVM profile, so it does not validate later gas schedule changes.
