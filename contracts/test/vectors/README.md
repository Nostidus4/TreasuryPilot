# Approval and policy golden vectors

Run `node tools/generate-vectors.cjs` from `contracts/` after `pnpm install --frozen-lockfile`. The independent oracle is pinned ethers 5.4.0. Foundry verifies all three files using the actual module's hash/domain functions, the Solidity struct-hash library, and ECDSA recovery.

The files have `formatVersion: 1`, `domain`, `types`, `message`, `typeHash`, `structHash`, `domainSeparator`, `digest`, `signer`, `signature` and `approverSig`. Amounts are decimal **strings**, including values above JavaScript's safe-integer limit. The 65-byte `signature` is the raw EIP-712 signature. The module input `approverSig` is the ABI-encoded `(address signer, bytes signature)` envelope and also supports ERC-1271.

Python consumers can pass `domain`/`types`/`message` to their typed-data encoder; TypeScript consumers can do the same without coercing amount strings to `Number`. Compare struct hash, domain separator and digest separately before comparing the signer. Domains include chain id and the treasury module clone address, never the factory or implementation address.

Fixture identity `7` is deliberately public, synthetic test data. No fixture key is used for deployment. The single-option, early-option and large-integer samples all use the 13-field ADR-019 schema. Governance exceptions and duplicate grants have no EIP-712 vectors (M04-D3).

`plan-attestation.json` and `plan-attestation-empty.json` cover signer-side
`PlanAttestation` per M08 section 6.3: the domain name is **TreasuryPilot Policy**,
with the module clone as verifyingContract. The independent ethers oracle and a
test-only Solidity encoder verify `keccak256(abi.encodePacked(stepIds))`, the
empty array, a large decimal-string nonce, hashes and ECDSA recovery. Fixture
identity `8` is public and distinct from the approval signer. Policy signatures
are raw EIP-712 signatures; they do not use the approval `(address,bytes)` envelope.
Empty-array vectors test encoding only; an executable plan still needs policy
validation. `PlanAttestedExecutor` verifies the same encoding on-chain (SC-L04); the Foundry vector test checks its library against these files.

`plan-hash.json` covers M08 sections 8.3 and 8.4: `planHash` is the EIP-712
`hashStruct(Plan)` over `Step[]`, and each `stepId` is
`keccak256(abi.encode("TP_STEP_V1", stepIdSource, uint8(action), stepIdWallet))`.
The `request` plan is WITHDRAW → REFILL → PAY; the `liquidity` plan is one SUPPLY with
`requestId = 0x0` and the liquidity cycle id (built from `liquidityCycle`, M08 §8.4) as
`stepIdSource`. `treasury` is the module clone, the same address as the approval `treasury`. Python checks it in
`packages/py-core/tests/test_plan_hash.py`.
