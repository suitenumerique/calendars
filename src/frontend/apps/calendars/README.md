# Calendars frontend

This is the Calendars frontend, built with [Vite](https://vite.dev/) and [TanStack Router](https://tanstack.com/router/).

## Getting Started

Install dependencies and run the development server:

```bash
npm install
npm run dev
```

Open [http://localhost:8930](http://localhost:8930) — Vite serves on the same
port whether you run `npm run dev` locally or via `make start`.

Routes are file-based under `src/routes/`. The TanStack Router code generator
produces `src/routes.gen.ts` as part of `npm run dev` / `npm run build`.

## Useful scripts

- `npm run dev` — start the Vite dev server.
- `npm run build` — type-check and produce a production build in `dist/`.
- `npm run preview` — preview the production build locally.
- `npm run test` — run the Jest test suite.
- `npm run lint` — run ESLint.
- `npm run ts:check` — run TypeScript in `--noEmit` mode.
- `npm run analyze` — build with the rollup bundle visualizer.
