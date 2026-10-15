# Compliance positioning

**Tracking:** #239 / DOM-015 · **Traces to:** NFR-CMP-02, NFR-CMP-03

This note is **positioning, not legal advice**. It states what the repository
does and does not do, so the team can answer the stablecoin question
consistently. It makes no claim about any law or licensing regime. A qualified
lawyer must review it before it is relied on.

## 1. Testnet only

- The competition build runs on **Ethereum Sepolia** (chainId 11155111) with a
  team-deployed `tUSDC` and Aave's test USDC, both labelled TEST, plus one run
  with Circle's testnet USDC ([ADR-012](../adr/ADR-012-chain-and-stablecoin.md),
  ADR-019). Local and CI runs use Anvil (31337). No real funds move.
- The signer's chain allowlist defaults to `[31337, 11155111]`
  (`services/signer/src/treasurypilot_signer/config.py`, `allowed_chain_ids`).
  A chain that is not in the configuration fails with `CHAIN_NOT_ALLOWED`.
- Evidence bundles carry a `TESTNET` flag from the `chains.is_testnet` column
  (`services/api/src/treasurypilot_api/audit/evidence_repository.py`).
- **Mainnet activation is gated by KYB** (#193, `docs/modules/compliance/README.md`,
  "KYB (CMP-L01)"). `GovernanceService._require_kyb()` rejects a mainnet
  `MODULE_SETUP` with `409 KYB_REQUIRED` unless the organization's latest KYB
  result is `APPROVED`, and a mainnet treasury does not reach `Ready` without it.
  A chain not known to be a testnet counts as mainnet, and a missing KYB service
  blocks (fail closed).
- **Limit of this gate:** no real KYB vendor is integrated. Outside
  `local`/`test`/`demo` the provider is `UnconfiguredKybProvider` and raises, so
  mainnet cannot be activated today. Screening is likewise a labelled fixture
  (TEST DATA), not a live sanctions list, and fails closed elsewhere.

## 2. Target market is outside mainland China

- The primary users are finance and treasury operators at stablecoin-native SMEs
  and Web3 businesses ([PROJECT_OVERVIEW](../PROJECT_OVERVIEW.md)).
- **NFR-CMP-02:** the product is not marketed to mainland China retail or business
  use of stablecoins; this note is the required statement
  ([NON_FUNCTIONAL_REQUIREMENTS](../NON_FUNCTIONAL_REQUIREMENTS.md)).
- The product is non-custodial: the Safe stays under the customer's owners, and
  custody of customer funds is a stated non-goal
  ([FEATURES](../FEATURES.md) non-goals, PROJECT_OVERVIEW).
- The repository has no jurisdiction-specific eligibility check. This is
  a positioning and go-to-market statement, not a technical control. Do not claim
  geo-blocking.

## 3. Reuse for tokenised deposits

- Money handling is asset-agnostic by design: integer base units
  ([ADR-014](../adr/ADR-014-money-representation.md)), one payment asset per
  treasury, and per-asset limits exist in the mandate model (treasury README §16,
  TRS-L02); multiple stablecoins per treasury is tagged Later (F-015, decisions-log Q2).
- The enforcement layer (Safe module mandate, EIP-712 approvals, policy
  validation, screening before PAY, audit log, evidence bundle) does not depend on
  who issues the token. A token that behaves as ERC-20 could be added through the
  asset allowlist.
- What would still be needed, and is **not built**: a real KYB/KYT/Travel Rule
  provider behind the existing adapters (NFR-CMP-04, F-111 (Later)), a
  per-asset review of transfer restrictions, and legal review for each issuer and
  jurisdiction. Depeg checks and fiat-denominated invoices are also phase Later
  (decisions-log Q20).
- No tokenised deposit has been tested. This section describes design intent only.

## 4. Third-party licenses

See [licenses.md](licenses.md) (NFR-CMP-03).
