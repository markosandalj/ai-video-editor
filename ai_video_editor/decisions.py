"""Orchestration of the edit-decision layer.

Single source of truth for how raw transcript + silence/keep regions become an
EDL, shared by ``process`` and ``batch`` so the two never drift. The ordering is:

    duplicates → asides → base EDL → enrichment → arbiter → final EDL

Enrichment and the arbiter are best-effort: any failure falls back to the base
EDL so a video is always rendered.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from ai_video_editor.audio.models import KeepRegion, SilenceRegion
from ai_video_editor.config.settings import Settings
from ai_video_editor.duplicate.aside import detect_asides
from ai_video_editor.duplicate.edl import EditDecisionList, build_edl
from ai_video_editor.duplicate.models import DuplicateFlag
from ai_video_editor.duplicate.pipeline import detect_duplicates
from ai_video_editor.enrich import (
    EnrichmentResult,
    apply_enrichment_arbiter,
    enrich_transcript,
    load_cached_enrichment,
    restatus_against_edl,
    save_enrichment,
)
from ai_video_editor.transcription.models import Transcript


def detect_all_flags(
    transcript: Transcript,
    silences: list[SilenceRegion],
    settings: Settings,
) -> list[DuplicateFlag]:
    """Duplicate/false-start/stutter/fragment flags plus aside flags."""
    flags = detect_duplicates(transcript.sentences, settings.duplicate_detection)
    flagged = {f.idx for f in flags if not f.word_trims}
    aside_flags = detect_asides(
        transcript.sentences, silences, flagged, settings.aside_detection
    )
    return flags + aside_flags


def decide_edits(
    video_path: Path,
    transcript: Transcript,
    keeps: list[KeepRegion],
    silences: list[SilenceRegion],
    settings: Settings,
    *,
    force: bool,
    log,
) -> tuple[EditDecisionList, EnrichmentResult | None]:
    """Produce the final EDL and (when enabled) the enrichment sidecar."""
    flags = detect_all_flags(transcript, silences, settings)
    edl = build_edl(transcript, keeps, flags)

    enrichment: EnrichmentResult | None = None
    if not settings.enrichment.enabled:
        log.info("Enrichment disabled — skipping arbiter")
        return edl, None

    try:
        enrichment = None if force else load_cached_enrichment(video_path)
        if enrichment is None:
            enrichment = enrich_transcript(transcript, edl, settings.enrichment)

        if settings.enrichment.arbiter_enabled:
            revised = apply_enrichment_arbiter(
                flags, transcript, enrichment, settings.enrichment
            )
            if revised != flags:
                edl = build_edl(transcript, keeps, revised)
                enrichment = restatus_against_edl(
                    enrichment, transcript, edl, settings.enrichment
                )
        save_enrichment(video_path, enrichment)
        statuses: dict[str, int] = {}
        for s in enrichment.sentences:
            statuses[s.status.value] = statuses.get(s.status.value, 0) + 1
        log.info("Enrichment: {} sentences scored ({})", len(enrichment.sentences), statuses)
    except Exception:
        log.exception("Enrichment/arbiter failed for {} — using base EDL", video_path)
        # Re-derive the base EDL untouched so a failure can't leave a half-applied state.
        edl = build_edl(transcript, keeps, flags)

    return edl, enrichment
