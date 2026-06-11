# AI Video Editor — Review UI

Word-level, Descript-style review editor for the AI Video Editor. Pick a
processed video, cut/keep individual words on a scrolling transcript, preview
the edit, then save a `*-review.edl.json` sidecar and render a reviewed MP4.

## Stack

- **Vite + React 19 + TypeScript** — app shell and build.
- **Tailwind CSS v4** (`@tailwindcss/vite`) — styling via the `@import "tailwindcss"` entry in `src/index.css`.
- **shadcn/ui** (new-york, neutral, Radix primitives) — base components in `src/components/ui`, configured in `components.json`.
- **video.js v10** (`@videojs/react`) — the player. A single `createPlayer` instance lives in `src/lib/player.ts`; `Player.Provider` is remounted per video.
- **usehooks-ts** — `useBoolean`, `useEventCallback`, `useEventListener`.
- **remeda** — array utilities (`flatMap`, `partition`, `sumBy`, `range`, `sortBy`).
- **oxlint** + **oxfmt** — linting and formatting (replaces ESLint + Prettier).

### API layer (`src/api/`)

All network access lives in `src/api/` and is fully typed against the backend:

- **openapi-typescript** generates `src/api/schema.d.ts` from the FastAPI OpenAPI
  spec (`npm run gen:api`, against a backend on `:8000`). It is committed and
  excluded from oxlint/oxfmt.
- **openapi-fetch** (`src/api/client.ts`) is the typesafe fetch client — paths,
  params, bodies, and responses are all inferred from the generated schema.
- **TanStack Query** wraps every call in hooks (`src/api/videos.ts`):
  `useVideos`, `useReview`, `useSaveReview`, `useRenderReview`. The shared
  `QueryClient` lives in `src/api/query-client.ts` and is provided in `main.tsx`.

Regenerate the types after changing the backend API:

```bash
# backend must be running on :8000
npm run gen:api
```

## Scripts

```bash
npm run dev           # Vite dev server (proxies /api and /media to 127.0.0.1:8000)
npm run build         # tsc -b && vite build
npm run preview       # preview the production build
npm run lint          # oxlint
npm run format        # oxfmt (write)
npm run format:check  # oxfmt --check
```

## Backend

The UI talks to the FastAPI backend (`ai_video_editor/web/app.py`). To run both
together, serve the built UI:

```bash
uv run python -m ai_video_editor.cli.app review-serve tests/fixtures
```

For frontend hot reload against the backend, run the backend on port 8000 and
`npm run dev` — Vite proxies `/api` and `/media` across.

## Keyboard shortcuts

Click a word to seek · shift-click or drag to select a range · `⌫` cut · `⏎`
keep · double-click toggles · `Space` play/pause · `N` next AI cut · `Esc`
clear selection.

## Adding shadcn components

```bash
npx shadcn@latest add <component>
```

Components land in `src/components/ui` and are excluded from oxlint.
