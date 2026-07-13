from __future__ import annotations

import numpy as np

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
