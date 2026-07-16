"""Orchestration of the edit-decision layer.

Single source of truth for how raw transcript + silence/keep regions become an
EDL, shared by ``process`` and ``batch`` so the two never drift:

    section editor → audio false starts → asides → final EDL

The review UI consumes the EDL directly; there is no separate annotation pass.
"""
from __future__ import annotations

from ai_video_editor.audio.models import DisruptionRegion, KeepRegion, SilenceRegion
from ai_video_editor.config.settings import Settings
from ai_video_editor.duplicate.aside import detect_asides
from ai_video_editor.duplicate.edl import EditDecisionList, build_edl
from ai_video_editor.duplicate.false_start_audio import detect_audio_false_starts
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason
from ai_video_editor.duplicate.pipeline import detect_duplicates
from ai_video_editor.duplicate.section_editor import detect_section_edits
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
    # cough/noise in the pause is independent evidence that it was a flubbed
    # restart.
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
    transcript: Transcript,
    keeps: list[KeepRegion],
    silences: list[SilenceRegion],
    settings: Settings,
    *,
    disruptions: list[DisruptionRegion] | None = None,
) -> EditDecisionList:
    """Produce the final EDL from the active cutting lanes."""
    flags = detect_all_flags(transcript, silences, disruptions or [], settings)
    return build_edl(transcript, keeps, flags)
