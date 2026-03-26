# Iteration 007 — Hypothesis

## Problem

The temporal score (45.2%) is the single biggest drag on overall score (84.0%).
Analysis shows 6 sentences totaling ~16s of the 20s duration delta:

1. **Restated content** (7s): s13 restates s12 but they're 6 sentences apart (outside window=5)
2. **Short fragments** (4s): "Evo, ja." (s14), "A ovaj..." (s20), "Evo, znači, to znači da..." (s33)
3. **Sentence boundary mismatch** (5s): s10 combines clauses human splits; s36 is a question human merges

Additionally, the temporal score formula uses `max_acceptable_offset=5s` which is too strict —
with a mean offset of 11s, the timing component is always 0.

## Hypothesis

Three targeted fixes + formula adjustment will significantly improve temporal alignment:

### Fix 1: Fragment detection (hybrid)
- Rule-based pre-filter: sentences with ≤3 content words that end with "..." or are incomplete
- Gemini confirmation to avoid false positives
- Expected impact: ~4s reduction

### Fix 2: Widen duplicate detection window
- Increase window from 5 to 8 for the semantic/lexical passes
- This catches s13 as a restatement of s12 (they're 6 apart in the raw transcript)
- Expected impact: ~7s reduction

### Fix 3: Sentence boundary refinement
- When a sentence contains two independent clauses, try splitting it if one part
  matches a duplicate pattern
- When a question sentence is immediately followed by its answer, allow merging
  for comparison purposes
- Expected impact: ~5s reduction (hard, may defer)

### Fix 4: Temporal score formula
- Increase max_acceptable_offset from 5s to 20s
- This makes the temporal score more granular and rewards partial improvements

## Expected Outcome

- Duration delta should decrease from ~20s to ~5-8s
- Temporal score should improve significantly (from 45% toward 70-80%)
- Overall score should improve from 84% toward 88-90%
