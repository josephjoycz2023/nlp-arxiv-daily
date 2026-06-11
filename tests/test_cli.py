"""CLI dispatch tests.

The hard guarantee: `render`-only must NOT make network calls (it only reads
persisted JSON), and `fetch`-only must NOT touch markdown. The cron path
(`run`) calls both in order.
"""

from __future__ import annotations

import datetime
import json
import textwrap
from pathlib import Path

import pytest

from nlp_arxiv_daily import cli
from nlp_arxiv_daily.fetcher import ArxivRateLimitExceeded
from nlp_arxiv_daily.openai_client import OpenAIConfigError
from nlp_arxiv_daily.types import Paper


@pytest.fixture
def fake_config_file(tmp_path):
    json_dir = tmp_path / "docs"
    json_dir.mkdir()
    archive_dir = json_dir / "archive"
    archive_web_dir = json_dir / "archive-web"
    archive_dir.mkdir()
    archive_web_dir.mkdir()
    # Empty JSON files so render() has something to read
    (json_dir / "main.json").write_text("{}")
    (json_dir / "main-web.json").write_text("{}")

    json_main = (json_dir / "main.json").as_posix()
    json_main_web = (json_dir / "main-web.json").as_posix()
    readme_path = (tmp_path / "README.md").as_posix()
    md_gitpage_path = (json_dir / "index.md").as_posix()
    archive_dir_path = archive_dir.as_posix()
    archive_web_dir_path = archive_web_dir.as_posix()

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            user_name: "alice"
            repo_name: "my-repo"
            show_authors: true
            show_links: true
            show_badge: false
            max_results: 1
            publish_readme: true
            publish_gitpage: true
            json_readme_path: "{json_main}"
            json_gitpage_path: "{json_main_web}"
            md_readme_path: "{readme_path}"
            md_gitpage_path: "{md_gitpage_path}"
            archive_readme_json_dir: "{archive_dir_path}"
            archive_readme_md_dir: "{archive_dir_path}"
            archive_gitpage_json_dir: "{archive_web_dir_path}"
            archive_gitpage_md_dir: "{archive_web_dir_path}"
            keywords:
              "NLP":
                filters: ["NLP"]
            """
        ).strip()
    )
    return str(cfg)


class TestArgparser:
    def test_no_subcommand_defaults_to_run(self):
        ns = cli.build_parser().parse_args([])
        assert ns.command is None  # main() coerces to "run"

    def test_subcommands_recognized(self):
        ns = cli.build_parser().parse_args(["run"])
        assert ns.command == "run"
        ns = cli.build_parser().parse_args(["fetch"])
        assert ns.command == "fetch"
        ns = cli.build_parser().parse_args(["render"])
        assert ns.command == "render"
        ns = cli.build_parser().parse_args(["run-personalized"])
        assert ns.command == "run-personalized"
        ns = cli.build_parser().parse_args(["filter-l1", "--date", "2026-06-06"])
        assert ns.command == "filter-l1"
        ns = cli.build_parser().parse_args(["review-l2", "--date", "2026-06-06"])
        assert ns.command == "review-l2"
        ns = cli.build_parser().parse_args(["build-digest", "--date", "2026-06-06"])
        assert ns.command == "build-digest"
        ns = cli.build_parser().parse_args(["run-scheduler"])
        assert ns.command == "run-scheduler"

    def test_config_path_default(self):
        ns = cli.build_parser().parse_args([])
        assert ns.config_path == "config.yaml"

    def test_config_path_override(self):
        ns = cli.build_parser().parse_args(["--config_path", "x.yaml", "fetch"])
        assert ns.config_path == "x.yaml"

    def test_backfill_delay_seconds_accepts_float(self):
        ns = cli.build_parser().parse_args(["backfill", "--start", "2025-08", "--delay-seconds", "3.5"])
        assert ns.delay_seconds == 3.5

    def test_parse_yyyy_mm_dd(self):
        assert cli._parse_yyyy_mm_dd("2026-06-06") == datetime.date(2026, 6, 6)


class TestDispatch:
    def test_main_no_subcommand_dispatches_run(self, monkeypatch, fake_config_file):
        called = []
        monkeypatch.setattr(cli, "cmd_run", lambda config: called.append(("run", config)))
        cli.main(["--config_path", fake_config_file])
        assert len(called) == 1
        assert called[0][0] == "run"

    def test_main_render_dispatches_render(self, monkeypatch, fake_config_file):
        called = []
        monkeypatch.setattr(cli, "cmd_render", lambda config: called.append(("render", config)))
        cli.main(["--config_path", fake_config_file, "render"])
        assert called and called[0][0] == "render"

    def test_main_fetch_dispatches_fetch(self, monkeypatch, fake_config_file):
        called = []
        monkeypatch.setattr(cli, "cmd_fetch", lambda config: called.append(("fetch", config)))
        cli.main(["--config_path", fake_config_file, "fetch"])
        assert called and called[0][0] == "fetch"

    def test_main_filter_l1_dispatches(self, monkeypatch, fake_config_file):
        called = []
        monkeypatch.setattr(cli, "cmd_filter_l1", lambda config, *, run_date: called.append(("filter-l1", run_date)))
        cli.main(["--config_path", fake_config_file, "filter-l1", "--date", "2026-06-06"])
        assert called == [("filter-l1", datetime.date(2026, 6, 6))]

    def test_main_run_personalized_dispatches(self, monkeypatch, fake_config_file):
        called = []
        monkeypatch.setattr(cli, "cmd_run_personalized", lambda config, *, run_date: called.append(("run-personalized", run_date)))
        cli.main(["--config_path", fake_config_file, "run-personalized", "--date", "2026-06-06"])
        assert called == [("run-personalized", datetime.date(2026, 6, 6))]

    def test_main_review_l2_dispatches(self, monkeypatch, fake_config_file):
        called = []
        monkeypatch.setattr(cli, "cmd_review_l2", lambda config, *, run_date: called.append(("review-l2", run_date)))
        cli.main(["--config_path", fake_config_file, "review-l2", "--date", "2026-06-06"])
        assert called == [("review-l2", datetime.date(2026, 6, 6))]

    def test_main_build_digest_dispatches(self, monkeypatch, fake_config_file):
        called = []
        monkeypatch.setattr(cli, "cmd_build_digest", lambda config, *, run_date: called.append(("build-digest", run_date)))
        cli.main(["--config_path", fake_config_file, "build-digest", "--date", "2026-06-06"])
        assert called == [("build-digest", datetime.date(2026, 6, 6))]

    def test_main_run_scheduler_dispatches(self, monkeypatch, fake_config_file):
        called = []
        monkeypatch.setattr(cli, "cmd_run_scheduler", lambda config, *, poll_seconds: called.append(("run-scheduler", poll_seconds)))
        cli.main(["--config_path", fake_config_file, "run-scheduler", "--poll-seconds", "12"])
        assert called == [("run-scheduler", 12.0)]

    def test_main_returns_1_for_missing_api_key(self, monkeypatch, fake_config_file):
        monkeypatch.setattr(
            cli,
            "cmd_run_personalized",
            lambda config, *, run_date=None: (_ for _ in ()).throw(OpenAIConfigError("missing key")),
        )
        assert cli.main(["--config_path", fake_config_file, "run-personalized"]) == 1


class TestCommandIsolation:
    """Behavioral isolation: render MUST NOT fetch, fetch MUST NOT render."""

    def test_render_does_not_fetch(self, monkeypatch, fake_config_file):
        def boom(*a, **kw):
            raise AssertionError("render must not call fetch_papers / get_daily_papers")

        monkeypatch.setattr("nlp_arxiv_daily.fetcher.fetch_papers", boom)
        monkeypatch.setattr("nlp_arxiv_daily.core.get_daily_papers", boom)
        # render against an empty JSON config — should produce empty markdown only
        cli.main(["--config_path", fake_config_file, "render"])

    def test_fetch_does_not_render(self, monkeypatch, fake_config_file):
        def boom(*a, **kw):
            raise AssertionError("fetch must not call json_to_md / render_archive_pages")

        monkeypatch.setattr("nlp_arxiv_daily.cli.json_to_md", boom)
        monkeypatch.setattr("nlp_arxiv_daily.cli.render_archive_pages", boom)
        monkeypatch.setattr(cli, "ensure_arxiv_preflight", lambda: None)

        # Mock fetch_papers so no network
        from nlp_arxiv_daily import fetcher

        monkeypatch.setattr(
            fetcher.arxiv,
            "Client",
            lambda **_kw: type("X", (), {"results": lambda self, s: iter([])})(),
        )

        class _FakeSearch:
            def __init__(self, *a, **kw):
                pass

        monkeypatch.setattr(fetcher.arxiv, "Search", _FakeSearch)
        cli.main(["--config_path", fake_config_file, "fetch"])

    def test_fetch_runs_preflight_before_fetching(self, monkeypatch, fake_config_file):
        order: list[str] = []

        monkeypatch.setattr(cli, "ensure_arxiv_preflight", lambda: order.append("preflight"))
        monkeypatch.setattr(cli, "fetch_papers", lambda **kwargs: order.append("fetch") or [])

        cli.main(["--config_path", fake_config_file, "fetch"])

        assert order[:2] == ["preflight", "fetch"]

    def test_fetch_exits_on_rate_limited_preflight(self, monkeypatch, fake_config_file):
        monkeypatch.setattr(
            cli,
            "ensure_arxiv_preflight",
            lambda: (_ for _ in ()).throw(ArxivRateLimitExceeded("Rate exceeded")),
        )
        monkeypatch.setattr(cli, "fetch_papers", lambda **kwargs: pytest.fail("fetch should not run after preflight failure"))

        assert cli.main(["--config_path", fake_config_file, "fetch"]) == 1


class TestCmdRunInvocation:
    def _personalized_config(self, fake_config_file):
        config = cli.load_config(fake_config_file)
        sandbox_root = Path(fake_config_file).parent / "personalized"
        config["personalized_docs_dir"] = str(sandbox_root)
        config["analysis_cache_dir"] = str(sandbox_root / "cache")
        config["personalized_logs_dir"] = str(sandbox_root / "logs")
        config["personalized_runs_dir"] = str(sandbox_root / "runs")
        return config

    def _fetched_papers(self):
        return {
            "agent": [
                Paper(
                    paper_id="2606.00001",
                    title="Memory Agent",
                    first_author="Alice",
                    update_time=datetime.date(2026, 6, 5),
                    paper_url="http://arxiv.org/abs/2606.00001v1",
                    code_link=None,
                    abstract="A memory paper.",
                    authors=("Alice",),
                    categories=("cs.CL",),
                    pdf_url="http://arxiv.org/pdf/2606.00001v1.pdf",
                    arxiv_short_id="2606.00001v1",
                )
            ]
        }

    def test_run_calls_fetch_then_render_in_order(self, monkeypatch, fake_config_file):
        order = []
        monkeypatch.setattr(cli, "cmd_fetch", lambda config: order.append("fetch"))
        monkeypatch.setattr(cli, "cmd_render", lambda config: order.append("render"))
        cli.main(["--config_path", fake_config_file, "run"])
        assert order == ["fetch", "render"]

    def test_run_personalized_writes_stage_record(self, monkeypatch, fake_config_file):
        config = self._personalized_config(fake_config_file)
        personalized_root = Path(config["personalized_docs_dir"])
        run_date = datetime.date(2026, 6, 6)

        l1_dir = personalized_root / "l1"
        l2_dir = personalized_root / "l2" / run_date.isoformat()
        digest_dir = personalized_root / "digest"
        logs_dir = personalized_root / "logs" / run_date.isoformat()
        l1_dir.mkdir(parents=True)
        l2_dir.mkdir(parents=True)
        digest_dir.mkdir(parents=True)
        logs_dir.mkdir(parents=True)

        l1_path = l1_dir / f"{run_date.isoformat()}.json"
        l1_path.write_text(
            json.dumps(
                {
                    "date": run_date.isoformat(),
                    "stats": {"total_papers": 1, "reject": 0, "archive_only": 0, "level2": 1},
                    "papers": [
                        {
                            "paper": {"paper_id": "2606.00001", "title": "Memory Agent"},
                            "l1": {"decision": "level2"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        review_path = l2_dir / "2606.00001.json"
        review_path.write_text(
            json.dumps(
                {
                    "paper": {"paper_id": "2606.00001", "title": "Memory Agent"},
                    "review": {"decision": "highlight"},
                }
            ),
            encoding="utf-8",
        )

        digest_path = digest_dir / f"{run_date.isoformat()}.md"
        digest_path.write_text("# digest", encoding="utf-8")
        (logs_dir / "digest.json").write_text(
            json.dumps(
                {
                    "summary": {
                        "must_read": 1,
                        "worth_archiving": 0,
                        "review_failures": 0,
                        "must_read_paper_ids": ["2606.00001"],
                    },
                }
            ),
            encoding="utf-8",
        )

        order = []
        monkeypatch.setattr(cli, "cmd_fetch", lambda cfg: order.append("fetch") or self._fetched_papers())
        monkeypatch.setattr(cli, "cmd_render", lambda cfg: order.append("render"))
        monkeypatch.setattr(cli, "filter_level1_for_date", lambda cfg, date: order.append("l1") or str(l1_path))
        monkeypatch.setattr(cli, "review_level2_for_date", lambda cfg, date: order.append("l2") or [str(review_path)])
        monkeypatch.setattr(cli, "build_digest_for_date", lambda cfg, date: order.append("digest") or str(digest_path))

        cli.cmd_run_personalized(config, run_date=run_date)

        assert order == ["fetch", "render", "l1", "l2", "digest"]
        record_path = Path(config["personalized_runs_dir"]) / f"{run_date.isoformat()}.json"
        latest_path = Path(config["personalized_runs_dir"]) / "latest.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        analysis_pool = json.loads((personalized_root / "pools" / f"{run_date.isoformat()}.json").read_text(encoding="utf-8"))
        pipeline_log = json.loads((personalized_root / "logs" / f"{run_date.isoformat()}" / "pipeline.json").read_text(encoding="utf-8"))
        assert record["stages"]["l1"]["stats"]["level2"] == 1
        assert record["stages"]["l2"]["stats"]["reviewed"] == 1
        assert record["stages"]["digest"]["stats"]["must_read"] == 1
        assert latest["date"] == run_date.isoformat()
        assert analysis_pool["stats"]["unique_papers"] == 1
        assert analysis_pool["papers"][0]["published_date"] == "2026-06-05"
        assert pipeline_log["stages"]["digest"]["stats"]["must_read"] == 1

    def test_run_personalized_resumes_from_next_incomplete_stage(self, monkeypatch, fake_config_file):
        config = self._personalized_config(fake_config_file)
        personalized_root = Path(config["personalized_docs_dir"])
        run_date = datetime.date(2026, 6, 6)

        (personalized_root / "pools").mkdir(parents=True)
        (personalized_root / "l1").mkdir(parents=True)
        (personalized_root / "l2" / run_date.isoformat()).mkdir(parents=True)
        Path(config["md_readme_path"]).write_text("rendered", encoding="utf-8")

        analysis_pool_path = personalized_root / "pools" / f"{run_date.isoformat()}.json"
        analysis_pool_path.write_text(
            json.dumps(
                {
                    "date": run_date.isoformat(),
                    "stats": {"topics": 1, "total_topic_hits": 1, "unique_papers": 1},
                    "papers": [{"paper_id": "2606.00001", "title": "Memory Agent"}],
                }
            ),
            encoding="utf-8",
        )

        l1_path = personalized_root / "l1" / f"{run_date.isoformat()}.json"
        l1_path.write_text(
            json.dumps(
                {
                    "date": run_date.isoformat(),
                    "stats": {"total_papers": 1, "reject": 0, "archive_only": 0, "level2": 1},
                    "papers": [
                        {
                            "paper": {"paper_id": "2606.00001", "title": "Memory Agent"},
                            "l1": {"decision": "level2"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        runs_dir = Path(config["personalized_runs_dir"])
        runs_dir.mkdir(parents=True)
        state_path = runs_dir / f"{run_date.isoformat()}.json"
        state_path.write_text(
            json.dumps(
                {
                    "date": run_date.isoformat(),
                    "pipeline": "run-personalized",
                    "status": "failed",
                    "created_at": "2026-06-06T00:00:00+00:00",
                    "updated_at": "2026-06-06T00:00:01+00:00",
                    "completed_at": None,
                    "stages": {
                        "fetch": {
                            "status": "completed",
                            "path": str(analysis_pool_path),
                            "keyword_count": 1,
                            "keywords": ["NLP"],
                            "stats": {"topics": 1, "total_topic_hits": 1, "unique_papers": 1},
                        },
                        "render": {"status": "completed"},
                        "l1": {
                            "status": "completed",
                            "path": str(l1_path),
                            "stats": {"total_papers": 1, "reject": 0, "archive_only": 0, "level2": 1},
                            "paper_ids": ["2606.00001"],
                            "level2_candidate_ids": ["2606.00001"],
                        },
                        "l2": {"status": "failed", "error": {"type": "RuntimeError", "message": "boom"}},
                        "digest": {"status": "pending"},
                    },
                }
            ),
            encoding="utf-8",
        )

        review_path = personalized_root / "l2" / run_date.isoformat() / "2606.00001.json"
        digest_path = personalized_root / "digest" / f"{run_date.isoformat()}.md"
        digest_log_path = personalized_root / "logs" / run_date.isoformat() / "digest.json"
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        digest_log_path.parent.mkdir(parents=True, exist_ok=True)

        order = []
        monkeypatch.setattr(cli, "cmd_fetch", lambda cfg: pytest.fail("fetch should be skipped"))
        monkeypatch.setattr(cli, "cmd_render", lambda cfg: pytest.fail("render should be skipped"))
        monkeypatch.setattr(cli, "filter_level1_for_date", lambda cfg, date: pytest.fail("l1 should be skipped"))
        monkeypatch.setattr(cli, "review_level2_for_date", lambda cfg, date: order.append("l2") or [str(review_path)])
        monkeypatch.setattr(cli, "build_digest_for_date", lambda cfg, date: order.append("digest") or str(digest_path))

        review_path.write_text(
            json.dumps(
                {
                    "paper": {"paper_id": "2606.00001", "title": "Memory Agent"},
                    "review": {"decision": "highlight"},
                }
            ),
            encoding="utf-8",
        )
        digest_path.write_text("# digest", encoding="utf-8")
        digest_log_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "must_read": 1,
                        "worth_archiving": 0,
                        "review_failures": 0,
                        "must_read_paper_ids": ["2606.00001"],
                    }
                }
            ),
            encoding="utf-8",
        )

        cli.cmd_run_personalized(config, run_date=run_date)

        assert order == ["l2", "digest"]
        resumed = json.loads(state_path.read_text(encoding="utf-8"))
        assert resumed["status"] == "completed"
        assert resumed["stages"]["fetch"]["status"] == "completed"
        assert resumed["stages"]["l2"]["status"] == "completed"
        assert resumed["stages"]["digest"]["status"] == "completed"

    def test_run_personalized_marks_fetch_stage_failed(self, monkeypatch, fake_config_file):
        config = self._personalized_config(fake_config_file)
        run_date = datetime.date(2026, 6, 6)
        monkeypatch.setattr(cli, "cmd_fetch", lambda cfg: (_ for _ in ()).throw(RuntimeError("fetch failed")))

        with pytest.raises(RuntimeError, match="fetch failed"):
            cli.cmd_run_personalized(config, run_date=run_date)

        state = json.loads(
            (Path(config["personalized_runs_dir"]) / f"{run_date.isoformat()}.json").read_text(encoding="utf-8")
        )
        assert state["status"] == "failed"
        assert state["stages"]["fetch"]["status"] == "failed"
        assert state["stages"]["fetch"]["error"]["message"] == "fetch failed"

    def test_run_personalized_marks_render_stage_failed(self, monkeypatch, fake_config_file):
        config = self._personalized_config(fake_config_file)
        run_date = datetime.date(2026, 6, 6)

        def fake_fetch(cfg):
            papers = self._fetched_papers()
            cli._write_analysis_pool_snapshot(cfg, papers, snapshot_date=run_date)
            return papers

        monkeypatch.setattr(cli, "cmd_fetch", fake_fetch)
        monkeypatch.setattr(cli, "cmd_render", lambda cfg: (_ for _ in ()).throw(RuntimeError("render failed")))

        with pytest.raises(RuntimeError, match="render failed"):
            cli.cmd_run_personalized(config, run_date=run_date)

        state = json.loads(
            (Path(config["personalized_runs_dir"]) / f"{run_date.isoformat()}.json").read_text(encoding="utf-8")
        )
        assert state["status"] == "failed"
        assert state["stages"]["fetch"]["status"] == "completed"
        assert state["stages"]["render"]["status"] == "failed"

    def test_run_personalized_marks_l1_stage_failed(self, monkeypatch, fake_config_file):
        config = self._personalized_config(fake_config_file)
        run_date = datetime.date(2026, 6, 6)

        def fake_fetch(cfg):
            papers = self._fetched_papers()
            cli._write_analysis_pool_snapshot(cfg, papers, snapshot_date=run_date)
            return papers

        Path(config["md_readme_path"]).write_text("rendered", encoding="utf-8")
        monkeypatch.setattr(cli, "cmd_fetch", fake_fetch)
        monkeypatch.setattr(cli, "cmd_render", lambda cfg: None)
        monkeypatch.setattr(cli, "filter_level1_for_date", lambda cfg, date: (_ for _ in ()).throw(RuntimeError("l1 failed")))

        with pytest.raises(RuntimeError, match="l1 failed"):
            cli.cmd_run_personalized(config, run_date=run_date)

        state = json.loads(
            (Path(config["personalized_runs_dir"]) / f"{run_date.isoformat()}.json").read_text(encoding="utf-8")
        )
        assert state["status"] == "failed"
        assert state["stages"]["render"]["status"] == "completed"
        assert state["stages"]["l1"]["status"] == "failed"


def test_build_digest_stage_record_prefers_stage_log(tmp_path):
    personalized_root = tmp_path / "personalized"
    digest_dir = personalized_root / "digest"
    logs_dir = personalized_root / "logs" / "2026-06-06"
    digest_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)

    digest_path = digest_dir / "2026-06-06.md"
    digest_path.write_text("# digest", encoding="utf-8")
    (logs_dir / "digest.json").write_text(
        json.dumps(
            {
                "summary": {
                    "must_read": 2,
                    "worth_archiving": 1,
                    "review_failures": 1,
                    "must_read_paper_ids": ["2606.00001", "2606.00002"],
                }
            }
        ),
        encoding="utf-8",
    )

    record = cli._build_digest_stage_record(str(digest_path))

    assert record["status"] == "completed"
    assert record["stats"] == {"must_read": 2, "worth_archiving": 1, "review_failures": 1}
    assert record["must_read_paper_ids"] == ["2606.00001", "2606.00002"]


def test_build_digest_stage_record_falls_back_to_legacy_digest_json(tmp_path):
    personalized_root = tmp_path / "personalized"
    digest_dir = personalized_root / "digest"
    digest_dir.mkdir(parents=True)

    digest_path = digest_dir / "2026-06-06.json"
    digest_path.write_text(
        json.dumps(
            {
                "date": "2026-06-06",
                "review_failures": [{"paper_id": "2606.00003"}],
                "digest": {
                    "must_read": [{"paper_id": "2606.00001"}, {"paper_id": "2606.00002"}],
                    "worth_archiving": [{"paper_id": "2606.00004"}],
                },
            }
        ),
        encoding="utf-8",
    )

    record = cli._build_digest_stage_record(str(digest_path))

    assert record["status"] == "completed"
    assert record["stats"] == {"must_read": 2, "worth_archiving": 1, "review_failures": 1}
    assert record["must_read_paper_ids"] == ["2606.00001", "2606.00002"]


class TestParseYyyyMm:
    def test_parses_valid_yyyy_mm(self):
        assert cli._parse_yyyy_mm("2025-08") == datetime.date(2025, 8, 1)

    @pytest.mark.parametrize("bad", ["", "2025", "2025-13-01", "abc-08", "2025/08"])
    def test_rejects_invalid(self, bad):
        with pytest.raises(Exception):
            cli._parse_yyyy_mm(bad)


class TestIterMonthRanges:
    def test_single_month(self):
        ranges = list(cli._iter_month_ranges(datetime.date(2025, 8, 1), datetime.date(2025, 8, 1)))
        assert ranges == [(datetime.date(2025, 8, 1), datetime.date(2025, 8, 31))]

    def test_year_boundary(self):
        # Dec 2025 → Feb 2026
        ranges = list(cli._iter_month_ranges(datetime.date(2025, 12, 1), datetime.date(2026, 2, 1)))
        assert [m[0] for m in ranges] == [
            datetime.date(2025, 12, 1),
            datetime.date(2026, 1, 1),
            datetime.date(2026, 2, 1),
        ]
        assert ranges[0][1] == datetime.date(2025, 12, 31)
        assert ranges[1][1] == datetime.date(2026, 1, 31)
        assert ranges[2][1] == datetime.date(2026, 2, 28)

    def test_normalizes_mid_month_inputs(self):
        # _parse_yyyy_mm always emits day=1, but the helper should still cope
        # with mid-month inputs by clamping to month boundaries.
        ranges = list(cli._iter_month_ranges(datetime.date(2025, 8, 17), datetime.date(2025, 9, 5)))
        assert [m[0] for m in ranges] == [
            datetime.date(2025, 8, 1),
            datetime.date(2025, 9, 1),
        ]


class TestBackfillDispatch:
    def test_backfill_with_explicit_end_invokes_cmd_backfill(self, monkeypatch, fake_config_file):
        captured = {}

        def fake(config, *, start, end, max_results, **_):
            captured["start"] = start
            captured["end"] = end
            captured["max_results"] = max_results

        monkeypatch.setattr(cli, "cmd_backfill", fake)
        cli.main(
            [
                "--config_path",
                fake_config_file,
                "backfill",
                "--start",
                "2025-08",
                "--end",
                "2026-03",
            ]
        )
        assert captured["start"] == datetime.date(2025, 8, 1)
        assert captured["end"] == datetime.date(2026, 3, 1)
        # Backfill default must NOT inherit config["max_results"] (which is the
        # daily-fetch top-N cap of ~10) — it ignores config and uses the
        # backfill-appropriate ceiling from fetcher.BACKFILL_DEFAULT_MAX_RESULTS.
        assert captured["max_results"] >= 1000

    def test_backfill_default_end_is_current_month(self, monkeypatch, fake_config_file):
        captured = {}
        monkeypatch.setattr(
            cli,
            "cmd_backfill",
            lambda config, *, start, end, max_results, **_: captured.setdefault("end", end),
        )
        # Pin "today" so the test is deterministic.
        monkeypatch.setattr(cli, "_current_month_first", lambda: datetime.date(2026, 4, 1))
        cli.main(["--config_path", fake_config_file, "backfill", "--start", "2025-08"])
        assert captured["end"] == datetime.date(2026, 4, 1)

    def test_backfill_max_results_override(self, monkeypatch, fake_config_file):
        captured = {}
        monkeypatch.setattr(
            cli,
            "cmd_backfill",
            lambda config, *, start, end, max_results, **_: captured.setdefault("max_results", max_results),
        )
        cli.main(
            [
                "--config_path",
                fake_config_file,
                "backfill",
                "--start",
                "2025-08",
                "--max-results",
                "50",
            ]
        )
        assert captured["max_results"] == 50

    def test_backfill_requires_start(self, fake_config_file):
        with pytest.raises(SystemExit):
            cli.main(["--config_path", fake_config_file, "backfill"])
