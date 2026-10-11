# Contract static analysis (SC-015 / #82)

Analyzer: `slither-analyzer==0.11.3`. Compiler: Solidity 0.8.28, Foundry v1.8.5. Production sources are analyzed with 100 detectors, including the deployable module, governance base, storage and factory. Dependencies, tests, scripts and deliberately insecure test assets are excluded from the finding report, not from compilation.

Final rerun for this change analyzed 75 contracts and reported 22 findings. The exact-fingerprint gate passed: its one High and two Medium findings match the accepted entries below; it found no untriaged High or Medium findings.

Reproduce from `contracts/`:

```sh
uv tool run --from slither-analyzer==0.11.3 slither . --compile-force-framework foundry \
  --filter-paths 'test|script|src/test-assets' --exclude-dependencies --fail-none --json slither.json
python tools/check_slither.py slither.json
```

`--fail-none` lets the analyzer write its complete report. The following gate fails for **every unreviewed High or Medium finding**, using exact normalized-description fingerprints from `contracts/tools/slither-triage.json`. It never excludes a whole detector. Failed or incomplete analyzer output also fails. CI uploads the full raw report.

## High and Medium triage

| Severity | Detector / site | Status | Reason and evidence |
|---|---|---|---|
| High | `uninitialized-state` / `TreasuryPilotStorage.requestPaid` as seen from the abstract governance base | Accepted | False positive from analyzing an abstract contract independently. The mapping starts false by Solidity semantics; concrete `pay` sets it before the Safe interaction. The governance base is not deployable. Successful payment, replay and cancellation tests plus I5/I11 exercise the actual writer. |
| Medium | `incorrect-equality` / `payeeStatus` | Accepted | Zero means never registered. This is an explicit sentinel, not a balance or wall-clock equality. Cooling is at least one second; boundary and reactivation tests cover each state. |
| Medium | `uninitialized-local` / `pay.usedException` | Fixed | Explicit initialization to false removes ambiguity. Exception matching, consumption and rollback tests pass. |
| Medium | `uninitialized-local` / `remainingToday.cap` | Fixed | Explicit initialization to zero preserves zero availability for unknown actions and removes the warning. |
| Medium | `unused-return` / `_healthFactor` | Accepted | The fixed Aave Pool returns six values; only the health factor is required by this guard. Borrow checks before and after, with a rollback test for a deteriorated result. |

## Other findings

Low `timestamp` findings are accepted: mandate validity, expiry, cooling and payment-option boundaries intentionally use chain time. The inclusive/exclusive boundaries are tested. Low `reentrancy-events` on the factory is accepted: there is no mutable factory configuration; initialization is guarded and its wallet/pool/token inspections are STATICCALLs. A failed initializer atomically rolls back the clone and event. Clone isolation and initialization-protection tests cover this flow.

Informational assembly findings are bounded calldata decoding and ERC20 return-word inspection with length checks. Aave's uppercase `POOL`/`UNDERLYING_ASSET_ADDRESS` names match its upstream ABI. Abstract unimplemented-function and constable-state reports concern the nondeployable base; concrete implementations write those fields. Different upstream pragmas all resolve to the single pinned compiler. Initialization complexity reflects explicit configuration validation.

This report is static-analysis evidence, not an external audit. The known architectural risks in ADR-019 still apply, including off-chain dynamic payment reserves and changing future lending rates.
