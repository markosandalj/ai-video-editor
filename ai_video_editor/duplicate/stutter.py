from __future__ import annotations

from collections import Counter

from loguru import logger

from ai_video_editor.transcription.models import Sentence


def _normalise(word: str) -> str:
    return word.lower().strip(".,;:!?\"'()-–—…")


def _get_ngrams(words: list[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]


def _has_repeated_ngrams(words: list[str]) -> bool:
    """
    Check if a word list contains repeated n-grams indicating stuttering.

    Returns True if:
    - Any 3-gram appears more than once, OR
    - Any 2-gram appears more than once
    """
    if len(words) < 4:
        return False

    trigrams = _get_ngrams(words, 3)
    trigram_counts = Counter(trigrams)
    for count in trigram_counts.values():
        if count > 1:
            return True

    bigrams = _get_ngrams(words, 2)
    bigram_counts = Counter(bigrams)
    for count in bigram_counts.values():
        if count > 1:
            return True

    return False


def detect_stutters(sentences: list[Sentence]) -> list[int]:
    """
    Scan sentences for intra-sentence stuttering (repeated word sequences).

    Returns a list of sentence indices that contain repeated n-grams
    suggesting the speaker stuttered or false-started within the sentence.
    """
    flagged: list[int] = []

    for i, sentence in enumerate(sentences):
        words = [_normalise(w.text) for w in sentence.words]
        words = [w for w in words if w]

        if _has_repeated_ngrams(words):
            flagged.append(i)
            logger.debug(
                "Stutter detected in sentence {}: \"{}\"",
                i, sentence.text[:80],
            )

    logger.info(
        "Stutter detection: {}/{} sentences flagged",
        len(flagged), len(sentences),
    )
    return flagged
