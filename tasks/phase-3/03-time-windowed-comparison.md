# Time-Windowed Comparison

Status: `done`
Phase: 3
Depends on: 3.01, 3.02

## Objective

Build a bounded comparison framework that only evaluates temporally adjacent sentences, preventing false positives from legitimate pedagogical recaps later in the lecture.

## Requirements

- Default lookahead window: **5 sentences**.
- Configurable via `DuplicateDetectionConfig.window_size`.
- Each sentence `i` is compared against sentences `i+1` through `i+window_size`.
- No comparison across distant parts of the lecture.
- Legitimate recaps/summaries (far apart in time) must NOT be flagged.

## Implementation Notes

- This is likely a utility/orchestration layer that both lexical and semantic similarity functions use, rather than a separate algorithm.
- Could be implemented as a generator that yields `(i, j)` pairs to compare, consumed by the similarity functions.
- The window is measured in sentence count, not time — simpler and more predictable.

## Acceptance Criteria

- [x] Window size configurable (default 5) via `DuplicateDetectionConfig.window_size`
- [x] Each sentence compared only against next N sentences
- [x] No comparison across distant parts of the lecture
- [x] Legitimate recaps/summaries not flagged as duplicates
- [x] Works as input constraint for both lexical and semantic tiers (generator pattern)
