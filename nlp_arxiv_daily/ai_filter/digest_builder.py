from __future__ import annotations

import datetime
import json
import logging
import os
from dataclasses import asdict

from nlp_arxiv_daily.ai_filter.analysis_cache import build_cache_namespace, load_stage_cache, save_stage_cache
from nlp_arxiv_daily.ai_filter.profile import load_research_profile
from nlp_arxiv_daily.ai_filter.stage_logging import write_stage_log_bundle
from nlp_arxiv_daily.openai_client import OpenAITextClient


def build_digest_for_date(config: dict, run_date: datetime.date) -> str:
    profile = load_research_profile(config["research_profile_path"])
    l1_path = os.path.join(config["personalized_docs_dir"], "l1", f"{run_date.isoformat()}.json")
    review_dir = os.path.join(config["personalized_docs_dir"], "l2", run_date.isoformat())
    if not os.path.exists(l1_path):
        raise FileNotFoundError(f"Missing L1 result file: {l1_path}. Run filter-l1 first.")
    if not os.path.isdir(review_dir):
        raise FileNotFoundError(f"Missing L2 review directory: {review_dir}. Run review-l2 first.")

    with open(l1_path, encoding="utf-8") as f:
        l1_payload = json.load(f)

    reviews: list[dict] = []
    for filename in sorted(name for name in os.listdir(review_dir) if name.endswith(".json")):
        with open(os.path.join(review_dir, filename), encoding="utf-8") as f:
            reviews.append(json.load(f))

    passed_reviews = [
        item
        for item in reviews
        if "review" in item and item.get("review", {}).get("decision") != "archive_only"
    ]
    passed_reviews.sort(
        key=lambda item: (
            item["review"]["decision"] != "highlight",
            item["review"]["priority"] != "must_read",
            -int(item["review"]["scores"]["relevance"]),
            item["paper"]["paper_id"],
        )
    )
    review_failures = [
        {
            "paper_id": item["paper"]["paper_id"],
            "title": item["paper"]["title"],
            "message": item["error"]["message"],
        }
        for item in reviews
        if "error" in item
    ]
    logging.info(
        "Digest start: %s L2-passed papers and %s review failures for %s.",
        len(passed_reviews),
        len(review_failures),
        run_date.isoformat(),
    )

    prompt_template = _read_text(config["digest_prompt_path"])
    schema = _read_json(config["digest_schema_path"])
    client = OpenAITextClient.from_config(config)
    cache_namespace = build_cache_namespace(
        {
            "stage": "digest",
            "profile": asdict(profile),
            "prompt_template": prompt_template,
            "schema": schema,
        }
    )

    digest_input = {
        "date": run_date.isoformat(),
        "stats": l1_payload["stats"],
        "passed_reviews": passed_reviews,
        "watchlist_candidates": passed_reviews[: profile.output.digest_max_papers],
        "archive_only": [
            {
                "paper_id": entry["paper"]["paper_id"],
                "title": entry["paper"]["title"],
                "matched_topic": entry["paper"]["matched_topic"],
                "archive_reason_cn": entry["l1"].get("archive_reason_cn") or entry["l1"]["reason_cn"],
            }
            for entry in l1_payload["papers"]
            if entry["l1"]["decision"] == "archive_only"
        ][: profile.output.digest_max_papers],
        "review_failures": review_failures,
    }

    prompt = prompt_template.replace("{{digest_input}}", json.dumps(digest_input, ensure_ascii=False, indent=2))
    prompt = prompt.replace("{{language}}", profile.output.language)
    digest_cache_key = build_cache_namespace(_digest_cache_basis(digest_input))
    cached_entry = load_stage_cache(config, "digest", cache_namespace, digest_cache_key)
    if cached_entry is None:
        digest = client.complete_json(
            prompt,
            schema=schema,
            schema_name="daily_digest",
            schema_description="Structured output for the daily personalized research digest.",
        )
        save_stage_cache(
            config,
            "digest",
            cache_namespace,
            digest_cache_key,
            {
                "digest": digest,
                "digest_cache_basis": _digest_cache_basis(digest_input),
            },
        )
    else:
        digest = cached_entry["payload"]["digest"]

    output_dir = os.path.join(config["personalized_docs_dir"], "digest")
    os.makedirs(output_dir, exist_ok=True)
    md_path = os.path.join(output_dir, f"{run_date.isoformat()}.md")

    payload = {
        "date": run_date.isoformat(),
        "stats": digest_input["stats"],
        "digest": digest,
        "review_failures": review_failures,
    }
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_render_digest_markdown(payload, passed_reviews))
    _write_digest_stage_logs(config, run_date, payload)
    logging.info("Digest complete: %s watchlist papers for %s.", len(digest["must_read"]), run_date.isoformat())
    return md_path


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _digest_cache_basis(digest_input: dict) -> dict:
    return _strip_date_fields(digest_input)


