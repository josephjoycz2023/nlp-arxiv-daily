from __future__ import annotations

import copy
import datetime
import json
import os
from dataclasses import asdict

from nlp_arxiv_daily.ai_filter.analysis_cache import build_cache_namespace, load_stage_cache, save_stage_cache
from nlp_arxiv_daily.ai_filter.profile import ResearchProfile, load_research_profile, render_tracks, trim_profile
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
    scored_entries: list[dict] = []
    for paper in papers:
        cached_entry = load_stage_cache(config, "l1", cache_namespace, paper["paper_id"])
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
            }
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
