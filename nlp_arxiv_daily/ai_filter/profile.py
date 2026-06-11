from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class TrackConfig:
    id: str
    name: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    priority: int = 3
    module_id: str = ""
    module_name: str = ""


@dataclass(frozen=True)
class ModuleConfig:
    id: str
    name: str
    summary: str
    enabled: bool
    priority: int
    decision_rules: tuple[str, ...]
    bonus_signals: tuple[str, ...]
    tracks: tuple[TrackConfig, ...]


@dataclass(frozen=True)
class Level1Thresholds:
    reject_below_relevance: int
    archive_below_total: int
    level2_min_total: int


@dataclass(frozen=True)
class Level1Config:
    max_prompt_profile_chars: int
    decision_thresholds: Level1Thresholds
    max_level2_candidates_per_day: int


@dataclass(frozen=True)
class Level2Config:
    max_papers_per_day: int
    skip_sections: tuple[str, ...]
    prefer_sections: tuple[str, ...]


@dataclass(frozen=True)
class OutputConfig:
    language: str
    digest_max_papers: int
    include_archive_summary: bool


@dataclass(frozen=True)
class ResearchProfile:
    short_profile: str
    full_profile: str
    modules: tuple[ModuleConfig, ...]
    tracks: tuple[TrackConfig, ...]
    level1: Level1Config
    level2: Level2Config
    output: OutputConfig


def load_research_profile(path: str) -> ResearchProfile:
    with open(path, encoding="utf-8") as f:
        data = yaml.load(f, Loader=yaml.FullLoader) or {}

    profile_block = data.get("profile") or {}
    level1_block = data.get("level1") or {}
    thresholds_block = level1_block.get("decision_thresholds") or {}
    level2_block = data.get("level2") or {}
    output_block = data.get("output") or {}

    modules = _load_modules(data)
    tracks = tuple(track for module in modules if module.enabled for track in module.tracks)
    if not tracks:
        tracks = tuple(
            TrackConfig(
                id=str(track["id"]),
                name=str(track["name"]),
                include=tuple(str(item) for item in track.get("include", [])),
                exclude=tuple(str(item) for item in track.get("exclude", [])),
                priority=int(track.get("priority", 3)),
            )
            for track in data.get("tracks", [])
        )

    return ResearchProfile(
        short_profile=str(profile_block.get("short", "")).strip(),
        full_profile=str(profile_block.get("full", "")).strip(),
        modules=modules,
        tracks=tracks,
        level1=Level1Config(
            max_prompt_profile_chars=int(level1_block.get("max_prompt_profile_chars", 350)),
            decision_thresholds=Level1Thresholds(
                reject_below_relevance=int(thresholds_block.get("reject_below_relevance", 2)),
                archive_below_total=int(thresholds_block.get("archive_below_total", 6)),
                level2_min_total=int(thresholds_block.get("level2_min_total", 8)),
            ),
            max_level2_candidates_per_day=int(level1_block.get("max_level2_candidates_per_day", 8)),
        ),
        level2=Level2Config(
            max_papers_per_day=int(level2_block.get("max_papers_per_day", 5)),
            skip_sections=tuple(str(item).lower() for item in level2_block.get("skip_sections", [])),
            prefer_sections=tuple(str(item).lower() for item in level2_block.get("prefer_sections", [])),
        ),
        output=OutputConfig(
            language=str(output_block.get("language", "Chinese")),
            digest_max_papers=int(output_block.get("digest_max_papers", 5)),
            include_archive_summary=bool(output_block.get("include_archive_summary", True)),
        ),
    )


def _load_modules(data: dict) -> tuple[ModuleConfig, ...]:
    modules: list[ModuleConfig] = []
    for module in data.get("modules", []):
        module_id = str(module.get("id", "")).strip()
        module_name = str(module.get("name", module_id)).strip()
        module_priority = int(module.get("priority", 3))
        module_tracks = tuple(
            TrackConfig(
                id=str(track["id"]),
                name=str(track["name"]),
                include=tuple(str(item) for item in track.get("include", [])),
                exclude=tuple(str(item) for item in track.get("exclude", [])),
                priority=int(track.get("priority", module_priority)),
                module_id=module_id,
                module_name=module_name,
            )
            for track in module.get("tracks", [])
        )
        modules.append(
            ModuleConfig(
                id=module_id,
                name=module_name,
                summary=str(module.get("summary", "")).strip(),
                enabled=bool(module.get("enabled", True)),
                priority=module_priority,
                decision_rules=tuple(str(item).strip() for item in module.get("decision_rules", []) if str(item).strip()),
                bonus_signals=tuple(str(item).strip() for item in module.get("bonus_signals", []) if str(item).strip()),
                tracks=module_tracks,
            )
        )
    return tuple(modules)


def render_tracks(profile: ResearchProfile) -> str:
    lines: list[str] = []
    if profile.modules:
        for module in profile.modules:
            if not module.enabled:
                continue
            lines.append(f"- module {module.id}: {module.name}")
            lines.append(f"  priority: {module.priority}/5")
            if module.summary:
                lines.append(f"  summary: {module.summary}")
            for rule in module.decision_rules:
                lines.append(f"  decision_rule: {rule}")
            for signal in module.bonus_signals:
                lines.append(f"  bonus_signal: {signal}")
            for track in module.tracks:
                include = ", ".join(track.include)
                exclude = ", ".join(track.exclude)
                lines.append(f"  - {track.id}: {track.name}")
                lines.append(f"    priority: {track.priority}/5")
                lines.append(f"    include: {include}")
                lines.append(f"    exclude: {exclude}")
        return "\n".join(lines)

    for track in profile.tracks:
        include = ", ".join(track.include)
        exclude = ", ".join(track.exclude)
        lines.append(f"- {track.id}: {track.name}")
        lines.append(f"  priority: {track.priority}/5")
        lines.append(f"  include: {include}")
        lines.append(f"  exclude: {exclude}")
    return "\n".join(lines)


def render_modules(profile: ResearchProfile) -> str:
    if not profile.modules:
        return ""

    lines: list[str] = []
    for module in profile.modules:
        if not module.enabled:
            continue
        lines.append(f"- {module.id}: {module.name}")
        lines.append(f"  priority: {module.priority}/5")
        if module.summary:
            lines.append(f"  summary: {module.summary}")
        for rule in module.decision_rules:
            lines.append(f"  decision_rule: {rule}")
        for signal in module.bonus_signals:
            lines.append(f"  bonus_signal: {signal}")
        for track in module.tracks:
            lines.append(f"  - track {track.id}: {track.name} (priority {track.priority}/5)")
    return "\n".join(lines)


def trim_profile(text: str, max_chars: int) -> str:
    trimmed = text.strip()
    if len(trimmed) <= max_chars:
        return trimmed
    return trimmed[: max_chars - 3].rstrip() + "..."
