from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any


def stable_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_cache_namespace(*parts: Any) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(stable_json_dumps(part).encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()[:16]


def load_stage_cache(config: dict, stage: str, namespace: str, key: str) -> dict | None:
    path = _stage_cache_path(config, stage, namespace, key)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_stage_cache(config: dict, stage: str, namespace: str, key: str, payload: dict) -> str:
    path = _stage_cache_path(config, stage, namespace, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    envelope = {
        "cached_at": datetime.now(UTC).isoformat(),
        "stage": stage,
        "namespace": namespace,
        "key": key,
        "payload": payload,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)
    return path


def analysis_cache_root(config: dict) -> str:
    configured = str(config.get("analysis_cache_dir", "")).strip()
    if configured:
        return configured
    return os.path.join(config["personalized_docs_dir"], "cache")


def _stage_cache_path(config: dict, stage: str, namespace: str, key: str) -> str:
    safe_key = key.replace("/", "_").replace("\\", "_")
    return os.path.join(analysis_cache_root(config), stage, namespace, f"{safe_key}.json")
