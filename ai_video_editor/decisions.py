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

from ai_video_editor.audio.models import DisruptionRegion, KeepRegion, SilenceRegion
from ai_video_editor.config.settings import Settings
from ai_video_editor.duplicate.aside import detect_asides
from ai_video_editor.duplicate.edl import EditDecisionList, build_edl
from ai_video_editor.duplicate.false_start_audio import detect_audio_false_starts
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason
from ai_video_editor.duplicate.pipeline import detect_duplicates
from ai_video_editor.duplicate.section_editor import detect_section_edits
from ai_video_editor.enrich import (
    EnrichmentResult,
    apply_enrichment_arbiter,
    enrich_transcript,
    load_cached_enrichment,
    restatus_against_edl,
    save_enrichment,
)
from ai_video_editor.llm import LangChainModelConfig
from ai_video_editor.transcription.models import Transcript


def detect_all_flags(
    transcript: Transcript,
    silences: list[SilenceRegion],
    disruptions: list[DisruptionRegion],
    settings: Settings,
    *,
    cutting_llm_config: LangChainModelConfig | None = None,
) -> list[DuplicateFlag]:
    """Duplicate/false-start/stutter/fragment flags, aside flags, and audio-driven
    (cough/noise) false starts."""
    llm_config = cutting_llm_config or settings.cutting_llm
    if settings.section_editor.enabled:
        # Section editor replaces the tiered duplicate detector for text-judgment
        # cuts; the audio lane (disruptions, asides) below still runs.
        flags = detect_section_edits(
            transcript.sentences,
            settings.section_editor,
            llm_config=settings.section_editor.llm,
        )
    else:
        flags = detect_duplicates(
            transcript.sentences,
            settings.duplicate_detection,
            llm_config=llm_config,
        )
    flagged = {f.idx for f in flags if not f.word_trims}

    # Audio evidence can overlap a text-derived flag. In that case it should
    # *upgrade* the existing full-sentence flag rather than being skipped: the
    # text-only enrichment arbiter may restore a short phrase that reads like a
    # natural transition, but the cough/noise in the pause is independent evidence
    # that it was a flubbed restart.
    audio_fs_flags = detect_audio_false_starts(
        transcript.sentences, disruptions, set(), settings.false_start_audio
    )
    audio_by_idx = {f.idx: f for f in audio_fs_flags}
    upgraded: list[DuplicateFlag] = []
    for f in flags:
        audio_f = audio_by_idx.get(f.idx)
        if audio_f is not None and not f.word_trims:
            upgraded.append(f.model_copy(update={
                "reason": FlagReason.FALSE_START,
                "confidence": max(f.confidence, audio_f.confidence),
                "note": audio_f.note if not f.note else f"{audio_f.note} | Text flag: {f.note}",
            }))
        else:
            upgraded.append(f)
    flags = upgraded

    standalone_audio_flags = [f for f in audio_fs_flags if f.idx not in flagged]
    flags.extend(standalone_audio_flags)
    flagged |= {f.idx for f in standalone_audio_flags if not f.word_trims}

    aside_flags = detect_asides(
        transcript.sentences,
        silences,
        flagged,
        settings.aside_detection,
        llm_config=llm_config,
    )
    flagged |= {f.idx for f in aside_flags if not f.word_trims}
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
    disruptions: list[DisruptionRegion] | None = None,
) -> tuple[EditDecisionList, EnrichmentResult | None]:
    """Produce the final EDL and (when enabled) the enrichment sidecar."""
    flags = detect_all_flags(transcript, silences, disruptions or [], settings)
    edl = build_edl(transcript, keeps, flags)

    enrichment: EnrichmentResult | None = None
    if not settings.enrichment.enabled:
        log.info("Enrichment disabled — skipping arbiter")
        return edl, None

    try:
        enrichment = None if force else load_cached_enrichment(video_path)
        if enrichment is None:
            enrichment = enrich_transcript(transcript, edl, settings.enrichment)

        # The arbiter was tuned to correct the tiered detector (~0.40 word-level
        # cut precision). Against the section editor (~0.77) its overrides are
        # noise: on the 98-fixture A/B its restores were a coin flip (103 good /
        # 103 bad) and its extra cuts worse than one (76/95), costing −0.030 F1.
        # Enrichment itself still runs — the sidecar feeds the review UI.
        arbiter_applicable = (
            settings.enrichment.arbiter_enabled and not settings.section_editor.enabled
        )
        if settings.enrichment.arbiter_enabled and not arbiter_applicable:
            log.info("Arbiter skipped — section editor is the cutter (see arbiter A/B)")
        if arbiter_applicable:
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
