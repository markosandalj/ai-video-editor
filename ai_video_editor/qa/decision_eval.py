"""Network-free, decision-level evaluation of the cut/keep layer.

Instead of rendering a video and re-transcribing it (minutes + two paid APIs per
run), this compares the *decisions* directly:

    raw transcript  +  EDL  +  human-edited ground-truth transcript

For every raw sentence it derives the pipeline's keep/cut call (from the EDL) and
the human's keep/cut call (by order-preserving alignment of the raw transcript to
the ground-truth edited transcript). The result is a per-sentence confusion
matrix — cut precision/recall against what the human actually did — broken down
by the mechanism that made each cut. It runs in well under a second for the whole
fixture set, which is what makes threshold sweeps in the iteration loop practical.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from ai_video_editor.duplicate.edl import EditAction, EditDecisionList
from ai_video_editor.qa.ground_truth import _align_monotonic
from ai_video_editor.transcription.models import Sentence, Transcript

MATCH_THRESHOLD = 65.0


@dataclass
class DecisionScore:
    name: str
    # positive class = CUT
    tp: int = 0  # pipeline cut, human cut
    fp: int = 0  # pipeline cut, human kept  (over-cut)
    fn: int = 0  # pipeline kept, human cut  (missed cut)
    tn: int = 0  # pipeline kept, human kept
    wrong_cut_by_reason: Counter = field(default_factory=Counter)
    right_cut_by_reason: Counter = field(default_factory=Counter)

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def cut_precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def cut_recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def cut_f1(self) -> float:
        p, r = self.cut_precision, self.cut_recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.n if self.n else 0.0


def _cut_reason(sentence: Sentence, edl: EditDecisionList) -> tuple[bool, str]:
    """Return (is_cut, reason) for a sentence given the EDL (kept < 50% ⇒ cut)."""
    dur = max(sentence.end - sentence.start, 0.0)
    if dur <= 0:
        return False, ""
    kept = 0.0
    reason = ""
    for d in edl.decisions:
        overlap = max(0.0, min(sentence.end, d.end) - max(sentence.start, d.start))
        if overlap <= 0:
            continue
        if d.action == EditAction.KEEP:
            kept += overlap
        elif not reason:
            reason = d.reason.value
    is_cut = (kept / dur) < 0.5
    return is_cut, (reason if is_cut else "")


def evaluate_decisions(
    raw_sentences: list[Sentence],
    edl: EditDecisionList,
    gt_sentences: list[Sentence],
    *,
    name: str = "",
    match_threshold: float = MATCH_THRESHOLD,
) -> DecisionScore:
    """Score the pipeline's keep/cut decisions for one video against ground truth."""
    aligned = _align_monotonic(raw_sentences, gt_sentences, match_threshold)
    human_kept = {pi for pi, _, _ in aligned}

    score = DecisionScore(name=name)
    for i, s in enumerate(raw_sentences):
        is_cut, reason = _cut_reason(s, edl)
        kept_by_human = i in human_kept
        if is_cut and not kept_by_human:
            score.tp += 1
            score.right_cut_by_reason[reason] += 1
        elif is_cut and kept_by_human:
            score.fp += 1
            score.wrong_cut_by_reason[reason] += 1
        elif not is_cut and not kept_by_human:
            score.fn += 1
        else:
            score.tn += 1
    return score


def _load_sentences(path: Path) -> list[Sentence]:
    return Transcript.model_validate_json(path.read_text("utf-8")).sentences


def evaluate_fixture(
    fixtures_dir: Path,
    name: str,
    *,
    edl_path: Path | None = None,
) -> DecisionScore | None:
    """Evaluate one fixture by name using cached sidecars only (no network)."""
    raw_t = fixtures_dir / f"{name}-raw.transcript.json"
    edl_p = edl_path or fixtures_dir / f"{name}-raw.edl.json"
    gt_t = fixtures_dir / f"{name}-edited.qa-transcript.json"
    if not (raw_t.exists() and edl_p.exists() and gt_t.exists()):
        logger.warning("Skipping {} — missing sidecars", name)
        return None
    raw = _load_sentences(raw_t)
    edl = EditDecisionList.model_validate_json(edl_p.read_text("utf-8"))
    gt = _load_sentences(gt_t)
    return evaluate_decisions(raw, edl, gt, name=name)


def discover_fixture_names(fixtures_dir: Path) -> list[str]:
    names = sorted(
        p.name[: -len("-raw.transcript.json")]
        for p in fixtures_dir.glob("*-raw.transcript.json")
    )
    return names


def aggregate(scores: list[DecisionScore]) -> DecisionScore:
    agg = DecisionScore(name="AGGREGATE")
    for s in scores:
        agg.tp += s.tp
        agg.fp += s.fp
        agg.fn += s.fn
        agg.tn += s.tn
        agg.wrong_cut_by_reason.update(s.wrong_cut_by_reason)
        agg.right_cut_by_reason.update(s.right_cut_by_reason)
    return agg


def format_report(scores: list[DecisionScore]) -> str:
    lines = [
        "Decision-level evaluation (positive class = CUT, vs human ground truth)",
        "",
        f"{'video':<12} {'n':>5} {'cutP':>6} {'cutR':>6} {'cutF1':>6} {'acc':>6} {'TP':>4} {'FP':>4} {'FN':>4}",
        "-" * 70,
    ]
    for s in scores:
        lines.append(
            f"{s.name:<12} {s.n:>5} {s.cut_precision:>6.3f} {s.cut_recall:>6.3f} "
            f"{s.cut_f1:>6.3f} {s.accuracy:>6.3f} {s.tp:>4} {s.fp:>4} {s.fn:>4}"
        )
    agg = aggregate(scores)
    lines += [
        "-" * 70,
        f"{'AGGREGATE':<12} {agg.n:>5} {agg.cut_precision:>6.3f} {agg.cut_recall:>6.3f} "
        f"{agg.cut_f1:>6.3f} {agg.accuracy:>6.3f} {agg.tp:>4} {agg.fp:>4} {agg.fn:>4}",
        "",
        f"Wrong cuts (human kept) by mechanism: {dict(agg.wrong_cut_by_reason)}",
        f"Right cuts by mechanism:              {dict(agg.right_cut_by_reason)}",
    ]
    return "\n".join(lines)
