# Iteration 008 — Hypothesis

## Problem

Two issues from iter-007:

1. **Fragment detection too narrow** (max_words=4): misses "Evo, ja." (2 words, not
   ending in "..."), "Evo, znači, to znači da..." (5 words, over limit), and
   "A ovaj broj...dolazi..." (12 words ending in "..." but too long).
2. **Gemini stutter non-determinism**: temperature=0.1 causes variable stutter verdicts
   between runs, sometimes trimming entire sentences (19 missing words in iter-007).

## Hypothesis

### Fix 1: Broaden fragment detection
- Raise `max_words` from 4 to 6 for `is_incomplete_fragment`
- Add a separate check: any sentence ending in "..." or "…" with ≤15 words is a candidate
  (regardless of content), sent to Gemini for confirmation
- This should catch all 4 remaining fragment/filler sentences

### Fix 2: Gemini temperature=0
- Set temperature=0 in `_get_llm()` for all Gemini calls
- This should stabilize stutter verdicts and reduce the 19 missing words

## Expected Outcome

- Extra words: 29 → ~15 (cutting 3-4 more fragments)
- Missing words: 19 → ~5 (stabilized Gemini trims)
- Word F1: 96.1% → ~97-98%
- Overall: 88.4% → ~89-90%
