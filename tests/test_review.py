from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np
import soundfile as sf

from ai_video_editor.audio.snap import AudioEnvelope, envelope_to_peaks, snap_edl_boundaries
from ai_video_editor.duplicate.edl import EditAction, EditDecision, EditDecisionList, EditReason
from ai_video_editor.review import (
    CutRange,
    ReviewSaveRequest,
    build_review_payload,
    build_reviewed_edl,
    review_edl_path_for,
    save_reviewed_edl,
)
from ai_video_editor.transcription.models import Sentence, Transcript, Word
from ai_video_editor.web import create_app


def _sentence(text: str, start: float, end: float) -> Sentence:
    tokens = text.split()
    step = (end - start) / max(len(tokens), 1)
    words = [
        Word(text=token, start=start + i * step, end=start + (i + 1) * step)
        for i, token in enumerate(tokens)
    ]
    return Sentence(text=text, start=start, end=end, words=words)


def _transcript() -> Transcript:
    return Transcript(
        sentences=[
            _sentence("Keep this introduction.", 0.0, 2.0),
            _sentence("Maybe restore this bridge.", 2.5, 4.0),
            _sentence("Keep this calculation.", 4.5, 6.0),
        ],
        source_video="lesson.mp4",
        language="hr",
        model_size="test",
    )


