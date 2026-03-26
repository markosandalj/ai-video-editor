# Iteration 006 — Analysis

**Date:** 2026-03-26
**Video:** test-2
**Outcome:** REGRESSED — word F1 97.1% → 96.3%, recall 99.8% → 98.8%

## Scores

| Metric              | Value   | Delta vs iter-005 |
|---------------------|---------|--------------------|
| **Word F1**         | 96.3%   | **-0.8%**          |
| **Word P**          | 93.9%   | -0.6%              |
| **Word R**          | 98.8%   | **-1.0%**          |
| **Sentence F1**     | 90.2%   | -3.6%              |
| **Temporal**        | 45.6%   | +0.4%              |
| **Spectrogram**     | 0.8150  | **-0.1243 FAILED** |
| **Overall**         | 82.5%   | **-1.5%**          |
| **Missing words**   | 7       | **+6**             |
| **Extra words**     | 39      | +4                 |

## What Happened

The holistic Gemini review flagged 7 sentences, 4 passed the safety gates and were cut.
However:

1. **Sentences cut contained real content** — sentence 1 ("Evo dobro.") was part of the
   opening that the human kept. Missing words went from 1 to 7.
2. **Extra words paradoxically increased** from 35 to 39 — the cuts didn't actually
   remove the problematic extra content, and re-transcription picked up new differences.
3. **Spectrogram failed** — more splice points from additional cuts degraded audio
   similarity below the 0.85 threshold.

## Root Cause

The algorithmic backup checks (`is_content_subset`, `is_trailing_filler`) are too
permissive. Short sentences like "Evo dobro." pass `is_trailing_filler` even though the
human kept them. The `is_content_subset` check matches partial content in neighbors too
aggressively.

## Action

Disabled holistic review from pipeline. Code preserved for future refinement.
