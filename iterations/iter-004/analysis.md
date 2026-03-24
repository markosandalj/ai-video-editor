# Iteration 004 — Analysis

**Date:** 2026-03-24
**Video:** test-2
**Outcome:** IMPROVED — word F1 94.3% → 94.7%, recall 97.7% → 99.8%

## Scores

| Metric              | Value   | Delta vs iter-002 |
|---------------------|---------|--------------------|
| **Word F1**         | 94.7%   | **+0.4%**          |
| **Word P**          | 90.1%   | -1.1%              |
| **Word R**          | 99.8%   | **+2.1%**          |
| **Sentence F1**     | 90.7%   | +1.8%              |
| **Sentence P**      | 83.0%   | -4.8%              |
| **Sentence R**      | 100.0%  | **+7.7%**          |
| **Temporal**        | 42.8%   | -2.4%              |
| **Splices**         | 0/9     | 0                  |
| **Spectrogram**     | 0.9809  | -0.0128            |
| **Continuity**      | 89.6%   | +2.1%              |
| **Overall**         | 84.2%   | +0.0%              |
| **Missing words**   | 1       | **-13**            |
| **Extra words**     | 66      | +9                 |
| Duration delta      | +31.4s  | +11.3s             |

## What Happened

### Bug 1 Fix: Speech rescued from silence gaps
The EDL builder now rescues unflagged sentences that fall inside silence regions.
Sentence 13 ("Taj naš broj...eksponent...ali dolje u razlomku") was correctly rescued.

### Bug 2 Fix: Protected keep-side sentences
The false-start detector now skips sentences that are the `idx_keep` of a confirmed
duplicate pair. Sentence 22 ("Dobro, i ovdje imamo još drugi broj.") is now correctly
kept instead of being wrongly flagged as filler.

## Current Status

- **Recall is near-perfect** (99.8% word, 100% sentence) — we're keeping virtually
  everything the human kept
- **Precision dropped slightly** because the rescued/protected sentences include both
  real content AND stutter that the human trimmed more surgically
- The duration delta (+31.4s) is the main remaining gap — we're keeping 31s more
  content than the human editor

## Remaining Issues

1. **66 extra words** — mostly from intra-sentence stutters (same issue as iter-003)
   that need sub-sentence trimming to fix
2. **+31.4s duration delta** — combination of stutter content and potentially
   unnecessary silence gaps we're still keeping
3. The single missing word ("njih") is likely a transcription-level difference
