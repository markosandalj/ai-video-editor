from __future__ import annotations

from loguru import logger

from ai_video_editor.config.settings import DuplicateDetectionConfig
from ai_video_editor.duplicate.gemini_verify import (
    detect_false_starts_with_gemini,
    pick_best_version_with_gemini,
    verify_duplicates_with_gemini,
    verify_fragments_with_gemini,
    verify_stutters_with_gemini,
)
from ai_video_editor.duplicate.redundancy import detect_fragment_candidates
from ai_video_editor.duplicate.lexical import compute_lexical_similarity
from ai_video_editor.duplicate.models import (
    DuplicateFlag,
    DuplicatePair,
    FlagReason,
    SimilarityScore,
    WordTrim,
)
from ai_video_editor.duplicate.stutter import compute_stutter_cut_ranges, detect_stutters
from ai_video_editor.duplicate.semantic import compute_semantic_similarity
from ai_video_editor.llm import LangChainModelConfig
from ai_video_editor.transcription.models import Sentence


def _default_keep_cut(idx_a: int, idx_b: int) -> tuple[int, int]:
    """Default: keep the later sentence (higher index), cut the earlier."""
    return (max(idx_a, idx_b), min(idx_a, idx_b))


def _too_short_for_auto_cut(
    sentences: list[Sentence], idx_a: int, idx_b: int, min_words: int
) -> bool:
    """Short near-identical pairs ('Dobro.' … 'Dobro.') are usually recurring
    discourse markers, not retakes — route them to Gemini instead of auto-cutting."""
    wc_a = len(sentences[idx_a].words)
    wc_b = len(sentences[idx_b].words)
    return min(wc_a, wc_b) < min_words


def _pair_confidence(pair: DuplicatePair) -> float:
    """Best available confidence for the pair, on a 0-1 scale.

    Lexical/semantic tiers have no model confidence, so we surface the raw
    similarity instead of the old hardcoded 1.0 — the review UI reads this to
    show how sure a cut is, and algorithmic cuts are *not* certain.
    """
    s = pair.score
    if pair.tier == "gemini" and s.gemini_confidence is not None:
        return s.gemini_confidence
    if pair.tier == "semantic" and s.semantic_cosine is not None:
        return min(1.0, max(0.0, s.semantic_cosine))
    best_lex = max(s.lexical_ratio or 0.0, s.lexical_token_sort or 0.0)
    return min(1.0, best_lex / 100.0)


