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


def chunk_into_sentences(words: list[Word]) -> list[Sentence]:
    """
    Group words into sentences by splitting on terminal punctuation.
    """
    if not words:
        return []

    sentences: list[Sentence] = []
    current: list[Word] = []

    for word in words:
        current.append(word)
        if _is_sentence_end(word):
            sentences.append(_build_sentence(current))
            current = []

    if current:
        sentences.append(_build_sentence(current))

    logger.info("Chunked {} words into {} sentences", len(words), len(sentences))
    return sentences


def _build_sentence(words: list[Word]) -> Sentence:
    text = " ".join(w.text for w in words)
    return Sentence(
        words=words,
        text=text,
        start=words[0].start,
        end=words[-1].end,
    )
