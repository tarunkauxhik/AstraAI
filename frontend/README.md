# AstraAi frontend

Vite + React + TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query and React Router.

```bash
npm install
npm run dev        # http://localhost:5173, /api proxied to the backend on :8000
npm run typecheck
npm test
npm run lint
npm run build
```

The browser only calls same-origin `/api/*`; Vite forwards it to FastAPI
(`ASTRAAI_API_URL` overrides the default `http://localhost:8000`). A production deployment
needs the same `/api` reverse proxy, since the backend has no CORS support.

- `src/api` – API client and types mirroring the backend models
- `src/lib/run-view.ts` – pure presentation logic: state precedence, stale evidence,
  timeline, polling policy (unit tested)
- `src/hooks` – polling and mutations
- `src/components/run` – run workspace panels
- `src/routes` – `/` new run, `/runs/:runId` run workspace