def _cluster_duplicate_flags(
    definite_pairs: list[DuplicatePair],
    sentences: list[Sentence],
    *,
    take_selection: str,
    prefer_completeness: bool,
) -> tuple[list[DuplicateFlag], set[int]]:
    """Group connected duplicate pairs into retake clusters; keep one survivor each.

    Returns ``(flags, survivor_indices)``. Cutting all-but-one per cluster makes
    the keep/cut assignment internally consistent — a sentence can no longer be
    the keep-side of one pair and the cut-side of another.
    """
    # Union-find over the sentence indices that appear in any confirmed pair.
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    keep_votes: dict[int, int] = {}
    confidence: dict[int, float] = {}
    for p in definite_pairs:
        union(p.idx_keep, p.idx_cut)
        keep_votes[p.idx_keep] = keep_votes.get(p.idx_keep, 0) + 1
        conf = _pair_confidence(p)
        confidence[p.idx_cut] = max(confidence.get(p.idx_cut, 0.0), conf)

    clusters: dict[int, list[int]] = {}
    for idx in parent:
        clusters.setdefault(find(idx), []).append(idx)

    flags: list[DuplicateFlag] = []
    survivors: set[int] = set()
    for members in clusters.values():
        if take_selection == "last":
            # Deterministic: the last take always wins — keep the highest index,
            # regardless of keep-votes. This is the property professors record for.
            survivor = max(members)
        else:
            def survivor_key(i: int) -> tuple:
                wc = len(sentences[i].words) if 0 <= i < len(sentences) else 0
                votes = keep_votes.get(i, 0)
                # Highest keep-votes wins; then completeness or recency; index breaks ties.
                return (votes, wc if prefer_completeness else 0, i)

            survivor = max(members, key=survivor_key)
        survivors.add(survivor)
        for i in members:
            if i == survivor:
                continue
            # Find a representative pair for this cut (for review traceability).
            rel = next(
                (p for p in definite_pairs if p.idx_cut == i or p.idx_keep == i),
                None,
            )
            flags.append(DuplicateFlag(
                idx=i,
                reason=FlagReason.DUPLICATE,
                confidence=confidence.get(i, 0.9),
                related_pair=rel,
            ))

    return flags, survivors


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
    *,
    llm_config: LangChainModelConfig | None = None,
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
        if best_lex >= cfg.lexical_definite and not _too_short_for_auto_cut(
            sentences, key[0], key[1], cfg.definite_min_words
        ):
            keep, cut = _default_keep_cut(key[0], key[1])
            definite_pairs.append(DuplicatePair(
                idx_keep=keep,
                idx_cut=cut,
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
        if cosine >= cfg.semantic_definite and not _too_short_for_auto_cut(
            sentences, key[0], key[1], cfg.definite_min_words
        ):
            merged = score_map[key]
            keep, cut = _default_keep_cut(key[0], key[1])
            definite_pairs.append(DuplicatePair(
                idx_keep=keep,
                idx_cut=cut,
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
        verdicts = verify_duplicates_with_gemini(
            borderline_scores,
            sentences,
            context_window=cfg.context_window,
            llm_config=llm_config,
        )

        for v in verdicts:
            if v.pair_id >= len(borderline_scores):
                continue
            bs = borderline_scores[v.pair_id]
            key = (bs.idx_a, bs.idx_b)
            merged = score_map[key]
            merged.gemini_is_duplicate = v.is_duplicate
            merged.gemini_confidence = v.confidence

            if v.is_duplicate and v.confidence >= cfg.gemini_confidence_threshold:
                if (
                    cfg.take_selection == "gemini"
                    and v.preferred_index is not None
                    and v.preferred_index in key
                ):
                    keep = v.preferred_index
                    cut = key[0] if key[1] == keep else key[1]
                else:
                    keep, cut = _default_keep_cut(key[0], key[1])
                definite_pairs.append(DuplicatePair(
                    idx_keep=keep,
                    idx_cut=cut,
                    score=merged,
                    tier="gemini",
                ))
                already_decided.add(key)

    logger.info("Tier 3 (Gemini): {} definite total", len(definite_pairs))

    # ------------------------------------------------------------------
    # Gemini "which to keep" — optional re-review of the keep side.
    # Only runs under take_selection='gemini'. The default 'last' keeps the
    # later take deterministically: the human keeps the later take in ~71-82%
    # of retake pairs, so keep-later outperforms a completeness-first LLM
    # re-litigation (see take_selection / llm_keep_review in settings).
    # ------------------------------------------------------------------
    if cfg.take_selection == "gemini" and cfg.llm_keep_review and definite_pairs:
        keep_decisions = pick_best_version_with_gemini(
            definite_pairs,
            sentences,
            prefer_completeness=cfg.prefer_completeness,
            llm_config=llm_config,
        )
        for pair in definite_pairs:
            preferred = keep_decisions.get(pair.idx_cut)
            if preferred is not None and preferred != pair.idx_keep:
                pair.idx_keep, pair.idx_cut = pair.idx_cut, pair.idx_keep

    # ------------------------------------------------------------------
    # Build flags — cluster connected retakes so the keep/cut assignment is
    # internally consistent (no sentence is both a keep-side and a cut-side).
    # ------------------------------------------------------------------
    flags: list[DuplicateFlag] = []
    flagged_indices: set[int] = set()
    protected_indices: set[int]

    if definite_pairs and cfg.cluster_retakes:
        dup_flags, protected_indices = _cluster_duplicate_flags(
            definite_pairs,
            sentences,
            take_selection=cfg.take_selection,
            prefer_completeness=cfg.prefer_completeness,
        )
        for f in dup_flags:
            flags.append(f)
            flagged_indices.add(f.idx)
    else:
        protected_indices = {p.idx_keep for p in definite_pairs}
        for pair in definite_pairs:
            if pair.idx_cut not in flagged_indices and pair.idx_cut not in protected_indices:
                flags.append(DuplicateFlag(
                    idx=pair.idx_cut,
                    reason=FlagReason.DUPLICATE,
                    confidence=_pair_confidence(pair),
                    related_pair=pair,
                ))
                flagged_indices.add(pair.idx_cut)

    # ------------------------------------------------------------------
    # False-start detection — sentences between duplicate pairs
    # ------------------------------------------------------------------

    for pair in definite_pairs:
        lo = min(pair.idx_cut, pair.idx_keep) + 1
        hi = max(pair.idx_cut, pair.idx_keep)
        if hi - lo < 1:
            continue

        block = sentences[lo:hi]
        unflagged_in_block = [i for i in range(lo, hi) if i not in flagged_indices]
        if not unflagged_in_block:
            continue

        earlier = min(pair.idx_cut, pair.idx_keep)
        later = max(pair.idx_cut, pair.idx_keep)
        before = sentences[earlier] if earlier >= 0 else None
        after = sentences[later] if later < len(sentences) else None

        verdict = detect_false_starts_with_gemini(
            block,
            before,
            after,
            llm_config=llm_config,
        )

        for local_idx in verdict.filler_indices:
            global_idx = lo + local_idx
            if global_idx in flagged_indices or global_idx >= hi:
                continue
            if global_idx in protected_indices:
                logger.info(
                    "Protecting sentence {} from false-start flag — "
                    "it is the keep-side of another duplicate pair",
                    global_idx,
                )
                continue
            flags.append(DuplicateFlag(
                idx=global_idx,
                reason=FlagReason.FALSE_START,
                confidence=0.8,
                related_pair=pair,
                note=verdict.reasoning,
            ))
            flagged_indices.add(global_idx)

    # ------------------------------------------------------------------
    # Stutter detection — word-level trims within sentences
    # ------------------------------------------------------------------
    stutter_indices = detect_stutters(sentences)
    unflagged_stutters = [i for i in stutter_indices if i not in flagged_indices]

    if unflagged_stutters:
        stutter_verdicts = verify_stutters_with_gemini(
            sentences,
            unflagged_stutters,
            llm_config=llm_config,
        )
        for idx, verdict in stutter_verdicts:
            if not verdict.is_stutter or idx in flagged_indices:
                continue
            if not verdict.word_indices_to_cut:
                continue

            sentence = sentences[idx]
            valid_indices = [
                wi for wi in verdict.word_indices_to_cut
                if 0 <= wi < len(sentence.words)
            ]
            if not valid_indices:
                continue

            trims: list[WordTrim] = []
            sorted_wi = sorted(valid_indices)

            run_start = sorted_wi[0]
            run_end = sorted_wi[0]
            for wi in sorted_wi[1:]:
                if wi == run_end + 1:
                    run_end = wi
                else:
                    trims.append(WordTrim(
                        start=sentence.words[run_start].start,
                        end=sentence.words[run_end].end,
                    ))
                    run_start = wi
                    run_end = wi
            trims.append(WordTrim(
                start=sentence.words[run_start].start,
                end=sentence.words[run_end].end,
            ))

            flags.append(DuplicateFlag(
                idx=idx,
                reason=FlagReason.STUTTER,
                confidence=verdict.confidence,
                note=verdict.reasoning,
                word_trims=trims,
            ))

            trim_dur = sum(t.end - t.start for t in trims)
            logger.info(
                "Stutter word-trim: sentence {} — {} trims, {:.1f}s cut",
                idx, len(trims), trim_dur,
            )

    # ------------------------------------------------------------------
    # Fragment detection — hybrid (rule pre-filter + Gemini confirmation)
    # ------------------------------------------------------------------
    fragment_candidates = detect_fragment_candidates(sentences, flagged_indices)
    if fragment_candidates:
        logger.info("Fragment detection: {} candidates found", len(fragment_candidates))
        verdicts = verify_fragments_with_gemini(
            fragment_candidates,
            sentences,
            llm_config=llm_config,
        )
        for v in verdicts:
            if v.should_cut and v.confidence >= 0.8 and v.sentence_index not in flagged_indices:
                flags.append(DuplicateFlag(
                    idx=v.sentence_index,
                    reason=FlagReason.FILLER,
                    confidence=v.confidence,
                    note=f"Fragment: {v.reasoning}",
                ))
                flagged_indices.add(v.sentence_index)
                logger.info(
                    "Fragment confirmed: sentence {} (confidence={:.0%})",
                    v.sentence_index, v.confidence,
                )

    flags.sort(key=lambda f: f.idx)

    stutter_count = sum(1 for f in flags if f.reason == FlagReason.STUTTER)
    filler_count = sum(1 for f in flags if f.reason == FlagReason.FILLER)
    logger.info(
        "Duplicate detection complete: {} flags "
        "({} duplicate, {} false-start, {} stutter, {} filler)",
        len(flags),
        sum(1 for f in flags if f.reason == FlagReason.DUPLICATE),
        sum(1 for f in flags if f.reason == FlagReason.FALSE_START),
        stutter_count,
        filler_count,
    )

    return flags
