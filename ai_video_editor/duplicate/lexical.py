from __future__ import annotations

from loguru import logger
from rapidfuzz import fuzz

from ai_video_editor.duplicate.models import SimilarityScore
from ai_video_editor.duplicate.windowed import windowed_pairs
from ai_video_editor.transcription.models import Sentence


def compute_lexical_similarity(
    sentences: list[Sentence],
    *,
    window: int = 5,
    threshold: float = 70.0,
) -> list[SimilarityScore]:
    """
    Compute Levenshtein-based similarity for sentence pairs within
    a lookahead window.

    Returns only pairs where **either** ``fuzz.ratio`` or
    ``fuzz.token_sort_ratio`` meets or exceeds *threshold* (0-100 scale).
    """
    results: list[SimilarityScore] = []

    for i, j in windowed_pairs(len(sentences), window):
        text_a = sentences[i].text
        text_b = sentences[j].text

        ratio = fuzz.ratio(text_a, text_b)
        token_sort = fuzz.token_sort_ratio(text_a, text_b)

        if max(ratio, token_sort) >= threshold:
            results.append(
                SimilarityScore(
                    idx_a=i,
                    idx_b=j,
                    lexical_ratio=round(ratio, 2),
                    lexical_token_sort=round(token_sort, 2),
                )
            )

    logger.info(
        "Lexical similarity: {} pairs above {:.0f} threshold (window={})",
        len(results),
        threshold,
        window,
    )
    return results
