from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ai_video_editor.duplicate.edl import EditAction, EditDecision, EditDecisionList, EditReason
from ai_video_editor.transcription.models import Sentence, Transcript, Word
from ai_video_editor.web import create_app
from ai_video_editor.web.diff import build_diff_payload


def _sentence(text: str, start: float, end: float) -> Sentence:
    tokens = text.split()
    step = (end - start) / max(len(tokens), 1)
    words = [
        Word(text=token, start=start + i * step, end=start + (i + 1) * step)
        for i, token in enumerate(tokens)
    ]
    return Sentence(text=text, start=start, end=end, words=words)


def _raw() -> Transcript:
    return Transcript(
        sentences=[
            _sentence("Keep this introduction.", 0.0, 2.0),  # both keep
            _sentence("Maybe restore this bridge.", 2.5, 4.0),  # pipeline cut, human keep
            _sentence("Keep this calculation.", 4.5, 6.0),  # pipeline keep, human cut
            _sentence("Useless trailing aside here.", 6.5, 8.0),  # both cut
        ],
        source_video="lesson-raw.mp4",
        language="hr",
        model_size="test",
    )


def _edl() -> EditDecisionList:
    return EditDecisionList(
        source_video="lesson-raw.mp4",
        total_duration=8.0,
        decisions=[
            EditDecision(start=0.0, end=2.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
            EditDecision(start=2.0, end=4.5, action=EditAction.CUT, reason=EditReason.FALSE_START),
            EditDecision(start=4.5, end=6.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
            EditDecision(start=6.0, end=8.0, action=EditAction.CUT, reason=EditReason.SILENCE),
        ],
    )


def _human_gt() -> Transcript:
    # Human kept sentences 0 and 1 only.
    return Transcript(
        sentences=[
            _sentence("Keep this introduction.", 0.0, 2.0),
            _sentence("Maybe restore this bridge.", 2.0, 3.5),
        ],
        source_video="lesson-edited.mp4",
        language="hr",
        model_size="test",
    )


def _write_fixture(tmp_path: Path) -> Path:
    video = tmp_path / "lesson-raw.mp4"
    video.write_bytes(b"fake video")
    video.with_suffix(".transcript.json").write_text(_raw().model_dump_json(), encoding="utf-8")
    video.with_suffix(".edl.json").write_text(_edl().model_dump_json(), encoding="utf-8")
    (tmp_path / "lesson-edited.qa-transcript.json").write_text(
        _human_gt().model_dump_json(), encoding="utf-8"
    )
    return video


def test_diff_payload_classifies_all_four_agreement_cases(tmp_path: Path) -> None:
    video = _write_fixture(tmp_path)
    payload = build_diff_payload(video)

    s = payload.summary
    assert s.has_ground_truth
    assert (s.agree_keep, s.pipeline_only_cut, s.human_only_cut, s.agree_cut) == (1, 1, 1, 1)
    assert s.pipeline_kept_sentences == 2  # s0, s2
    assert s.human_kept_sentences == 2  # s0, s1

    by_idx = {sent.idx: sent for sent in payload.sentences}
    assert by_idx[0].pipeline_kept and by_idx[0].human_kept  # agreement keep
    assert (not by_idx[1].pipeline_kept) and by_idx[1].human_kept  # over-cut
    assert by_idx[2].pipeline_kept and (not by_idx[2].human_kept)  # missed cut
    assert (not by_idx[3].pipeline_kept) and (not by_idx[3].human_kept)  # agreement cut

    # Words in a human-cut sentence are all marked human_kept=False (struck).
    assert all(not w.human_kept for w in by_idx[2].words)
    # Words in a human-kept, pipeline-cut sentence: human keeps, pipeline strikes.
    assert all(w.human_kept and not w.pipeline_kept for w in by_idx[1].words)


def test_diff_without_ground_truth_marks_human_kept(tmp_path: Path) -> None:
    video = tmp_path / "lesson-raw.mp4"
    video.write_bytes(b"fake video")
    video.with_suffix(".transcript.json").write_text(_raw().model_dump_json(), encoding="utf-8")
    video.with_suffix(".edl.json").write_text(_edl().model_dump_json(), encoding="utf-8")

    payload = build_diff_payload(video)
    assert not payload.summary.has_ground_truth
    assert payload.summary.human_kept_sentences == 0
    # Human side is neutral (everything kept) when there is no ground truth.
    assert all(w.human_kept for sent in payload.sentences for w in sent.words)


def test_diff_human_kept_survives_chunking_and_tokenisation_mismatch(tmp_path: Path) -> None:
    """Regression for the `test-1` bug: the human-edited video is re-transcribed
    independently, so it can merge two raw sentences into one and re-spell a word
    ("obadvije" -> "oba dvije"). A 1:1 sentence/word alignment then falsely struck
    the absorbed sentence and the split word. The global word-LCS + gap bridging
    must mark every raw word as human-kept here."""
    video = tmp_path / "lesson-raw.mp4"
    video.write_bytes(b"fake video")

    raw = Transcript(
        sentences=[
            _sentence("Na obadvije te osi.", 0.0, 2.0),
            _sentence("Evo i gore i dolje i lijevo i desno.", 2.0, 5.0),
        ],
        source_video="lesson-raw.mp4",
        language="hr",
        model_size="test",
    )
    # Human edit kept everything but re-transcribed it as ONE sentence with a
    # different tokenisation of "obadvije".
    gt = Transcript(
        sentences=[
            _sentence(
                "Na oba dvije te osi, evo i gore i dolje i lijevo i desno.", 0.0, 5.0
            ),
        ],
        source_video="lesson-edited.mp4",
        language="hr",
        model_size="test",
    )
    edl = EditDecisionList(
        source_video="lesson-raw.mp4",
        total_duration=5.0,
        decisions=[EditDecision(start=0.0, end=5.0, action=EditAction.KEEP, reason=EditReason.SPEECH)],
    )
    video.with_suffix(".transcript.json").write_text(raw.model_dump_json(), encoding="utf-8")
    video.with_suffix(".edl.json").write_text(edl.model_dump_json(), encoding="utf-8")
    (tmp_path / "lesson-edited.qa-transcript.json").write_text(
        gt.model_dump_json(), encoding="utf-8"
    )

    payload = build_diff_payload(video)

    assert payload.summary.has_ground_truth
    # Both raw sentences are present in the human edit -> neither is a human cut.
    assert all(sent.human_kept for sent in payload.sentences)
    # No raw word may be struck on the human side, including the split "obadvije".
    struck = [w.text for sent in payload.sentences for w in sent.words if not w.human_kept]
    assert struck == [], f"unexpected human-cut words: {struck}"


def test_diff_api_endpoint(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    client = TestClient(create_app(media_root=tmp_path, frontend_dist=tmp_path / "missing-dist"))

    res = client.get("/api/videos/lesson-raw/diff")
    assert res.status_code == 200
    body = res.json()
    assert body["video"]["id"] == "lesson-raw"
    assert len(body["sentences"]) == 4
    assert body["summary"]["human_only_cut"] == 1
