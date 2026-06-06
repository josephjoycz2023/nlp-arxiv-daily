from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class TrackConfig:
    id: str
    name: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]


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

    tracks = tuple(
        TrackConfig(
            id=str(track["id"]),
            name=str(track["name"]),
            include=tuple(str(item) for item in track.get("include", [])),
            exclude=tuple(str(item) for item in track.get("exclude", [])),
        )
        for track in data.get("tracks", [])
    )

    return ResearchProfile(
        short_profile=str(profile_block.get("short", "")).strip(),
        full_profile=str(profile_block.get("full", "")).strip(),
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


def render_tracks(profile: ResearchProfile) -> str:
    lines: list[str] = []
    for track in profile.tracks:
        include = ", ".join(track.include)
        exclude = ", ".join(track.exclude)
        lines.append(f"- {track.id}: {track.name}")
        lines.append(f"  include: {include}")
        lines.append(f"  exclude: {exclude}")
    return "\n".join(lines)


def trim_profile(text: str, max_chars: int) -> str:
    trimmed = text.strip()
    if len(trimmed) <= max_chars:
        return trimmed
    return trimmed[: max_chars - 3].rstrip() + "..."
