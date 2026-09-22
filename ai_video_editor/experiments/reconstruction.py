from __future__ import annotations

from ai_video_editor.audio.models import KeepRegion, SilenceRegion
from ai_video_editor.duplicate.edl import EditAction, EditDecisionList, EditReason


def derive_cached_cutting_inputs(
    baseline_edl: EditDecisionList,
) -> tuple[list[KeepRegion], list[SilenceRegion]]:
    """Derive fixed silence context and model-controllable speech spans.

    Cached experiments do not re-run acoustic analysis. Baseline silence cuts
    stay fixed, while baseline keeps and non-silence cuts become speech spans
    that the cutting model may reclassify.
    """
    keep_spans: list[tuple[float, float]] = []
    silences: list[SilenceRegion] = []

    for decision in baseline_edl.decisions:
        if decision.action == EditAction.KEEP:
            keep_spans.append((decision.start, decision.end))
        elif decision.reason == EditReason.SILENCE:
            silences.append(SilenceRegion(start=decision.start, end=decision.end))
        else:
            keep_spans.append((decision.start, decision.end))

    keep_regions = [
        KeepRegion(start=start, end=end)
        for start, end in _merge_spans(keep_spans)
    ]
    return keep_regions, silences


def _merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if end <= start:
            continue
        if merged and start <= merged[-1][1] + 0.01:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
