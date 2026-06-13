# Personalized Research Dashboard Web

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
## Data Source

The current frontend reads personalized pipeline outputs from:

- `../docs/personalized/pools/`
- `../docs/personalized/logs/`
- `../docs/personalized/l1/`
- `../docs/personalized/l2/`
- `../docs/personalized/digest/`

The date selector is based on `pool` snapshots, not each paper's own `published_date`.
