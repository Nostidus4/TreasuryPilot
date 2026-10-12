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

Install the Python workspace with `uv sync --frozen`. On Windows, install Foundry
and run `./infra/scripts/deploy-local.ps1`. Its fixed
Anvil keys are public development identities and must never be funded or reused
on a public network. On other hosts, `make deploy-local` starts its own Anvil.
For an existing Anvil on port 8545, set the five `DEMO_*` addresses to development
accounts and run:

```sh
cd contracts
FOUNDRY_PROFILE=deploy forge script script/Deploy.s.sol:Deploy \
  --rpc-url http://127.0.0.1:8545 --private-key "$ANVIL_PRIVATE_KEY" --broadcast
../.venv/bin/python ../infra/scripts/publish_manifest.py \
  --prediction ../deployments/predictions/31337.json \
  --manifest ../deployments/31337.json --rpc-url http://127.0.0.1:8545
```

The Sepolia branch uses the committed USDC, Aave V3 pool and EAS addresses. It
deploys tUSDC as a separately labelled test asset; the module is configured to
the actual Sepolia USDC reserve. CREATE2 uses the canonical `0x4e59…` deployer
with versioned salts. The Sepolia manifest has null implementation/Safe fields
until the deployment is broadcast and its RPC state verified. Dry runs never
write the published manifest. After a successful Sepolia deployment, run the
publisher with prediction `deployments/predictions/11155111.json` and manifest
`deployments/11155111.json`, using the same RPC.

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
block. Confirmation depth is an additional check; `--confirmations 0` does not
disable finality. Anvil requires the canonical receipt match without consensus
finality. RPC finality failures stop submission so the caller can retry later.

### Pinned Aave fork

`FOUNDRY_PROFILE=fork forge test` uses Sepolia block 11,890,000 and verifies the
reserve-to-aToken mapping before running D2/D3 and borrow/repay cases. It uses the
actual Aave LINK reserve because the USDC and DAI supply caps were already full
at this pinned state; the LINK reserve has no supply cap. Only test Safe balances
are placed in the token storage for the fork. The pool, aToken, reserve accounting
and interest model all execute their real deployed bytecode.
