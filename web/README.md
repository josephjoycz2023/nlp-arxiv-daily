# Web Dashboard

This directory contains the Astro frontend for the personalized research dashboard.
It reads build-time data from `../docs/personalized/` and publishes a static site grouped by `Digest`, `L2`, `L1`, and `Archived`.

## Local Development

Requirements:

- Node `>= 22.12`
- dependencies installed in `web/`

Install dependencies:

```powershell
cd web
corepack pnpm install
```

Start the local dev server:

```powershell
cd web
corepack pnpm dev
```

Then open:

```text
http://localhost:4321
```

If PowerShell blocks `pnpm`, you can use the local Astro binary directly:

```powershell
cd web
.\node_modules\.bin\astro.cmd dev
```

## Build and Preview

Build the static site:

```powershell
cd web
corepack pnpm build
```

Preview the built site locally:

```powershell
cd web
corepack pnpm preview
```

If needed, you can also build directly with Astro:

```powershell
cd web
.\node_modules\.bin\astro.cmd build
```

## Why Pagefind Works on GitHub Pages

This project uses `astro-pagefind`.

That means:

- search indexes are generated at build time
- the final output is fully static
- no backend search service is required
- once `dist/` is deployed to GitHub Pages, Pagefind works directly in the browser

So the behavior you saw in `monologg/nlp-arxiv-daily` is not a special GitHub feature.
It works because Pagefind is a static-search solution and GitHub Pages can host the generated files.

## Data Source

The current frontend reads personalized pipeline outputs from:

- `../docs/personalized/pools/`
- `../docs/personalized/logs/`
- `../docs/personalized/l1/`
- `../docs/personalized/l2/`
- `../docs/personalized/digest/`

The date selector is based on `pool` snapshots, not each paper's own `published_date`.

## Notes

- `astro.config.mjs` already includes the `astro-pagefind` integration.
- Search indexes are generated during `build`, not during plain file editing.
- If you update pipeline outputs under `docs/personalized/`, restart or rebuild the frontend to refresh the rendered snapshot.
