from __future__ import annotations

import datetime
import json
import logging
import os
import threading
from collections.abc import Callable


def pipeline_record_path(config: dict, run_date: datetime.date) -> str:
    return os.path.join(config["personalized_runs_dir"], f"{run_date.isoformat()}.json")


def has_pipeline_record_for_date(config: dict, run_date: datetime.date) -> bool:
    record_path = pipeline_record_path(config, run_date)
    if not os.path.exists(record_path):
        return False

    try:
        with open(record_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False

    return payload.get("pipeline") == "run-personalized" and payload.get("date") == run_date.isoformat()


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class SchedulerProcessLock:
    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self._held = False

    def acquire(self) -> None:
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if self._remove_stale_lock():
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            else:
                raise RuntimeError(f"Scheduler is already running: {self.lock_path}")

        payload = {
            "pid": os.getpid(),
            "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        try:
            os.remove(self.lock_path)
        except FileNotFoundError:
            pass
        self._held = False

    def _remove_stale_lock(self) -> bool:
        try:
            with open(self.lock_path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            os.remove(self.lock_path)
            return True

        pid = int(payload.get("pid", 0) or 0)
        if pid_is_running(pid):
            return False

        os.remove(self.lock_path)
        return True

    def __enter__(self) -> SchedulerProcessLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class BackgroundPipelineScheduler:
    def __init__(
        self,
        config: dict,
        *,
        run_pipeline: Callable[[datetime.date], None],
        poll_seconds: float = 30.0,
        now_fn: Callable[[], datetime.datetime] | None = None,
        lock_path: str | None = None,
    ):
        self.config = config
        self.run_pipeline = run_pipeline
        self.poll_seconds = max(1.0, float(poll_seconds))
        self.now_fn = now_fn or (lambda: datetime.datetime.now().astimezone())
        self.lock_path = lock_path or config["scheduler_lock_path"]
        self.stop_event = threading.Event()
        self.pending_dates: set[datetime.date] = set()
        self.last_observed_date: datetime.date | None = None
        self.active_thread: threading.Thread | None = None
        self.active_run_date: datetime.date | None = None

    def run_forever(self) -> None:
        with SchedulerProcessLock(self.lock_path):
            now = self.now_fn()
            self.last_observed_date = now.date()
            self._queue_today_if_missing(now.date(), reason="startup")

            while not self.stop_event.is_set():
                self.tick(self.now_fn())
                self.stop_event.wait(self.poll_seconds)

            self._wait_for_active_run()

    def stop(self) -> None:
        self.stop_event.set()

    def tick(self, now: datetime.datetime) -> None:
        current_date = now.date()

        if self.last_observed_date is None:
            self.last_observed_date = current_date
        elif current_date != self.last_observed_date:
            self.last_observed_date = current_date
            self._queue_today_if_missing(current_date, reason="midnight")

        self._collect_finished_run()
        self._start_next_pending_run()

    def _queue_today_if_missing(self, run_date: datetime.date, *, reason: str) -> None:
        if has_pipeline_record_for_date(self.config, run_date):
            logging.info("scheduler skip %s: %s already has a pipeline record", reason, run_date.isoformat())
            return
        if run_date == self.active_run_date or run_date in self.pending_dates:
            return
        logging.info("scheduler queue %s: %s", reason, run_date.isoformat())
        self.pending_dates.add(run_date)

    def _collect_finished_run(self) -> None:
        if self.active_thread is None or self.active_thread.is_alive():
            return
        self.active_thread.join(timeout=0)
        logging.info("scheduler run finished: %s", self.active_run_date.isoformat() if self.active_run_date else "unknown")
        self.active_thread = None
        self.active_run_date = None

    def _start_next_pending_run(self) -> None:
        if self.active_thread is not None:
            return

        while self.pending_dates:
            run_date = min(self.pending_dates)
            self.pending_dates.remove(run_date)

            if has_pipeline_record_for_date(self.config, run_date):
                logging.info("scheduler drop queued date with existing record: %s", run_date.isoformat())
                continue

            self.active_run_date = run_date
            self.active_thread = threading.Thread(
                target=self._run_pipeline_wrapper,
                args=(run_date,),
                name=f"personalized-pipeline-{run_date.isoformat()}",
                daemon=False,
            )
            self.active_thread.start()
            return

    def _run_pipeline_wrapper(self, run_date: datetime.date) -> None:
        logging.info("scheduler run started: %s", run_date.isoformat())
        try:
            self.run_pipeline(run_date)
        except Exception:
            logging.exception("scheduler run failed: %s", run_date.isoformat())
        else:
            logging.info("scheduler run completed: %s", run_date.isoformat())

    def _wait_for_active_run(self) -> None:
        if self.active_thread is None:
            return
        logging.info("scheduler stopping after active run finishes: %s", self.active_run_date.isoformat())
        self.active_thread.join()
        self.active_thread = None
        self.active_run_date = None
