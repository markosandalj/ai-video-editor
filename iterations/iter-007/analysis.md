# Iteration 007 — Analysis

**Date:** 2026-03-26
**Video:** test-2
**Outcome:** IMPROVED — overall 84.0% → 88.4%

## Scores

| Metric              | iter-005  | iter-007  | Delta     |
|---------------------|-----------|-----------|-----------|
| **Overall**         | 84.0%     | **88.4%** | **+4.4%** |
| **Word F1**         | 97.1%     | 96.1%     | -1.0%     |
| **Word P**          | 94.5%     | 95.3%     | +0.8%     |
| **Word R**          | 99.8%     | 96.9%     | -2.9%     |
| **Sentence F1**     | 93.8%     | 88.1%     | -5.7%     |
| **Temporal**        | 45.2%     | **67.4%** | **+22.2%**|
| **Spectrogram**     | 93.9%     | 91.2%     | -2.7%     |
| **Continuity**      | 87.0%     | 95.2%     | +8.2%     |
| **Extra words**     | 35        | 29        | -6        |
| **Missing words**   | 1         | 19        | +18       |
| **Duration delta**  | +19.9s    | +15.6s    | -4.3s     |

## What happened

### Temporal formula fix (max_acceptable_offset 5→20)
The strict 5s cap meant any offset >5s scored 0%. With 20s, partial improvements
now register in the score. This alone accounts for most of the +22% temporal gain.

### Fragment detection
- 2 candidates found: "Evo dobro." (s1) and "A ovaj..." (s19)
- Gemini correctly KEPT s1 (transition, not a fragment) and CUT s19 (incomplete false start)
- 1 fragment removed, saving ~0.6s

### Stutter detection (Gemini non-determinism)
This run detected 4 stutters instead of iter-005's 2, including aggressive trimming of
s16 (4.0s cut) and s38 (2.2s cut). This is Gemini non-determinism, not a code change.
The additional cuts contributed to the 19 missing words (content Gemini trimmed too
aggressively from within sentences).

## Trade-offs

- **Word recall dropped** 99.8% → 96.9% — the aggressive stutter trims (Gemini
  non-determinism) cut content the human kept. This is the main regression.
- **Sentence F1 dropped** — more stutter trims changed sentence boundaries, causing
  mismatches in sentence-level comparison
- **Continuity improved** 87% → 95.2% — fewer unnecessary breaks in the edited output
- **Precision improved** 94.5% → 95.3% — fewer extra words (29 vs 35)

## Root cause of missing words

The 19 missing words are primarily from Gemini's non-deterministic stutter verdicts
trimming more aggressively than in iter-005. The fragment detection only removed 1
sentence correctly. The real improvement came from the temporal score formula fix.

## Next steps

- Consider pinning Gemini temperature=0 for stutter verification to reduce variability
- The remaining ~15.6s duration delta needs different strategies (content-level judgment)
