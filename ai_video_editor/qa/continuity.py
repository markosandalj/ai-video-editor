from __future__ import annotations

from pathlib import Path

from loguru import logger
from rapidfuzz import fuzz

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
    """
    matched = 0
    missing: list[str] = []
    used_actual: set[int] = set()

    for expected in expected_sentences:
        best_score = 0.0
        best_idx = -1

        for i, actual in enumerate(actual_sentences):
            if i in used_actual:
                continue
            score = max(
                fuzz.ratio(expected.text, actual.text),
                fuzz.token_sort_ratio(expected.text, actual.text),
            )
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx >= 0 and best_score >= threshold:
            used_actual.add(best_idx)
            matched += 1
        else:
            missing.append(expected.text)

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
