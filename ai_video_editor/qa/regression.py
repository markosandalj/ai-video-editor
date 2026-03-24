from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from ai_video_editor.qa.models import QAReport


class PairScore(BaseModel):
    name: str
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    temporal_score: float = 0.0
    overall_score: float = 0.0


class RegressionEntry(BaseModel):
    timestamp: str = ""
    pairs: list[PairScore] = Field(default_factory=list)
    aggregate_score: float = 0.0

    def model_post_init(self, __context: object) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def discover_pairs(directory: Path) -> list[tuple[str, Path, Path]]:
    """
    Find raw/edited video pairs by naming convention.

    Looks for ``<name>-raw.mp4`` and ``<name>-edited.mp4`` in the same directory.
    Returns list of ``(name, raw_path, edited_path)`` tuples.
    """
    raw_files: dict[str, Path] = {}
    edited_files: dict[str, Path] = {}

    for f in sorted(directory.iterdir()):
        if not f.is_file() or f.suffix.lower() != ".mp4":
            continue
        m = re.match(r"^(.+)-raw\.mp4$", f.name)
        if m:
            raw_files[m.group(1)] = f
            continue
        m = re.match(r"^(.+)-edited\.mp4$", f.name)
        if m:
            edited_files[m.group(1)] = f

    pairs = []
    for name in sorted(raw_files.keys()):
        if name in edited_files:
            pairs.append((name, raw_files[name], edited_files[name]))

    logger.info("Discovered {} test pairs in {}", len(pairs), directory)
    return pairs


def record_scores(
    reports: list[QAReport],
    history_path: Path,
) -> RegressionEntry:
    """
    Build a RegressionEntry from QA reports and append to the history file.
    """
    pair_scores: list[PairScore] = []
    for r in reports:
        ps = PairScore(name=r.video_name, overall_score=r.overall_score)
        if r.transcript_comparison:
            ps.precision = r.transcript_comparison.precision
            ps.recall = r.transcript_comparison.recall
            ps.f1 = r.transcript_comparison.f1
        if r.temporal_comparison:
            ps.temporal_score = r.temporal_comparison.temporal_score
        pair_scores.append(ps)

    aggregate = (
        sum(p.overall_score for p in pair_scores) / len(pair_scores)
        if pair_scores else 0.0
    )

    entry = RegressionEntry(
        pairs=pair_scores,
        aggregate_score=round(aggregate, 4),
    )

    history: list[dict] = []
    if history_path.exists():
        history = json.loads(history_path.read_text("utf-8"))

    history.append(entry.model_dump())
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("Regression score recorded: {:.1%} ({} pairs)", aggregate, len(pair_scores))
    return entry


def check_regression(
    current: RegressionEntry,
    history_path: Path,
) -> list[str]:
    """
    Compare current scores against the previous run.
    Returns a list of regression warnings (empty = no regressions).
    """
    if not history_path.exists():
        return []

    history = json.loads(history_path.read_text("utf-8"))
    if len(history) < 2:
        return []

    previous = RegressionEntry.model_validate(history[-2])
    warnings: list[str] = []

    if current.aggregate_score < previous.aggregate_score - 0.01:
        warnings.append(
            f"REGRESSION: aggregate score dropped "
            f"{previous.aggregate_score:.1%} → {current.aggregate_score:.1%}"
        )

    prev_by_name = {p.name: p for p in previous.pairs}
    for p in current.pairs:
        prev_p = prev_by_name.get(p.name)
        if prev_p and p.overall_score < prev_p.overall_score - 0.01:
            warnings.append(
                f"REGRESSION [{p.name}]: "
                f"{prev_p.overall_score:.1%} → {p.overall_score:.1%}"
            )

    if warnings:
        for w in warnings:
            logger.warning(w)
    else:
        logger.info("No regressions detected vs. previous run")

    return warnings
