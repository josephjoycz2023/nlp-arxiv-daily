# Personalized Research Dashboard

This repository is no longer a generic keyword-based arXiv digest.
It is now a personalized paper-review workflow built around a weighted research profile, staged review pipeline, and pool-date based dashboard.

## 1. What This Project Is

The current system is designed to:

- freeze a daily paper pool
- run weighted L1 relevance screening
- run L2 full-paper feasibility review
- generate a markdown digest
- publish a web dashboard grouped by `Digest`, `L2`, `L1`, and `Archived`

The key idea is that the unit of analysis is a `pool date`, not the paper's own `published_date`.

That means:

- the date selector in the web UI switches between frozen retrieval pools
- papers inside a pool may come from earlier arXiv dates
- L1, L2, and Digest all operate on the same fixed pool, which makes the workflow reproducible and resumable

## 2. Research Profile and Weighted Priorities

The main profile lives in `configs/research_profile.yaml`.

The project supports explicit priority levels from 1 to 5, where 5 is the highest weight.
These weights affect:

- L1 relevance decisions
- L2 review priority
- digest ranking
- web grouping order

Current research directions:

1. LLM training datasets and evaluation datasets, especially emotion, multi-turn dialogue, tool use, SFT, RL, and on-policy distillation (level 4)
2. LLM memory, especially multi-agent memory frameworks, long-term memory, personalized memory, persona consistency, emotional stability, and implicit memory indexing (level 5)
3. Neuroscience intersecting with language and memory (level 1)
4. Training and inference acceleration for large models (level 2)
5. POI scenarios combined with AI, especially tool use and situated capabilities in companion products (level 3)

An important review principle in this repository is:

- a paper only needs to strongly match one important direction
- the analysis should not force unrelated directions into the explanation
- evaluation, safety auditing, negative assessment, and reliability work can be first-class value on their own

## 3. Artifact Layout

Personalized outputs are written under `docs/personalized/`:

```text
docs/personalized/
  pools/YYYY-MM-DD.json
  l1/YYYY-MM-DD.json
  l1/YYYY-MM-DD.md
  l2/YYYY-MM-DD/*.json
  digest/YYYY-MM-DD.md
  runs/YYYY-MM-DD.json
  runs/latest.json
  cache/
  logs/YYYY-MM-DD/
    pipeline.json
    l1.json
    l2.json
    digest.json
```

Important notes:

- `pools/YYYY-MM-DD.json`
  The frozen retrieval pool for that run. This is the source of truth for date filtering in the web UI.
- `l1/YYYY-MM-DD.json`
  Structured L1 screening results.
- `l2/YYYY-MM-DD/*.json`
  Per-paper L2 review outputs. This is the new location replacing the old `reviews/` path.
- `digest/YYYY-MM-DD.md`
  Final markdown digest. This is the new location replacing the old `daily/` path.
- `logs/YYYY-MM-DD/*.json`
  Stage-level structured logs. These are currently the most reliable web data source.

## 4. Web UI

The frontend lives in `web/` and is built with Astro.

The current web dashboard is organized around the personalized workflow:

- a left sidebar switches between `pool dates`
- the main area is split into four fixed columns:
  - `Digest`
  - `L2`
  - `L1`
  - `Archived`
- each column is further grouped by research direction
- digest markdown is rendered directly in the UI
- the same paper appears only once, in the deepest stage it reached

This is intentionally different from the older keyword/month archive site.

## 5. Running the Pipeline

### Full personalized run

```bash
uv run python -m nlp_arxiv_daily run-personalized --date 2026-06-11
```

### Stage-by-stage debugging

```bash
uv run python -m nlp_arxiv_daily filter-l1 --date 2026-06-11
uv run python -m nlp_arxiv_daily review-l2 --date 2026-06-11
uv run python -m nlp_arxiv_daily build-digest --date 2026-06-11
```

### Web development

```bash
cd web
pnpm install
pnpm dev
```

### Static build

```bash
cd web
pnpm build
pnpm preview
```

## 6. Core Files

- General runtime config: `config.yaml`
- Research profile: `configs/research_profile.yaml`
- L1 prompt: `prompts/l1_abstract_filter.md`
- L2 prompt: `prompts/l2_paper_review.md`

Together, these files determine:

- retrieval scope
- direction weighting
- L1 pass/archive/reject behavior
- L2 review framing and action recommendations
- digest ranking and emphasis

## 7. How This Repo Differs From the Older Project Shape

Compared with the earlier public project lineage, this repository now focuses on:

- personalized research triage instead of generic keyword aggregation
- staged review (`L1 -> L2 -> Digest`) instead of a flat daily list
- pool-date snapshots instead of month-centric browsing
- direction-aware grouping instead of keyword tabs
- stronger emphasis on evaluation, negative assessment, reliability, and ToC relevance

## 8. Good Fit Use Cases

This repository is a good fit if you want to:

- run a personal research radar rather than a public paper portal
- assign heavier weight to a few core directions
- separate broad relevance screening from deeper feasibility review
- preserve a frozen daily candidate pool for reproducibility
- publish both machine-readable artifacts and a browsable dashboard

## 9. Project Lineage and Integrity

To preserve integrity, the upstream public references are still part of this repository's story:

- [monologg/nlp-arxiv-daily](https://github.com/monologg/nlp-arxiv-daily)
  This is the most direct public lineage reference for the NLP-focused arXiv tracking and Astro publishing pattern.
- [Vincentqyw/cv-arxiv-daily](https://github.com/Vincentqyw/cv-arxiv-daily)
  An earlier source of the broader arXiv-daily workflow pattern.

This repository now diverges significantly in product shape and review logic, but it intentionally keeps that lineage visible instead of hiding it.
