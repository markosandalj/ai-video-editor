from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ai_video_editor.duplicate.edl import EditAction, EditDecision, EditDecisionList, EditReason
from ai_video_editor.review import (
    ReviewSaveRequest,
    build_review_payload,
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
