"""Network-free, decision-level evaluation of the cut/keep layer.

Instead of rendering a video and re-transcribing it (minutes + two paid APIs per
run), this compares the *decisions* directly:

    raw transcript  +  EDL  +  human-edited ground-truth transcript

For every raw sentence it derives the pipeline's keep/cut call (from the EDL) and
the human's keep/cut call (by word coverage against the ground-truth edited
transcript). The result is a per-sentence confusion matrix — cut precision/recall
against what the human actually did — broken down by the mechanism that made each
cut. It runs quickly enough for threshold sweeps in the iteration loop.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loguru import logger
from rapidfuzz import fuzz

from ai_video_editor.duplicate.edl import EditAction, EditDecisionList
from ai_video_editor.qa.ground_truth import _align_monotonic, derive_word_coverage
from ai_video_editor.qa.models import CutDecisionResult
from ai_video_editor.transcription.models import Sentence, Transcript, Word

MATCH_THRESHOLD = 65.0
COVERAGE_THRESHOLD = 0.5
TAKE_RECONCILIATION_WINDOW = 6
TAKE_RECONCILIATION_SIMILARITY = 75.0


@dataclass
class DecisionScore:
    name: str
    # positive class = CUT
    tp: int = 0  # pipeline cut, human cut
    fp: int = 0  # pipeline cut, human kept  (over-cut)
    fn: int = 0  # pipeline kept, human cut  (missed cut)
    tn: int = 0  # pipeline kept, human kept
    take_disagreements: int = 0
    wrong_cut_by_reason: Counter = field(default_factory=Counter)
    right_cut_by_reason: Counter = field(default_factory=Counter)

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def cut_precision(self) -> float:
        made_cuts = self.tp + self.fp
        return self.tp / made_cuts if made_cuts else 1.0

    @property
    def cut_recall(self) -> float:
        needed_cuts = self.tp + self.fn
        return self.tp / needed_cuts if needed_cuts else 1.0

    @property
    def cut_f1(self) -> float:
        p, r = self.cut_precision, self.cut_recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.n if self.n else 0.0


@dataclass
class HumanVerdicts:
    """Human keep/cut verdicts for raw sentences plus diagnostic metadata."""

    human_kept: list[bool]
    coverage: list[float]
    take_disagreement_pairs: list[tuple[int, int]] = field(default_factory=list)

    @property
    def take_disagreement_indices(self) -> set[int]:
        return {
            idx
            for pair in self.take_disagreement_pairs
            for idx in pair
        }


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


def _sentence_similarity(a: Sentence, b: Sentence) -> float:
    return max(fuzz.ratio(a.text, b.text), fuzz.token_sort_ratio(a.text, b.text))


def _reconcile_take_disagreements(
    sentences: list[Sentence],
    pipeline_cuts: list[bool],
    human_kept: list[bool],
    *,
    window: int = TAKE_RECONCILIATION_WINDOW,
    similarity_threshold: float = TAKE_RECONCILIATION_SIMILARITY,
) -> tuple[list[bool], list[tuple[int, int]]]:
    """Credit near-identical retakes as content-correct but track take swaps.

    A common artifact is that the GT's single copy of a retake gets credited to
    the version the pipeline cut, while the version the pipeline kept gets zero
    coverage. That is a wrong-take disagreement, not a missed content cut plus
    overcut pair.
    """
    candidates: list[tuple[float, int, int]] = []
    overcut_like = [
        i for i, (pipeline_cut, kept) in enumerate(zip(pipeline_cuts, human_kept))
        if pipeline_cut and kept
    ]
    missed_like = [
        i for i, (pipeline_cut, kept) in enumerate(zip(pipeline_cuts, human_kept))
        if not pipeline_cut and not kept
    ]

    for cut_idx in overcut_like:
        for kept_idx in missed_like:
            if abs(cut_idx - kept_idx) > window:
                continue
            sim = _sentence_similarity(sentences[cut_idx], sentences[kept_idx])
            if sim >= similarity_threshold:
                candidates.append((sim, cut_idx, kept_idx))

    reconciled = list(human_kept)
    used: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, cut_idx, kept_idx in sorted(candidates, reverse=True):
        if cut_idx in used or kept_idx in used:
            continue
        used.add(cut_idx)
        used.add(kept_idx)
        # Align the human verdict with the pipeline's chosen copy for the
        # content-level confusion matrix; the pair is still counted separately.
        reconciled[cut_idx] = False
        reconciled[kept_idx] = True
        pairs.append((cut_idx, kept_idx))

    return reconciled, pairs


def derive_human_verdicts(
    raw_sentences: list[Sentence],
    gt_sentences: list[Sentence],
    *,
    pipeline_cuts: list[bool] | None = None,
    method: Literal["words", "sentences"] = "words",
    match_threshold: float = MATCH_THRESHOLD,
    coverage_threshold: float = COVERAGE_THRESHOLD,
) -> HumanVerdicts:
    """Derive human keep/cut verdicts for each raw sentence.

    ``method="words"`` is the default QA path. ``method="sentences"`` preserves
    the previous monotonic sentence-alignment behaviour for A/B comparisons.
    """
    if method == "sentences":
        aligned = _align_monotonic(raw_sentences, gt_sentences, match_threshold)
        kept_indices = {pi for pi, _, _ in aligned}
        human_kept = [i in kept_indices for i in range(len(raw_sentences))]
        return HumanVerdicts(
            human_kept=human_kept,
            coverage=[1.0 if kept else 0.0 for kept in human_kept],
        )

    if method != "words":
        raise ValueError(f"Unknown human verdict method: {method!r}")

    coverage = derive_word_coverage(raw_sentences, gt_sentences)
    human_kept = [value >= coverage_threshold for value in coverage]
    take_disagreements: list[tuple[int, int]] = []
    if pipeline_cuts is not None:
        if len(pipeline_cuts) != len(raw_sentences):
            raise ValueError("pipeline_cuts length must match raw_sentences")
        human_kept, take_disagreements = _reconcile_take_disagreements(
            raw_sentences,
            pipeline_cuts,
            human_kept,
        )

    return HumanVerdicts(
        human_kept=human_kept,
        coverage=coverage,
        take_disagreement_pairs=take_disagreements,
    )


def evaluate_decisions(
    raw_sentences: list[Sentence],
    edl: EditDecisionList,
    gt_sentences: list[Sentence],
    *,
    name: str = "",
    match_threshold: float = MATCH_THRESHOLD,
    method: Literal["words", "sentences"] = "words",
) -> DecisionScore:
    """Score the pipeline's keep/cut decisions for one video against ground truth."""
    pipeline = [_cut_reason(s, edl) for s in raw_sentences]
    pipeline_cuts = [is_cut for is_cut, _ in pipeline]
    verdicts = derive_human_verdicts(
        raw_sentences,
        gt_sentences,
        pipeline_cuts=pipeline_cuts,
        method=method,
        match_threshold=match_threshold,
    )

    score = DecisionScore(
        name=name,
        take_disagreements=len(verdicts.take_disagreement_pairs),
    )
    for i, (is_cut, reason) in enumerate(pipeline):
        kept_by_human = verdicts.human_kept[i]
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


