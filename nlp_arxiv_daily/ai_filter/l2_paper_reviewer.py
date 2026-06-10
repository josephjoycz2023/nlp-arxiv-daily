from __future__ import annotations

import datetime
import json
import os
from dataclasses import asdict

from nlp_arxiv_daily.ai_filter.analysis_cache import build_cache_namespace, load_stage_cache, save_stage_cache
from nlp_arxiv_daily.ai_filter.pdf_loader import download_pdf_text, paper_url_to_pdf_url
from nlp_arxiv_daily.ai_filter.profile import load_research_profile, render_tracks
from nlp_arxiv_daily.ai_filter.section_extractor import extract_review_sections
from nlp_arxiv_daily.openai_client import OpenAITextClient


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

    review_dir = os.path.join(config["personalized_docs_dir"], "reviews", run_date.isoformat())
    os.makedirs(review_dir, exist_ok=True)

    written_paths: list[str] = []
    for candidate in candidates:
        paper = candidate["paper"]
        pdf_url = paper.get("pdf_url") or paper_url_to_pdf_url(paper["paper_url"])
        review_path = os.path.join(review_dir, f"{paper['paper_id']}.json")
        cached_entry = load_stage_cache(config, "l2", cache_namespace, paper["paper_id"])
        if cached_entry is not None:
            cached_payload = cached_entry["payload"]
            payload = {
                "date": run_date.isoformat(),
                "paper": paper,
                "l1": candidate["l1"],
                "review_input": cached_payload["review_input"],
                "review": cached_payload["review"],
            }
            with open(review_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            written_paths.append(review_path)
            continue
        try:
            paper_text, page_count = download_pdf_text(pdf_url)
            sections, extraction_note, truncated = extract_review_sections(
                paper_text,
                prefer_sections=profile.level2.prefer_sections,
                skip_sections=profile.level2.skip_sections,
            )
            prompt = _render_l2_prompt(prompt_template, profile.full_profile, render_tracks(profile), sections)
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
        except Exception as e:
            payload = {
                "date": run_date.isoformat(),
                "paper": paper,
                "l1": candidate["l1"],
                "error": {
                    "stage": "l2_review",
                    "message": str(e),
                },
            }

        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        written_paths.append(review_path)

    return written_paths


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _render_l2_prompt(template: str, full_profile: str, tracks_text: str, sections: dict[str, str]) -> str:
    prompt = template.replace("{{profile.full}}", full_profile)
    prompt = prompt.replace("{{tracks}}", tracks_text)
    prompt = prompt.replace("{{paper_sections}}", json.dumps(sections, ensure_ascii=False, indent=2))
    return prompt
