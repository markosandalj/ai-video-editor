from __future__ import annotations

from pathlib import Path

from loguru import logger

from ai_video_editor.qa.ground_truth import _align_monotonic
from ai_video_editor.qa.models import ContinuityResult
from ai_video_editor.transcription.models import Sentence

CONTINUITY_THRESHOLD = 70.0


def verify_continuity(
    expected_sentences: list[Sentence],
    actual_sentences: list[Sentence],
    *,
    threshold: float = CONTINUITY_THRESHOLD,
) -> ContinuityResult:
    """
    Compare actual transcription of the rendered video against the
    expected post-edit transcript to verify no content was dropped.

    *actual_sentences* should come from a prior ``transcribe_for_qa``
    call so the pipeline output is only transcribed once per QA run.

    Uses order-preserving alignment: content is delivered in order, so a recap
    sentence must not borrow a match from a later occurrence.
    """
    aligned = _align_monotonic(expected_sentences, actual_sentences, threshold)
    matched_expected = {ei for ei, _, _ in aligned}
    matched = len(aligned)
    missing = [
        s.text for i, s in enumerate(expected_sentences) if i not in matched_expected
    ]

    alignment = matched / len(expected_sentences) if expected_sentences else 1.0

    result = ContinuityResult(
        expected_sentences=len(expected_sentences),
        found_sentences=matched,
        missing_sentences=missing,
        alignment_score=round(alignment, 4),
    )

    logger.info(
        "Continuity: {}/{} sentences found (score={:.1%}), {} missing",
        matched, len(expected_sentences), alignment, len(missing),
    )
    return result
