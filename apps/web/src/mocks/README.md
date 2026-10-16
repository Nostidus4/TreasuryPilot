# Mock API

The web app runs against this in-memory backend while `services/api` only exposes `/health`.
Handlers follow `docs/API_SPEC.md` and `docs/modules/mandate` §6. Components never import from
here: they call the hooks in `features/*/api.ts`, which use `lib/api/http.ts`.

- **On** by default in dev and in builds without `VITE_API_URL`. **Off** when `VITE_API_URL` is set
  or `VITE_API_MOCK=false`.
- State lives in memory and resets on reload; only the session flag is kept in `sessionStorage`.
- Async work (extraction, screening, cooling, execution, pause) is driven by `schedule()` in `db.ts`.
  Tests set `timeScale: 0` so every transition is immediate.

## Triggers

| Input                                         | Result                                                           |
| --------------------------------------------- | ---------------------------------------------------------------- |
| Sign in as `linh@northwind.test`              | Seeded org with data. Any other email is a new user with no org. |
| Email starting with `ratelimit`               | 429 `RATE_LIMITED`                                               |
| `/verify?token=expired`                       | 410 `TOKEN_EXPIRED`                                              |
| Safe or payee address ending in `dead`        | `NOT_A_SAFE` / screening hit                                     |
| Safe address ending in `bad`                  | Coverage `PARTIAL`                                               |
| Uploaded file name containing `inject`        | Instruction-like text warning                                    |
| Copilot question containing "budget exceeded" | 429 `AI_BUDGET_EXCEEDED`                                         |

## Endpoints that are not in API_SPEC yet

These were needed by the UI and should be confirmed with the backend owners:

- Guardian Safe creation/registration is intentionally not mocked. The wizard stays blocked until MDT-010 can deploy and record a threshold-1 Safe with human guardian and pause-only Sentinel owners, then verify Sentinel health.
- `GET /orgs/{o}/treasuries/{t}/borrow-proposals/{id}` — borrow proposal read model (ADR-019 D6).
- `POST /orgs/{o}/requests/{r}/cancel-tx/submitted` — report the `cancelRequest` tx hash (M16-D12).
- `POST /orgs/{o}/notifications/all/read` — mark everything read.
- `module/deploy-tx`, `activation-tx`, `registration-tx`, `resume-tx` return `{governanceTx}` (the API `GovernanceTxView` shape; detail, signatures and submitted return it flat)
  (signed in-app, M03-D1) instead of the older `{safeTx}` shape.
- `POST …/approve` accepts an optional `option` (`EARLY` | `STANDARD`) for display only; the
  signed typed data always carries both amounts.
