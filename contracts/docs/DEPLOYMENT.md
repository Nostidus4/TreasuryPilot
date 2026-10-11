# Local and Sepolia deployments

The local path deploys the module implementation, immutable factory and test
token at versioned CREATE2 addresses, then makes Safe T/O1/O2, one module clone,
the fixed Safe MultiSend bytecode, and a clearly labelled local EAS double. All
three Safes have a 1-of-1 demo owner. Safe T creates its module and enables it in
the same owner-authorized MultiSend transaction; O1 and O2 enable that clone in
their own owner transactions. The script checks those module flags and writes
`deployments/31337.json` with all addresses and runtime code hashes.

On Windows, install Foundry and run `./infra/scripts/deploy-local.ps1`. Its fixed
Anvil keys are public development identities and must never be funded or reused
on a public network. On other hosts, start Anvil at port 8545, set the five
`DEMO_*` addresses to development accounts and run `make deploy-local`, or run:

```sh
cd contracts
FOUNDRY_PROFILE=deploy forge script script/Deploy.s.sol:Deploy \
  --rpc-url http://127.0.0.1:8545 --private-key "$ANVIL_PRIVATE_KEY" --broadcast
```

The Sepolia branch uses the committed USDC, Aave V3 pool and EAS addresses. It
deploys tUSDC as a separately labelled test asset; the module is configured to
the actual Sepolia USDC reserve. CREATE2 uses the canonical `0x4e59…` deployer
with versioned salts. The Sepolia manifest has null implementation/Safe fields
until the deployment is actually broadcast. `RegisterReceiptSchema.s.sol` is
idempotent and writes the schema UID into that manifest.

Do not use local mock EAS addresses as production addresses. Verify public-network
contracts after deployment using the published compiler settings and verify the
receipt from its actual successful `PaymentExecuted` transaction before calling
the Python attestation helper. A payment finality delay is required by ADR-018.

### Pinned Aave fork

`FOUNDRY_PROFILE=fork forge test` uses Sepolia block 11,890,000 and verifies the
reserve-to-aToken mapping before running D2/D3 and borrow/repay cases. It uses the
actual Aave LINK reserve because the USDC and DAI supply caps were already full
at this pinned state; the LINK reserve has no supply cap. Only test Safe balances
are placed in the token storage for the fork. The pool, aToken, reserve accounting
and interest model all execute their real deployed bytecode.
