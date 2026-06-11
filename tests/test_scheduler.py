from __future__ import annotations

import datetime
import json
from pathlib import Path

from nlp_arxiv_daily import scheduler


class _ImmediateThread:
    def __init__(self, *, target, args=(), name=None, daemon=None):
        self._target = target
        self._args = args
        self._alive = False

    def start(self):
        self._alive = True
        try:
            self._target(*self._args)
        finally:
            self._alive = False

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        return None


class _StubThread:
    def __init__(self, alive: bool):
        self._alive = alive

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self._alive = False


def _config(tmp_path: Path) -> dict:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    return {
        "personalized_runs_dir": str(runs_dir),
        "scheduler_lock_path": str(runs_dir / "scheduler.lock"),
    }


def test_has_pipeline_record_for_date_requires_matching_run_record(tmp_path):
    config = _config(tmp_path)
    run_date = datetime.date(2026, 6, 11)
    record_path = Path(config["personalized_runs_dir"]) / "2026-06-11.json"
    record_path.write_text(
        json.dumps(
            {
                "date": "2026-06-11",
                "pipeline": "run-personalized",
                "status": "completed",
            }
        ),
        encoding="utf-8",
    )

    assert scheduler.has_pipeline_record_for_date(config, run_date) is True
    assert scheduler.has_pipeline_record_for_date(config, datetime.date(2026, 6, 12)) is False


def test_scheduler_does_not_queue_date_when_record_already_exists(tmp_path):
    config = _config(tmp_path)
    run_date = datetime.date(2026, 6, 11)
    record_path = Path(config["personalized_runs_dir"]) / "2026-06-11.json"
    record_path.write_text(
        json.dumps({"date": "2026-06-11", "pipeline": "run-personalized"}),
        encoding="utf-8",
    )

    service = scheduler.BackgroundPipelineScheduler(
        config,
        run_pipeline=lambda date: None,
    )
    service._queue_today_if_missing(run_date, reason="startup")

    assert service.pending_dates == set()


def test_scheduler_queues_new_day_while_busy_then_runs_after_previous_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler.threading, "Thread", _ImmediateThread)
    config = _config(tmp_path)
    invocations: list[datetime.date] = []
    service = scheduler.BackgroundPipelineScheduler(
        config,
        run_pipeline=lambda run_date: invocations.append(run_date),
    )

    previous_day = datetime.date(2026, 6, 10)
    current_day = datetime.date(2026, 6, 11)
    service.last_observed_date = previous_day
    service.active_run_date = previous_day
    service.active_thread = _StubThread(alive=True)

    service.tick(datetime.datetime(2026, 6, 11, 0, 0, 1))

    assert current_day in service.pending_dates
    assert invocations == []

    service.active_thread = _StubThread(alive=False)
    service.tick(datetime.datetime(2026, 6, 11, 0, 5, 0))

    assert invocations == [current_day]
    assert service.pending_dates == set()
