# Orchestrator Dashboard UI

The QuAIA™ orchestrator's real-time monitoring dashboard, a React single-page app served by the orchestrator. The root [README](../../README.md#web-ui-monitoring-dashboard) describes its views and the dashboard REST and SSE API it reads.

## Stack

* React 19.3 with the React Compiler (`babel-plugin-react-compiler` through `@rolldown/plugin-babel`), built by Vite 8 and type-checked by TypeScript 7.
* Plain CSS in cascade layers (`public/layers.css` sets their order, and every build checks it is linked first) on design tokens (`src/styles/tokens.css`) with a light, a dark and a raised-contrast theme; no CSS framework.
* TanStack Query over a small `fetch` wrapper (`src/data/client.ts`) for the `/api/dashboard/*` and `/api/auth/*` endpoints, refreshed by the global SSE stream (`src/live/`) and by polling of the visible view only.
* One log tail (`src/logs/`) for the sheets and the Logs view: the newest log page merged by entry `id` with the per-agent SSE stream, reloaded on every stream connect.
* Hand-built SVG charts (`src/charts/`), each with a text alternative; `lucide-react` icons; the Atkinson Hyperlegible fonts.
* An accessible UI kit (`src/kit/`: native `<dialog>` modals and side sheets, popovers, tooltips, tabs, meters, status aspects) ported from the operator panel's `main` at commit `85f880afbc7b0d586e1d4b099d0885cad99497a2`, without its panel-only parts.

Motion (view cross-fades, the task title morphing from its row into its sheet, sheets and popovers rising in, the topology's flow while a task starts) runs only when the system allows motion, and every status pairs its colour with an icon and a word.

## Scripts

Node.js 24 with npm 11.10 or newer: `.npmrc` disables the packages' install scripts and accepts only versions released at least three days ago.

* `npm ci` installs the pinned dependencies.
* `npm run dev` starts the dev server at `http://localhost:5173`, proxying `/api` to `http://localhost:$ORCHESTRATOR_PORT`; it stops at once when `ORCHESTRATOR_PORT` is not set.
* `npm run lint` runs ESLint with the accessibility rules of `eslint-plugin-jsx-a11y-x` and allows no warning.
* `npm run build` type-checks the app and the build config and bundles into `dist/`, with `licenses.md`, the licences of the bundled packages and fonts.
* `npm test` runs the Vitest suite once.
* `npm run preview` serves the last build without the orchestrator proxy.

`start.bat` and `start.sh` build the app, copy `dist/` into `orchestrator/static/`, where the orchestrator serves it, and start the dev server; they also need `ORCHESTRATOR_PORT`. The orchestrator's Docker image runs `npm ci` and `npm run build` itself.

## Tests

The tests sit next to the code they cover (`*.test.ts`, `*.test.tsx`) and run in jsdom with Testing Library. `src/testing/` holds the shared helpers: `installDom` and `axeViolations` (every view, sheet and kit component is checked with axe-core), stubbed API routes, fixtures and `renderView`, which renders a view with its own query cache, live store and navigation spies; keyboard tests use `@testing-library/user-event`, because jsdom does not move the focus on Tab. The style tests read the stylesheets: `tokens.test.ts` checks the contrast of every text and boundary pair and the colour-blind separation of the chart series in every theme, and `motion.test.ts` that every animation and every moving transition runs only without reduced motion.

The `Dashboard UI` CI job runs `npm ci`, `npm run lint`, `npm run build` and `npm test`, then `npm audit --omit=dev` without failing the build.
