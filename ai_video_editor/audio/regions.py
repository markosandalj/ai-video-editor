from __future__ import annotations

from loguru import logger

from ai_video_editor.audio.models import KeepRegion, SilenceRegion
from ai_video_editor.config.settings import Settings


def compute_keep_regions(
    silences: list[SilenceRegion],
    total_duration: float,
    settings: Settings,
) -> list[KeepRegion]:
    """
    Invert silence regions into keep regions, apply padding, merge overlapping,
    and clamp to [0, total_duration].
    """
    padding_s = settings.audio.padding_ms / 1000.0

    speech: list[tuple[float, float]] = []
    cursor = 0.0
    for s in sorted(silences, key=lambda r: r.start):
        if s.start > cursor:
            speech.append((cursor, s.start))
        cursor = max(cursor, s.end)
    if cursor < total_duration:
        speech.append((cursor, total_duration))

    padded = [
        (max(0.0, start - padding_s), min(total_duration, end + padding_s))
        for start, end in speech
    ]

    merged: list[tuple[float, float]] = []
    for start, end in padded:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    regions = [KeepRegion(start=round(s, 4), end=round(e, 4)) for s, e in merged]

    kept = sum(r.duration for r in regions)
    logger.info(
        "Keep regions: {} segments, {:.1f}s kept of {:.1f}s total ({:.0f}% retained)",
        len(regions),
        kept,
        total_duration,
        (kept / total_duration * 100) if total_duration > 0 else 0,
    )
    for r in regions:
        logger.debug("  keep: {:.2f}s – {:.2f}s ({:.2f}s)", r.start, r.end, r.duration)

    return regions
