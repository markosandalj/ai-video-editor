# Iteration 005 — Analysis

**Date:** 2026-03-25
**Video:** test-2
**Outcome:** IMPROVED — word F1 94.7% → 97.1% (+2.4%), biggest improvement yet

## Scores

| Metric              | Value   | Delta vs iter-004 |
|---------------------|---------|--------------------|
| **Word F1**         | 97.1%   | **+2.4%**          |
| **Word P**          | 94.5%   | **+4.4%**          |
| **Word R**          | 99.8%   | 0.0%               |
| **Sentence F1**     | 93.8%   | +3.1%              |
| **Sentence P**      | 90.5%   | +7.5%              |
| **Sentence R**      | 97.4%   | -2.6%              |
| **Temporal**        | 45.2%   | +2.4%              |
| **Splices**         | 0/9     | 0                  |
| **Spectrogram**     | 0.9393  | -0.0416            |
| **Continuity**      | 87.0%   | -2.6%              |
| **Overall**         | 84.0%   | -0.2%              |
| **Missing words**   | 1       | 0                  |
| **Extra words**     | 35      | **-31**            |
| Duration delta      | +19.9s  | **-11.5s**         |

## What Happened

Sub-sentence (word-level) stutter trimming was implemented:

1. **Stutter detection** (from iter-003) flagged 4 sentences
2. **Gemini verification** with word-indexed prompts returned specific word indices to cut
3. **Word-level EDL** punched out just the stuttered words from keep spans
4. Two correct trims:
   - Sentence 12: "taj naš broj" (3 words, 0.9s) — first repeated occurrence removed
   - Sentence 19: First 13 words (3.7s) — entire false start removed, clean take kept
5. Two correctly kept:
   - Sentence 25: "isto tako" repeated but used in distinct clauses (intentional)
   - Sentence 39: "na neki broj" used as elaboration (pedagogical)

## Remaining Issues

1. **35 extra words** still present — these are from sentences where the speaker
   didn't strictly repeat an n-gram but said something similarly/unnecessarily
2. **+19.9s duration delta** — still 20s longer than the human edit
3. **Spectrogram similarity dropped** (0.9393 vs 0.9809) — likely due to more splice
   points from word-level cuts creating slightly different audio characteristics
