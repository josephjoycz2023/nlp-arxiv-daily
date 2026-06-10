from __future__ import annotations

import datetime
import json
import logging
import os
from dataclasses import asdict

from nlp_arxiv_daily.ai_filter.analysis_cache import build_cache_namespace, load_stage_cache, save_stage_cache
from nlp_arxiv_daily.ai_filter.pdf_loader import download_pdf_text, paper_url_to_pdf_url
from nlp_arxiv_daily.ai_filter.profile import load_research_profile, render_modules, render_tracks
from nlp_arxiv_daily.ai_filter.section_extractor import extract_review_sections
from nlp_arxiv_daily.ai_filter.stage_logging import write_stage_log_bundle
from nlp_arxiv_daily.openai_client import OpenAIAllKeysFailedError, OpenAIConfigError, OpenAITextClient


def review_level2_for_date(config: dict, run_date: datetime.date) -> list[str]:
    profile = load_research_profile(config["research_profile_path"])
    l1_path = os.path.join(config["personalized_docs_dir"], "l1", f"{run_date.isoformat()}.json")
    if not os.path.exists(l1_path):
        raise FileNotFoundError(f"Missing L1 result file: {l1_path}. Run filter-l1 first.")

    with open(l1_path, encoding="utf-8") as f:
        l1_payload = json.load(f)

    prompt_template = _read_text(config["l2_prompt_path"])
    schema = _read_json(config["l2_schema_path"])
    client = OpenAITextClient.from_config(config)
    cache_namespace = build_cache_namespace(
        {
            "stage": "l2",
            "profile": asdict(profile),
            "prompt_template": prompt_template,
            "schema": schema,
        }
    )

    candidates = [entry for entry in l1_payload["papers"] if entry["l1"]["decision"] == "level2"]
    candidates.sort(key=lambda item: (-item["l1"]["total_score"], item["paper"]["paper_id"]))
    candidates = candidates[: profile.level2.max_papers_per_day]
    logging.info("L2 start: %s L1-passed papers queued for %s.", len(candidates), run_date.isoformat())

    review_dir = os.path.join(config["personalized_docs_dir"], "reviews", run_date.isoformat())
    os.makedirs(review_dir, exist_ok=True)

    written_paths: list[str] = []
    stage_payloads: list[dict] = []
    for index, candidate in enumerate(candidates, start=1):
        paper = candidate["paper"]
        logging.info(
            "L2 progress %s/%s: paper_id=%s title=%s",
            index,
            len(candidates),
            paper.get("paper_id", ""),
            paper.get("title", ""),
        )
        pdf_url = paper.get("pdf_url") or paper_url_to_pdf_url(paper["paper_url"])
        review_path = os.path.join(review_dir, f"{paper['paper_id']}.json")
        cached_entry = load_stage_cache(config, "l2", cache_namespace, paper["paper_id"])
        if cached_entry is not None:
            cached_payload = cached_entry["payload"]
            payload = {
                "date": run_date.isoformat(),
                "paper": paper,
                "l1": candidate["l1"],
                "analysis_meta": {"from_cache": True},
                "review_input": cached_payload["review_input"],
                "review": cached_payload["review"],
            }
            with open(review_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            written_paths.append(review_path)
            stage_payloads.append(payload)
            logging.info(
                "L2 finished %s/%s: paper_id=%s decision=%s cache=%s",
                index,
                len(candidates),
                paper.get("paper_id", ""),
                payload["review"]["decision"],
                True,
            )
            continue
        try:
            paper_text, page_count = download_pdf_text(pdf_url)
            sections, extraction_note, truncated = extract_review_sections(
                paper_text,
                prefer_sections=profile.level2.prefer_sections,
                skip_sections=profile.level2.skip_sections,
            )
            prompt = _render_l2_prompt(
                prompt_template,
                profile.full_profile,
                render_modules(profile),
                render_tracks(profile),
                sections,
            )
            model_output = client.complete_json(
                prompt,
                schema=schema,
                schema_name="l2_review",
                schema_description="Structured output for the full-paper L2 reviewer.",
            )
            payload = {
                "date": run_date.isoformat(),
                "paper": paper,
                "l1": candidate["l1"],
                "analysis_meta": {"from_cache": False},
                "review_input": {
                    "pdf_url": pdf_url,
                    "page_count": page_count,
                    "section_titles": list(sections.keys()),
                    "section_lengths": {name: len(value) for name, value in sections.items()},
                    "section_extraction_note": extraction_note,
                    "truncated_for_prompt": truncated,
                },
                "review": model_output,
            }
            save_stage_cache(
                config,
                "l2",
                cache_namespace,
                paper["paper_id"],
                {
                    "paper_id": paper["paper_id"],
                    "review_input": payload["review_input"],
                    "review": payload["review"],
                },
            )
        except (OpenAIAllKeysFailedError, OpenAIConfigError):
            raise
        except Exception as e:
            payload = {
                "date": run_date.isoformat(),
                "paper": paper,
                "l1": candidate["l1"],
                "analysis_meta": {"from_cache": False},
                "error": {
                    "stage": "l2_review",
                    "message": str(e),
                },
            }

        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        written_paths.append(review_path)
        stage_payloads.append(payload)
        logging.info(
            "L2 finished %s/%s: paper_id=%s status=%s cache=%s",
            index,
            len(candidates),
            paper.get("paper_id", ""),
            payload.get("review", {}).get("decision", "error"),
            False,
        )

    _write_l2_stage_logs(config, run_date, stage_payloads)
    logging.info("L2 complete: %s papers remained actionable for %s.", len([item for item in stage_payloads if item.get("review", {}).get("decision") != "archive_only"]), run_date.isoformat())
    return written_paths


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _render_l2_prompt(
    template: str,
    full_profile: str,
    modules_text: str,
    tracks_text: str,
    sections: dict[str, str],
) -> str:
    prompt = template.replace("{{profile.full}}", full_profile)
    prompt = prompt.replace("{{modules}}", modules_text)
    prompt = prompt.replace("{{tracks}}", tracks_text)
    prompt = prompt.replace("{{paper_sections}}", json.dumps(sections, ensure_ascii=False, indent=2))
    return prompt


def _write_l2_stage_logs(config: dict, run_date: datetime.date, payloads: list[dict]) -> None:
    passed_entries = [
        item for item in payloads if "review" in item and item["review"]["decision"] != "archive_only"
    ]
    log_payload = {
        "stage": "l2",
        "date": run_date.isoformat(),
        "summary": {
            "total_candidates": len(payloads),
            "passed_l2": len(passed_entries),
            "highlight": sum(1 for item in payloads if item.get("review", {}).get("decision") == "highlight"),
            "normal": sum(1 for item in payloads if item.get("review", {}).get("decision") == "normal"),
            "archive_only": sum(1 for item in payloads if item.get("review", {}).get("decision") == "archive_only"),
            "failed": sum(1 for item in payloads if "error" in item),
            "passed_paper_ids": [item["paper"]["paper_id"] for item in passed_entries],
        },
        "papers": [],
    }
    for item in payloads:
        paper = item["paper"]
        if "review" in item:
            review = item["review"]
            log_payload["papers"].append(
                {
                    "paper_id": paper["paper_id"],
                    "title": paper["title"],
                    "passed_l2": review["decision"] != "archive_only",
                    "decision": review["decision"],
                    "priority": review["priority"],
                    "summary_cn": review["summary_cn"],
                    "recommended_action_cn": review["recommended_action_cn"],
                    "relevance": review["scores"]["relevance"],
                    "module_assessments": review.get("module_assessments", []),
                    "from_cache": item.get("analysis_meta", {}).get("from_cache", False),
                }
            )
            continue
        log_payload["papers"].append(
            {
                "paper_id": paper["paper_id"],
                "title": paper["title"],
                "passed_l2": False,
                "decision": "error",
                "priority": "error",
                "summary_cn": item["error"]["message"],
                "recommended_action_cn": "",
                "relevance": None,
                "from_cache": item.get("analysis_meta", {}).get("from_cache", False),
            }
        )

    lines = [
        f"[L2] date={run_date.isoformat()} total={log_payload['summary']['total_candidates']} passed={log_payload['summary']['passed_l2']} highlight={log_payload['summary']['highlight']} normal={log_payload['summary']['normal']} archive_only={log_payload['summary']['archive_only']} failed={log_payload['summary']['failed']}",
        "",
        "[Per Paper]",
    ]
    for item in log_payload["papers"]:
        status = "PASS" if item["passed_l2"] else "SKIP"
        lines.append(
            f"- [{status}] {item['paper_id']} | {item['title']} | decision={item['decision']} | priority={item['priority']} | cache={item['from_cache']} | reason={item['summary_cn']}"
        )
    lines.extend(
        [
            "",
            "[Summary]",
            f"- passed paper ids: {', '.join(log_payload['summary']['passed_paper_ids']) if log_payload['summary']['passed_paper_ids'] else 'none'}",
        ]
    )
    write_stage_log_bundle(
        config,
        run_date,
        "l2",
        payload=log_payload,
        text="\n".join(lines),
    )
