"""Materialised per-sentence alignment between raw transcript, EDL, and human edit.

The decision-level eval (``decision_eval.py``) reduces each video to a confusion
matrix. That tells you *how many* decisions were wrong but not *which* ones or
*why*. This module writes the full alignment out as a sidecar so mistakes can be
inspected and mined for patterns across the fixture set:

    <name>.alignment.json  — one row per raw sentence, both verdicts + outcome
    <name>.alignment.txt   — human-readable decision diff of the same rows

Outcome classes (positive class = CUT, same convention as decision_eval):
    true_cut    pipeline cut,  human cut   — correct cut
    overcut     pipeline cut,  human kept  — we removed content the human kept
    missed_cut  pipeline kept, human cut   — we kept content the human removed
    true_keep   pipeline kept, human kept  — correct keep
    take_swap   both kept one near-identical take, but not the same one
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from ai_video_editor.duplicate.edl import EditDecisionList
from ai_video_editor.qa.decision_eval import (
    MATCH_THRESHOLD,
    _cut_reason,
    derive_human_verdicts,
)
from ai_video_editor.qa.ground_truth import _align_monotonic
from ai_video_editor.transcription.models import Sentence


class AlignmentRow(BaseModel):
    """One raw sentence with the pipeline's and the human's verdict."""
    idx: int
    text: str
    start: float
    end: float
    word_count: int
    pipeline_cut: bool
    cut_reason: str = ""  # EDL mechanism ("duplicate", "false_start", ...) if cut
    human_kept: bool
    coverage: float = 0.0
    gt_idx: int | None = None
    gt_text: str | None = None
    similarity: float | None = None
    outcome: str  # true_cut | overcut | missed_cut | true_keep | take_swap


class AlignmentDump(BaseModel):
    """Full decision diff for one video."""
    name: str
    match_threshold: float = MATCH_THRESHOLD
    take_disagreements: int = 0
    rows: list[AlignmentRow] = Field(default_factory=list)
    # GT sentences that matched no raw sentence — usually transcription drift;
    # a high count means the human verdicts derived here are less trustworthy.
    gt_unmatched: list[str] = Field(default_factory=list)

    def count(self, outcome: str) -> int:
        return sum(1 for r in self.rows if r.outcome == outcome)


def build_alignment(
    name: str,
    raw_sentences: list[Sentence],
    edl: EditDecisionList,
    gt_sentences: list[Sentence],
    *,
    match_threshold: float = MATCH_THRESHOLD,
) -> AlignmentDump:
    """Align raw sentences to the human edit and pair with the EDL's decisions."""
    aligned = _align_monotonic(raw_sentences, gt_sentences, match_threshold)
    gt_by_raw = {pi: (gi, score) for pi, gi, score in aligned}
    matched_gi = {gi for _, gi, _ in aligned}
    pipeline = [_cut_reason(s, edl) for s in raw_sentences]
    verdicts = derive_human_verdicts(
        raw_sentences,
        gt_sentences,
        pipeline_cuts=[is_cut for is_cut, _ in pipeline],
        match_threshold=match_threshold,
    )
    take_swap_indices = verdicts.take_disagreement_indices

    rows: list[AlignmentRow] = []
    for i, s in enumerate(raw_sentences):
        is_cut, reason = pipeline[i]
        match = gt_by_raw.get(i)
        human_kept = verdicts.human_kept[i]
        if i in take_swap_indices:
            outcome = "take_swap"
        elif is_cut:
            outcome = "overcut" if human_kept else "true_cut"
        else:
            outcome = "true_keep" if human_kept else "missed_cut"
        rows.append(AlignmentRow(
            idx=i,
            text=s.text,
            start=s.start,
            end=s.end,
            word_count=len(s.words),
            pipeline_cut=is_cut,
            cut_reason=reason,
            human_kept=human_kept,
            coverage=round(verdicts.coverage[i], 4),
            gt_idx=match[0] if match else None,
            gt_text=gt_sentences[match[0]].text if match else None,
            similarity=round(match[1], 1) if match else None,
            outcome=outcome,
        ))

    gt_unmatched = [
        gt_sentences[gi].text
        for gi in range(len(gt_sentences))
        if gi not in matched_gi
    ]
    return AlignmentDump(
        name=name,
        match_threshold=match_threshold,
        take_disagreements=len(verdicts.take_disagreement_pairs),
        rows=rows,
        gt_unmatched=gt_unmatched,
    )


_MARKERS = {
    "true_keep": "=     ",
    "true_cut": "x     ",
    "missed_cut": "!MISS ",
    "overcut": "!OVER ",
    "take_swap": "~SWAP ",
}


def format_alignment_text(dump: AlignmentDump) -> str:
    """Render the decision diff as grep-friendly plain text.

    ``=`` both kept, ``x`` both cut, ``!MISS`` human cut but we kept,
    ``!OVER`` we cut but human kept.
    """
    lines = [
        f"Decision diff: {dump.name}",
        f"  true_keep={dump.count('true_keep')} true_cut={dump.count('true_cut')} "
        f"missed_cut={dump.count('missed_cut')} overcut={dump.count('overcut')} "
        f"take_disagreements={dump.take_disagreements} "
        f"gt_unmatched={len(dump.gt_unmatched)}",
        "",
    ]
    for r in dump.rows:
        marker = _MARKERS[r.outcome]
        reason = f" [{r.cut_reason}]" if r.cut_reason else ""
        line = f'[{r.idx:>4}] {marker}{reason:<14} cov={r.coverage:.0%} "{r.text}"'
        if r.outcome == "overcut" and r.gt_idx is not None:
            line += f'  (human kept as gt#{r.gt_idx} @{r.similarity:.0f}%)'
        lines.append(line)
    if dump.gt_unmatched:
        lines += ["", "GT sentences with no raw match (alignment blind spots):"]
        lines += [f'  ? "{t}"' for t in dump.gt_unmatched]
    return "\n".join(lines)


def dump_alignment(
    name: str,
    raw_sentences: list[Sentence],
    edl: EditDecisionList,
    gt_sentences: list[Sentence],
    output_dir: Path,
    *,
    match_threshold: float = MATCH_THRESHOLD,
) -> AlignmentDump:
    """Build the alignment for one video and write both sidecar files."""
    dump = build_alignment(
        name, raw_sentences, edl, gt_sentences, match_threshold=match_threshold
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{name}.alignment.json"
    txt_path = output_dir / f"{name}.alignment.txt"
    json_path.write_text(dump.model_dump_json(indent=2), encoding="utf-8")
    txt_path.write_text(format_alignment_text(dump), encoding="utf-8")
    logger.info(
        "Alignment dump: {} ({} rows, {} missed, {} overcut, {} take disagreements) → {}",
        name, len(dump.rows), dump.count("missed_cut"), dump.count("overcut"),
        dump.take_disagreements,
        json_path.name,
    )
    return dump
