# Finance review of business rules and demo limits

DOM-008 / #232. Baseline: main `4b2ee5e89763450078767d564a07f73fabfe2d63`,
2026-10-14. Status: **written technical review and proposed company profile;
second-person review and live-demo funding confirmation pending**.
This reviews synthetic token-unit examples and code consistency; it does not
represent interviews, independent professional certification or investment advice.

## 1. Company profile and accepted numbers

Proposed synthetic profile: a 20-person Web3 software company paying recurring
hosting, infrastructure and contractor invoices in one treasury token. The
company and vendors are fictional. Use frequent 100-850 token invoices and one
2,100-token over-cap request to explain routine approval vs exact owner exception.
10,000 in T and 20 in O1 are illustrative scenario balances, not a claim about
funded wallets or a newly agreed production policy.

[OQ-05](../OPEN_QUESTIONS.md) already accepts source YAML limits, scaled to faucet
budget. [Deploy.s.sol](../../contracts/script/Deploy.s.sol) encodes the unscaled
limits, floors, targets, cooling, validity and approval age below; `minSupply` is
an off-chain treasury setting (ADR-019), not set by the script. The Circle evidence
run uses the division by 100 accepted in [ADR-012](../adr/ADR-012-chain-and-stablecoin.md)
(OQ-03/PH-2) and is PAY-only; Aave's test USDC is the Sepolia treasury asset under
ADR-019. They must remain separate asset/configuration identities.

| Parameter                              | Main synthetic demo: tokens / base units                    | Circle PAY-only scale: tokens / base units               |
| -------------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------- |
| PAY per request                        | 2,000 / `2000000000`                                        | 20 / `20000000`                                          |
| PAY daily                              | 10,000 / `10000000000`                                      | 100 / `100000000`                                        |
| REFILL per request                     | 2,500 / `2500000000`                                        | 25 / `25000000`                                          |
| REFILL daily                           | 12,000 / `12000000000`                                      | 120 / `120000000`                                        |
| Safe T hard floor                      | 1,000 / `1000000000`                                        | 10 / `10000000`                                          |
| O1 hard floor                          | 10 / `10000000`                                             | 0.1 / `100000`                                           |
| O1 soft target                         | 150 / `150000000`                                           | 1.5 / `1500000`                                          |
| SUPPLY per call / daily                | 5,000 / 20,000 / `5000000000` / `20000000000`; script sets 0 when no pool | Disabled for Circle PAY-only                             |
| minSupply (off-chain liquidity policy) | 500 / `500000000`                                           | Disabled                                                 |
| Payee cooling                          | 300 seconds in demo; documented production default 24 hours | Same safety semantics; token scaling does not scale time |
| Mandate validity                       | 30 days from initial deployment                             | Same; repeat deploy does not renew it                    |
| Approval max age                       | 14 days (`approvalMaxAge`)                                  | Same                                                     |

Status: Sepolia contracts are not deployed. `deployments/11155111.json` is
`configured_only` (no Safe, module or aToken addresses). It records that Aave USDC
supply is expected to revert while reserve capacity is full (cap 2,000,000,000
tokens vs aToken supply of about 4.54 billion at historical block 11890000), so
live headroom must be checked before any D2 supply; withdraw, refill and PAY do not
depend on it. All figures here are proposed parameters, not observed deployments.

The scaling example is recorded for runbook preparation. Today's deployment script
does not automatically select or install the Circle profile; do not mutate the
Aave-asset manifest to pretend it does. #230 and the owner must supply/configure
the separate PAY-only evidence run and record actual funded balances.

## 2. Review conclusions

