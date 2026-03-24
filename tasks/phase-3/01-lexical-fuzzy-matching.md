# Lexical Fuzzy Matching

Status: `done`
Phase: 3
Depends on: phase-2 complete

## Objective

Implement Levenshtein-based string similarity to detect near-exact sentence repetitions. This is the fast, cheap first tier in the tiered duplicate detection pipeline.

## Requirements

- Use `rapidfuzz` (C++ backed, 10-100x faster than thefuzz, same API).
- Compute both `fuzz.ratio()` (strict order) and `fuzz.token_sort_ratio()` (order-independent) between sentence pairs.
- Accept a configurable threshold (default TBD during integration with 3.04).
- Input: list of `Sentence` objects (from our transcript models).
- Output: list of `(i, j, score)` tuples where score exceeds the threshold.

## Implementation Notes

- Library: `rapidfuzz` (add to pyproject.toml).
- Operate on `Sentence.text` only — timestamps are not relevant at this tier.
- Filler words ("znači", "evo", "dakle") are common in Croatian lectures. Consider stripping them before comparison to reduce noise, or leave that to the combined scoring layer.
- This tier runs locally, no API calls.

## Acceptance Criteria

- [x] `rapidfuzz` added to dependencies
- [x] Function: `compute_lexical_similarity(sentences, window, threshold) -> list[SimilarityScore]`
- [x] Both `fuzz.ratio` and `fuzz.token_sort_ratio` available
- [x] Only compares within the lookahead window (uses `windowed_pairs` generator)
- [x] Handles filler words and minor transcription variations gracefully
