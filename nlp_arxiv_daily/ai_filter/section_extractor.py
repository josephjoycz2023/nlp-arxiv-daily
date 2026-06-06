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
) -> tuple[dict[str, str], str | None, bool]:
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
        note = "未识别到偏好章节标题，退回为整篇 PDF 文本截断片段。"
        selected = {"full_text_excerpt": paper_text.strip()}

    total_chars = sum(len(value) for value in selected.values())
    truncated = total_chars > max_total_chars
    if truncated:
        budget = max(max_total_chars // max(len(selected), 1), 1_200)
        selected = {name: value[:budget].strip() for name, value in selected.items()}
        extra_note = "已按提示词预算截断章节内容。"
        note = extra_note if note is None else f"{note} {extra_note}"

    return selected, note, truncated
