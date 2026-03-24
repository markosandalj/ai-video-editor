# Iteration 003 — Analysis

**Date:** 2026-03-24
**Video:** test-2
**Outcome:** REGRESSED — reverted

## Scores

| Metric              | Value  | Delta vs iter-002 |
|---------------------|--------|--------------------|
| **Word F1**         | 92.4%  | **-1.9%**          |
| **Word P**          | 97.8%  | **+6.6%**          |
| **Word R**          | 87.6%  | **-10.1%**         |
| **Sentence F1**     | 90.0%  | +1.1%              |
| **Temporal**        | 45.8%  | +0.6%              |
| **Splices**         | 0/7    | 0                  |
| **Spectrogram**     | 0.9922 | -0.0015            |
| **Continuity**      | 90.7%  | +3.2%              |
| **Overall**         | 85.1%  | +0.9%              |

## What Happened

The stutter detection correctly identified 5 sentences with repeated n-grams. Gemini correctly confirmed 3 as stutters and kept 2 (intentional pedagogical repetition). However, **cutting entire sentences that contain stutters also removed the actual content within those sentences**.

For example, the sentence "A ovaj tu, a ovaj tu broj koji je ovdje sada predstavljen slovom n, on mi dolazi..." contains both:
- The stutter: "a ovaj tu, a ovaj tu"
- The actual content: "broj koji je ovdje sada predstavljen slovom n, on mi dolazi"

Cutting the whole sentence removed the content the human editor kept (by trimming only the stutter part).

## Root Cause

The approach of cutting **entire sentences** is too aggressive when the stutter is intra-sentence. The correct approach would be to trim the stuttered portion and keep the rest, but that requires sub-sentence editing which our current pipeline doesn't support at the word/time level.

## Lesson Learned

Intra-sentence stutter removal needs sub-sentence precision (trim the repeated words, keep the rest) rather than whole-sentence cutting. This is a more complex change that requires word-level EDL support.

## Action

Kept stutter detection code (`stutter.py`, `verify_stutters_with_gemini`) but disabled
it from `pipeline.py`. The detection and Gemini verification modules remain available for
re-enablement once sub-sentence trimming is implemented in a future iteration.
