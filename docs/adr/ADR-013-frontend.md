# ADR-013: Frontend: React + Vite + wagmi
**Status:** Accepted (G2, 2026-10-11) · **Decision:** Q31

## Decision
- React 18 + Vite + TypeScript.
- wagmi/viem + RainbowKit for wallet connection, SIWE and EIP-712 `signTypedData`.
- TanStack Query for server state; React Hook Form + Zod for forms.
- Tailwind + shadcn/ui for UI; Recharts for charts.
- Routing with React Router.
- Static build served by nginx.

## Consequences
The typed-data displayed in the UI must be byte-identical to what the API returns and the contract verifies (golden vectors, ADR-003).
