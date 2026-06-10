from __future__ import annotations

import datetime
import json
import os


def stage_log_root(config: dict) -> str:
    return config.get("personalized_logs_dir") or os.path.join(config["personalized_docs_dir"], "logs")


def stage_log_dir(config: dict, run_date: datetime.date) -> str:
    path = os.path.join(stage_log_root(config), run_date.isoformat())
    os.makedirs(path, exist_ok=True)
    return path


def write_stage_log_bundle(
    config: dict,
    run_date: datetime.date,
    stage: str,
    *,
    payload: dict,
    text: str,
) -> dict[str, str]:
    output_dir = stage_log_dir(config, run_date)
    json_path = os.path.join(output_dir, f"{stage}.json")
    log_path = os.path.join(output_dir, f"{stage}.log")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")
    return {"json_path": json_path, "log_path": log_path}
