from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from ai_video_editor.duplicate.edl import EditDecisionList
from ai_video_editor.enrich.models import (
    EnrichmentResult,
    EnrichmentStatus,
)
from ai_video_editor.qa.decision_eval import (
    DecisionScore,
    MATCH_THRESHOLD,
    _cut_reason,
    aggregate,
    derive_human_verdicts,
)
from ai_video_editor.transcription.models import Sentence


class BinaryMetrics(BaseModel):
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


class RankingPoint(BaseModel):
    is_target: bool
    score: float


class AnnotationActionabilityScore(BaseModel):
    name: str = ""
    n: int = 0
    wrong_cuts: int = 0
    missed_cuts: int = 0
    restore: BinaryMetrics = Field(default_factory=BinaryMetrics)
    attention: BinaryMetrics = Field(default_factory=BinaryMetrics)
    ranking_average_precision: float = 0.0
    status_counts: dict[str, int] = Field(default_factory=dict)
    ranking_points: list[RankingPoint] = Field(default_factory=list, exclude=True)


def decision_score_to_dict(score: DecisionScore) -> dict[str, object]:
    return {
        "name": score.name,
        "n": score.n,
        "cut_precision": score.cut_precision,
        "cut_recall": score.cut_recall,
        "cut_f1": score.cut_f1,
        "accuracy": score.accuracy,
        "tp": score.tp,
        "fp": score.fp,
        "fn": score.fn,
        "tn": score.tn,
        "take_disagreements": score.take_disagreements,
        "wrong_cut_by_reason": dict(score.wrong_cut_by_reason),
        "right_cut_by_reason": dict(score.right_cut_by_reason),
    }


def aggregate_decision_scores(scores: list[DecisionScore]) -> dict[str, object]:
    return decision_score_to_dict(aggregate(scores)) if scores else decision_score_to_dict(DecisionScore(name="AGGREGATE"))


def score_annotation_actionability(
    raw_sentences: list[Sentence],
    baseline_edl: EditDecisionList,
    gt_sentences: list[Sentence],
    enrichment: EnrichmentResult,
    *,
    name: str = "",
    match_threshold: float = MATCH_THRESHOLD,
) -> AnnotationActionabilityScore:
    enrichment_by_idx = enrichment.by_index()
    pipeline_cuts = [_cut_reason(sentence, baseline_edl)[0] for sentence in raw_sentences]
    human_verdicts = derive_human_verdicts(
        raw_sentences,
        gt_sentences,
        pipeline_cuts=pipeline_cuts,
        match_threshold=match_threshold,
    )

    restore_tp = restore_fp = restore_fn = 0
    attention_tp = attention_fp = attention_fn = 0
    wrong_cuts = missed_cuts = 0
    status_counts: Counter[str] = Counter()
    ranking_points: list[RankingPoint] = []

    for idx, sentence in enumerate(raw_sentences):
        pipeline_cut = pipeline_cuts[idx]
        kept_by_human = human_verdicts.human_kept[idx]
        wrong_cut = pipeline_cut and kept_by_human
        missed_cut = (not pipeline_cut) and (not kept_by_human)
        wrong_cuts += int(wrong_cut)
        missed_cuts += int(missed_cut)

        item = enrichment_by_idx.get(idx)
        if item is not None:
            status_counts[item.status.value] += 1
            keep_confidence = item.keep_confidence
            restore_signal = pipeline_cut and item.status == EnrichmentStatus.RESTORE
            attention_signal = (not pipeline_cut) and item.status == EnrichmentStatus.YELLOW
        else:
            keep_confidence = 0.0 if pipeline_cut else 100.0
            restore_signal = False
            attention_signal = False

        if restore_signal and wrong_cut:
            restore_tp += 1
        elif restore_signal:
            restore_fp += 1
        elif wrong_cut:
            restore_fn += 1

        if attention_signal and missed_cut:
            attention_tp += 1
        elif attention_signal:
            attention_fp += 1
        elif missed_cut:
            attention_fn += 1

        rank_score = keep_confidence / 100.0 if pipeline_cut else (100.0 - keep_confidence) / 100.0
        ranking_points.append(
            RankingPoint(
                is_target=wrong_cut or missed_cut,
                score=max(0.0, min(1.0, rank_score)),
            )
        )

    return AnnotationActionabilityScore(
        name=name,
        n=len(raw_sentences),
        wrong_cuts=wrong_cuts,
        missed_cuts=missed_cuts,
        restore=_binary_metrics(restore_tp, restore_fp, restore_fn),
        attention=_binary_metrics(attention_tp, attention_fp, attention_fn),
        ranking_average_precision=average_precision(ranking_points),
        status_counts=dict(status_counts),
        ranking_points=ranking_points,
    )


def aggregate_annotation_scores(scores: list[AnnotationActionabilityScore]) -> AnnotationActionabilityScore:
    restore_tp = sum(s.restore.tp for s in scores)
    restore_fp = sum(s.restore.fp for s in scores)
    restore_fn = sum(s.restore.fn for s in scores)
    attention_tp = sum(s.attention.tp for s in scores)
    attention_fp = sum(s.attention.fp for s in scores)
    attention_fn = sum(s.attention.fn for s in scores)
    status_counts: Counter[str] = Counter()
    ranking_points: list[RankingPoint] = []

    for score in scores:
        status_counts.update(score.status_counts)
        ranking_points.extend(score.ranking_points)

    return AnnotationActionabilityScore(
        name="AGGREGATE",
        n=sum(s.n for s in scores),
        wrong_cuts=sum(s.wrong_cuts for s in scores),
        missed_cuts=sum(s.missed_cuts for s in scores),
        restore=_binary_metrics(restore_tp, restore_fp, restore_fn),
        attention=_binary_metrics(attention_tp, attention_fp, attention_fn),
        ranking_average_precision=average_precision(ranking_points),
        status_counts=dict(status_counts),
        ranking_points=ranking_points,
    )


def average_precision(points: list[RankingPoint]) -> float:
    total_targets = sum(1 for point in points if point.is_target)
    if total_targets == 0:
        return 0.0
    hits = 0
    precision_sum = 0.0
    for rank, point in enumerate(sorted(points, key=lambda p: p.score, reverse=True), start=1):
        if not point.is_target:
            continue
        hits += 1
        precision_sum += hits / rank
    return precision_sum / total_targets


def _binary_metrics(tp: int, fp: int, fn: int) -> BinaryMetrics:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return BinaryMetrics(tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1)
