# Iteration 011 — Hypothesis

## Baseline
- Aggregate score: 89.2% (13 videos)
- Worst: test-10 (80.3%), test-7 (82.5%), test-8 (85.7%)
- Root cause: duplicate detection over-cuts — 7/11 false positives on test-7, ~76 missing words from one cut on test-8

## Root Cause Analysis

Three mechanism failures in duplicate detection:
1. Always keeps later sentence, cuts earlier — but in educational content the first occurrence is often the complete explanation
2. Auto-confirm at lexical≥85 / semantic≥0.90 bypasses Gemini — educational sentences reuse vocabulary
3. Gemini confidence threshold 0.7 is too permissive

## Changes

### Change 1: Keep the longer sentence
When a duplicate pair is confirmed, keep whichever sentence has more words.
The longer version is more likely the complete explanation.
Fallback: if equal length, keep the later (status quo).

### Change 2: Length ratio guard (1.5x)
If one sentence has >1.5x more words than the other, force Gemini verification
even if lexical or semantic auto-confirmed it. This prevents cutting elaborations.

### Change 3: Raise all thresholds
- `lexical_definite`: 85 → 90
- `semantic_definite`: 0.90 → 0.95
- `gemini_confidence_threshold`: 0.70 → 0.80

## Expected Impact
- Fewer false positive duplicate flags → improved word recall
- test-7, test-8, test-10 should see the biggest gains
- Risk: some actual duplicates might not be caught → slight precision decrease
