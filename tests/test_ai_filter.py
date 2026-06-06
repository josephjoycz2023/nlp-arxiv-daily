from __future__ import annotations

import datetime
import json
import textwrap
from pathlib import Path

import pytest

from nlp_arxiv_daily.ai_filter.digest_builder import build_digest_for_date
from nlp_arxiv_daily.ai_filter.l1_abstract_filter import (
    _apply_level2_daily_cap,
    _normalize_l1_result,
    filter_level1_for_date,
)
from nlp_arxiv_daily.ai_filter.l2_paper_reviewer import review_level2_for_date
from nlp_arxiv_daily.ai_filter.pdf_loader import download_pdf_text, paper_url_to_pdf_url
from nlp_arxiv_daily.ai_filter.profile import load_research_profile
from nlp_arxiv_daily.ai_filter.section_extractor import extract_review_sections


class _FakeClient:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = []

    def complete_json(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return self._outputs.pop(0)


@pytest.fixture
def ai_workspace(tmp_path):
    docs_dir = tmp_path / "docs"
    topic_dir = docs_dir / "agent" / "20260606"
    topic_dir.mkdir(parents=True)
    (topic_dir / "2606.00001.json").write_text(
        json.dumps(
            {
                "paper_id": "2606.00001",
                "arxiv_short_id": "2606.00001v1",
                "published_date": "2026-06-06",
                "title": "Memory Agent",
                "authors": "Alice et.al.",
                "authors_full": ["Alice", "Bob"],
                "paper_url": "http://arxiv.org/abs/2606.00001v1",
                "pdf_url": "http://arxiv.org/pdf/2606.00001v1.pdf",
                "code_link": None,
                "abstract": "A paper about long-term memory for agents with experiments.",
                "categories": ["cs.CL", "cs.AI"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "l1.md").write_text("{{profile.short}}\n{{tracks}}\n{{title}}\n{{abstract}}\n{{categories}}\n{{matched_topic}}", encoding="utf-8")
    (prompts_dir / "l2.md").write_text("{{profile.full}}\n{{tracks}}\n{{paper_sections}}", encoding="utf-8")
    (prompts_dir / "digest.md").write_text("{{language}}\n{{digest_input}}", encoding="utf-8")

    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()
    for name in ("l1.json", "l2.json", "digest.json"):
        (schemas_dir / name).write_text("{}", encoding="utf-8")

    profile_path = tmp_path / "research_profile.yaml"
    profile_path.write_text(
        textwrap.dedent(
            """
            profile:
              short: "focus on memory agents"
              full: "focus on memory agents and productization"
            tracks:
              - id: memory_personalization
                name: memory
                include: ["memory"]
                exclude: ["biology"]
            level1:
              max_prompt_profile_chars: 350
              decision_thresholds:
                reject_below_relevance: 1
                archive_below_total: 6
                level2_min_total: 8
              max_level2_candidates_per_day: 8
            level2:
              max_papers_per_day: 5
              skip_sections: ["introduction", "related work"]
              prefer_sections: ["abstract", "method", "experiments", "results", "conclusion"]
            output:
              language: Chinese
              digest_max_papers: 5
              include_archive_summary: true
            """
        ).strip(),
        encoding="utf-8",
    )

    personalized_dir = tmp_path / "personalized"
    config = {
        "kv": {"agent": "LLM Agent"},
        "json_gitpage_path": str(docs_dir / "main-web.json"),
        "personalized_docs_dir": str(personalized_dir),
        "research_profile_path": str(profile_path),
        "l1_prompt_path": str(prompts_dir / "l1.md"),
        "l2_prompt_path": str(prompts_dir / "l2.md"),
        "digest_prompt_path": str(prompts_dir / "digest.md"),
        "l1_schema_path": str(schemas_dir / "l1.json"),
        "l2_schema_path": str(schemas_dir / "l2.json"),
        "digest_schema_path": str(schemas_dir / "digest.json"),
        "openai_api_key": "test-key",
        "openai_model": "gpt-5-mini",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_timeout": 30,
        "openai_instructions": "",
    }
    return config


def test_load_research_profile(ai_workspace):
    profile = load_research_profile(ai_workspace["research_profile_path"])
    assert profile.short_profile == "focus on memory agents"
    assert profile.level1.max_level2_candidates_per_day == 8


def test_level1_filter_writes_output(ai_workspace, monkeypatch):
    fake_client = _FakeClient(
        [
            {
                "decision": "level2",
                "matched_tracks": ["memory_personalization"],
                "scores": {
                    "topic_relevance": 4,
                    "scenario_fit": 4,
                    "landing_potential": 3,
                    "abstract_evidence_strength": 3,
                    "distance_penalty": 0
                },
                "total_score": 14,
                "reason_cn": "高度相关。",
                "archive_reason_cn": None
            }
        ]
    )
    monkeypatch.setattr(
        "nlp_arxiv_daily.ai_filter.l1_abstract_filter.OpenAITextClient.from_config",
        lambda config: fake_client,
    )

    path = filter_level1_for_date(ai_workspace, datetime.date(2026, 6, 6))

    payload = json.loads(open(path, encoding="utf-8").read())
    assert payload["stats"]["level2"] == 1
    assert payload["papers"][0]["l1"]["decision"] == "level2"


def test_level1_filter_requires_abstract(ai_workspace, monkeypatch):
    snapshot_path = Path(ai_workspace["json_gitpage_path"]).parent / "agent" / "20260606" / "2606.00001.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["abstract"] = ""
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "nlp_arxiv_daily.ai_filter.l1_abstract_filter.OpenAITextClient.from_config",
        lambda config: _FakeClient([]),
    )

    with pytest.raises(ValueError):
        filter_level1_for_date(ai_workspace, datetime.date(2026, 6, 6))


def test_extract_review_sections_falls_back_and_truncates():
    sections, note, truncated = extract_review_sections("plain text only " * 4000, prefer_sections=("abstract",), skip_sections=())
    assert "full_text_excerpt" in sections
    assert note is not None
    assert truncated is True


def test_extract_review_sections_prefers_named_sections():
    text = """
Abstract
This is the abstract.
Introduction
Ignore this.
Method
This is the method.
Results
This is the result.
Conclusion
This is the conclusion.
"""
    sections, note, truncated = extract_review_sections(
        text,
        prefer_sections=("abstract", "method", "results", "conclusion"),
        skip_sections=("introduction", "related work"),
    )
    assert sections["abstract"] == "This is the abstract."
    assert sections["method"] == "This is the method."
    assert note is None
    assert truncated is False


def test_normalize_l1_result_and_daily_cap(ai_workspace):
    profile = load_research_profile(ai_workspace["research_profile_path"])
    result = _normalize_l1_result(
        {
            "decision": "level2",
            "matched_tracks": ["memory_personalization"],
            "scores": {
                "topic_relevance": 4,
                "scenario_fit": 4,
                "landing_potential": 4,
                "abstract_evidence_strength": 4,
                "distance_penalty": 0,
            },
            "total_score": 16,
            "reason_cn": "strong",
            "archive_reason_cn": None,
        },
        profile,
    )
    assert result["decision"] == "level2"

    entries = [
        {"paper": {"paper_id": "2606.00001"}, "l1": dict(result)},
        {"paper": {"paper_id": "2606.00002"}, "l1": dict(result)},
    ]
    tiny_profile = load_research_profile(ai_workspace["research_profile_path"])
    tiny_profile = tiny_profile.__class__(
        short_profile=tiny_profile.short_profile,
        full_profile=tiny_profile.full_profile,
        tracks=tiny_profile.tracks,
        level1=tiny_profile.level1.__class__(
            max_prompt_profile_chars=tiny_profile.level1.max_prompt_profile_chars,
            decision_thresholds=tiny_profile.level1.decision_thresholds,
            max_level2_candidates_per_day=1,
        ),
        level2=tiny_profile.level2,
        output=tiny_profile.output,
    )
    _apply_level2_daily_cap(entries, tiny_profile)
    assert entries[0]["l1"]["decision"] == "level2"
    assert entries[1]["l1"]["decision"] == "archive_only"
    assert entries[1]["l1"]["decision_source"] == "daily_cap"


def test_pdf_loader_downloads_and_extracts_text(monkeypatch):
    sleeps = []
    monkeypatch.setattr("nlp_arxiv_daily.ai_filter.pdf_loader.time.monotonic", lambda: 1000.0)
    monkeypatch.setattr("nlp_arxiv_daily.ai_filter.pdf_loader.time.sleep", lambda seconds: sleeps.append(seconds))

    class _Response:
        content = b"%PDF-fake"

        def raise_for_status(self):
            pass

    class _FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _FakeReader:
        def __init__(self, stream):
            self.pages = [_FakePage("first page"), _FakePage("second page")]

    monkeypatch.setattr("nlp_arxiv_daily.ai_filter.pdf_loader.requests.get", lambda url, timeout: _Response())
    monkeypatch.setattr("nlp_arxiv_daily.ai_filter.pdf_loader.PdfReader", _FakeReader)

    text, page_count = download_pdf_text("http://arxiv.org/pdf/2606.00001v1.pdf")

    assert "first page" in text
    assert page_count == 2
    assert paper_url_to_pdf_url("http://arxiv.org/abs/2606.00001v1") == "http://arxiv.org/pdf/2606.00001v1.pdf"


def test_l2_review_writes_error_payload_when_pdf_fails(ai_workspace, monkeypatch):
    l1_dir = Path(ai_workspace["personalized_docs_dir"]) / "l1"
    l1_dir.mkdir(parents=True)
    (l1_dir / "2026-06-06.json").write_text(
        json.dumps(
            {
                "date": "2026-06-06",
                "stats": {"total_papers": 1, "reject": 0, "archive_only": 0, "level2": 1},
                "papers": [
                    {
                        "paper": json.loads(
                            (
                                Path(ai_workspace["json_gitpage_path"]).parent
                                / "agent"
                                / "20260606"
                                / "2606.00001.json"
                            ).read_text(encoding="utf-8")
                        )
                        | {"matched_topic": "agent"},
                        "l1": {"decision": "level2", "total_score": 12}
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "nlp_arxiv_daily.ai_filter.l2_paper_reviewer.download_pdf_text",
        lambda pdf_url: (_ for _ in ()).throw(RuntimeError("pdf failed")),
    )
    monkeypatch.setattr(
        "nlp_arxiv_daily.ai_filter.l2_paper_reviewer.OpenAITextClient.from_config",
        lambda config: _FakeClient([]),
    )

    paths = review_level2_for_date(ai_workspace, datetime.date(2026, 6, 6))

    payload = json.loads(open(paths[0], encoding="utf-8").read())
    assert payload["error"]["message"] == "pdf failed"


def test_l2_review_writes_success_payload(ai_workspace, monkeypatch):
    l1_dir = Path(ai_workspace["personalized_docs_dir"]) / "l1"
    l1_dir.mkdir(parents=True)
    paper_payload = json.loads(
        (Path(ai_workspace["json_gitpage_path"]).parent / "agent" / "20260606" / "2606.00001.json").read_text(
            encoding="utf-8"
        )
    )
    (l1_dir / "2026-06-06.json").write_text(
        json.dumps(
            {
                "date": "2026-06-06",
                "stats": {"total_papers": 1, "reject": 0, "archive_only": 0, "level2": 1},
                "papers": [
                    {
                        "paper": paper_payload | {"matched_topic": "agent"},
                        "l1": {"decision": "level2", "total_score": 12}
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "nlp_arxiv_daily.ai_filter.l2_paper_reviewer.download_pdf_text",
        lambda pdf_url: ("Abstract\nA\nMethod\nB\nResults\nC\nConclusion\nD", 4),
    )
    fake_client = _FakeClient(
        [
            {
                "decision": "highlight",
                "priority": "must_read",
                "summary_cn": "summary",
                "research_goal_cn": "goal",
                "method_cn": "method",
                "experiment_cn": "experiment",
                "result_cn": "result",
                "landing_value_cn": "landing",
                "scores": {
                    "relevance": 90,
                    "credibility": 80,
                    "landing_feasibility": 85,
                    "actionability": 88
                },
                "risks_cn": ["risk"],
                "recommended_action_cn": "act"
            }
        ]
    )
    monkeypatch.setattr(
        "nlp_arxiv_daily.ai_filter.l2_paper_reviewer.OpenAITextClient.from_config",
        lambda config: fake_client,
    )

    paths = review_level2_for_date(ai_workspace, datetime.date(2026, 6, 6))

    payload = json.loads(open(paths[0], encoding="utf-8").read())
    assert payload["review"]["decision"] == "highlight"
    assert payload["review_input"]["page_count"] == 4


def test_digest_builder_writes_markdown(ai_workspace, monkeypatch):
    personalized_root = Path(ai_workspace["personalized_docs_dir"])
    (personalized_root / "l1").mkdir(parents=True)
    (personalized_root / "reviews" / "2026-06-06").mkdir(parents=True)
    (personalized_root / "l1" / "2026-06-06.json").write_text(
        json.dumps(
            {
                "date": "2026-06-06",
                "stats": {"total_papers": 1, "reject": 0, "archive_only": 0, "level2": 1},
                "papers": []
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (personalized_root / "reviews" / "2026-06-06" / "2606.00001.json").write_text(
        json.dumps(
            {
                "date": "2026-06-06",
                "paper": {
                    "paper_id": "2606.00001",
                    "title": "Memory Agent",
                    "paper_url": "http://arxiv.org/abs/2606.00001v1",
                    "pdf_url": "http://arxiv.org/pdf/2606.00001v1.pdf",
                    "code_link": "https://github.com/acme/memory-agent"
                },
                "review": {
                    "decision": "highlight",
                    "priority": "must_read",
                    "summary_cn": "summary",
                    "research_goal_cn": "goal",
                    "method_cn": "method",
                    "experiment_cn": "experiment",
                    "result_cn": "result",
                    "landing_value_cn": "landing",
                    "scores": {
                        "relevance": 90,
                        "credibility": 80,
                        "landing_feasibility": 85,
                        "actionability": 88
                    },
                    "risks_cn": ["risk"],
                    "recommended_action_cn": "act"
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (personalized_root / "reviews" / "2026-06-06" / "2606.00002.json").write_text(
        json.dumps(
            {
                "date": "2026-06-06",
                "paper": {"paper_id": "2606.00002", "title": "Broken Review"},
                "error": {"message": "pdf parse failed"}
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fake_client = _FakeClient(
        [
            {
                "overview_cn": "overview",
                "must_read": [
                    {
                        "paper_id": "2606.00001",
                        "title": "Memory Agent",
                        "summary_cn": "summary",
                        "why_relevant_cn": "relevant",
                        "recommended_action_cn": "act"
                    }
                ],
                "worth_archiving": [],
                "rejected_themes_cn": ["too benchmark-heavy"]
            }
        ]
    )
    monkeypatch.setattr(
        "nlp_arxiv_daily.ai_filter.digest_builder.OpenAITextClient.from_config",
        lambda config: fake_client,
    )

    json_path = build_digest_for_date(ai_workspace, datetime.date(2026, 6, 6))

    payload = json.loads(open(json_path, encoding="utf-8").read())
    assert payload["digest"]["overview_cn"] == "overview"
    markdown = (personalized_root / "daily" / "2026-06-06.md").read_text(encoding="utf-8")
    assert "https://github.com/acme/memory-agent" in markdown
    assert "pdf parse failed" in markdown
