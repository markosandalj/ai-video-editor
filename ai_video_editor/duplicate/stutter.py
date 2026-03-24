from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from loguru import logger

from ai_video_editor.transcription.models import Sentence


@dataclass
class StutterSpan:
    """Word-index range of a repeated portion within a sentence.

    ``first_start..first_end`` is the first (stuttered) occurrence.
    ``second_start..second_end`` is the second (clean) occurrence.
    The default strategy keeps the second occurrence and cuts the first.
    """
    first_start: int
    first_end: int
    second_start: int
    second_end: int
    ngram: tuple[str, ...]


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


def find_stutter_spans(words: list[str]) -> list[StutterSpan]:
    """Find repeated n-gram spans within a word list.

    Returns spans sorted by ``first_start``, longest match first for
    overlapping repeats.  The caller can decide what to cut.
    """
    if len(words) < 4:
        return []

    spans: list[StutterSpan] = []
    used_first: set[int] = set()
    used_second: set[int] = set()

    for n in (3, 2):
        ngrams = _get_ngrams(words, n)
        positions: dict[tuple[str, ...], list[int]] = {}
        for i, gram in enumerate(ngrams):
            positions.setdefault(gram, []).append(i)

        for gram, idxs in positions.items():
            if len(idxs) < 2:
                continue
            first_pos = idxs[0]
            second_pos = idxs[-1]
            first_range = set(range(first_pos, first_pos + n))
            second_range = set(range(second_pos, second_pos + n))
            if first_range & used_first or second_range & used_second:
                continue
            if first_range & second_range:
                continue
            spans.append(StutterSpan(
                first_start=first_pos,
                first_end=first_pos + n,
                second_start=second_pos,
                second_end=second_pos + n,
                ngram=gram,
            ))
            used_first.update(first_range)
            used_second.update(second_range)

    spans.sort(key=lambda s: s.first_start)
    return spans


def compute_stutter_cut_ranges(
    sentence: Sentence,
) -> list[tuple[float, float]]:
    """Return time ranges to CUT from a sentence's audio.

    For each stutter span, the first (stuttered) occurrence is cut.
    Returns a list of ``(start_time, end_time)`` pairs.
    """
    words_norm = [_normalise(w.text) for w in sentence.words]
    spans = find_stutter_spans(words_norm)

    if not spans:
        return []

    cuts: list[tuple[float, float]] = []
    for span in spans:
        first_words = sentence.words[span.first_start : span.first_end]
        if not first_words:
            continue
        cut_start = first_words[0].start
        cut_end = first_words[-1].end
        cuts.append((cut_start, cut_end))

    merged: list[tuple[float, float]] = []
    for start, end in sorted(cuts):
        if merged and start <= merged[-1][1] + 0.05:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    return merged


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