@dataclass
class WordDecisionScore:
    """Word-level cut/keep confusion vs the human edit (positive class = CUT).

    Sentence-level scoring counts a word-trim that removes a stutter as a full
    missed/over cut. This scores every word independently, so a partial trim is
    credited for the words it correctly removed and only penalised for the rest.
    """
    name: str = ""
    tp: int = 0  # word cut by pipeline, cut by human
    fp: int = 0  # word cut by pipeline, kept by human
    fn: int = 0  # word kept by pipeline, cut by human
    tn: int = 0

    @property
    def cut_precision(self) -> float:
        made = self.tp + self.fp
        return self.tp / made if made else 1.0

    @property
    def cut_recall(self) -> float:
        needed = self.tp + self.fn
        return self.tp / needed if needed else 1.0

    @property
    def cut_f1(self) -> float:
        p, r = self.cut_precision, self.cut_recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def _word_is_cut(word: Word, edl: EditDecisionList) -> bool:
    """A word is cut if its midpoint lands in no KEEP decision."""
    mid = (word.start + word.end) / 2.0
    for d in edl.decisions:
        if d.action == EditAction.KEEP and d.start <= mid <= d.end:
            return False
    return True


def evaluate_decisions_word_level(
    raw_sentences: list[Sentence],
    edl: EditDecisionList,
    gt_sentences: list[Sentence],
    *,
    name: str = "",
) -> WordDecisionScore:
    """Score the EDL's cut/keep at word granularity against the human edit."""
    from ai_video_editor.qa.ground_truth import derive_word_keep_flags

    human_kept = derive_word_keep_flags(raw_sentences, gt_sentences)
    score = WordDecisionScore(name=name)
    for si, sentence in enumerate(raw_sentences):
        for wi, word in enumerate(sentence.words):
            pipeline_cut = _word_is_cut(word, edl)
            kept_by_human = human_kept[si][wi]
            if pipeline_cut and not kept_by_human:
                score.tp += 1
            elif pipeline_cut and kept_by_human:
                score.fp += 1
            elif not pipeline_cut and not kept_by_human:
                score.fn += 1
            else:
                score.tn += 1
    return score


