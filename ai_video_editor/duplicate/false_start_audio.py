"""Audio-driven candidates for semantic review, never automatic speech cuts.

A long pause, noise, a short phrase and a prompt resumption can indicate a
failed restart, but also a useful correction. These cues therefore travel to
the section editor with the surrounding text. They never become cut flags or
override a text decision by themselves.
"""
from __future__ import annotations

from loguru import logger
from pydantic import BaseModel

from ai_video_editor.audio.models import DisruptionRegion
from ai_video_editor.config.settings import FalseStartAudioConfig
from ai_video_editor.transcription.models import Sentence


class AudioFalseStartCandidate(BaseModel):
    sentence_index: int
    evidence: str


def _disruption_in_gap(
    disruptions: list[DisruptionRegion], gap_start: float, gap_end: float
) -> DisruptionRegion | None:
    """The loudest disruption sitting inside the pause [gap_start, gap_end]."""
    inside = [
        d for d in disruptions
        if d.start >= gap_start - 0.05 and d.end <= gap_end + 0.05
    ]
    if not inside:
        return None
    return max(inside, key=lambda d: d.peak_db)


def detect_audio_false_start_candidates(
    sentences: list[Sentence],
    disruptions: list[DisruptionRegion],
    flagged_indices: set[int],
    cfg: FalseStartAudioConfig,
) -> list[AudioFalseStartCandidate]:
    """Suggest short phrases for review; the audio shape says nothing about meaning."""
    if not cfg.enabled or len(sentences) < 3:
        return []

    candidates: list[AudioFalseStartCandidate] = []
    for i in range(1, len(sentences) - 1):  # need a neighbour on each side
        if i in flagged_indices:
            continue
        s = sentences[i]
        if len(s.words) > cfg.max_words:
            continue

        gap_before = s.start - sentences[i - 1].end
        gap_after = sentences[i + 1].start - s.end
        if gap_before < cfg.min_gap_before_s:
            continue
        if gap_after > cfg.max_gap_after_s:
            continue

        disruption = _disruption_in_gap(disruptions, sentences[i - 1].end, s.start)
        if cfg.require_disruption and disruption is None:
            continue

        if disruption is not None:
            if disruption.source == "stt_event":
                cue = f"STT-tagged {disruption.label or 'event'}"
            else:
                cue = f"{disruption.peak_db:.0f}dB disruption"
            note = (
                f"Audio candidate: {len(s.words)}-word phrase after a "
                f"{cue} in a {gap_before:.1f}s pause; "
                f"speaker resumes {gap_after:.1f}s later"
            )
        else:
            note = (
                f"Audio candidate: {len(s.words)}-word phrase after a "
                f"{gap_before:.1f}s pause; speaker resumes {gap_after:.1f}s later"
            )

        candidates.append(AudioFalseStartCandidate(
            sentence_index=i,
            evidence=note,
        ))

    if candidates:
        logger.info("Audio false-start detection: {} candidates for review", len(candidates))
    return candidates
