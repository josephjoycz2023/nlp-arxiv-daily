from __future__ import annotations

import datetime
import json
import os

from nlp_arxiv_daily.ai_filter.profile import load_research_profile
from nlp_arxiv_daily.openai_client import OpenAITextClient


def build_digest_for_date(config: dict, run_date: datetime.date) -> str:
    profile = load_research_profile(config["research_profile_path"])
    l1_path = os.path.join(config["personalized_docs_dir"], "l1", f"{run_date.isoformat()}.json")
    review_dir = os.path.join(config["personalized_docs_dir"], "reviews", run_date.isoformat())
    if not os.path.exists(l1_path):
        raise FileNotFoundError(f"Missing L1 result file: {l1_path}. Run filter-l1 first.")
    if not os.path.isdir(review_dir):
        raise FileNotFoundError(f"Missing L2 review directory: {review_dir}. Run review-l2 first.")

    with open(l1_path, encoding="utf-8") as f:
        l1_payload = json.load(f)

    reviews = []
    for filename in sorted(name for name in os.listdir(review_dir) if name.endswith(".json")):
        with open(os.path.join(review_dir, filename), encoding="utf-8") as f:
            reviews.append(json.load(f))

    successful_reviews = [item for item in reviews if "review" in item]
    successful_reviews.sort(
        key=lambda item: (
            item["review"]["decision"] != "highlight",
            item["review"]["priority"] != "must_read",
            -int(item["review"]["scores"]["relevance"]),
            item["paper"]["paper_id"],
        )
    )

    prompt_template = _read_text(config["digest_prompt_path"])
    schema = _read_json(config["digest_schema_path"])
    client = OpenAITextClient.from_config(config)

    digest_input = {
        "date": run_date.isoformat(),
        "stats": l1_payload["stats"],
        "top_reviews": successful_reviews[: profile.output.digest_max_papers],
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
        "review_failures": [
            {
                "paper_id": item["paper"]["paper_id"],
                "title": item["paper"]["title"],
                "message": item["error"]["message"],
            }
            for item in reviews
            if "error" in item
        ],
    }

    prompt = prompt_template.replace("{{digest_input}}", json.dumps(digest_input, ensure_ascii=False, indent=2))
    prompt = prompt.replace("{{language}}", profile.output.language)
    digest = client.complete_json(
        prompt,
        schema=schema,
        schema_name="daily_digest",
        schema_description="Structured output for the daily personalized research digest.",
    )

    output_dir = os.path.join(config["personalized_docs_dir"], "daily")
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, f"{run_date.isoformat()}.json")
    md_path = os.path.join(output_dir, f"{run_date.isoformat()}.md")

    payload = {
        "date": run_date.isoformat(),
        "stats": digest_input["stats"],
        "digest": digest,
        "review_failures": digest_input["review_failures"],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_render_digest_markdown(payload, successful_reviews))
    return json_path


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _render_digest_markdown(payload: dict, successful_reviews: list[dict]) -> str:
    review_lookup = {item["paper"]["paper_id"]: item for item in successful_reviews}
    digest = payload["digest"]
    lines = [
        f"# Personalized Research Brief - {payload['date']}",
        "",
        f"今日检索论文：{payload['stats']['total_papers']} 篇",
        f"一级过滤后存档：{payload['stats']['archive_only']} 篇",
        f"进入二级深读：{payload['stats']['level2']} 篇",
        f"重点推荐：{len(digest['must_read'])} 篇",
        "",
        digest["overview_cn"],
        "",
        "## 今日必读",
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
                f"中文简述：{item['summary_cn']}",
                "",
                f"为什么相关：{item['why_relevant_cn']}",
                "",
                f"相关性：{review['scores']['relevance']}/100  ",
                f"可信性：{review['scores']['credibility']}/100  ",
                f"落地价值：{review['scores']['landing_feasibility']}/100",
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

    lines.extend(["## 值得存档", ""])
    for item in digest["worth_archiving"]:
        lines.append(f"- {item['title']}：{item['reason_cn']}")

    lines.extend(["", "## 今日不进入关注池的主要原因", ""])
    for reason in digest["rejected_themes_cn"]:
        lines.append(f"- {reason}")

    if payload["review_failures"]:
        lines.extend(["", "## 本次未完成的二级深读", ""])
        for failure in payload["review_failures"]:
            lines.append(f"- {failure['title']}：{failure['message']}")

    return "\n".join(lines).strip() + "\n"
