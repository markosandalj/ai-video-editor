"""Regression tests for deterministic non-adjacent correction chains."""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_video_editor.config.settings import SectionEditorConfig
from ai_video_editor.duplicate.local_corrections import detect_local_corrections
from ai_video_editor.duplicate.models import FlagReason
from ai_video_editor.transcription.models import Sentence, Transcript, Word

FIXTURES = Path(__file__).parent / "fixtures"


def _transcript(name: str) -> Transcript:
    return Transcript.model_validate_json(
        (FIXTURES / f"{name}-raw.transcript.json").read_text()
    )


def _sentence(text: str, start: float, end: float) -> Sentence:
    raw_words = text.split()
    step = (end - start) / len(raw_words)
    words = [
        Word(text=word, start=start + index * step, end=start + (index + 1) * step)
        for index, word in enumerate(raw_words)
    ]
    return Sentence(text=text, words=words, start=start, end=end)


def test_derives_exact_essay_splice_without_removing_remainders() -> None:
    sentences = _transcript("engleski25ljeto-esej").sentences

    flags = detect_local_corrections(sentences)
    by_index = {flag.idx: flag for flag in flags}

    assert set(by_index) == {40, 43}
    assert by_index[40].reason is FlagReason.FALSE_START
    assert len(by_index[40].word_trims) == 1
    assert by_index[40].word_trims[0].start == sentences[40].words[3].start
    assert by_index[40].word_trims[0].end == sentences[40].words[11].end
    assert len(by_index[43].word_trims) == 1
    assert by_index[43].word_trims[0].start == sentences[43].words[0].start
    assert by_index[43].word_trims[0].end == sentences[43].words[6].end
    assert "lokalnom lancu ispravka" in by_index[40].note


def test_cuts_complete_near_identical_earlier_take() -> None:
    sentences = _transcript("engleski25ljeto-listening-1").sentences

    flags = detect_local_corrections(sentences)

    assert len(flags) == 1
    assert flags[0].idx == 148
    assert flags[0].reason is FlagReason.DUPLICATE
    assert flags[0].word_trims == []
    assert all(flag.idx != 150 for flag in flags)


def test_section_editor_merges_deterministic_corrections_after_sol(monkeypatch) -> None:
    import ai_video_editor.duplicate.section_editor as section_editor

    sentences = _transcript("engleski25ljeto-esej").sentences
    monkeypatch.setattr(section_editor, "build_chat_model", lambda _config: object())
    monkeypatch.setattr(
        section_editor,
        "_edit_section_with_retry",
        lambda _sentences, _section, _llm, _cfg, _health: [],
    )

    flags = section_editor.detect_section_edits(sentences, SectionEditorConfig())

    assert {flag.idx for flag in flags} == {40, 43}


@pytest.mark.parametrize("fixture", ["test-6", "test-44", "test-45"])
def test_rejects_known_full_corpus_controls(fixture: str) -> None:
    assert detect_local_corrections(_transcript(fixture).sentences) == []


def test_requires_a_visibly_truncated_middle_attempt() -> None:
    sentences = [
        _sentence("Ovo je dovoljno duga ranija verzija iste jasne misli", 0, 4),
        _sentence("Ovdje govornik samo zastane bez prekida", 4.2, 5.0),
        _sentence("Ovo je dovoljno duga ranija verzija iste jasne misli", 5.2, 9),
    ]

    assert detect_local_corrections(sentences) == []


def test_requires_endpoints_to_be_within_ten_seconds() -> None:
    sentences = [
        _sentence("Ovo je dovoljno duga ranija verzija iste jasne misli", 0, 4),
        _sentence("Ovaj pokušaj...", 4.2, 5.0),
        _sentence("Ovo je dovoljno duga ranija verzija iste jasne misli", 14.1, 18),
    ]

    assert detect_local_corrections(sentences) == []


def test_near_identical_full_cut_requires_similar_endpoint_lengths() -> None:
    sentences = [
        _sentence("Ovo je dovoljno duga ranija verzija iste jasne misli", 0, 4),
        _sentence("Ovaj pokušaj...", 4.2, 5.0),
        _sentence(
            "Ovo je dovoljno duga ranija verzija iste jasne misli uz puno "
            "novog važnog objašnjenja koje treba ostati",
            5.2,
            10,
        ),
    ]

    assert detect_local_corrections(sentences) == []
