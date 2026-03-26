# Iteration 009 — Analysis

**Date:** 2026-03-26
**Video:** test-2
**Outcome:** IMPROVED — overall 89.0% → 91.6%

## Scores

| Metric              | iter-008  | iter-009  | Delta     |
|---------------------|-----------|-----------|-----------|
| **Overall**         | 89.0%     | **91.6%** | **+2.6%** |
| **Word F1**         | 96.3%     | 96.3%     | 0.0%      |
| **Word P**          | 95.9%     | 95.0%     | -0.9%     |
| **Word R**          | 96.7%     | 97.7%     | +1.0%     |
| **Sentence F1**     | 89.2%     | **92.9%** | **+3.7%** |
| **Sentence R**      | 94.9%     | **100.0%**| **+5.1%** |
| **Temporal**        | 70.4%     | **76.1%** | **+5.7%** |
| **Spectrogram**     | 90.7%     | 91.6%     | +0.9%     |
| **Continuity**      | 95.0%     | **97.6%** | **+2.6%** |
| **Extra words**     | 25        | 31        | +6        |
| **Missing words**   | 20        | 14        | -6        |
| **Duration delta**  | +13.4s    | +13.6s    | +0.2s     |

## What happened

### Fragment detection fix (per-word punctuation stripping)
The root cause was that `_normalise` only stripped punctuation from string boundaries,
not individual words. "Evo," (with comma) was 4 chars and treated as a content word.

After fix: 4 fragment candidates detected (up from 3):
- s1 "Evo dobro." → KEEP (correct)
- s14 "Evo, ja." → CUT 100% (correct — **new**)
- s20 "A ovaj..." → CUT 100% (correct)
- s33 "Evo, znači, to znači da..." → CUT 100% (correct)

### Stutter detection (this run)
Only 4 stutters (vs 5 in iter-008) — s16 was not flagged this run due to transcription
chunking variance. This improved recall (no full-sentence stutter overcut).

### Key improvements
- **Sentence recall hit 100%** — every ground truth sentence is now matched
- **Temporal score +5.7%** — mean offset dropped from 10.5s to 8.2s
- **Continuity 97.6%** — nearly all sentences flow correctly

### Remaining issues
- "Taj naš broj..." (restated content, ~7s) — still kept
- "A ovaj broj...dolazi..." (stutter-trim remainder, ~4s) — still appears
- 3 sentence merge mismatches
- Extra words increased slightly (31 vs 25) due to transcription variance

## Summary

A one-line bug fix (per-word punctuation stripping) yielded +2.6% overall improvement
by correctly catching "Evo, ja." as a fragment. Combined with favorable stutter detection
variance, this iteration achieved the best overall score yet.
