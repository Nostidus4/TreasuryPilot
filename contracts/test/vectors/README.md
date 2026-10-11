# PaymentApproval golden vectors

Run `node tools/generate-vectors.cjs` from `contracts/` after `pnpm install --frozen-lockfile`. The independent oracle is pinned ethers 5.4.0. Foundry verifies all three files using the actual module's hash/domain functions, the Solidity struct-hash library, and ECDSA recovery.

The files have `formatVersion: 1`, `domain`, `types`, `message`, `typeHash`, `structHash`, `domainSeparator`, `digest`, `signer`, `signature` and `approverSig`. Amounts are decimal **strings**, including values above JavaScript's safe-integer limit. The 65-byte `signature` is the raw EIP-712 signature. The module input `approverSig` is the ABI-encoded `(address signer, bytes signature)` envelope and also supports ERC-1271.

Python consumers can pass `domain`/`types`/`message` to their typed-data encoder; TypeScript consumers can do the same without coercing amount strings to `Number`. Compare struct hash, domain separator and digest separately before comparing the signer. Domains include chain id and the treasury module clone address, never the factory or implementation address.

Fixture identity `7` is deliberately public, synthetic test data. No fixture key is used for deployment. The single-option, early-option and large-integer samples all use the 13-field ADR-019 schema. Governance exceptions and duplicate grants have no EIP-712 vectors (M04-D3).
