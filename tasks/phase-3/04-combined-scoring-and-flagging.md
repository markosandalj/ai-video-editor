# Combined Scoring & Flagging

Status: `done`
Phase: 3
Depends on: 3.03, 3.05 (Gemini verification)

## Objective

Merge lexical, semantic, and Gemini verification results into a final decision: which sentences to cut and which to keep.

## Requirements

- **Tiered approach** (not weighted average):
  1. **Tier 1 — Lexical (fast filter):** rapidfuzz ratio/token_sort_ratio. Pairs above a high threshold (e.g., 85+) are immediately flagged as duplicates.
  2. **Tier 2 — Semantic (medium filter):** Cosine similarity on multilingual embeddings. Pairs above threshold that weren't caught by Tier 1.
  3. **Tier 3 — Gemini (borderline judge):** Only pairs that score above a lower "maybe" threshold but below the "definite" threshold are sent to Gemini for verification.
- **Keep rule:** Always keep the **later** take (the correction). The earlier take is marked for deletion.
- **False starts:** Everything between a flagged duplicate pair (mistake → correction) is sent to Gemini to decide what's filler vs. real content. Filler is also marked for deletion.
- Configurable thresholds for all tiers.

## Implementation Notes

- Thresholds need tuning with real data. Start with sensible defaults, expose in `DuplicateDetectionConfig`.
- The false-start detection block: extract sentences between indices `i` and `j` (the duplicate pair), send to Gemini with context, ask "which of these are filler/false starts?"
- Output: list of sentence indices marked for deletion, with reasons (duplicate, false_start, filler).

## Acceptance Criteria

- [x] Tiered evaluation: lexical → semantic → Gemini (`pipeline.detect_duplicates`)
- [x] Gemini only called on borderline cases (saves API cost)
- [x] Earlier sentence in a duplicate pair always marked for deletion
- [x] False starts between duplicate pairs identified via Gemini
- [x] Configurable thresholds for all three tiers (`DuplicateDetectionConfig`)
- [x] Output: list of `DuplicateFlag` objects with action and reason
