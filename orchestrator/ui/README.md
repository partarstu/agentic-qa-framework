# Orchestrator Dashboard UI

A React + TypeScript + Vite single-page app that provides the QuAIA™ orchestrator's real-time web monitoring
dashboard: agent status, task history, error log and log viewer, served by the orchestrator (see the root
[README](../../README.md#web-ui-monitoring-dashboard) for the feature list and dashboard REST/SSE API reference).

## Stack

* React 19 + TypeScript, built with Vite 7
* Tailwind CSS v4 for styling
* TanStack Query + `axios` for data fetching against the orchestrator's `/api/dashboard/*` REST endpoints
* Native `EventSource` (see `src/api/sse.ts`) for the orchestrator's SSE streams (`snapshot`, `agent_activity`,
  `task_done`, `log_batch`, `gap`, `heartbeat`), with reconnect/backoff and short-lived stream-token handling
  (`src/api/streamToken.ts`)
* JWT-based login (`src/components/LoginPage.tsx`, `src/context/AuthContext.tsx`, `src/api/authApi.ts`) against the
  orchestrator's `/api/auth/*` endpoints

## Running in development

The dev server proxies `/api` requests to a locally running orchestrator, so the orchestrator's port must be known
up front:

```bash
cd orchestrator/ui
export ORCHESTRATOR_PORT=8000   # must match the running orchestrator; Windows: set ORCHESTRATOR_PORT=8000
npm install
npm run dev
```

The dev server runs at `http://localhost:5173` and proxies `/api` calls to `http://localhost:$ORCHESTRATOR_PORT`.
`vite.config.ts` throws immediately on `npm run dev`/`vite` if `ORCHESTRATOR_PORT` is not set.

## Building for production

```bash
cd orchestrator/ui
# Windows
start.bat
# Linux/macOS
./start.sh
```

Both scripts also require `ORCHESTRATOR_PORT` to be set. They install dependencies if needed, run `npm run build`
(`tsc -b && vite build`), copy the resulting `dist/` into `orchestrator/static/` so the orchestrator can serve the
built assets directly, and then start the dev server (`npm run dev`) on top of that build.

## Other scripts

* `npm run lint` — ESLint (`eslint.config.js`)
* `npm run preview` — serve the last production build locally without the orchestrator proxy