def _edl() -> EditDecisionList:
    return EditDecisionList(
        source_video="lesson.mp4",
        total_duration=6.0,
        decisions=[
            EditDecision(start=0.0, end=2.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
            EditDecision(start=2.0, end=4.5, action=EditAction.CUT, reason=EditReason.FALSE_START),
            EditDecision(start=4.5, end=6.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
        ],
    )


def _write_fixture(tmp_path: Path) -> Path:
    video = tmp_path / "lesson-raw.mp4"
    video.write_bytes(b"fake video")
    video.with_suffix(".transcript.json").write_text(
        _transcript().model_dump_json(indent=2),
        encoding="utf-8",
    )
    video.with_suffix(".edl.json").write_text(
        _edl().model_dump_json(indent=2),
        encoding="utf-8",
    )
    return video


def test_review_payload_maps_word_actions() -> None:
    payload = build_review_payload(Path("lesson-raw.mp4"), _transcript(), _edl())

    assert payload.video.id == "lesson-raw"
    # Words inherit the AI decision based on their midpoint.
    assert [sentence.action for sentence in payload.sentences] == [
        EditAction.KEEP,
        EditAction.CUT,
        EditAction.KEEP,
    ]
    # Each word carries a global index and AI-cut words expose the reason.
    all_words = [word for sentence in payload.sentences for word in sentence.words]
    assert [word.idx for word in all_words] == list(range(len(all_words)))
    cut_words = [word for word in all_words if not word.ai_kept]
    assert cut_words and all(word.reason == EditReason.FALSE_START.value for word in cut_words)


def test_save_reviewed_edl_cuts_mid_sentence(tmp_path: Path) -> None:
    video = _write_fixture(tmp_path)
    original_edl = video.with_suffix(".edl.json").read_text(encoding="utf-8")
    payload = build_review_payload(video, _transcript(), _edl())

    # Cut a single word inside the otherwise-kept first sentence.
    first_word = payload.sentences[0].words[0]
    request = ReviewSaveRequest(
        cut_words=[
            word.idx
            for sentence in payload.sentences
            for word in sentence.words
            if not word.ai_kept
        ]
        + [first_word.idx],
    )

    response = save_reviewed_edl(video, request)
    reviewed_path = review_edl_path_for(video)
    reviewed = EditDecisionList.model_validate_json(reviewed_path.read_text(encoding="utf-8"))

    assert Path(response.review_edl_path) == reviewed_path
    # The first kept span must now start after the removed first word.
    first_keep = next(d for d in reviewed.decisions if d.action == EditAction.KEEP)
    assert first_keep.start >= first_word.end - 0.01
    # Original EDL is untouched.
    assert video.with_suffix(".edl.json").read_text(encoding="utf-8") == original_edl


def test_reviewed_edl_uses_acoustic_split_instead_of_word_timestamp() -> None:
    transcript = _transcript()
    db = np.full(650, -20.0)
    # First word ends at 2/3s. Put the only stable quiet region around 0.78s.
    db[76:81] = -75.0
    envelope = AudioEnvelope.from_db(db, hop_ms=10, frame_ms=20, noise_floor_db=-72.0)
    payload = build_review_payload(
        Path("lesson-raw.mp4"),
        transcript,
        _edl(),
        acoustic_envelope=envelope,
    )
    first_word = payload.sentences[0].words[0]

    reviewed = build_reviewed_edl(
        Path("lesson-raw.mp4"),
        payload,
        ReviewSaveRequest(cut_words=[first_word.idx]),
    )

    first_keep = next(d for d in reviewed.decisions if d.action == EditAction.KEEP)
    assert first_word.cut_out == 0.79
    assert first_keep.start == first_word.cut_out
    assert first_keep.start != first_word.end


def test_preview_and_automatic_edl_share_identical_split_points() -> None:
    transcript = _transcript()
    db = np.full(650, -20.0)
    db[208:213] = -75.0
    envelope = AudioEnvelope.from_db(db, hop_ms=10, frame_ms=20, noise_floor_db=-72.0)
    payload = build_review_payload(
        Path("lesson-raw.mp4"), transcript, _edl(), acoustic_envelope=envelope
    )

    snapped = snap_edl_boundaries(_edl(), transcript, envelope)

    preview_split = payload.sentences[0].words[-1].cut_out
    assert preview_split == payload.sentences[1].words[0].cut_in
    assert snapped.decisions[0].end == preview_split
    assert snapped.decisions[1].start == preview_split


def test_save_reviewed_edl_can_restore_ai_cut(tmp_path: Path) -> None:
    video = _write_fixture(tmp_path)
    # Cut nothing -> everything from the first word to the last is kept.
    response = save_reviewed_edl(video, ReviewSaveRequest(cut_words=[]))
    assert response.keep_duration > _edl().keep_duration


def test_review_api_lists_loads_and_saves(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    client = TestClient(create_app(media_root=tmp_path, frontend_dist=tmp_path / "missing-dist"))

    videos = client.get("/api/videos")
    assert videos.status_code == 200
    assert videos.json()[0]["id"] == "lesson-raw"

    review = client.get("/api/videos/lesson-raw/review")
    assert review.status_code == 200
    body = review.json()
    assert len(body["sentences"]) == 3
    assert body["sentences"][0]["words"], "words should be present in payload"

    saved = client.post(
        "/api/videos/lesson-raw/review",
        json={"cut_words": []},
    )
    assert saved.status_code == 200
    assert (tmp_path / "lesson-raw-review.edl.json").exists()

    # The saved sidecar is now reflected as the current state on reload.
    reloaded = client.get("/api/videos/lesson-raw/review")
    assert reloaded.status_code == 200


def test_payload_exposes_cut_ranges_from_ai_edl() -> None:
    payload = build_review_payload(Path("lesson-raw.mp4"), _transcript(), _edl())
    # The AI EDL has a single CUT segment; it surfaces as the canonical cut state.
    assert [(r.start, r.end) for r in payload.cut_ranges] == [(2.0, 4.5)]


def test_range_save_keeps_complement_of_cuts() -> None:
    payload = build_review_payload(Path("lesson-raw.mp4"), _transcript(), _edl())
    reviewed = build_reviewed_edl(
        Path("lesson-raw.mp4"),
        payload,
        ReviewSaveRequest(cut_ranges=[CutRange(start=1.0, end=3.0)]),
    )
    keeps = [(d.start, d.end) for d in reviewed.decisions if d.action == EditAction.KEEP]
    cuts = [(d.start, d.end) for d in reviewed.decisions if d.action == EditAction.CUT]
    assert keeps == [(0.0, 1.0), (3.0, 6.0)]
    assert cuts == [(1.0, 3.0)]


def test_empty_cut_ranges_restores_everything() -> None:
    payload = build_review_payload(Path("lesson-raw.mp4"), _transcript(), _edl())
    reviewed = build_reviewed_edl(
        Path("lesson-raw.mp4"), payload, ReviewSaveRequest(cut_ranges=[])
    )
    assert [d.action for d in reviewed.decisions] == [EditAction.KEEP]
    assert reviewed.cut_duration == 0.0


def test_overlapping_cut_ranges_merge() -> None:
    payload = build_review_payload(Path("lesson-raw.mp4"), _transcript(), _edl())
    reviewed = build_reviewed_edl(
        Path("lesson-raw.mp4"),
        payload,
        ReviewSaveRequest(cut_ranges=[CutRange(start=1.0, end=3.0), CutRange(start=2.0, end=4.0)]),
    )
    keeps = [(d.start, d.end) for d in reviewed.decisions if d.action == EditAction.KEEP]
    assert keeps == [(0.0, 1.0), (4.0, 6.0)]


def test_range_save_round_trips_through_payload(tmp_path: Path) -> None:
    video = _write_fixture(tmp_path)
    save_reviewed_edl(video, ReviewSaveRequest(cut_ranges=[CutRange(start=1.0, end=3.0)]))

    from ai_video_editor.review import load_review_payload

    reloaded = load_review_payload(video)
    assert [(r.start, r.end) for r in reloaded.cut_ranges] == [(1.0, 3.0)]


def test_legacy_cut_words_used_only_when_ranges_omitted(tmp_path: Path) -> None:
    video = _write_fixture(tmp_path)
    payload = build_review_payload(video, _transcript(), _edl())
    first_word = payload.sentences[0].words[0]

    # cut_ranges omitted (None) -> the word path runs and cuts the first word.
    reviewed = build_reviewed_edl(video, payload, ReviewSaveRequest(cut_words=[first_word.idx]))
    first_keep = next(d for d in reviewed.decisions if d.action == EditAction.KEEP)
    assert first_keep.start >= first_word.end - 0.01


def test_envelope_to_peaks_normalizes_speech_above_silence() -> None:
    db = np.concatenate([np.full(50, -20.0), np.full(50, -75.0)])
    envelope = AudioEnvelope.from_db(db, hop_ms=10, frame_ms=20, noise_floor_db=-72.0)
    peaks = envelope_to_peaks(envelope, buckets=10)

    assert len(peaks) == 10
    assert all(0.0 <= p <= 1.0 for p in peaks)
    assert peaks[0] > 0.5  # speech
    assert peaks[-1] == 0.0  # silence at/below the noise floor


def test_peaks_endpoint_returns_normalized_waveform(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    samples = np.zeros(16_000 * 6, dtype=np.float32)
    samples[1_000:5_000] = 0.2
    sf.write(tmp_path / "lesson-raw_denoised.wav", samples, 16_000)
    client = TestClient(create_app(media_root=tmp_path, frontend_dist=tmp_path / "missing-dist"))

    response = client.get("/api/videos/lesson-raw/peaks", params={"buckets": 100})
    assert response.status_code == 200
    body = response.json()
    assert body["length"] == len(body["peaks"]) <= 100
    assert body["peaks"] and all(0.0 <= p <= 1.0 for p in body["peaks"])
    assert body["duration"] > 0


def test_review_api_backfills_acoustic_splits_for_existing_video(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    samples = np.zeros(16_000 * 6, dtype=np.float32)
    samples[1_000:5_000] = 0.2
    sf.write(tmp_path / "lesson-raw_denoised.wav", samples, 16_000)
    client = TestClient(create_app(media_root=tmp_path, frontend_dist=tmp_path / "missing-dist"))

    response = client.get("/api/videos/lesson-raw/review")

    assert response.status_code == 200
    assert (tmp_path / "lesson-raw.audio.json").exists()
    first_word = response.json()["sentences"][0]["words"][0]
    assert first_word["cut_in"] is not None
    assert first_word["cut_out"] is not None