def _strip_date_fields(value):
    if isinstance(value, dict):
        return {key: _strip_date_fields(item) for key, item in value.items() if key != "date"}
    if isinstance(value, list):
        return [_strip_date_fields(item) for item in value]
    return value


def _render_digest_markdown(payload: dict, passed_reviews: list[dict]) -> str:
    review_lookup = {item["paper"]["paper_id"]: item for item in passed_reviews}
    digest = payload["digest"]
    lines = [
        f"# Personalized Research Brief - {payload['date']}",
        "",
        f"- 今日检索论文：{payload['stats']['total_papers']} 篇",
        f"- L1 进入二级分析：{payload['stats']['level2']} 篇",
        f"- L2 最终通过：{len(passed_reviews)} 篇",
        f"- 重点关注：{len(digest['must_read'])} 篇",
        "",
        "## 综述",
        "",
        digest["overview_cn"],
        "",
        "## 重点关注清单",
        "",
    ]

    for index, item in enumerate(digest["must_read"], start=1):
        review_item = review_lookup.get(item["paper_id"])
        if review_item is None:
            continue
        review = review_item["review"]
        paper = review_item["paper"]
        lines.extend(
            [
                f"### {index}. {item['title']}",
                "",
                f"摘要：{item['summary_cn']}",
                "",
                f"关注原因：{item['why_relevant_cn']}",
                "",
                f"相关性：{review['scores']['relevance']}/100  ",
                f"可信度：{review['scores']['credibility']}/100  ",
                f"落地性：{review['scores']['landing_feasibility']}/100",
                "",
                f"建议动作：{item['recommended_action_cn']}",
                "",
                "风险：",
            ]
        )
        for risk in review["risks_cn"]:
            lines.append(f"- {risk}")
        lines.extend(
            [
                "",
                "链接：",
                f"- arXiv: {paper['paper_url']}",
                f"- PDF: {paper.get('pdf_url') or ''}",
            ]
        )
        if paper.get("code_link"):
            lines.append(f"- Code: {paper['code_link']}")
        lines.extend(["", "---", ""])

    lines.extend(["## 建议继续跟踪", ""])
    for item in digest["worth_archiving"]:
        lines.append(f"- {item['title']}：{item['reason_cn']}")

    lines.extend(["", "## 今日未优先推进的共性原因", ""])
    for reason in digest["rejected_themes_cn"]:
        lines.append(f"- {reason}")

    if payload["review_failures"]:
        lines.extend(["", "## 本次未完成的二级分析", ""])
        for failure in payload["review_failures"]:
            lines.append(f"- {failure['title']}：{failure['message']}")

    return "\n".join(lines).strip() + "\n"


def _write_digest_stage_logs(config: dict, run_date: datetime.date, payload: dict) -> None:
    digest = payload["digest"]
    summary = {
        "must_read": len(digest["must_read"]),
        "worth_archiving": len(digest["worth_archiving"]),
        "review_failures": len(payload["review_failures"]),
        "must_read_paper_ids": [item["paper_id"] for item in digest["must_read"]],
    }
    log_payload = {
        "stage": "digest",
        "date": run_date.isoformat(),
        "summary": summary,
        "overview_cn": digest["overview_cn"],
        "must_read": digest["must_read"],
        "worth_archiving": digest["worth_archiving"],
        "review_failures": payload["review_failures"],
        "rejected_themes_cn": digest["rejected_themes_cn"],
    }
    lines = [
        f"[DIGEST] date={run_date.isoformat()} must_read={summary['must_read']} worth_archiving={summary['worth_archiving']} review_failures={summary['review_failures']}",
        "",
        "[Overview]",
        digest["overview_cn"],
        "",
        "[Watchlist]",
    ]
    for item in digest["must_read"]:
        lines.append(
            f"- {item['paper_id']} | {item['title']} | why={item['why_relevant_cn']} | action={item['recommended_action_cn']}"
        )
    lines.extend(["", "[Worth Following]"])
    for item in digest["worth_archiving"]:
        lines.append(f"- {item['paper_id']} | {item['title']} | reason={item['reason_cn']}")
    lines.extend(["", "[Rejected Themes]"])
    for item in digest["rejected_themes_cn"]:
        lines.append(f"- {item}")
    if payload["review_failures"]:
        lines.extend(["", "[Review Failures]"])
        for item in payload["review_failures"]:
            lines.append(f"- {item['paper_id']} | {item['title']} | message={item['message']}")
    write_stage_log_bundle(
        config,
        run_date,
        "digest",
        payload=log_payload,
        text="\n".join(lines),
    )
