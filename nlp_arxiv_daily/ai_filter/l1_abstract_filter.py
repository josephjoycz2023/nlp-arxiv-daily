from __future__ import annotations

import copy
import datetime
import json
import logging
import os
from dataclasses import asdict

from nlp_arxiv_daily.ai_filter.analysis_cache import build_cache_namespace, load_stage_cache, save_stage_cache
from nlp_arxiv_daily.ai_filter.profile import ResearchProfile, load_research_profile, render_tracks, trim_profile
from nlp_arxiv_daily.ai_filter.stage_logging import write_stage_log_bundle
from nlp_arxiv_daily.openai_client import OpenAITextClient


LEVEL2_DECISION = "level2"
ARCHIVE_DECISION = "archive_only"
REJECT_DECISION = "reject"


def filter_level1_for_date(config: dict, run_date: datetime.date) -> str:
    profile = load_research_profile(config["research_profile_path"])
    prompt_template = _read_text(config["l1_prompt_path"])
    schema = _read_json(config["l1_schema_path"])
    client = OpenAITextClient.from_config(config)
    cache_namespace = build_cache_namespace(
        {
            "stage": "l1",
            "profile": asdict(profile),
            "prompt_template": prompt_template,
            "schema": schema,
        }
    )

    papers = _load_daily_papers(config, run_date)
    logging.info("L1 start: %s papers queued for %s.", len(papers), run_date.isoformat())
    scored_entries: list[dict] = []
    for index, paper in enumerate(papers, start=1):
        logging.info(
            "L1 progress %s/%s: paper_id=%s title=%s",
            index,
            len(papers),
            paper.get("paper_id", ""),
            paper.get("title", ""),
        )
        cached_entry = load_stage_cache(config, "l1", cache_namespace, paper["paper_id"])
        from_cache = cached_entry is not None
        if cached_entry is None:
            _validate_level1_inputs(paper, run_date)
            prompt = _render_l1_prompt(prompt_template, profile, paper)
            model_output = client.complete_json(
                prompt,
                schema=schema,
                schema_name="l1_score",
                schema_description="Structured output for the abstract-only L1 paper filter.",
            )
            normalized_result = _normalize_l1_result(model_output, profile)
            save_stage_cache(
                config,
                "l1",
                cache_namespace,
                paper["paper_id"],
                {
                    "paper_id": paper["paper_id"],
                    "l1": normalized_result,
                },
            )
        else:
            normalized_result = cached_entry["payload"]["l1"]
        scored_entries.append(
            {
                "paper": paper,
                "l1": copy.deepcopy(normalized_result),
                "analysis_meta": {"from_cache": from_cache},
            }
        )
        logging.info(
            "L1 finished %s/%s: paper_id=%s decision=%s cache=%s",
            index,
            len(papers),
            paper.get("paper_id", ""),
            normalized_result["decision"],
            from_cache,
        )

    _apply_level2_daily_cap(scored_entries, profile)
    scored_entries.sort(
        key=lambda item: (
            item["l1"]["decision"] != LEVEL2_DECISION,
            -item["l1"]["total_score"],
            -item["l1"]["scores"]["topic_relevance"],
            item["paper"]["paper_id"],
        )
    )

    payload = {
        "date": run_date.isoformat(),
        "stats": _level1_stats(scored_entries),
        "papers": scored_entries,
    }

    output_dir = os.path.join(config["personalized_docs_dir"], "l1")
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, f"{run_date.isoformat()}.json")
    md_path = os.path.join(output_dir, f"{run_date.isoformat()}.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_render_l1_markdown(payload))
    _write_l1_stage_logs(config, run_date, payload)
    logging.info("L1 complete: %s passed to L2 for %s.", payload["stats"][LEVEL2_DECISION], run_date.isoformat())
    return json_path


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _docs_root(config: dict) -> str:
    return os.path.dirname(config["json_gitpage_path"]) or "."


def _topic_dir_name(topic: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in topic.strip())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "unknown-topic"


def _load_daily_papers(config: dict, run_date: datetime.date) -> list[dict]:
    analysis_pool_path = os.path.join(config["personalized_docs_dir"], "pools", f"{run_date.isoformat()}.json")
    if os.path.exists(analysis_pool_path):
        with open(analysis_pool_path, encoding="utf-8") as f:
            payload = json.load(f)
        papers = list(payload.get("papers", []))
        for paper in papers:
            matched_topics = list(paper.get("matched_topics", []))
            if matched_topics and not paper.get("matched_topic"):
                paper["matched_topic"] = ", ".join(matched_topics)
        return papers

    docs_root = _docs_root(config)
    snapshot_dir = run_date.strftime("%Y%m%d")
    papers_by_id: dict[str, dict] = {}
    for topic in config["kv"]:
        topic_dir = os.path.join(docs_root, _topic_dir_name(topic), snapshot_dir)
        if not os.path.isdir(topic_dir):
            continue
        for filename in sorted(name for name in os.listdir(topic_dir) if name.endswith(".json")):
            with open(os.path.join(topic_dir, filename), encoding="utf-8") as f:
                paper = json.load(f)
            paper_id = str(paper["paper_id"])
            existing = papers_by_id.get(paper_id)
            if existing is None:
                paper["matched_topics"] = [topic]
                papers_by_id[paper_id] = paper
                continue
            if topic not in existing["matched_topics"]:
                existing["matched_topics"].append(topic)
    papers = list(papers_by_id.values())
    for paper in papers:
        paper["matched_topic"] = ", ".join(paper["matched_topics"])
    if not papers:
        raise FileNotFoundError(
            f"No per-paper snapshots found for {run_date.isoformat()} under {docs_root}. Run fetch first."
        )
    return papers


def _validate_level1_inputs(paper: dict, run_date: datetime.date) -> None:
    if not paper.get("abstract"):
        raise ValueError(
            "Level1 filtering requires abstract metadata in per-paper snapshots. "
            f"Paper {paper.get('paper_id', '<unknown>')} from {run_date.isoformat()} lacks it; "
            "rerun fetch with the AI-enabled snapshot schema."
        )


def _render_l1_prompt(template: str, profile: ResearchProfile, paper: dict) -> str:
    replacements = {
        "{{profile.short}}": trim_profile(profile.short_profile, profile.level1.max_prompt_profile_chars),
        "{{tracks}}": render_tracks(profile),
        "{{title}}": str(paper.get("title", "")).strip(),
        "{{abstract}}": str(paper.get("abstract", "")).strip(),
        "{{categories}}": ", ".join(paper.get("categories", [])),
        "{{matched_topic}}": str(paper.get("matched_topic", "")).strip(),
        "{{authors}}": ", ".join(paper.get("authors_full", [])),
    }
    prompt = template
    for key, value in replacements.items():
        prompt = prompt.replace(key, value)
    return prompt


def _normalize_l1_result(model_output: dict, profile: ResearchProfile) -> dict:
    scores = {
        "topic_relevance": int(model_output["scores"]["topic_relevance"]),
        "scenario_fit": int(model_output["scores"]["scenario_fit"]),
        "landing_potential": int(model_output["scores"]["landing_potential"]),
        "abstract_evidence_strength": int(model_output["scores"]["abstract_evidence_strength"]),
        "distance_penalty": int(model_output["scores"]["distance_penalty"]),
    }
    total_score = (
        scores["topic_relevance"]
        + scores["scenario_fit"]
        + scores["landing_potential"]
        + scores["abstract_evidence_strength"]
        - scores["distance_penalty"]
    )
    thresholds = profile.level1.decision_thresholds

    if scores["topic_relevance"] <= thresholds.reject_below_relevance:
        decision = REJECT_DECISION
        decision_source = "thresholds"
    elif total_score < thresholds.level2_min_total or total_score < thresholds.archive_below_total:
        decision = ARCHIVE_DECISION
        decision_source = "thresholds"
    else:
        decision = LEVEL2_DECISION
        decision_source = "thresholds"

    archive_reason = model_output.get("archive_reason_cn")
    return {
        "decision": decision,
        "model_decision": str(model_output.get("decision", "")).strip(),
        "decision_source": decision_source,
        "matched_tracks": [str(track) for track in model_output.get("matched_tracks", [])],
        "scores": scores,
        "total_score": total_score,
        "model_total_score": int(model_output.get("total_score", total_score)),
        "reason_cn": str(model_output.get("reason_cn", "")).strip(),
        "archive_reason_cn": str(archive_reason).strip() if archive_reason else None,
    }


def _apply_level2_daily_cap(entries: list[dict], profile: ResearchProfile) -> None:
    max_candidates = profile.level1.max_level2_candidates_per_day
    level2_candidates = [entry for entry in entries if entry["l1"]["decision"] == LEVEL2_DECISION]
    level2_candidates.sort(
        key=lambda item: (
            -item["l1"]["total_score"],
            -item["l1"]["scores"]["topic_relevance"],
            item["paper"]["paper_id"],
        )
    )
    for overflow in level2_candidates[max_candidates:]:
        overflow["l1"]["decision"] = ARCHIVE_DECISION
        overflow["l1"]["decision_source"] = "daily_cap"
        overflow["l1"]["archive_reason_cn"] = "超过当日 level2 候选上限，保留到 archive_only。"


def _level1_stats(entries: list[dict]) -> dict[str, int]:
    stats = {"total_papers": len(entries), REJECT_DECISION: 0, ARCHIVE_DECISION: 0, LEVEL2_DECISION: 0}
    for entry in entries:
        stats[entry["l1"]["decision"]] += 1
    return stats


def _render_l1_markdown(payload: dict) -> str:
    lines = [
        f"# Level 1 Filter - {payload['date']}",
        "",
        f"- total papers: {payload['stats']['total_papers']}",
        f"- level2 candidates: {payload['stats'][LEVEL2_DECISION]}",
        f"- archived: {payload['stats'][ARCHIVE_DECISION]}",
        f"- rejected: {payload['stats'][REJECT_DECISION]}",
        "",
        "## Level2 Candidates",
        "",
    ]

    level2_entries = [entry for entry in payload["papers"] if entry["l1"]["decision"] == LEVEL2_DECISION]
    archive_entries = [entry for entry in payload["papers"] if entry["l1"]["decision"] == ARCHIVE_DECISION]

    for entry in level2_entries:
        lines.extend(
            [
                f"- {entry['paper']['title']} ({entry['paper']['paper_id']})",
                f"  - topic: {entry['paper']['matched_topic']}",
                f"  - total_score: {entry['l1']['total_score']}",
                f"  - reason: {entry['l1']['reason_cn']}",
            ]
        )

    lines.extend(["", "## Archived", ""])
    for entry in archive_entries:
        archive_reason = entry["l1"]["archive_reason_cn"] or entry["l1"]["reason_cn"]
        lines.extend(
            [
                f"- {entry['paper']['title']} ({entry['paper']['paper_id']})",
                f"  - reason: {archive_reason}",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def _write_l1_stage_logs(config: dict, run_date: datetime.date, payload: dict) -> None:
    passed_entries = [entry for entry in payload["papers"] if entry["l1"]["decision"] == LEVEL2_DECISION]
    summary = {
        "total_papers": payload["stats"]["total_papers"],
        "passed_l1": len(passed_entries),
        "archived": payload["stats"][ARCHIVE_DECISION],
        "rejected": payload["stats"][REJECT_DECISION],
        "passed_paper_ids": [entry["paper"]["paper_id"] for entry in passed_entries],
    }
    log_payload = {
        "stage": "l1",
        "date": run_date.isoformat(),
        "summary": summary,
        "papers": [
            {
                "paper_id": entry["paper"]["paper_id"],
                "title": entry["paper"]["title"],
                "matched_topic": entry["paper"].get("matched_topic", ""),
                "passed_l1": entry["l1"]["decision"] == LEVEL2_DECISION,
                "decision": entry["l1"]["decision"],
                "total_score": entry["l1"]["total_score"],
                "matched_tracks": entry["l1"]["matched_tracks"],
                "reason_cn": entry["l1"]["reason_cn"],
                "archive_reason_cn": entry["l1"].get("archive_reason_cn"),
                "from_cache": entry.get("analysis_meta", {}).get("from_cache", False),
            }
            for entry in payload["papers"]
        ],
    }
    lines = [
        f"[L1] date={run_date.isoformat()} total={summary['total_papers']} passed={summary['passed_l1']} archived={summary['archived']} rejected={summary['rejected']}",
        "",
        "[Per Paper]",
    ]
    for item in log_payload["papers"]:
        status = "PASS" if item["passed_l1"] else "SKIP"
        reason = item["reason_cn"] if item["passed_l1"] else (item["archive_reason_cn"] or item["reason_cn"])
        lines.append(
            f"- [{status}] {item['paper_id']} | {item['title']} | decision={item['decision']} | score={item['total_score']} | topic={item['matched_topic']} | cache={item['from_cache']} | reason={reason}"
        )
    lines.extend(
        [
            "",
            "[Summary]",
            f"- passed paper ids: {', '.join(summary['passed_paper_ids']) if summary['passed_paper_ids'] else 'none'}",
        ]
    )
    write_stage_log_bundle(
        config,
        run_date,
        "l1",
        payload=log_payload,
        text="\n".join(lines),
    )
