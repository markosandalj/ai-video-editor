from __future__ import annotations

import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer

from ai_video_editor.duplicate.models import SimilarityScore
from ai_video_editor.duplicate.windowed import windowed_pairs
from ai_video_editor.transcription.models import Sentence

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading sentence-transformer model: {}", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def compute_semantic_similarity(
    sentences: list[Sentence],
    *,
    window: int = 5,
    threshold: float = 0.75,
) -> list[SimilarityScore]:
    """
    Compute cosine similarity between sentence embeddings for pairs
    within a lookahead window.

    Returns only pairs where cosine similarity meets or exceeds *threshold*
    (0.0–1.0 scale).
    """
    if not sentences:
        return []

    model = _get_model()
    texts = [s.text for s in sentences]

    logger.info("Encoding {} sentences with {}", len(texts), _MODEL_NAME)
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    results: list[SimilarityScore] = []

    for i, j in windowed_pairs(len(sentences), window):
        cosine = float(np.dot(embeddings[i], embeddings[j]))

        if cosine >= threshold:
            results.append(
                SimilarityScore(
                    idx_a=i,
                    idx_b=j,
                    semantic_cosine=round(cosine, 4),
                )
            )

    logger.info(
        "Semantic similarity: {} pairs above {:.2f} threshold (window={})",
        len(results),
        threshold,
        window,
    )
    return results
