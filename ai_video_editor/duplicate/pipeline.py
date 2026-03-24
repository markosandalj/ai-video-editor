from __future__ import annotations

from loguru import logger

from ai_video_editor.config.settings import DuplicateDetectionConfig
from ai_video_editor.duplicate.gemini_verify import (
    detect_false_starts_with_gemini,
    verify_duplicates_with_gemini,
)
from ai_video_editor.duplicate.lexical import compute_lexical_similarity
from ai_video_editor.duplicate.models import (
    DuplicateFlag,
    DuplicatePair,
    FlagReason,
    SimilarityScore,
)
from ai_video_editor.duplicate.semantic import compute_semantic_similarity
from ai_video_editor.transcription.models import Sentence


def _merge_score(base: SimilarityScore, other: SimilarityScore) -> SimilarityScore:
    """Merge two partial SimilarityScore objects for the same pair."""
    return SimilarityScore(
        idx_a=base.idx_a,
        idx_b=base.idx_b,
        lexical_ratio=base.lexical_ratio if base.lexical_ratio is not None else other.lexical_ratio,
        lexical_token_sort=base.lexical_token_sort if base.lexical_token_sort is not None else other.lexical_token_sort,
        semantic_cosine=base.semantic_cosine if base.semantic_cosine is not None else other.semantic_cosine,
        gemini_is_duplicate=base.gemini_is_duplicate if base.gemini_is_duplicate is not None else other.gemini_is_duplicate,
        gemini_confidence=base.gemini_confidence if base.gemini_confidence is not None else other.gemini_confidence,
    )


def detect_duplicates(
    sentences: list[Sentence],
    cfg: DuplicateDetectionConfig | None = None,
) -> list[DuplicateFlag]:
    """
    Run the full tiered duplicate-detection pipeline.

    Tier 1 (lexical) -> Tier 2 (semantic) -> Tier 3 (Gemini).
    Returns a list of ``DuplicateFlag`` objects for every sentence that
    should be removed.
    """
    if cfg is None:
        cfg = DuplicateDetectionConfig()

    if len(sentences) < 2:
        return []

    # ------------------------------------------------------------------
    # Tier 1: Lexical
    # ------------------------------------------------------------------
    lexical_scores = compute_lexical_similarity(
        sentences,
        window=cfg.window_size,
        threshold=cfg.lexical_maybe,
    )

    score_map: dict[tuple[int, int], SimilarityScore] = {}
    for s in lexical_scores:
        score_map[(s.idx_a, s.idx_b)] = s

    definite_pairs: list[DuplicatePair] = []
    borderline_keys: set[tuple[int, int]] = set()

    for key, score in score_map.items():
        best_lex = max(score.lexical_ratio or 0, score.lexical_token_sort or 0)
        if best_lex >= cfg.lexical_definite:
            definite_pairs.append(DuplicatePair(
                idx_keep=key[1],
                idx_cut=key[0],
                score=score,
                tier="lexical",
            ))
        else:
            borderline_keys.add(key)

    logger.info(
        "Tier 1 (lexical): {} definite, {} borderline",
        len(definite_pairs),
        len(borderline_keys),
    )

    # ------------------------------------------------------------------
    # Tier 2: Semantic — only for borderline pairs + new discoveries
    # ------------------------------------------------------------------
    semantic_scores = compute_semantic_similarity(
        sentences,
        window=cfg.window_size,
        threshold=cfg.semantic_maybe,
    )

    already_decided = {(p.idx_cut, p.idx_keep) for p in definite_pairs}

    for s in semantic_scores:
        key = (s.idx_a, s.idx_b)
        if key in already_decided:
            continue

        if key in score_map:
            score_map[key] = _merge_score(score_map[key], s)
        else:
            score_map[key] = s

        cosine = s.semantic_cosine or 0.0
        if cosine >= cfg.semantic_definite:
            merged = score_map[key]
            definite_pairs.append(DuplicatePair(
                idx_keep=key[1],
                idx_cut=key[0],
                score=merged,
                tier="semantic",
            ))
            already_decided.add(key)
            borderline_keys.discard(key)
        else:
            borderline_keys.add(key)

    logger.info(
        "Tier 2 (semantic): {} definite total, {} borderline for Gemini",
        len(definite_pairs),
        len(borderline_keys),
    )

    # ------------------------------------------------------------------
    # Tier 3: Gemini — only borderline pairs
    # ------------------------------------------------------------------
    borderline_scores = [score_map[k] for k in sorted(borderline_keys)]

    if borderline_scores:
        verdicts = verify_duplicates_with_gemini(borderline_scores, sentences)

        for v in verdicts:
            if v.pair_id >= len(borderline_scores):
                continue
            bs = borderline_scores[v.pair_id]
            key = (bs.idx_a, bs.idx_b)
            merged = score_map[key]
            merged.gemini_is_duplicate = v.is_duplicate
            merged.gemini_confidence = v.confidence

            if v.is_duplicate and v.confidence >= cfg.gemini_confidence_threshold:
                definite_pairs.append(DuplicatePair(
                    idx_keep=key[1],
                    idx_cut=key[0],
                    score=merged,
                    tier="gemini",
                ))
                already_decided.add(key)

    logger.info("Tier 3 (Gemini): {} definite total", len(definite_pairs))

    # ------------------------------------------------------------------
    # Build flags — earlier take always cut, later take kept
    # ------------------------------------------------------------------
    flags: list[DuplicateFlag] = []
    flagged_indices: set[int] = set()

    for pair in definite_pairs:
        if pair.idx_cut not in flagged_indices:
            flags.append(DuplicateFlag(
                idx=pair.idx_cut,
                reason=FlagReason.DUPLICATE,
                confidence=1.0 if pair.tier != "gemini" else (pair.score.gemini_confidence or 1.0),
                related_pair=pair,
            ))
            flagged_indices.add(pair.idx_cut)

    # ------------------------------------------------------------------
    # False-start detection — sentences between duplicate pairs
    # ------------------------------------------------------------------
    for pair in definite_pairs:
        lo = pair.idx_cut + 1
        hi = pair.idx_keep
        if hi - lo < 1:
            continue

        block = sentences[lo:hi]
        already_flagged_block = [i for i in range(lo, hi) if i in flagged_indices]
        unflagged_in_block = [i for i in range(lo, hi) if i not in flagged_indices]
        if not unflagged_in_block:
            continue

        before = sentences[pair.idx_cut] if pair.idx_cut >= 0 else None
        after = sentences[pair.idx_keep] if pair.idx_keep < len(sentences) else None

        verdict = detect_false_starts_with_gemini(block, before, after)

        for local_idx in verdict.filler_indices:
            global_idx = lo + local_idx
            if global_idx in flagged_indices or global_idx >= hi:
                continue
            flags.append(DuplicateFlag(
                idx=global_idx,
                reason=FlagReason.FALSE_START,
                confidence=0.8,
                related_pair=pair,
                note=verdict.reasoning,
            ))
            flagged_indices.add(global_idx)

    flags.sort(key=lambda f: f.idx)

    logger.info(
        "Duplicate detection complete: {} flags ({} duplicate, {} false-start)",
        len(flags),
        sum(1 for f in flags if f.reason == FlagReason.DUPLICATE),
        sum(1 for f in flags if f.reason == FlagReason.FALSE_START),
    )

    return flags
