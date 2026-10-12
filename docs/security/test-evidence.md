# Contract security evidence

Scope: real Safe 1.4.1 proxies, module clones and synthetic assets. Backend recovery,
quote validation and invoice extraction are owned by other modules; these tests
only claim their on-chain boundaries. Foundry v1.8.5, solc 0.8.28, optimizer 200.

## Local campaign (2026-10-12)

`FOUNDRY_PROFILE=ci forge test -v` passed 71 tests, including all 14 invariants:
10,000 runs, depth 32, 320,000 handler calls, zero unexpected reverts.
Fuzz tests also ran 10,000 cases. The handler checks authority, current approval,
payee cooling, budgets, floors, replay, exception scope, status, persistent counters,
refill bound, cancellation, fixed-pool deltas, zero allowance and exact discount.
It first executes successful PAY and REFILL, so those checks are not vacuous.
`FOUNDRY_PROFILE=fork forge test` passed four tests against the Sepolia Aave V3
reserve at pinned block 11,890,000. Supply, accrual, withdrawal, refill, payment,
borrow and repayment use the deployed pool/token/aToken contracts; only fixture
Safe balances are inserted with Foundry storage cheatcodes. Two repeated fork
runs produced the same passing cases and gas usage. LINK was selected because its
reserve has no supply cap at the pinned block.

The local deployment script was exercised on fresh Anvil chains. Repeating the
deployment produced identical CREATE2 addresses, code hashes, module clones and
Safe addresses. A second deployment and dry run on the same Anvil chain also
passed with the same factory and independent Safe/module identities. Script
predictions are isolated from published manifests; publication rejects unmined
code and verifies actual runtime hashes, identity and enablement before writing.
Schema registration tests preserve the published manifest and write a scalar UID.
The Sepolia script was simulated twice without `--broadcast`; it
produced the same predicted deployment addresses. No live Sepolia transaction
was sent.

The updated Python campaign passed 52 tests (core coverage 93%), including
attestation refusal before finality, canonical-block mismatch, unavailable
finality, schema ABI mismatches and failed manifest publication. It handles the
versioned JSON block envelope returned by Foundry v1.8.5. A separate local PAY
and EAS submission through a development keystore succeeded against the deployed
module/Safes and local EAS double; the stored 256 bytes matched all eight receipt
fields and the actual payment transaction. This is local ABI/CLI evidence; it is
not a public EASScan receipt.

Mutation experiment: replacing the inclusive early-payment predicate with
`bool early = false` caused I14 to fail after 39 runs / 1,219 calls. Foundry shrank
the sequence to `pay(1667625102)`, seed
`0x40462ea8f428947d290ab90b6b352e077e34020d9fb69a0d56e3082019aab7f7`.
The mutation was restored before the successful 10,000-run campaign.

## Source acceptance mapping

| Source case | Contract evidence |
| --- | --- |
| AT-01 | Payment with replay evidence |
| AT-02 | Refill shortage, then exact payment |
| AT-05 | Signature mutations, unknown/cooling payees, caps and floors |
| AT-06 | Retry rejects paid request and used fingerprint; flags provide chain evidence |
| AT-07 | Completed refill survives pause; retry cannot refill twice; payment resumes |
| AT-08 | Pause/revoke, mandate and approval expiry in governance/payment tests |
| AT-10 | Two pre-signed payments compete; second rechecks current cash floor |
| AT-11 | Exact exception, used once; wrong version, daily cap and floor remain enforced |
| AT-12 | Only minimum shortage refilled while treasury reserve holds; target remains unmet |
| AT-04/13 | Optional labelled ERC20 test router, minimum output, execution-day budgets, zero allowance |

AT-03 native-gas bootstrapping, AT-09 invoice parsing and backend retry/reporting
are not implemented by the contract suite. Static-analysis findings and exact
triage are recorded in [static-analysis.md](static-analysis.md). CI publishes the
raw Slither artifact and reruns the independent ethers vectors and invariant campaign.
