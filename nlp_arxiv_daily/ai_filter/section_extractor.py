from __future__ import annotations

import re


SECTION_PATTERN = re.compile(
    r"(?im)^(?:\d+(?:\.\d+)*)?\s*(abstract|introduction|related work|method(?:ology)?|approach|experiments?|results?|discussion|limitations?|conclusion)\s*$"
)

CANONICAL_SECTION_NAMES = {
    "abstract": "abstract",
    "introduction": "introduction",
    "related work": "related work",
    "method": "method",
    "methodology": "method",
    "approach": "approach",
    "experiment": "experiments",
    "experiments": "experiments",
    "result": "results",
    "results": "results",
    "discussion": "discussion",
    "limitation": "limitation",
    "limitations": "limitation",
    "conclusion": "conclusion",
}

def extract_review_sections(
    paper_text: str,
    *,
    prefer_sections: tuple[str, ...],
    skip_sections: tuple[str, ...],
    max_total_chars: int = 24_000,
) -> tuple[dict[str, str], dict[str, int], str | None, bool]:
    matches = list(SECTION_PATTERN.finditer(paper_text))
    sections: dict[str, str] = {}

    for index, match in enumerate(matches):
        raw_name = match.group(1).lower()
        section_name = CANONICAL_SECTION_NAMES.get(raw_name, raw_name)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(paper_text)
        body = paper_text[start:end].strip()
        if body:
            sections[section_name] = body

    selected: dict[str, str] = {}
    for name in prefer_sections:
        if name in skip_sections:
            continue
        if name in sections:
            selected[name] = sections[name]

    note: str | None = None
    if not selected:
        note = "Preferred sections were not found; using a full-text excerpt instead."
        selected = {"full_text_excerpt": paper_text.strip()}

    section_lengths = {name: len(value) for name, value in selected.items()}
    truncated = sum(section_lengths.values()) > max_total_chars
    if truncated:
        selected = _truncate_selected_sections(selected, max_total_chars)
        extra_note = "Sections were trimmed to fit the prompt budget."
        note = extra_note if note is None else f"{note} {extra_note}"

    return selected, section_lengths, note, truncated


def _truncate_selected_sections(selected: dict[str, str], max_total_chars: int) -> dict[str, str]:
    remaining = dict(selected)
    truncated: dict[str, str] = {}
    remaining_budget = max_total_chars

    while remaining:
        share = max(remaining_budget // len(remaining), 1)
        short_sections = {
            name: value for name, value in remaining.items() if len(value) <= share
        }
        if short_sections:
            for name, value in short_sections.items():
                truncated[name] = value
                remaining_budget -= len(value)
                del remaining[name]
            continue

        share = max(remaining_budget // len(remaining), 1)
        for name, value in remaining.items():
            truncated[name] = value[:share].strip()
        break

    return truncated
