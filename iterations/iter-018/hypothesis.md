# Iteration 018 — Hypothesis

**Date:** 2026-07-15
**Fixture set:** 15 error-heavy videos

## Problem

The section editor sometimes labels a complete, useful sentence as a whole-sentence
`false_start`. The clearest example was `test-18`, where a long explanation of the
cylinder-volume formula was cut even though the human editor kept it.

## Hypothesis

If every whole-sentence `false_start` must identify the index of a later completed
version, the system will reject unsupported false-start claims and reduce harmful
overcuts.

Partial false starts and stutters would remain unchanged because their completed
version can occur later within the same sentence.

## Change Plan

- Extend `kept_index` semantics to whole-sentence false starts.
- Add a candidate-only prompt instruction requiring that evidence.
- Reject a whole-sentence false start when the later index is missing, invalid,
  earlier, or more than 60 seconds away.
- Evaluate against a fresh unchanged-model baseline on the same 15 videos.

## Risk

Real false starts do not always have a clean sentence-level replacement. The rule
may therefore preserve genuine flubs and lower cut recall.

## Expected Outcome

- At least 5% fewer overcut words.
- At least +0.5 percentage points cut precision.
- No more than 1 percentage point recall loss.
- No more than 0.5 percentage points F1 loss.
- Fewer overcut words in `test-18` without material per-video regressions.

## Outcome

**Rejected and reverted.** The candidate completed without pipeline failures,
but cut precision fell from 0.784 to 0.782, recall fell from 0.673 to 0.659,
and F1 fell from 0.724 to 0.715. It saved 13 overcut words while introducing
104 additional missed-cut words. The narrow benefit on `test-18` did not
compensate for regressions elsewhere.
