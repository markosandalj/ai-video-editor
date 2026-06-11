from __future__ import annotations

import re

from loguru import logger

from ai_video_editor.transcription.models import Sentence, Word

_TERMINAL_PUNCT = re.compile(r"[.?!]$")

_ABBREVIATIONS = {
    "dr.", "mr.", "mrs.", "ms.", "prof.", "sr.", "jr.",
    "st.", "ave.", "blvd.", "str.", "br.", "sv.", "tj.",
    "npr.", "sl.", "čl.", "gl.", "god.", "tel.",
}


def _is_sentence_end(word: Word) -> bool:
    lower = word.text.lower().rstrip(",;:")
    if lower in _ABBREVIATIONS:
        return False
    return bool(_TERMINAL_PUNCT.search(word.text))


def chunk_into_sentences(
    words: list[Word],
    *,
    pause_split_s: float = 0.0,
) -> list[Sentence]:
    """
    Group words into sentences by splitting on terminal punctuation.

    When ``pause_split_s`` > 0, each punctuation-delimited sentence is further
    split wherever the gap between two consecutive words is at least that many
    seconds. Long intra-sentence pauses are where speakers abandon a thought
    and restart, so splitting there hands the downstream cut logic a unit shaped
    like the false start it needs to remove.
    """
    if not words:
        return []

    sentences: list[Sentence] = []
    current: list[Word] = []

    for word in words:
        current.append(word)
        if _is_sentence_end(word):
            sentences.extend(_split_on_pauses(current, pause_split_s))
            current = []

    if current:
        sentences.extend(_split_on_pauses(current, pause_split_s))

    logger.info("Chunked {} words into {} sentences", len(words), len(sentences))
    return sentences


def _split_on_pauses(words: list[Word], pause_split_s: float) -> list[Sentence]:
    """Split a word run wherever an inter-word gap is >= ``pause_split_s``."""
    if pause_split_s <= 0 or len(words) < 2:
        return [_build_sentence(words)]

    runs: list[list[Word]] = []
    run: list[Word] = [words[0]]
    for prev, word in zip(words, words[1:]):
        if word.start - prev.end >= pause_split_s:
            runs.append(run)
            run = [word]
        else:
            run.append(word)
    runs.append(run)

    return [_build_sentence(r) for r in runs]


def _build_sentence(words: list[Word]) -> Sentence:
    text = " ".join(w.text for w in words)
    return Sentence(
        words=words,
        text=text,
        start=words[0].start,
        end=words[-1].end,
    )
