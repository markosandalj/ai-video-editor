from __future__ import annotations

from ai_video_editor.qa.decision_eval import DecisionScore, aggregate


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
    aggregate_score = aggregate(scores) if scores else DecisionScore(name="AGGREGATE")
    return decision_score_to_dict(aggregate_score)
