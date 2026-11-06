# Frontend scaffold

Next.js App Router, TypeScript, Tailwind, shadcn/ui configuration, TanStack Query and native fetch. Node version: `.nvmrc`; npm version: `package.json`. Commands and local backend setup are in the repository README. Feature screens are implemented in later phases.

- app: routes/layout; components/ui: shared UI. Feature code for search/images/auth/admin will be created as each phase is implemented.
- lib/api/client.ts: browser-only same-origin fetch transport, forwards AbortSignal, no automatic retries; auth lifecycle is added with the auth feature.
- QueryProvider: one QueryClient per browser mount, retries and refetch-on-focus disabled to avoid recreating search snapshots.
- components.json: shadcn aliases/theme config; Button is the starter component. Run CLI commands from frontend when adding components.
- Copy .env.example to .env.local. BACKEND_ORIGIN is server-side, used by rewrites for /v1/* and /health/*; use the same frontend hostname for auth/cookies during local development. Set FastAPI Origin allowlist to the frontend origin when auth is implemented.
- No model keys or database credentials in NEXT_PUBLIC_* variables. Backend authorization and cache cleanup on logout remain future auth work.

## Dependency audit at scaffold setup

The installed dependency tree reports 8 moderate advisories in development-only ESLint/typescript-eslint dependencies (minimatch). Runtime dependencies have no reported advisory in this audit. Keep the lockfile and review compatible tooling updates; do not use `npm audit fix --force`, which currently proposes downgrading the Next ESLint config to a different major. This is a point-in-time report; rerun audit when updating dependencies.
