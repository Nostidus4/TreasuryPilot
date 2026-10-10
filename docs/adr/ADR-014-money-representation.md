# ADR-014: Money as integer base units end-to-end
**Status:** Proposed · **Rules:** BR-020, BR-083 · **FR:** FR-109

## Decision
Amounts are non-negative integers in the asset's smallest unit everywhere:
- Solidity: `uint256`
- Postgres: `NUMERIC(78,0)`
- Python: `int`
- JSON: decimal string
- TS: `bigint`

Display formatting happens only in the UI using registry decimals. Floats are forbidden by lint rule (ruff custom check / review).

## Consequences
Conversions happen at the edges only. Tests use the Domain §3.4 examples in base units.
