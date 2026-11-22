# Time-Travel DB & Bug Rewinder — Frontend

Frontend for the hackathon project **Time-Travel DB & Bug Rewinder**. When a bad deploy or script corrupts production data, an agent rewinds a **clone** of the database to just before the crash, keeps the legitimate new writes, proposes a patch, and waits for a **human to approve** before anything touches production. Every apply can be undone.

Built from the three Google Stitch designs (Console Incident, Console Review, Audit Log List) with React, Vite and Tailwind CSS. It runs on **mock data** by default, or against the real Python backend with `npm run dev:live` — see [docs/BACKEND_INTEGRATION.md](docs/BACKEND_INTEGRATION.md).

## Requirements

- Node.js 20.19+ or 22.12+ (tested with Node 26)
- npm 10+

## Getting started

```bash
npm install
npm run dev
```

Open http://localhost:5173. No backend or environment variables are needed for the mock mode.

To use the real backend, start it from the repository root (`python3 server.py`) and run `npm run dev:live` here.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Start the development server with hot reload on http://localhost:5173 |
| `npm run dev:live` | Same, but against the real Python backend (proxies `/api` to port 8000) |
| `npm run build` | Production build into `dist/` (served by `server.py` at `/app/`) |
| `npm run build:live` | Production build wired to the real backend (use this one for `/app/`) |
| `npm test` | Unit tests for the backend adapters (`node --test`, no extra dependencies) |
| `npm run preview` | Serve the production build locally on http://localhost:4173 |

## Screens

| Route | Screen | Stitch design |
|---|---|---|
| `/console` | **Console — Incident.** Live database (inventory, orders, change log), demo actions, recovery composer and streaming progress | `design/stitch-exports/console-incident` |
| `/console/review` | **Console — Review & approve.** Clone banner, progress stepper, stats, merge plan with plain-language reasons, conflict resolution, patch diff, approve / discard / undo | `design/stitch-exports/console-review` |
| `/audit-log` | **Audit log.** Search, status and scenario filters, pagination, record drawer (`?q=&status=&scenario=&page=&recovery=`) | `design/stitch-exports/audit-log-list` |

`/` redirects to `/console`. Unknown routes show a "Page not found" screen.

### Demo flow (PRD §5)

1. **Console** opens in the incident state from the design: inventory wiped to 0 and orders #1041–#1043 placed. (Press **Reset demo** to start from healthy data, then use **Sync Warehouse** and **Place 3 Orders**.)
2. **Run time-travel** — progress streams step by step, then the **Review** screen opens.
3. Review the merge plan, conflict and patch → **Approve & go live** → **Apply to live**.
4. Back on the Console, **Re-run Sync** touches only 1 row, which confirms the fix.
5. Optional: **Undo recovery** from the Review screen. Every apply, discard and undo shows up in the **Audit log**.

### Testing loading, error and empty states

Add a `mock` query parameter to any URL (mock mode only):

| URL | Shows |
|---|---|
| `/console?mock=slow` | Slow responses: skeletons, spinners, streaming progress |
| `/console?mock=error` | Every request fails: error banners with Retry |
| `/audit-log?mock=empty` | Empty audit log |

Mock data lives in memory, so **refreshing the page resets it** (in-app navigation keeps it).

## Project structure

```
time-travel-frontend/
├── index.html                 Fonts (Inter, JetBrains Mono, Material Symbols) and the app root
├── tailwind.config.js         Theme merged from the three Stitch exports
├── vite.config.js
├── .env.example               VITE_USE_MOCKS / VITE_API_BASE_URL (copy to .env.local)
├── design/stitch-exports/     Original Stitch exports (code.html, screen.png, DESIGN.md) — reference only
├── docs/
│   └── BACKEND_INTEGRATION.md Actions, data shapes and open questions for the backend team
└── src/
    ├── main.jsx               Entry point
    ├── app/App.jsx            Router and providers
    ├── pages/                 One file per screen: ConsolePage, ReviewPage, AuditLogPage, NotFoundPage
    ├── components/
    │   ├── layout/            AppHeader (navigation, status chips, Reset demo), AppLayout
    │   ├── ui/                Reusable pieces: Button, Card, Pill, Icon, Modal (ConfirmDialog), Drawer,
    │   │                      SelectField, Skeleton, EmptyState/ErrorBanner, Toaster, RichText
    │   ├── console/           Incident screen cards (scenario, actions, inventory, orders, change log,
    │   │                      recovery composer, progress panel)
    │   ├── review/            Review screen pieces (banner, stepper, stat strip, merge plan, conflict,
    │   │                      patch diff, approval bar, smoke checks, live snapshot cards)
    │   └── audit/             Audit log pieces (summary cards, filters, table, pagination, detail drawer)
    ├── context/               DemoContext (app state + actions), ToastContext
    ├── services/              api.js (the only backend boundary), httpClient.js, config.js, errors.js
    ├── mocks/                 demoData.js (mock content), mockServer.js (in-memory fake backend)
    ├── constants/             Recovery step labels, default prompt, page size
    ├── hooks/                 useElapsed, usePageTitle
    ├── utils/format.js        Date, duration, risk-band and status helpers
    └── styles/index.css       Tailwind layers and custom classes from the Stitch exports
```

**Rule of thumb:** components never fetch data or import mocks. They get data from `DemoContext` (or, on the Audit log page, from `services/api.js`). That keeps the backend swap to one file.

## Backend integration

Short version (details and data shapes in [docs/BACKEND_INTEGRATION.md](docs/BACKEND_INTEGRATION.md)):

1. Agree endpoint paths with the backend team (none are invented here).
2. `cp .env.example .env.local`, set `VITE_USE_MOCKS=false` and `VITE_API_BASE_URL`.
3. Replace each `notConnected(...)` in `src/services/api.js` with a `request(...)` call.

Actions that need the backend: load scenarios and live data, Sync Warehouse, Place 3 Orders, Reset demo, Run time-travel (with streaming progress), Approve & go live, Discard plan, Undo recovery, and the audit log list / summary / record.

## Design notes

- Visuals follow the Stitch exports: light "Vapor Engine" theme, Inter + JetBrains Mono, Material Symbols icons, the same Tailwind classes and colours.
- The three exports had different sample data and slightly different headers. They are unified into one header and one consistent demo story (Limited Drop Hoodie oversold by order #1043).
- Added where the designs had no screen: confirmation dialogs (approve, discard, undo, reset, scenario switch), the "recovery live" state of the Review screen, the audit record drawer, toasts, and loading, empty and error states.
- Responsive: two columns on desktop (≥1024px), stacked on tablet, card lists instead of wide tables on mobile, dialogs as bottom sheets on phones.
- No sign-in: authentication is out of scope for this build (PRD §4). The avatar in the header is decorative.

## Deployment note

This is a single-page app with client-side routes. On static hosting, configure a fallback so every path serves `index.html` (e.g. Netlify `_redirects`: `/* /index.html 200`; Vercel rewrites).

## Security

No API keys, tokens or secrets are in this repository. Anything prefixed `VITE_` is shipped to the browser, so never put secrets in `.env` files for this project. `.env` and `.env.*` are git-ignored (except `.env.example`).
