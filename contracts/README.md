# TreasuryPilot contracts

Foundry workspace for the on-chain enforcement layer. The foundation pins:

- Foundry `v1.8.5` (`.foundry-version`)
- Solidity `0.8.28` (`foundry.toml`)
- Safe smart account contracts `1.4.1` ([commit `bf943f8`](https://github.com/safe-global/safe-smart-account/commit/bf943f80fec5ac647159d26161446ac5d716a294))
- OpenZeppelin Contracts `5.2.0` ([commit `acd4ff7`](https://github.com/OpenZeppelin/openzeppelin-contracts/commit/acd4ff74de833399287ed6b31b4debf6b2b35527))

Solidity dependencies are resolved through the pnpm workspace so the exact tarballs and integrity hashes are recorded in the root `pnpm-lock.yaml`.

```bash
corepack pnpm@9.15.9 install --frozen-lockfile
cd contracts
forge build
forge test
```

`TestUSDC` is explicitly labelled as a test asset, uses six decimals and has unrestricted minting for local tests only. Do not deploy it as a real asset.