| Rule area                        | Assessment                                                                                                                                                  | Demo/release action                                                                                                                                 |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| BR-020/083 units                 | Base-unit integers avoid float/precision drift. A token-unit cap is not a USD limit and says nothing about depeg risk.                                      | Always show asset identity, decimals and TEST label; avoid USD-valued savings without an explicit FX model.                                         |
| BR-021/022/026 daily budget      | UTC calendar windows are deterministic but allow a burst around midnight. Limits persist across mandate versions and are shared across operational wallets. | Explain calendar-day semantics and test midnight behavior; do not describe it as a rolling 24h cap.                                                 |
| BR-023 separate budgets          | Internal refill and external payment are different flows; using separate counters prevents treating refill as vendor expense.                               | Report both flows independently; 12,000 refill budget is authority, not available cash.                                                             |
| BR-030..036 floors/targets       | Hard buffer protects cash; target is a soft operational convenience. Target top-up is request-bound and occurs only with a shortage.                        | Show minimum-only fallback and complete STOP when minimum cannot be met; no partial vendor payment.                                                 |
| BR-005/007/008 maker-checker     | Separation reduces unilateral errors. Current approver signature is on-chain; creator/editor identity and flag acknowledgment are backend responsibilities. | Use separate operator and approver demo identities; label solo mode. One M1 approver is not a multisig request approval.                            |
| BR-017 cooling                   | Five minutes enables a short demo but has weaker reaction time than 24h. Even an exception must not bypass cooling.                                         | Pre-register routine vendors; show a fresh payee block. Production policy requires separate operational calibration.                                |
| BR-040..043 exception            | Exact one-time cap override is narrower than a policy increase. It does not waive daily cap, floor, payee or expiry.                                        | Include 2,100-token request; owner grant only for that request/amount/payee/expiry/version; its full amount counts toward the daily PAY budget (BR-042), so show remaining budget.                                       |
| BR-024/052/ADR-019 early payment | Exact early debit must match credited saving. Discount is economically useful only after execution fees and forgone interest.                               | Store the exact early option; report net modeled value and assumptions. Do not credit a discount while paying the full standard amount.             |
| BR-037/038 idle liquidity        | Dynamic obligations plus static floor/holds form required reserve; pool accessibility is bounded by available cash.                                         | The contract checks static floor/caps, the backend dynamic reserve. Recheck live cap/cash before D2/D3; no promised yield or guaranteed withdrawal. |
| BR-044 borrowing                 | Rate/HF at execution do not guarantee future financing cost. Borrow proposal is advisory; an owner grant is required for P2 execution.                      | Present unknown HF as unknown and record repayment assumptions; avoid treating a proposal as executable authorization.                              |
| BR-060 recovery                  | Timeout cannot safely mean failure; rerunning with new request IDs can double obligations even if a step guard works.                                       | Resolve Unknown outcomes before new work. Backend recovery remains to be integrated.                                                                |
| Late fees                        | Engine values accrued fees, but PAY authorizes only signed early/standard options. Late-fee valuation does not itself increase the signed amount.           | Re-confirm/re-approve any changed obligation amount; state fee assumptions and avoid claiming the fee was transferred by the original PAY.          |

## 3. Worked integer examples

The following assumptions are synthetic: no protected other holds, fixed six
decimals, no transaction fee in the refill example, and a current valid approval.
They are calculation examples, not wallet balances observed on-chain.

**Exact 2% option:** standard 250, early 245 through the approved date. Gross
saving is 5 (`5000000`). With O1 balance 20, floor 10 and target 150:
minimum shortage = `245 + 10 - 20 = 235`; preferred = `245 + 150 - 20 = 375`.
A 375 refill leaves O1 at 150 after PAY and, from T=10,000, leaves T=9,625.
PAY usage is 245; REFILL usage is 375, not a second vendor expense.

**Minimum fallback:** T=1,250 with floor 1,000 gives source capacity 250. Preferred
375 does not fit; minimum 235 fits, leaving O1=10 and T=1,015. Target is unmet and
must be reported. With T=1,200, capacity 200 is below minimum: STOP with zero
refill/PAY; do not send a partial amount.

**Early value with opportunity cost:** at a synthetic 5% annual supply rate,
paying 245 twenty days before due forgoes
`245000000 * 500 * 20 // (10000 * 365) = 671232` base units. With zero execution
fee, net modeled value is `5000000 - 671232 = 4328768`. A live fee estimate can
reduce that further. These fixed-rate integer expectations are not realized yield.

**Reserve withdrawal:** Safe cash 1,000, floor 1,000 and approved reserve 250
give deficit 250. The 5% target is `ceil(250000000 * 105 / 100) = 262500000`.
Withdraw at most that target, aToken balance and pool available cash. If only 50
is available, withdrawable cash is 50 and shortfall is 200; surface insufficient
liquidity, not an automatically authorized borrow.

## 4. Acceptance and open coordination

- Written review and accepted OQ-05 numeric limits are recorded here.
- Proposed company profile, actual faucet balances, Circle evidence config and
  owner/operator identities require team confirmation; #70/#230 own live inputs.
- A second advisor/developer should review arithmetic, realism and the distinction
  between enforced chain rules and incomplete backend controls.
- Demo/runbook and deck should adopt the reviewed figures and show blocked cases.
  Do not change production thresholds from this synthetic exercise.

Sources: [business rules](../BUSINESS_RULES.md), [financial engine](../modules/financial-engine/README.md),
[ADR-019](../adr/ADR-019-aave-liquidity-and-payment-options.md),
[liquidity code](../../packages/py-core/src/treasurypilot_core/engine/liquidity.py),
[payment value code](../../packages/py-core/src/treasurypilot_core/engine/payment_terms.py).
