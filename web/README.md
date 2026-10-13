# RelayOps web client

React, TypeScript and Vite client for the local RelayOps API. The production build is served by FastAPI; it requires no external font, image, CDN, or browser API key.

## Build and check

```sh
npm ci
npm test
npm run build
```

`dist/` is the generated production client. The eight policy tests check separation of reviewer/operator actions, observer restrictions, exact revision and expiry checks, invalid proposal metadata, active-run polling states, evidence citation resolution, and combined search/status filters.

## Development

Start the backend on `127.0.0.1:8765`, then run:

```sh
npm run dev
```

Vite listens on localhost and proxies `/api` to the backend. `changeOrigin: false` preserves the incoming host for the backend's same-origin mutation checks. The normal, documented application setup uses the production build served from the same FastAPI origin.

## Interface

- Operations: searchable case queue, cited diagnosis, evidence records, investigation activity, reviewed proposals, operation receipts, JSON report export.
- Scenario lab: creates isolated cases from the backend's scenario catalog.
- Restricted repair: original/candidate diff, baseline and independent verification, reviewed patch artifact download after execution.
- Evaluations: backend-generated deterministic regression results, explicitly separate from model evaluation.
- Knowledge: operating notes from the API.

All mutations use the API's demo-role and explicit-request headers. Demo personas are not authentication; the server remains responsible for permission, revision, hash, expiry and target-scope enforcement. Approval and execution are separate operations. The coding workflow never claims an arbitrary-code sandbox or general repository repair.

Fixture mode is labelled deterministic throughout. OpenAI mode is selectable only when the backend reports it available. Active runs are polled once per second, with timers and fetches cancelled on cleanup. Data is not fabricated when the backend is unavailable.

## Source map

| File | Responsibility |
|---|---|
| `src/App.tsx` | Screens, forms, API orchestration, case polling, confirmation focus handling |
| `src/types.ts` | API response contracts |
| `src/api.ts` | Request headers, errors and downloads |
| `src/policy.ts` | Display permissions, citation resolution, search and polling decisions |
| `src/policy.test.ts` | Policy regression tests |
| `src/style.css` | Responsive visual system and reduced-motion behavior |

The policy tests complement backend and browser integration checks; they do not replace them.
