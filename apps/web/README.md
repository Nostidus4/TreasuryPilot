# TreasuryPilot web

React 18 + Vite + TypeScript application shell. It includes protected routing, TanStack Query, Tailwind/shadcn foundations, wallet configuration and an OpenAPI-generated client.

```bash
corepack pnpm@9.15.9 --dir apps/web dev
```

The development server runs at `http://localhost:5173`. Set `VITE_API_URL` to override the default API base URL (`http://localhost:8000`). Set `VITE_OIDC_ENABLED=true` to show the company SSO option when the API has OIDC configured.
