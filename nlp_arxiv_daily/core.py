from __future__ import annotations

import logging
import os
import re
from typing import Any

import yaml

from nlp_arxiv_daily.fetcher import configure_hf_papers, fetch_papers
from nlp_arxiv_daily.types import Paper


logging.basicConfig(format="[%(asctime)s %(levelname)s] %(message)s", datefmt="%m/%d/%Y %H:%M:%S", level=logging.INFO)
for noisy_logger in ("httpx", "httpcore", "openai", "openai._base_client"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def _load_yaml_dict(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    try:
        data = yaml.load(content, Loader=yaml.FullLoader)
    except yaml.YAMLError:
        # Windows paths in double-quoted YAML scalars use backslashes, but YAML
        # interprets them as escapes (`\U`, `\t`, ...). Normalize only after a
        # parse failure so existing POSIX configs remain unchanged.
        normalized = re.sub(
            r'(^\s*[^#\n][^:\n]*:\s*)"([^"\n]*\\[^"\n]*)"',
            lambda match: f'{match.group(1)}"{match.group(2).replace("\\", "/")}"',
            content,
            flags=re.MULTILINE,
        )
        data = yaml.load(normalized, Loader=yaml.FullLoader)
    return data or {}


def _merge_local_config(config: dict, config_file: str) -> dict:
    config_dir = os.path.dirname(os.path.abspath(config_file))
    local_config_file = os.path.join(config_dir, "config.local.yaml")
    if os.path.abspath(config_file) == os.path.abspath(local_config_file) or not os.path.exists(local_config_file):
        return config

    merged = dict(config)
    merged.update(_load_yaml_dict(local_config_file))
    return merged


def _redact_config_for_logging(config: dict) -> dict:
    redacted = dict(config)
    if redacted.get("openai_api_key"):
        redacted["openai_api_key"] = "***redacted***"
    if redacted.get("openai_api_keys"):
        redacted["openai_api_keys"] = ["***redacted***"] * len(redacted["openai_api_keys"])
    if redacted.get("deepseek_api_key"):
        redacted["deepseek_api_key"] = "***redacted***"
    if redacted.get("deepseek_api_keys"):
        redacted["deepseek_api_keys"] = ["***redacted***"] * len(redacted["deepseek_api_keys"])
    return redacted


def _normalize_api_key_candidates(*values: Any) -> list[str]:
    candidates: list[str] = []

    def add_candidate(value: Any) -> None:
        if isinstance(value, str):
            parts = [part.strip() for part in re.split(r"[\r\n,;]+", value) if part.strip()]
            for part in parts:
                if part not in candidates:
                    candidates.append(part)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                add_candidate(item)

    for value in values:
        add_candidate(value)
    return candidates


def papers_to_legacy_rows(papers: list[Paper], topic: str) -> tuple[dict, dict]:
    """Render a list[Paper] into ({topic: {paper_id: row}}, {topic: {paper_id: web_row}}).

    Shared by `get_daily_papers` (daily cron) and `cli.cmd_backfill` so both
    persist data in the same JSON shape the renderer expects.
    """
    content: dict[str, str] = {}
    content_to_web: dict[str, str] = {}
    for p in papers:
        code_md = f"**[link]({p.code_link})**" if p.code_link else "null"
        content[p.paper_id] = (
            f"|**{p.update_time}**|**{p.title}**|{p.first_author} et.al."
            f"|[{p.arxiv_short_id}]({p.paper_url})|{code_md}|\n"
        )
        web_line = f"- {p.update_time}, **{p.title}**, {p.first_author} et.al., Paper: [{p.paper_url}]({p.paper_url})"
        if p.code_link:
            web_line += f", Code: **[{p.code_link}]({p.code_link})**"
        content_to_web[p.paper_id] = web_line + "\n"

    return {topic: content}, {topic: content_to_web}


def load_config(config_file: str) -> dict:
    """
    config_file: input config file path
    return: a dict of configuration
    """

    # make filters pretty
    def pretty_filters(**config) -> dict:
        keywords = {}
        EXCAPE = '"'
        QUOTA = ""  # NO-USE
        # Whitespace around OR is required — arxiv parses `NLPOR"..."` as a
        # single token, which yields no results and triggers 429s on retry.
        OR = " OR "

        def parse_filters(filters: list):
            ret = ""
            for idx in range(0, len(filters)):
                filter = filters[idx]
                if len(filter.split()) > 1:
                    ret += EXCAPE + filter + EXCAPE
                else:
                    ret += QUOTA + filter + QUOTA
                if idx != len(filters) - 1:
                    ret += OR
            return ret

        for k, v in config["keywords"].items():
            keywords[k] = parse_filters(v["filters"])
        return keywords

    config = _load_yaml_dict(config_file)
    config = _merge_local_config(config, config_file)
    config.setdefault("openai_api_key", os.getenv("OPENAI_API_KEY", ""))
    config.setdefault("openai_api_keys", os.getenv("OPENAI_API_KEYS", ""))
    config.setdefault("analysis_request_timeout_seconds", 45)
    config.setdefault("openai_model", "gpt-5-mini")
    config.setdefault("openai_base_url", "https://api.openai.com/v1")
    config.setdefault("openai_timeout", int(config["analysis_request_timeout_seconds"]))
    config.setdefault("openai_instructions", "")
    config.setdefault("llm_provider", "openai")
    config.setdefault("deepseek_api_key", os.getenv("DEEPSEEK_API_KEY", ""))
    config.setdefault("deepseek_api_keys", os.getenv("DEEPSEEK_API_KEYS", ""))
    config.setdefault("deepseek_model", "deepseek-v4-pro")
    config.setdefault("deepseek_base_url", "https://api.deepseek.com")
    config.setdefault("deepseek_timeout", int(config["analysis_request_timeout_seconds"]))
    config.setdefault("deepseek_instructions", "")
    config.setdefault("deepseek_reasoning_effort", "high")
    config.setdefault("deepseek_thinking_enabled", True)
    config.setdefault("research_profile_path", "configs/research_profile.yaml")
    config.setdefault("personalized_docs_dir", "./docs/personalized")
    config.setdefault("analysis_cache_dir", os.path.join(config["personalized_docs_dir"], "cache"))
    config.setdefault("personalized_runs_dir", os.path.join(config["personalized_docs_dir"], "runs"))
    config.setdefault("personalized_logs_dir", os.path.join(config["personalized_docs_dir"], "logs"))
    config.setdefault("l1_prompt_path", "prompts/l1_abstract_filter.md")
    config.setdefault("l2_prompt_path", "prompts/l2_paper_review.md")
    config.setdefault("digest_prompt_path", "prompts/daily_digest.md")
    config.setdefault("l1_schema_path", "schemas/l1_score.schema.json")
    config.setdefault("l2_schema_path", "schemas/l2_review.schema.json")
    config.setdefault("digest_schema_path", "schemas/digest.schema.json")
    config.setdefault("enable_hf_papers", True)
    config["openai_api_keys"] = _normalize_api_key_candidates(config.get("openai_api_keys", ""), config["openai_api_key"])
    config["deepseek_api_keys"] = _normalize_api_key_candidates(
        config.get("deepseek_api_keys", ""),
        config["deepseek_api_key"],
    )
    configure_hf_papers(config["enable_hf_papers"])
    config["kv"] = pretty_filters(**config)
    logging.info(f"config = {_redact_config_for_logging(config)}")
    return config


def get_daily_papers(topic, query="nlp", max_results=2):
    """
    Backward-compat adapter: fetch via `fetcher.fetch_papers`, then pre-render
    markdown rows in the legacy shape. Used by `cli.cmd_fetch` to keep the
    JSON files in the existing format the renderer expects.
    """
    papers = fetch_papers(query=query, max_results=max_results)
    return papers_to_legacy_rows(papers, topic)


def demo(**config) -> None:
    """Backward-compat alias for `cli.cmd_run`. Prefer the CLI entrypoint."""
    from nlp_arxiv_daily.cli import cmd_run

    cmd_run(config)
