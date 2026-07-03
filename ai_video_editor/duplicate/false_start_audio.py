"""Audio-driven false-start detection.

The existing false-start detector only looks *between* confirmed duplicate
pairs, so it can only catch a flubbed take when the speaker repeats a whole
sentence. But the most common flub is subtler: the speaker finishes a thought,
coughs or pauses, mutters a short hesitant restart ("I dobro.", "Pa dobro,
ovako."), then redoes the line. There's no textual duplicate, so the transcript
looks innocent — "I dobro." is indistinguishable from a natural transition.

What gives it away is the *audio shape*: a long pause, a cough/noise inside that
pause, a short stranded phrase, then a prompt resumption. This pass fuses those
acoustic cues (from :mod:`ai_video_editor.audio.disruption`) with the transcript
timing to flag exactly that pattern. It is deliberately conservative — all of
"short", "long pause before", "disruption in the pause", and "prompt resume
after" must hold — because the cost of cutting real content is high.
"""
from __future__ import annotations

from loguru import logger

from ai_video_editor.audio.models import DisruptionRegion
from ai_video_editor.config.settings import FalseStartAudioConfig
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason
from ai_video_editor.transcription.models import Sentence


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


def detect_audio_false_starts(
    sentences: list[Sentence],
    disruptions: list[DisruptionRegion],
    flagged_indices: set[int],
    cfg: FalseStartAudioConfig,
) -> list[DuplicateFlag]:
    """Flag short, stranded phrases that follow an acoustic disruption in a pause."""
    if not cfg.enabled or len(sentences) < 3:
        return []

    flags: list[DuplicateFlag] = []
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
                f"Audio false start: stranded {len(s.words)}-word phrase after a "
                f"{cue} in a {gap_before:.1f}s pause; "
                f"speaker resumes {gap_after:.1f}s later"
            )
        else:
            note = (
                f"Audio false start: stranded {len(s.words)}-word phrase after a "
                f"{gap_before:.1f}s pause; speaker resumes {gap_after:.1f}s later"
            )

        flags.append(DuplicateFlag(
            idx=i,
            reason=FlagReason.FALSE_START,
            confidence=cfg.confidence,
            note=note,
        ))

    if flags:
        logger.info("Audio false-start detection: {} sentences flagged", len(flags))
    return flags
