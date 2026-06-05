from __future__ import annotations

import datetime
import json
import os
import re

from nlp_arxiv_daily.types import Paper, PapersByKeyword, PapersByMonth


ARXIV_KEY_RE = re.compile(r"^(\d{4})\.\d{4,5}")


def bucket_by_month(papers_by_keyword: PapersByKeyword) -> PapersByMonth:
    """
    {keyword: {paper_key: line}} → {yymm: {keyword: {paper_key: line}}}.
    paper_key matching ARXIV_KEY_RE (e.g. "2604.21637") is bucketed by its YYMM
    prefix. Keys that don't match are silently dropped — defensive against any
    legacy entries that don't follow arxiv's id format.
    """
    by_month: PapersByMonth = {}
    for keyword, papers in papers_by_keyword.items():
        for key, line in papers.items():
            m = ARXIV_KEY_RE.match(key)
            if not m:
                continue
            yymm = m.group(1)
            by_month.setdefault(yymm, {}).setdefault(keyword, {})[key] = line
    return by_month


def _yymm_to_archive_basename(yymm: str) -> str:
    return f"20{yymm[:2]}-{yymm[2:]}"


def _current_yymm() -> str:
    today = datetime.date.today()
    return f"{today.year % 100:02d}{today.month:02d}"


def _current_yyyymmdd() -> str:
    return datetime.date.today().strftime("%Y%m%d")


def _load_papers_json(path: str, into: dict) -> None:
    if not os.path.exists(path):
        return
    with open(path) as f:
        content = f.read()
    if not content:
        return
    for kw, papers in json.loads(content).items():
        into.setdefault(kw, {}).update(papers)


def _ordered_bucket(bucket: PapersByKeyword, keyword_order: list[str] | None) -> PapersByKeyword:
    """Return `bucket` with keys reordered per `keyword_order`. Keys not in the
    order list keep their original relative position at the end. `None` is identity."""
    if not keyword_order:
        return bucket
    ordered: PapersByKeyword = {k: bucket[k] for k in keyword_order if k in bucket}
    for k, v in bucket.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def _load_json_dict(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        content = f.read()
    return json.loads(content) if content else {}


def _topic_dir_name(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.strip().lower()).strip("-")
    return slug or "unknown-topic"


def _paper_basic_info(paper: Paper) -> dict[str, str | None]:
    return {
        "paper_id": paper.paper_id,
        "published_date": paper.update_time.isoformat(),
        "title": paper.title,
        "authors": f"{paper.first_author} et.al.",
        "paper_url": paper.paper_url,
        "code_link": paper.code_link,
    }


def write_topic_paper_files(
    papers_by_topic: dict[str, list[Paper]],
    docs_dir: str,
) -> None:
    """Persist per-paper JSON files under docs/<topic>/<YYYYMMDD>/<paper_id>.json."""
    for topic, papers in papers_by_topic.items():
        topic_dir = os.path.join(docs_dir, _topic_dir_name(topic))
        for paper in papers:
            day_dir = os.path.join(topic_dir, paper.update_time.strftime("%Y%m%d"))
            os.makedirs(day_dir, exist_ok=True)
            paper_path = os.path.join(day_dir, f"{paper.paper_id}.json")
            with open(paper_path, "w") as f:
                json.dump(_paper_basic_info(paper), f, indent=2)


def write_keyword_day_snapshots(
    new_papers_list: list[PapersByKeyword],
    docs_dir: str,
    *,
    snapshot_date: str | None = None,
    keyword_order: list[str] | None = None,
) -> None:
    """Persist per-keyword daily snapshots under docs/<keyword>/<YYYYMMDD>/papers.json.

    Re-runs on the same date merge into the same `papers.json`, making the
    write idempotent for repeated local fetches on one day.
    """
    if snapshot_date is None:
        snapshot_date = _current_yyyymmdd()

    ordered_batches = new_papers_list
    if keyword_order:
        ordered_batches = [_ordered_bucket(batch, keyword_order) for batch in new_papers_list]

    for batch in ordered_batches:
        for keyword, papers in batch.items():
            day_dir = os.path.join(docs_dir, keyword, snapshot_date)
            os.makedirs(day_dir, exist_ok=True)
            snapshot_path = os.path.join(day_dir, "papers.json")
            existing = _load_json_dict(snapshot_path)
            existing.update(papers)
            with open(snapshot_path, "w") as f:
                json.dump(existing, f)


def write_papers_split(
    new_papers_list: list[PapersByKeyword],
    main_json_path: str,
    archive_dir: str,
    current_yymm: str | None = None,
    keyword_order: list[str] | None = None,
) -> None:
    """
    Re-bucket all known papers (existing main + archive + new daily) by YYMM and
    write current month → main_json_path, older months → archive_dir/YYYY-MM.json.

    Idempotent: running with new_papers_list=[] re-distributes existing data.
    Migration is implicit — first run with a legacy "all months in main" file
    splits it.

    `keyword_order` (when given) controls the order of top-level keyword keys
    in every emitted JSON file. The Astro site iterates JSON entries in
    insertion order, so this makes config.yaml the source of truth for both
    markdown and the gitpage site. Keys missing from the order list are
    appended at the end.
    """
    if current_yymm is None:
        current_yymm = _current_yymm()

    accumulated: PapersByKeyword = {}
    _load_papers_json(main_json_path, accumulated)
    if os.path.isdir(archive_dir):
        for name in sorted(os.listdir(archive_dir)):
            if name.endswith(".json"):
                _load_papers_json(os.path.join(archive_dir, name), accumulated)

    for new_papers in new_papers_list:
        for kw, papers in new_papers.items():
            accumulated.setdefault(kw, {}).update(papers)

    by_month = bucket_by_month(accumulated)

    main_dir = os.path.dirname(main_json_path)
    if main_dir:
        os.makedirs(main_dir, exist_ok=True)
    main_bucket = _ordered_bucket(by_month.pop(current_yymm, {}), keyword_order)
    with open(main_json_path, "w") as f:
        json.dump(main_bucket, f)

    os.makedirs(archive_dir, exist_ok=True)
    for yymm, bucket in by_month.items():
        archive_path = os.path.join(archive_dir, f"{_yymm_to_archive_basename(yymm)}.json")
        with open(archive_path, "w") as f:
            json.dump(_ordered_bucket(bucket, keyword_order), f)


def update_json_file(filename, data_dict):
    """
    daily update json file using data_dict
    """
    if os.path.exists(filename):
        with open(filename) as f:
            content = f.read()
        m = json.loads(content) if content else {}
    else:
        m = {}

    json_data = m.copy()

    # update papers in each keywords
    for data in data_dict:
        for keyword in data:
            papers = data[keyword]

            if keyword in json_data:
                json_data[keyword].update(papers)
            else:
                json_data[keyword] = papers

    with open(filename, "w") as f:
        json.dump(json_data, f)
