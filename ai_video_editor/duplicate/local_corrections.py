"""Deterministic cuts for exceptionally clear local correction chains.

This lane is intentionally narrow. It handles two structural families:
a completed take separated from a highly similar earlier take by one or two
visibly truncated attempts, and an adjacent restart whose opening repeats the
trailing words of the previous sentence. Unlike the section editor, it makes
no semantic judgment and performs no model call: every emitted trim follows
directly from exact repeated word boundaries.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason, WordTrim
from ai_video_editor.transcription.models import Sentence

_MIN_ENDPOINT_WORDS = 7
_MAX_ENDPOINT_GAP_SECONDS = 10.0
_MIN_NEAR_IDENTICAL_SIMILARITY = 98.0
_MIN_ENDPOINT_LENGTH_RATIO = 0.8
_MIN_MIDDLE_CONTINUATION_WORDS = 3
_MIN_SPLICE_SIMILARITY = 65.0
_MIN_PREFIX_SIMILARITY = 85.0

_ADJACENT_MIN_SPAN_TOKENS = 3
_ADJACENT_MIN_SIMILARITY = 90.0
_ADJACENT_MAX_GAP_SECONDS = 10.0
_ADJACENT_LENGTH_SLACK = 2
_ADJACENT_MIN_LATER_COVERAGE = 0.5


def _indexed_tokens(sentence: Sentence) -> list[tuple[int, str]]:
    indexed: list[tuple[int, str]] = []
    for word_index, word in enumerate(sentence.words):
        token = "".join(char for char in word.text.casefold() if char.isalnum())
        if token:
            indexed.append((word_index, token))
    return indexed


def _visibly_truncated(sentence: Sentence) -> bool:
    text = sentence.text.strip()
    if text.endswith(("...", "-", "–")):
        return True
    return any(
        word.text.rstrip(".,;:!?").endswith(("-", "–"))
        for word in sentence.words
    )


def _similarities(
    earlier_tokens: list[str], later_tokens: list[str]
) -> tuple[float, float]:
    earlier_text = " ".join(earlier_tokens)
    later_text = " ".join(later_tokens)
    overall = max(
        fuzz.partial_ratio(earlier_text, later_text),
        fuzz.token_set_ratio(earlier_text, later_text),
    )
    prefix = fuzz.ratio(
        " ".join(earlier_tokens[:4]),
        " ".join(later_tokens[:4]),
    )
    return overall, prefix


def _restarted_opening(
    earlier_tokens: list[str], later_tokens: list[str]
) -> tuple[int, int] | None:
    """Return ``(opening_length, repeated_start)`` for a doubled later opening."""
    max_length = min(6, len(earlier_tokens), len(later_tokens))
    for opening_length in range(max_length, 1, -1):
        opening = earlier_tokens[:opening_length]
        if later_tokens[:opening_length] != opening:
            continue
        last_repeated_start = min(
            opening_length + 3,
            len(later_tokens) - opening_length,
        )
        for repeated_start in range(opening_length, last_repeated_start + 1):
            if later_tokens[repeated_start:repeated_start + opening_length] != opening:
                continue
            if repeated_start + opening_length < len(later_tokens):
                return opening_length, repeated_start
    return None


def _word_trim(sentence: Sentence, start_word: int, end_word: int) -> WordTrim:
    """Build a trim from an exclusive word-index range."""
    return WordTrim(
        start=sentence.words[start_word].start,
        end=sentence.words[end_word - 1].end,
    )


def _derive_chain_flags(
    sentences: list[Sentence], earlier_index: int, later_index: int
) -> list[DuplicateFlag]:
    earlier = sentences[earlier_index]
    later = sentences[later_index]
    earlier_indexed = _indexed_tokens(earlier)
    later_indexed = _indexed_tokens(later)
    if (
        len(earlier_indexed) < _MIN_ENDPOINT_WORDS
        or len(later_indexed) < _MIN_ENDPOINT_WORDS
    ):
        return []

    earlier_tokens = [token for _, token in earlier_indexed]
    later_tokens = [token for _, token in later_indexed]
    overall, prefix = _similarities(earlier_tokens, later_tokens)
    length_ratio = min(len(earlier_tokens), len(later_tokens)) / max(
        len(earlier_tokens), len(later_tokens)
    )
    endpoint_vocabulary = set(earlier_tokens) & set(later_tokens)
    middle_continuation_words = sum(
        token in endpoint_vocabulary
        for sentence in sentences[earlier_index + 1:later_index]
        for _, token in _indexed_tokens(sentence)
    )

    if (
        overall >= _MIN_NEAR_IDENTICAL_SIMILARITY
        and length_ratio >= _MIN_ENDPOINT_LENGTH_RATIO
        and middle_continuation_words >= _MIN_MIDDLE_CONTINUATION_WORDS
    ):
        return [DuplicateFlag(
            idx=earlier_index,
            reason=FlagReason.DUPLICATE,
            confidence=0.99,
            note=(
                "Mehanički prepoznat raniji potpuni pokušaj u lokalnom lancu "
                f"ispravka; dovršena verzija je rečenica [{later_index}]."
            ),
        )]

    restarted = _restarted_opening(earlier_tokens, later_tokens)
    if (
        overall < _MIN_SPLICE_SIMILARITY
        or prefix < _MIN_PREFIX_SIMILARITY
        or restarted is None
    ):
        return []

    opening_length, repeated_start = restarted
    earlier_cut_start = earlier_indexed[opening_length - 1][0] + 1
    later_cut_end = later_indexed[repeated_start + opening_length - 1][0] + 1
    note = (
        "Mehanički prepoznat ponovljeni početak u lokalnom lancu ispravka; "
        f"dovršena verzija je rečenica [{later_index}]."
    )
    return [
        DuplicateFlag(
            idx=earlier_index,
            reason=FlagReason.FALSE_START,
            confidence=0.99,
            note=note,
            word_trims=[_word_trim(earlier, earlier_cut_start, len(earlier.words))],
        ),
        DuplicateFlag(
            idx=later_index,
            reason=FlagReason.FALSE_START,
            confidence=0.99,
            note=note,
            word_trims=[_word_trim(later, 0, later_cut_end)],
        ),
    ]


def _anchored(a: str, b: str) -> bool:
    return a.startswith(b) or b.startswith(a)


def _adjacent_repeat_match(
    earlier_tokens: list[str], later_tokens: list[str]
) -> tuple[int, int] | None:
    """Return ``(suffix_length, prefix_length)`` for the longest anchored repeat.

    The earlier sentence's trailing tokens must fuzzily match the later
    sentence's opening tokens. Both span endpoints are anchored (equal tokens,
    tolerating transcription merges like "od tud"/"odtud"), which rejects
    order-flipped synonym pairs and paraphrased restarts.
    """
    for span in range(len(earlier_tokens), _ADJACENT_MIN_SPAN_TOKENS - 1, -1):
        suffix = earlier_tokens[-span:]
        lo = max(span - _ADJACENT_LENGTH_SLACK, 2)
        hi = min(span + _ADJACENT_LENGTH_SLACK, len(later_tokens))
        for prefix_length in sorted(range(lo, hi + 1), key=lambda k: abs(k - span)):
            prefix = later_tokens[:prefix_length]
            if not (_anchored(suffix[0], prefix[0]) and _anchored(suffix[-1], prefix[-1])):
                continue
            similarity = fuzz.ratio(" ".join(suffix), " ".join(prefix))
            if similarity >= _ADJACENT_MIN_SIMILARITY:
                return span, prefix_length
    return None


def _derive_adjacent_flags(
    sentences: list[Sentence], earlier_index: int
) -> list[DuplicateFlag]:
    earlier = sentences[earlier_index]
    later = sentences[earlier_index + 1]
    if later.start - earlier.end > _ADJACENT_MAX_GAP_SECONDS:
        return []
    earlier_indexed = _indexed_tokens(earlier)
    later_indexed = _indexed_tokens(later)
    if len(earlier_indexed) < _ADJACENT_MIN_SPAN_TOKENS or len(later_indexed) < 2:
        return []

    match = _adjacent_repeat_match(
        [token for _, token in earlier_indexed],
        [token for _, token in later_indexed],
    )
    if match is None:
        return []
    span, prefix_length = match
    if prefix_length < _ADJACENT_MIN_LATER_COVERAGE * len(later_indexed):
        # The repeat is only a small opening fraction of the later sentence:
        # that is the restate-and-elaborate teaching pattern ("...tlak od
        # sedam bara." → "Tlak od sedam bara nalazi se..."), which the human
        # keeps on both sides. A re-delivery covers most of the later take.
        return []
    note = (
        "Mehanički prepoznat ponovljeni završetak odmah ponovljen na početku "
        f"sljedeće rečenice; zadržana verzija je rečenica [{earlier_index + 1}]."
    )

    if span == len(earlier_indexed):
        # A whole-sentence restart is only safe when the later sentence
        # continues past the repeated opening; exact standalone twins are
        # deliberate repetition (dictation, emphasis) and must stay.
        if prefix_length >= len(later_indexed):
            return []
        return [DuplicateFlag(
            idx=earlier_index,
            reason=FlagReason.FALSE_START,
            confidence=0.99,
            note=note,
        )]

    reason = (
        FlagReason.DUPLICATE
        if prefix_length >= len(later_indexed)
        else FlagReason.FALSE_START
    )
    cut_start = earlier_indexed[-span][0]
    return [DuplicateFlag(
        idx=earlier_index,
        reason=reason,
        confidence=0.99,
        note=note,
        word_trims=[_word_trim(earlier, cut_start, len(earlier.words))],
    )]


def detect_local_corrections(sentences: list[Sentence]) -> list[DuplicateFlag]:
    """Return exact cuts for adjacent restarts and short local correction chains."""
    flags: list[DuplicateFlag] = []
    for earlier_index, earlier in enumerate(sentences):
        if earlier_index + 1 < len(sentences):
            flags.extend(_derive_adjacent_flags(sentences, earlier_index))
        for distance in (2, 3):
            later_index = earlier_index + distance
            if later_index >= len(sentences):
                continue
            later = sentences[later_index]
            if later.start - earlier.end > _MAX_ENDPOINT_GAP_SECONDS:
                continue
            if not any(
                _visibly_truncated(sentence)
                for sentence in sentences[earlier_index + 1:later_index]
            ):
                continue
            flags.extend(_derive_chain_flags(sentences, earlier_index, later_index))
    return flags