def aggregate_word_scores(scores: list[WordDecisionScore]) -> WordDecisionScore:
    agg = WordDecisionScore(name="AGGREGATE")
    for s in scores:
        agg.tp += s.tp
        agg.fp += s.fp
        agg.fn += s.fn
        agg.tn += s.tn
    return agg


def to_cut_decision_result(score: DecisionScore) -> CutDecisionResult:
    """Convert a DecisionScore into the serialisable QA-report model."""
    return CutDecisionResult(
        true_cuts=score.tp,
        overcuts=score.fp,
        missed_cuts=score.fn,
        true_keeps=score.tn,
        take_disagreements=score.take_disagreements,
        wrong_cut_by_reason=dict(score.wrong_cut_by_reason),
        right_cut_by_reason=dict(score.right_cut_by_reason),
    )


def _load_sentences(path: Path) -> list[Sentence]:
    return Transcript.model_validate_json(path.read_text("utf-8")).sentences


def evaluate_fixture(
    fixtures_dir: Path,
    name: str,
    *,
    edl_path: Path | None = None,
    method: Literal["words", "sentences"] = "words",
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
    return evaluate_decisions(raw, edl, gt, name=name, method=method)


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
        agg.take_disagreements += s.take_disagreements
        agg.wrong_cut_by_reason.update(s.wrong_cut_by_reason)
        agg.right_cut_by_reason.update(s.right_cut_by_reason)
    return agg


def format_report(scores: list[DecisionScore]) -> str:
    lines = [
        "Decision-level evaluation (positive class = CUT, vs human ground truth)",
        "",
        f"{'video':<12} {'n':>5} {'cutP':>6} {'cutR':>6} {'cutF1':>6} {'acc':>6} {'TP':>4} {'FP':>4} {'FN':>4} {'swap':>5}",
        "-" * 76,
    ]
    for s in scores:
        lines.append(
            f"{s.name:<12} {s.n:>5} {s.cut_precision:>6.3f} {s.cut_recall:>6.3f} "
            f"{s.cut_f1:>6.3f} {s.accuracy:>6.3f} {s.tp:>4} {s.fp:>4} {s.fn:>4} "
            f"{s.take_disagreements:>5}"
        )
    agg = aggregate(scores)
    lines += [
        "-" * 76,
        f"{'AGGREGATE':<12} {agg.n:>5} {agg.cut_precision:>6.3f} {agg.cut_recall:>6.3f} "
        f"{agg.cut_f1:>6.3f} {agg.accuracy:>6.3f} {agg.tp:>4} {agg.fp:>4} {agg.fn:>4} "
        f"{agg.take_disagreements:>5}",
        "",
        f"Take disagreements:                    {agg.take_disagreements}",
        f"Wrong cuts (human kept) by mechanism: {dict(agg.wrong_cut_by_reason)}",
        f"Right cuts by mechanism:              {dict(agg.right_cut_by_reason)}",
    ]
    return "\n".join(lines)
