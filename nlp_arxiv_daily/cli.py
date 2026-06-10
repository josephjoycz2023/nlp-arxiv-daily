"""CLI subcommand dispatch for the nlp_arxiv_daily pipeline.

Four subcommands:
- `fetch`    — query arxiv per keyword, persist current/archive JSON splits.
- `render`   — read the persisted JSON, write README/gitpage/archive markdown.
- `run`      — fetch then render (this is what the cron workflow calls).
- `backfill` — date-range fetch (across many months) merged into the archive.

JSON is the boundary between fetch and render, so the two subcommands can
also be run independently — useful for backfills and golden-output testing.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
from collections.abc import Iterator

from nlp_arxiv_daily.ai_filter import build_digest_for_date, filter_level1_for_date, review_level2_for_date
from nlp_arxiv_daily.ai_filter.stage_logging import write_stage_log_bundle
from nlp_arxiv_daily.core import load_config, papers_to_legacy_rows
from nlp_arxiv_daily.fetcher import (
    BACKFILL_DEFAULT_MAX_RESULTS,
    BACKFILL_RATE_LIMIT_SECONDS,
    ArxivRateLimitExceeded,
    ensure_arxiv_preflight,
    fetch_papers,
    fetch_papers_in_range,
)
from nlp_arxiv_daily.renderer import json_to_md, render_archive_pages
from nlp_arxiv_daily.storage import write_papers_split, write_topic_paper_files
from nlp_arxiv_daily.types import Paper


def cmd_fetch(config: dict) -> dict[str, list[Paper]]:
    """Query arxiv for every keyword in `config["kv"]`, persist outputs."""
    keywords = config["kv"]
    max_results = config["max_results"]
    keyword_order = list(keywords.keys())

    data_collector = []
    papers_by_topic: dict[str, list[Paper]] = {}

    ensure_arxiv_preflight()
    logging.info("GET daily papers begin")
    for topic, keyword in keywords.items():
        logging.info(f"Keyword: {topic}")
        papers = fetch_papers(query=keyword, max_results=max_results)
        papers_by_topic[topic] = papers
        data, _ = papers_to_legacy_rows(papers, topic)
        data_collector.append(data)
        logging.info("")
    logging.info("GET daily papers end")

    if config["publish_readme"]:
        write_papers_split(
            data_collector,
            config["json_readme_path"],
            config["archive_readme_json_dir"],
            keyword_order=keyword_order,
        )
    if config["publish_gitpage"]:
        docs_dir = os.path.dirname(config["json_gitpage_path"]) or "."
        write_topic_paper_files(papers_by_topic, docs_dir)
    _write_analysis_pool_snapshot(config, papers_by_topic, snapshot_date=datetime.date.today())
    return papers_by_topic


def cmd_render(config: dict) -> None:
    """Render README + README-archive markdown.

    The gitpage flavor (docs/index.md + docs/archive-web/*.md) was retired
    in PRSL-77's cutover — the Astro site under web/ now consumes the
    gitpage JSON files directly, so there's no markdown to write for it.
    `publish_gitpage` therefore controls only the JSON persistence in
    `cmd_fetch`, not anything in this function.
    """
    show_badge = config["show_badge"]
    user_name = config["user_name"]
    repo_name = config["repo_name"]
    keyword_order = list(config["kv"].keys())

    if config["publish_readme"]:
        json_to_md(
            config["json_readme_path"],
            config["md_readme_path"],
            task="Update Readme",
            show_badge=show_badge,
            user_name=user_name,
            repo_name=repo_name,
            archive_index_link="docs/archive/index.md",
            keyword_order=keyword_order,
        )
        render_archive_pages(
            config["archive_readme_json_dir"],
            config["archive_readme_md_dir"],
            show_badge=show_badge,
            user_name=user_name,
            repo_name=repo_name,
            keyword_order=keyword_order,
        )


def cmd_run(config: dict) -> None:
    """Full pipeline: fetch then render. The cron workflow calls this."""
    cmd_fetch(config)
    cmd_render(config)


def cmd_run_personalized(config: dict, *, run_date: datetime.date | None = None) -> None:
    """Fetch, render, then run the personalized AI pipeline for one analysis pool date."""
    if run_date is None:
        run_date = datetime.date.today()
    state = _load_personalized_run_state(config, run_date)

    if not _is_stage_completed(config, state, "fetch"):
        _mark_stage_in_progress(state, "fetch")
        _write_personalized_run_state(config, run_date, state)
        try:
            papers_by_topic = cmd_fetch(config) or {}
            analysis_pool_path = os.path.join(config["personalized_docs_dir"], "pools", f"{run_date.isoformat()}.json")
            if run_date != datetime.date.today() and papers_by_topic:
                analysis_pool_path = _write_analysis_pool_snapshot(config, papers_by_topic, snapshot_date=run_date)
            state["stages"]["fetch"] = _build_fetch_stage_record(config, analysis_pool_path)
            _write_personalized_run_state(config, run_date, state)
        except Exception as e:
            _mark_stage_failed(state, "fetch", e)
            _write_personalized_run_state(config, run_date, state)
            raise

    if not _is_stage_completed(config, state, "render"):
        _mark_stage_in_progress(state, "render")
        _write_personalized_run_state(config, run_date, state)
        try:
            cmd_render(config)
            state["stages"]["render"] = _build_render_stage_record(config)
            _write_personalized_run_state(config, run_date, state)
        except Exception as e:
            _mark_stage_failed(state, "render", e)
            _write_personalized_run_state(config, run_date, state)
            raise

    if not _is_stage_completed(config, state, "l1"):
        _mark_stage_in_progress(state, "l1")
        _write_personalized_run_state(config, run_date, state)
        try:
            l1_path = filter_level1_for_date(config, run_date)
            state["stages"]["l1"] = _build_l1_stage_record(l1_path)
            _write_personalized_run_state(config, run_date, state)
        except Exception as e:
            _mark_stage_failed(state, "l1", e)
            _write_personalized_run_state(config, run_date, state)
            raise

    if not _is_stage_completed(config, state, "l2"):
        _mark_stage_in_progress(state, "l2")
        _write_personalized_run_state(config, run_date, state)
        try:
            l2_paths = review_level2_for_date(config, run_date)
            state["stages"]["l2"] = _build_l2_stage_record(l2_paths)
            _write_personalized_run_state(config, run_date, state)
        except Exception as e:
            _mark_stage_failed(state, "l2", e)
            _write_personalized_run_state(config, run_date, state)
            raise

    if not _is_stage_completed(config, state, "digest"):
        _mark_stage_in_progress(state, "digest")
        _write_personalized_run_state(config, run_date, state)
        try:
            digest_path = build_digest_for_date(config, run_date)
            state["stages"]["digest"] = _build_digest_stage_record(digest_path)
            _write_personalized_run_state(config, run_date, state)
        except Exception as e:
            _mark_stage_failed(state, "digest", e)
            _write_personalized_run_state(config, run_date, state)
            raise

    state["status"] = "completed"
    state["completed_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    _write_personalized_run_state(config, run_date, state)


def cmd_filter_l1(config: dict, *, run_date: datetime.date) -> None:
    filter_level1_for_date(config, run_date)


def cmd_review_l2(config: dict, *, run_date: datetime.date) -> None:
    review_level2_for_date(config, run_date)


def cmd_build_digest(config: dict, *, run_date: datetime.date) -> None:
    build_digest_for_date(config, run_date)


def _initial_personalized_run_state(config: dict, run_date: datetime.date) -> dict:
    return {
        "date": run_date.isoformat(),
        "pipeline": "run-personalized",
        "status": "running",
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "completed_at": None,
        "stages": {
            "fetch": {
                "status": "pending",
                "keyword_count": len(config["kv"]),
                "keywords": list(config["kv"].keys()),
            },
            "render": {
                "status": "pending",
            },
            "l1": {
                "status": "pending",
            },
            "l2": {
                "status": "pending",
            },
            "digest": {
                "status": "pending",
            },
        },
    }


def _load_personalized_run_state(config: dict, run_date: datetime.date) -> dict:
    record_path, _ = _personalized_run_record_paths(config, run_date)
    if os.path.exists(record_path):
        return _read_json_file(record_path)
    return _initial_personalized_run_state(config, run_date)


def _write_personalized_run_state(config: dict, run_date: datetime.date, state: dict) -> str:
    record_path, latest_path = _personalized_run_record_paths(config, run_date)
    state["updated_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    runs_dir = config["personalized_runs_dir"]
    os.makedirs(runs_dir, exist_ok=True)
    for path in (record_path, latest_path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    _write_pipeline_stage_logs(config, run_date, state)
    return record_path


def _personalized_run_record_paths(config: dict, run_date: datetime.date) -> tuple[str, str]:
    runs_dir = config["personalized_runs_dir"]
    record_path = os.path.join(runs_dir, f"{run_date.isoformat()}.json")
    latest_path = os.path.join(runs_dir, "latest.json")
    return record_path, latest_path


def _mark_stage_in_progress(state: dict, stage_name: str) -> None:
    state["status"] = "running"
    stage_state = dict(state["stages"].get(stage_name, {}))
    stage_state["status"] = "running"
    stage_state["started_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    stage_state.pop("error", None)
    state["stages"][stage_name] = stage_state


def _mark_stage_failed(state: dict, stage_name: str, error: Exception) -> None:
    state["status"] = "failed"
    stage_state = dict(state["stages"].get(stage_name, {}))
    stage_state["status"] = "failed"
    stage_state["failed_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    stage_state["error"] = {
        "type": error.__class__.__name__,
        "message": str(error),
    }
    state["stages"][stage_name] = stage_state


def _is_stage_completed(config: dict, state: dict, stage_name: str) -> bool:
    stage_state = state.get("stages", {}).get(stage_name, {})
    return stage_state.get("status") == "completed" and _stage_outputs_exist(config, stage_name, stage_state)


def _write_analysis_pool_snapshot(
    config: dict,
    papers_by_topic: dict[str, list[Paper]],
    *,
    snapshot_date: datetime.date,
) -> str:
    papers_by_id: dict[str, dict] = {}
    for topic, papers in papers_by_topic.items():
        for paper in papers:
            existing = papers_by_id.get(paper.paper_id)
            if existing is None:
                existing = {
                    "paper_id": paper.paper_id,
                    "arxiv_short_id": paper.arxiv_short_id,
                    "published_date": paper.update_time.isoformat(),
                    "title": paper.title,
                    "authors": f"{paper.first_author} et.al.",
                    "authors_full": list(paper.authors),
                    "paper_url": paper.paper_url,
                    "pdf_url": paper.pdf_url,
                    "code_link": paper.code_link,
                    "abstract": paper.abstract,
                    "categories": list(paper.categories),
                    "matched_topics": [],
                }
                papers_by_id[paper.paper_id] = existing
            if topic not in existing["matched_topics"]:
                existing["matched_topics"].append(topic)

    papers = sorted(papers_by_id.values(), key=lambda item: item["paper_id"])
    for paper in papers:
        paper["matched_topic"] = ", ".join(paper["matched_topics"])

    output_dir = os.path.join(config["personalized_docs_dir"], "pools")
    os.makedirs(output_dir, exist_ok=True)
    snapshot_path = os.path.join(output_dir, f"{snapshot_date.isoformat()}.json")
    payload = {
        "date": snapshot_date.isoformat(),
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "stats": {
            "topics": len(papers_by_topic),
            "total_topic_hits": sum(len(items) for items in papers_by_topic.values()),
            "unique_papers": len(papers),
        },
        "papers": papers,
    }
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return snapshot_path


def _build_fetch_stage_record(config: dict, analysis_pool_path: str) -> dict:
    payload = _read_json_file(analysis_pool_path)
    return {
        "status": "completed",
        "path": analysis_pool_path,
        "keyword_count": len(config["kv"]),
        "keywords": list(config["kv"].keys()),
        "stats": payload.get("stats", {}),
    }


def _build_render_stage_record(config: dict) -> dict:
    return {
        "status": "completed",
        "artifacts": {
            "readme": config["md_readme_path"] if config.get("publish_readme") else None,
            "gitpage_json": config["json_gitpage_path"] if config.get("publish_gitpage") else None,
        },
    }


def _build_l1_stage_record(l1_path: str) -> dict:
    payload = _read_json_file(l1_path)
    return {
        "status": "completed",
        "path": l1_path,
        "stats": payload.get("stats", {}),
        "paper_ids": [entry["paper"]["paper_id"] for entry in payload.get("papers", [])],
        "level2_candidate_ids": [
            entry["paper"]["paper_id"]
            for entry in payload.get("papers", [])
            if entry.get("l1", {}).get("decision") == "level2"
        ],
    }


def _build_l2_stage_record(l2_paths: list[str]) -> dict:
    reviews = [_read_json_file(path) for path in l2_paths]
    return {
        "status": "completed",
        "paths": l2_paths,
        "stats": {
            "total": len(reviews),
            "reviewed": sum(1 for item in reviews if "review" in item),
            "failed": sum(1 for item in reviews if "error" in item),
        },
        "papers": [
            {
                "paper_id": item["paper"]["paper_id"],
                "title": item["paper"].get("title", ""),
                "status": "reviewed" if "review" in item else "error",
            }
            for item in reviews
        ],
    }


def _build_digest_stage_record(digest_path: str) -> dict:
    log_dir = os.path.dirname(os.path.dirname(digest_path))
    run_date = os.path.splitext(os.path.basename(digest_path))[0]
    digest_log_path = os.path.join(log_dir, "logs", run_date, "digest.json")
    if os.path.exists(digest_log_path):
        payload = _read_json_file(digest_log_path)
        return {
            "status": "completed",
            "path": digest_path,
            "stats": {
                "must_read": payload["summary"]["must_read"],
                "worth_archiving": payload["summary"]["worth_archiving"],
                "review_failures": payload["summary"]["review_failures"],
            },
            "must_read_paper_ids": payload["summary"]["must_read_paper_ids"],
        }

    payload = _read_json_file(digest_path)
    digest = payload.get("digest", {})
    must_read = digest.get("must_read", [])
    worth_archiving = digest.get("worth_archiving", [])
    return {
        "status": "completed",
        "path": digest_path,
        "stats": {
            "must_read": len(must_read),
            "worth_archiving": len(worth_archiving),
            "review_failures": len(payload.get("review_failures", [])),
        },
        "must_read_paper_ids": [item["paper_id"] for item in must_read if "paper_id" in item],
    }


def _write_pipeline_stage_logs(config: dict, run_date: datetime.date, record: dict) -> None:
    stages = record["stages"]
    lines = [
        f"[PIPELINE] date={run_date.isoformat()} pipeline={record['pipeline']} status={record.get('status', 'completed')}",
        "",
        "[Stages]",
        f"- fetch: status={stages['fetch']['status']} keywords={stages['fetch'].get('keyword_count', 0)}",
        f"- render: status={stages['render']['status']}",
        f"- l1: status={stages['l1']['status']} total={stages['l1'].get('stats', {}).get('total_papers', 0)} passed={stages['l1'].get('stats', {}).get('level2', 0)}",
        f"- l2: status={stages['l2']['status']} total={stages['l2'].get('stats', {}).get('total', 0)} reviewed={stages['l2'].get('stats', {}).get('reviewed', 0)} failed={stages['l2'].get('stats', {}).get('failed', 0)}",
        f"- digest: status={stages['digest']['status']} must_read={stages['digest'].get('stats', {}).get('must_read', 0)} worth_archiving={stages['digest'].get('stats', {}).get('worth_archiving', 0)}",
        "",
        "[Highlights]",
        f"- L1 passed paper ids: {', '.join(stages['l1'].get('level2_candidate_ids', [])) or 'none'}",
        f"- Digest must-read paper ids: {', '.join(stages['digest'].get('must_read_paper_ids', [])) or 'none'}",
    ]
    write_stage_log_bundle(
        config,
        run_date,
        "pipeline",
        payload=record,
        text="\n".join(lines),
    )


def _read_json_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _stage_outputs_exist(config: dict, stage_name: str, stage_state: dict) -> bool:
    if stage_name == "fetch":
        path = stage_state.get("path")
        return bool(path and os.path.exists(path))
    if stage_name == "render":
        if config.get("publish_readme"):
            return os.path.exists(config["md_readme_path"])
        return True
    if stage_name == "l1":
        path = stage_state.get("path")
        return bool(path and os.path.exists(path))
    if stage_name == "l2":
        paths = stage_state.get("paths", [])
        return bool(paths) and all(os.path.exists(path) for path in paths)
    if stage_name == "digest":
        path = stage_state.get("path")
        return bool(path and os.path.exists(path))
    return False


def _parse_yyyy_mm(value: str) -> datetime.date:
    """`"2025-08"` → date(2025, 8, 1). Raises argparse-friendly ValueError."""
    try:
        year_str, month_str = value.split("-")
        return datetime.date(int(year_str), int(month_str), 1)
    except (ValueError, AttributeError) as e:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {value!r}") from e


def _parse_yyyy_mm_dd(value: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from e


def _iter_month_ranges(start: datetime.date, end: datetime.date) -> Iterator[tuple[datetime.date, datetime.date]]:
    """Yield (first_of_month, last_of_month) for every month in [start, end].
    Both bounds are normalized to the first of their month before iteration."""
    cur = datetime.date(start.year, start.month, 1)
    end_first = datetime.date(end.year, end.month, 1)
    while cur <= end_first:
        next_first = datetime.date(cur.year + 1, 1, 1) if cur.month == 12 else datetime.date(cur.year, cur.month + 1, 1)
        last = next_first - datetime.timedelta(days=1)
        yield cur, last
        cur = next_first


def cmd_backfill(
    config: dict,
    *,
    start: datetime.date,
    end: datetime.date,
    max_results: int = BACKFILL_DEFAULT_MAX_RESULTS,
    delay_seconds: float = BACKFILL_RATE_LIMIT_SECONDS,
    only_keywords: list[str] | None = None,
) -> None:
    """Fetch every (keyword × month) in [start, end] and merge into the archive.

    Idempotent — the underlying `write_papers_split` re-buckets all known
    papers, so re-running over an already-populated range is safe.

    `max_results` controls per (keyword × month) cap. Defaults to the backfill-
    appropriate ceiling (NOT `config["max_results"]`, which is the daily-fetch
    cap of ~10 — far too low for a months-wide recovery).

    `delay_seconds` overrides the per-request gap to dodge 429s on large runs.
    `only_keywords` restricts fetch to a subset of config keys — useful when
    seeding newly-added tags without re-querying the existing ones.
    """
    keywords = config["kv"]
    keyword_order = list(keywords.keys())
    if only_keywords:
        unknown = [k for k in only_keywords if k not in keywords]
        if unknown:
            raise ValueError(f"Unknown keyword(s) in --keywords: {unknown}. Available: {list(keywords)}")
        keywords = {k: keywords[k] for k in only_keywords}
        logging.info(f"BACKFILL restricted to {len(keywords)} keyword(s): {list(keywords)}")

    months = list(_iter_month_ranges(start, end))
    logging.info(f"BACKFILL begin: {start.isoformat()} → {end.isoformat()} ({len(months)} months)")

    ensure_arxiv_preflight()
    failed_queries: list[str] = []
    for month_start, month_end in months:
        logging.info(f"=== {month_start.strftime('%Y-%m')} ===")
        # Per-month checkpoint: collect this month's results and flush before
        # moving on. A SIGTERM/Ctrl-C mid-run then loses at most the in-flight
        # month, not the whole backfill. write_papers_split is idempotent so
        # restarting the same range merges cleanly.
        month_data: list = []
        month_papers_by_topic: dict[str, list[Paper]] = {}
        for topic, keyword in keywords.items():
            logging.info(f"Keyword: {topic}")
            try:
                papers = fetch_papers_in_range(
                    query=keyword,
                    start=month_start,
                    end=month_end,
                    max_results=max_results,
                    delay_seconds=delay_seconds,
                )
            except Exception as e:
                # One bad keyword × month must not kill the rest of the backfill.
                tag = f"{month_start.strftime('%Y-%m')}/{topic}"
                logging.warning(f"BACKFILL skip {tag}: {e}")
                failed_queries.append(tag)
                continue
            month_papers_by_topic[topic] = papers
            data, _ = papers_to_legacy_rows(papers, topic)
            month_data.append(data)

        if config["publish_readme"] and month_data:
            write_papers_split(
                month_data,
                config["json_readme_path"],
                config["archive_readme_json_dir"],
                keyword_order=keyword_order,
            )
        if config["publish_gitpage"] and month_papers_by_topic:
            docs_dir = os.path.dirname(config["json_gitpage_path"]) or "."
            write_topic_paper_files(month_papers_by_topic, docs_dir)
        logging.info(f"checkpoint flushed for {month_start.strftime('%Y-%m')}")

    if failed_queries:
        logging.warning(f"BACKFILL completed with {len(failed_queries)} skipped queries: " + ", ".join(failed_queries))

    logging.info("BACKFILL render begin")
    cmd_render(config)
    logging.info("BACKFILL done")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nlp_arxiv_daily")
    parser.add_argument(
        "--config_path",
        type=str,
        default="config.yaml",
        help="configuration file path",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="fetch then render (default)")
    personalized = sub.add_parser("run-personalized", help="fetch, render, and build the personalized AI digest")
    personalized.add_argument(
        "--date",
        type=_parse_yyyy_mm_dd,
        default=None,
        help="analysis pool date label in YYYY-MM-DD (default: today)",
    )
    sub.add_parser("fetch", help="fetch arxiv + persist JSON splits")
    sub.add_parser("render", help="render persisted JSON to markdown")
    filter_l1 = sub.add_parser("filter-l1", help="run abstract-level L1 filtering on one analysis pool date")
    filter_l1.add_argument("--date", required=True, type=_parse_yyyy_mm_dd, help="analysis pool date in YYYY-MM-DD")
    review_l2 = sub.add_parser("review-l2", help="run full-paper L2 review on one analysis pool date")
    review_l2.add_argument("--date", required=True, type=_parse_yyyy_mm_dd, help="analysis pool date in YYYY-MM-DD")
    build_digest = sub.add_parser("build-digest", help="build the personalized daily digest for one analysis pool date")
    build_digest.add_argument("--date", required=True, type=_parse_yyyy_mm_dd, help="analysis pool date in YYYY-MM-DD")

    backfill = sub.add_parser("backfill", help="fetch a date range and merge into archive")
    backfill.add_argument(
        "--start",
        required=True,
        type=_parse_yyyy_mm,
        help="start month (inclusive), YYYY-MM",
    )
    backfill.add_argument(
        "--end",
        type=_parse_yyyy_mm,
        default=None,
        help="end month (inclusive), YYYY-MM (default: current month)",
    )
    backfill.add_argument(
        "--max-results",
        type=int,
        default=BACKFILL_DEFAULT_MAX_RESULTS,
        help=f"max results per (keyword × month) query (default: {BACKFILL_DEFAULT_MAX_RESULTS})",
    )
    backfill.add_argument(
        "--delay-seconds",
        type=float,
        default=BACKFILL_RATE_LIMIT_SECONDS,
        help=f"per-request gap to the arxiv API (default: {BACKFILL_RATE_LIMIT_SECONDS}s, minimum enforced: 3.5s).",
    )
    backfill.add_argument(
        "--keywords",
        type=str,
        default=None,
        help="comma-separated subset of config keyword names to backfill (default: all)",
    )
    return parser


def _current_month_first() -> datetime.date:
    today = datetime.date.today()
    return datetime.date(today.year, today.month, 1)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config_path)
    command = args.command or "run"

    try:
        if command == "backfill":
            end = args.end if args.end is not None else _current_month_first()
            only_keywords = [k.strip() for k in args.keywords.split(",")] if args.keywords else None
            cmd_backfill(
                config,
                start=args.start,
                end=end,
                max_results=args.max_results,
                delay_seconds=args.delay_seconds,
                only_keywords=only_keywords,
            )
            return 0
        if command == "run-personalized":
            cmd_run_personalized(config, run_date=args.date)
            return 0
        if command == "filter-l1":
            cmd_filter_l1(config, run_date=args.date)
            return 0
        if command == "review-l2":
            cmd_review_l2(config, run_date=args.date)
            return 0
        if command == "build-digest":
            cmd_build_digest(config, run_date=args.date)
            return 0

        # Resolve handler at call time so tests can monkeypatch cmd_* on this module.
        handler = {"run": cmd_run, "fetch": cmd_fetch, "render": cmd_render}[command]
        handler(config)
        return 0
    except ArxivRateLimitExceeded as e:
        logging.error(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
