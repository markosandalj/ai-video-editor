from __future__ import annotations

import numpy as np
import pytest

from ai_video_editor.audio.snap import AudioEnvelope, snap_cut_boundary, snap_edl_boundaries
from ai_video_editor.duplicate.edl import EditAction, EditDecision, EditDecisionList, EditReason
from ai_video_editor.transcription.models import Sentence, Transcript, Word


def test_snap_cut_boundary_prefers_center_of_longest_quiet_run() -> None:
    db = np.full(30, -20.0)
    db[8:13] = -70.0
    db[18] = -90.0  # Deeper, but only one frame: prefer the stable quiet run.
    envelope = AudioEnvelope.from_db(db, hop_ms=10, frame_ms=20, noise_floor_db=-72.0)

    snapped = snap_cut_boundary(0.15, envelope, window_s=0.15, lo=0.0, hi=0.3)

    assert snapped == 0.11


def test_snap_cut_boundary_never_crosses_safety_bounds() -> None:
    db = np.full(50, -20.0)
    db[2:8] = -80.0
    envelope = AudioEnvelope.from_db(db, hop_ms=10, frame_ms=20, noise_floor_db=-75.0)

    snapped = snap_cut_boundary(0.25, envelope, window_s=0.25, lo=0.2, hi=0.4)

    assert 0.2 <= snapped <= 0.4


def test_snap_edl_boundaries_moves_export_splice_into_quiet_audio() -> None:
    db = np.full(100, -20.0)
    db[59:64] = -75.0
    envelope = AudioEnvelope.from_db(db, hop_ms=10, frame_ms=20, noise_floor_db=-72.0)
    transcript = Transcript(
        sentences=[
            Sentence(text="cut", start=0.0, end=0.5, words=[Word(text="cut", start=0.0, end=0.5)]),
            Sentence(text="keep", start=0.5, end=1.0, words=[Word(text="keep", start=0.5, end=1.0)]),
        ],
        source_video="clip.mp4",
        language="hr",
        model_size="test",
    )
    edl = EditDecisionList(
        source_video="clip.mp4",
        total_duration=1.0,
        decisions=[
            EditDecision(start=0.0, end=0.5, action=EditAction.CUT, reason=EditReason.FALSE_START),
            EditDecision(start=0.5, end=1.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
        ],
    )

    snapped = snap_edl_boundaries(edl, transcript, envelope)

    assert snapped.decisions[0].end == 0.62
    assert snapped.decisions[1].start == 0.62


@pytest.mark.parametrize("gap_s", [0.08, 2.4, 10.0])
@pytest.mark.parametrize("with_audio", [True, False])
def test_snap_edl_preserves_both_edges_of_a_silence_cut(gap_s, with_audio) -> None:
    next_word_start = 1.0 + gap_s
    duration = next_word_start + 1.0
    times = 0.01 + np.arange(round(duration * 100)) * 0.01
    db = np.where((times >= 1.0) & (times <= next_word_start), -80.0, -20.0)
    envelope = AudioEnvelope.from_db(
        db if with_audio else np.array([]),
        hop_ms=10,
        frame_ms=20,
        noise_floor_db=-80.0,
        duration_s=duration,
    )
    transcript = Transcript(
        sentences=[
            Sentence(text="Prije", start=0.0, end=1.0,
                     words=[Word(text="Prije", start=0.0, end=1.0)]),
            Sentence(text="Poslije", start=next_word_start, end=duration,
                     words=[Word(text="Poslije", start=next_word_start, end=duration)]),
        ],
        source_video="clip.mp4",
        language="hr",
        model_size="test",
    )
    edl = EditDecisionList(
        source_video="clip.mp4",
        total_duration=duration,
        decisions=[
            EditDecision(start=0.0, end=1.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
            EditDecision(start=1.0, end=next_word_start, action=EditAction.CUT,
                         reason=EditReason.SILENCE),
            EditDecision(start=next_word_start, end=duration, action=EditAction.KEEP,
                         reason=EditReason.SPEECH),
        ],
    )
    original = edl.model_dump()

    snapped = snap_edl_boundaries(edl, transcript, envelope)

    before, cut, after = snapped.decisions
    assert cut.duration > 0
    assert 1.0 <= cut.start <= 1.25
    assert next_word_start - 0.25 <= cut.end <= next_word_start
    assert before.end == cut.start
    assert cut.end == after.start
    assert before.start == 0.0 and after.end == duration
    assert edl.model_dump() == original
