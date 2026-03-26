# Iteration 008 — Analysis

**Date:** 2026-03-26
**Video:** test-2
**Outcome:** IMPROVED — overall 88.4% → 89.0%

## Scores

| Metric              | iter-007  | iter-008  | Delta     |
|---------------------|-----------|-----------|-----------|
| **Overall**         | 88.4%     | **89.0%** | **+0.6%** |
| **Word F1**         | 96.1%     | 96.3%     | +0.2%     |
| **Word P**          | 95.3%     | 95.9%     | +0.6%     |
| **Word R**          | 96.9%     | 96.7%     | -0.2%     |
| **Sentence F1**     | 88.1%     | 89.2%     | +1.1%     |
| **Temporal**        | 67.4%     | **70.4%** | **+3.0%** |
| **Spectrogram**     | 91.2%     | 90.7%     | -0.5%     |
| **Continuity**      | 95.2%     | 95.0%     | -0.2%     |
| **Extra words**     | 29        | 25        | -4        |
| **Missing words**   | 19        | 20        | +1        |
| **Duration delta**  | +15.6s    | +13.4s    | -2.2s     |

## What happened

### Fragment detection improvement
- 3 candidates (up from 2): s1 "Evo dobro." (KEEP), s19 "A ovaj..." (CUT 95%),
  s32 "Evo, znači, to znači da..." (CUT 100%)
- Successfully caught the trailing filler s32 that was previously missed due to
  max_words=4 being too strict (now 6, plus "..." ending catches longer fragments)

### Gemini temperature=0
- Stutter verdicts remained aggressive: s16 (16/16 words) and s18 (13/13 words)
  still fully trimmed. Temperature=0 did NOT reduce the aggressiveness.
- New: s24 got a 1-word trim ("n") — Gemini interpreted the letter "n" as a false start,
  which subtly changed the transcript ("Evo, n mi" → "Evo, mi")
- s38 trim was slightly different (7 words vs 8 in iter-007) — marginal improvement

### Remaining differences (from diff)
Pipeline still keeps that human cuts:
1. "Taj naš broj..." (10 words, ~7s) — restated content, not catchable by fragments
2. "Evo, ja." (2 words, ~1.2s) — not detected as fragment candidate this run
3. "A ovaj broj...dolazi..." (12 words) — cut by fragment detector? No, still present

Pipeline sentence splits vs human merges (3 instances):
- "...raditi. Pa znači..." vs human's single sentence
- "...potencije. A kako se potencije množe?" vs human's single sentence
- "Evo, ona glasi nekako ovako. Znači a..." vs human's single sentence

## Key insight

temperature=0 did NOT solve the Gemini over-trimming issue. The aggressive full-sentence
trims (s16, s18) are deterministic — Gemini genuinely considers the entire sentence
a stutter/false start. A hard cap on trim percentage may be needed.
