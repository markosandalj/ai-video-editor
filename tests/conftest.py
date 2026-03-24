from __future__ import annotations

import pytest

from ai_video_editor.transcription.models import Sentence, Word


def _sentence(text: str, start: float, end: float) -> Sentence:
    """Helper to build a Sentence with a single Word (timestamps only matter at sentence level)."""
    words = [Word(text=w, start=start, end=end) for w in text.split()]
    return Sentence(words=words, text=text, start=start, end=end)


@pytest.fixture
def croatian_transcript_with_duplicates() -> list[Sentence]:
    """
    Synthetic Croatian transcript with known patterns:
      [0] Original sentence
      [1] False start / filler
      [2] Exact repeat of [0]  (duplicate — [0] should be cut)
      [3] Unique content
      [4] Paraphrased version of [3] (semantic duplicate — [3] should be cut)
      [5] Unique content
      [6] Legitimate recap (far from [0], should NOT be flagged)
    """
    return [
        _sentence("Dakle danas ćemo raditi na projektu za web aplikaciju", 0.0, 3.0),
        _sentence("Znači ovaj", 3.5, 4.0),
        _sentence("Dakle danas ćemo raditi na projektu za web aplikaciju", 4.5, 7.5),
        _sentence("Prvo trebamo napraviti bazu podataka s korisnicima", 8.0, 11.0),
        _sentence("Trebamo kreirati bazu za podatke o korisnicima", 11.5, 14.5),
        _sentence("CSS framework koji koristimo je Tailwind", 15.0, 18.0),
        _sentence("Kao što sam rekao na početku radimo web aplikaciju", 50.0, 53.0),
    ]


@pytest.fixture
def simple_duplicate_pair() -> list[Sentence]:
    """Two identical sentences for basic testing."""
    return [
        _sentence("Ovo je testna rečenica za provjeru", 0.0, 2.0),
        _sentence("Ovo je testna rečenica za provjeru", 3.0, 5.0),
    ]


@pytest.fixture
def no_duplicates() -> list[Sentence]:
    """Three completely different sentences."""
    return [
        _sentence("Danas učimo o bazama podataka", 0.0, 2.0),
        _sentence("Sutra ćemo raditi na frontendu", 3.0, 5.0),
        _sentence("CSS animacije su jako korisne", 6.0, 8.0),
    ]
