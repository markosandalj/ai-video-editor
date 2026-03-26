from __future__ import annotations

from rapidfuzz import fuzz
from loguru import logger

from ai_video_editor.transcription.models import Sentence


def _normalise(text: str) -> str:
    return text.lower().strip(".,;:!?\"'()-–—…").strip()


def _word_count(text: str) -> int:
    return len(text.split())


def is_trailing_filler(sentence: Sentence, max_words: int = 5) -> bool:
    """Short trailing filler with no real content (e.g. 'Evo, znači, to znači da...')."""
    text = _normalise(sentence.text)
    if _word_count(sentence.text) > max_words:
        return False
    filler_markers = {"evo", "znači", "dakle", "ovaj", "dobro", "okej"}
    words = text.split()
    content_words = [w for w in words if w not in filler_markers and len(w) > 2]
    return len(content_words) == 0


def is_content_subset(
    sentence: Sentence,
    neighbours: list[Sentence],
    threshold: float = 85.0,
) -> bool:
    """True if the sentence's content is largely contained in a nearby sentence."""
    text = _normalise(sentence.text)
    if _word_count(sentence.text) < 3:
        return True

    for nb in neighbours:
        nb_text = _normalise(nb.text)
        if len(nb_text) <= len(text):
            continue
        ratio = fuzz.partial_ratio(text, nb_text)
        if ratio >= threshold:
            return True
    return False


def is_repeated_question(
    sentence: Sentence,
    all_kept: list[tuple[int, Sentence]],
    own_idx: int,
    threshold: float = 80.0,
) -> bool:
    """True if this sentence is a question that appears similarly elsewhere."""
    text = sentence.text.strip()
    if not text.endswith("?"):
        return False

    norm = _normalise(text)
    for idx, other in all_kept:
        if idx == own_idx:
            continue
        other_norm = _normalise(other.text)
        if norm in other_norm or fuzz.ratio(norm, other_norm) >= threshold:
            return True
    return False


def is_incomplete_fragment(
    sentence: Sentence,
    max_words: int = 4,
) -> bool:
    """
    Detect incomplete/abandoned sentence fragments.
    E.g. "Evo, ja.", "A ovaj...", "Evo, znači, to znači da..."
    """
    text = sentence.text.strip()
    words = text.split()

    if len(words) > max_words:
        return False

    if text.endswith("...") or text.endswith("…"):
        return True

    norm = _normalise(text)
    norm_words = norm.split()
    filler_markers = {"evo", "znači", "dakle", "ovaj", "dobro", "okej", "pa", "a", "i", "ja"}
    content_words = [w for w in norm_words if w not in filler_markers and len(w) > 2]
    if len(content_words) == 0:
        return True

    return False


def detect_fragment_candidates(
    sentences: list[Sentence],
    flagged_indices: set[int],
    max_words: int = 4,
) -> list[int]:
    """
    Return indices of sentences that look like incomplete fragments.
    Skips already-flagged sentences.
    """
    candidates = []
    for i, s in enumerate(sentences):
        if i in flagged_indices:
            continue
        if is_incomplete_fragment(s, max_words=max_words):
            candidates.append(i)
    return candidates


def algorithmic_redundancy_check(
    sentence_idx: int,
    sentence: Sentence,
    all_kept: list[tuple[int, Sentence]],
    window: int = 3,
) -> bool:
    """
    Returns True if at least one algorithmic check flags this sentence as redundant.
    Used as a safety gate alongside Gemini's holistic review.
    """
    if is_trailing_filler(sentence):
        logger.debug("Algorithmic check: sentence {} is trailing filler", sentence_idx)
        return True

    position = None
    for i, (idx, _) in enumerate(all_kept):
        if idx == sentence_idx:
            position = i
            break

    if position is not None:
        lo = max(0, position - window)
        hi = min(len(all_kept), position + window + 1)
        neighbours = [s for j, (_, s) in enumerate(all_kept) if lo <= j < hi and j != position]

        if is_content_subset(sentence, neighbours):
            logger.debug("Algorithmic check: sentence {} is content subset", sentence_idx)
            return True

    if is_repeated_question(sentence, all_kept, sentence_idx):
        logger.debug("Algorithmic check: sentence {} is repeated question", sentence_idx)
        return True

    return False
