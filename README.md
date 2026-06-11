# Personalized Research Dashboard

[中文](README.zh-CN.md) | [English](README.en.md)

This repository is now a personalized arXiv research workflow rather than a generic keyword digest.
It builds a fixed daily paper pool, runs weighted L1/L2 review stages around your research profile, writes per-paper outputs under `docs/personalized/`, and publishes a web dashboard grouped by `Digest`, `L2`, `L1`, and `Archived`.

## What It Does

- Freezes each run as a pool snapshot: `docs/personalized/pools/YYYY-MM-DD.json`
- Runs profile-aware L1 relevance filtering and L2 feasibility review
- Stores per-paper L2 outputs under `docs/personalized/l2/YYYY-MM-DD/*.json`
- Stores the final markdown brief under `docs/personalized/digest/YYYY-MM-DD.md`
- Publishes a pool-date based Astro dashboard for browsing results

## Quick Start

```bash
uv run python -m nlp_arxiv_daily run-personalized --date 2026-06-11

cd web
pnpm install
pnpm dev
```

## Core Configuration

- Research profile and direction weights: `configs/research_profile.yaml`
- General fetch/runtime config: `config.yaml`
- L1 prompt: `prompts/l1_abstract_filter.md`
- L2 prompt: `prompts/l2_paper_review.md`

## Reference

To preserve project integrity:

- This repository has diverged substantially into a personalized review system.
- Its public project lineage still includes [monologg/nlp-arxiv-daily](https://github.com/monologg/nlp-arxiv-daily), which established the NLP-focused arXiv daily pipeline and Astro publishing pattern.
- That work also traces back to the broader arXiv-daily idea from [Vincentqyw/cv-arxiv-daily](https://github.com/Vincentqyw/cv-arxiv-daily).

If you want the full current documentation, use the language-specific READMEs above.
