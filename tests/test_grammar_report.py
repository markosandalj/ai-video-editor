from __future__ import annotations

from pathlib import Path

from ai_video_editor.audio.models import AudioMeta
from ai_video_editor.config.settings import Settings
from ai_video_editor.transcription.grammar import (
    GrammarReport,
    WordCorrection,
    _apply_corrections,
)
from ai_video_editor.transcription.grammar_report import (
    grammar_report_path_for,
    load_cached_grammar_report,
    save_grammar_report,
)
from ai_video_editor.transcription.models import Sentence, Transcript, Word
from ai_video_editor.transcription.pipeline import transcribe_with_elevenlabs_and_grammar


def test_grammar_report_cache_round_trip(tmp_path: Path) -> None:
    video = tmp_path / "lesson-raw.mp4"
    report = GrammarReport(
        source_video=str(video),
        max_passes=5,
        passes=2,
        total_suggestions=3,
        total_corrections=2,
        converged=True,
        corrections_log=[
            {"pass": 1, "wrong": "zomirali", "correct": "zumirali", "replacements": 2}
        ],
        pass_logs=[
            {"pass": 1, "mode": "strict", "suggestions": 2, "replacements": 2},
            {"pass": 2, "mode": "strict", "suggestions": 1, "replacements": 0},
        ],
    )

    path = save_grammar_report(video, report)

    assert path == video.with_suffix(".grammar-report.json")
    loaded = load_cached_grammar_report(video)
    assert loaded is not None
    assert loaded.total_suggestions == 3
    assert loaded.total_corrections == 2
    assert loaded.corrections_log[0]["wrong"] == "zomirali"
    assert load_cached_grammar_report(tmp_path / "missing.mp4") is None


def test_elevenlabs_pipeline_saves_grammar_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video = tmp_path / "lesson-raw.mp4"
    denoised = AudioMeta(
        source_video=str(video),
        sample_rate=16000,
        channels=1,
        duration_s=1.0,
        path=str(tmp_path / "lesson-raw_denoised.wav"),
    )

    def fake_transcribe_elevenlabs(*args, **kwargs):
        return [Word(text="zomirali", start=0.0, end=1.0)], "zomirali", []

    def fake_correct_grammar(draft: Transcript, *, max_passes: int):
        corrected = draft.model_copy(
            update={
                "sentences": [
                    draft.sentences[0].model_copy(update={"text": "zumirali"})
                ]
            }
        )
        return corrected, GrammarReport(
            source_video=draft.source_video,
            max_passes=max_passes,
            passes=1,
            total_suggestions=1,
            total_corrections=1,
            converged=True,
            corrections_log=[
                {"pass": 1, "wrong": "zomirali", "correct": "zumirali", "replacements": 1}
            ],
            pass_logs=[
                {"pass": 1, "mode": "strict", "suggestions": 1, "replacements": 1}
            ],
        )

    monkeypatch.setattr(
        "ai_video_editor.transcription.pipeline.transcribe_elevenlabs",
        fake_transcribe_elevenlabs,
    )
    monkeypatch.setattr(
        "ai_video_editor.transcription.pipeline.correct_grammar",
        fake_correct_grammar,
    )

    transcript = transcribe_with_elevenlabs_and_grammar(denoised, video, Settings())

    assert transcript.sentences[0].text == "zumirali"
    report = load_cached_grammar_report(video)
    assert report is not None
    assert grammar_report_path_for(video).exists()
    assert report.passes == 1
    assert report.total_suggestions == 1
    assert report.total_corrections == 1


def test_apply_corrections_logs_sentence_occurrences() -> None:
    word = Word(text="zomirali", start=1.0, end=1.5)
    sentence = Sentence(
        words=[word],
        text="Ovdje smo zomirali sliku.",
        start=1.0,
        end=3.0,
    )

    _, replacement_count, log_entries = _apply_corrections(
        [sentence],
        [WordCorrection(wrong="zomirali", correct="zumirali")],
        set(),
        1,
    )

    assert replacement_count == 1
    assert log_entries == [
        {
            "pass": 1,
            "wrong": "zomirali",
            "correct": "zumirali",
            "replacements": 1,
            "occurrences": [
                {
                    "sentence_index": 0,
                    "start": 1.0,
                    "end": 3.0,
                    "before": "Ovdje smo zomirali sliku.",
                    "after": "Ovdje smo zumirali sliku.",
                    "replacements": 1,
                }
            ],
        }
    ]
