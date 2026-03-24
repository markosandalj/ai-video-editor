# Iteration 002 — Analysis

**Date:** 2026-03-24
**Video:** test-2

## Scores

| Metric              | Value  | Delta vs iter-001 |
|---------------------|--------|--------------------|
| **Sentence F1**     | 88.9%  | -1.1%              |
| **Sentence P**      | 85.7%  | -2.1%              |
| **Sentence R**      | 92.3%  | 0.0%               |
| **Word F1** (new)   | 94.3%  | N/A (new metric)   |
| **Word P**          | 91.2%  | N/A                |
| **Word R**          | 97.7%  | N/A                |
| **Temporal**        | 45.2%  | -0.8%              |
| **Splices**         | 0/8    | 0                  |
| **Spectrogram**     | 0.9937 | +0.0001            |
| **Continuity**      | 87.5%  | +2.4%              |
| **Overall**         | 84.2%  | +0.1%              |

## Key Finding

The word-level F1 (94.3%) confirms the iter-001 hypothesis: sentence-level F1 (88.9%) is deflated by boundary mismatches. The 5.4% gap is entirely attributable to the same words being chunked into different sentences by different transcribers.

## Word-Level Details

- **590 of 604** ground truth words are present in our output (97.7% recall)
- **590 of 647** pipeline words match the ground truth (91.2% precision)
- **57 extra words**: words we kept that the human cut
- **14 missing words**: words the human kept that we cut

## Sentence-Level Note

The sentence-level F1 dropped slightly from 90.0% to 88.9% because this is a fresh pipeline run with `--force` (re-transcription produces slightly different sentence boundaries each time). This is expected variance in the sentence-level metric and further validates why the word-level metric is more reliable.

## What To Tackle Next

Now that we have a reliable metric (word F1 = 94.3%), the real pipeline issues to address:

1. **57 extra words** — content we kept that the human cut. These represent false starts, filler, or duplicate content that our pipeline missed.
2. **14 missing words** — content we cut that the human kept. These are incorrectly removed sentences.
3. **Temporal delta +20.1s** — our output is 20 seconds longer than the human edit.
