# Iteration 019 — Local repeat hints

**Date:** 2026-07-15  
**Status:** Failed and reverted

## Problem

The section editor misses obvious local corrections where a speaker says a
clause, then immediately says a cleaner version. The fresh 15-video baseline
cuts only 2 of 12 explicitly sourced positive cases, while safely keeping all
10 intentional-repeat controls.

Baseline: precision 0.791, recall 0.687, F1 0.736, 1,158 overcut words,
1,992 missed-cut words, and 0/29 failed sections.

## Hypothesis

If the existing prompt explicitly shows Sol a small set of mechanically found
local repetitions, Sol will notice and remove more abandoned earlier takes
without treating normal teaching repetition as an automatic cut.

The hints will cover only:

- adjacent-sentence suffix/prefix matches of at least 85%, at least three
  words, and separated by at least one second;
- strong 2–6 word restarts after a comma or a truncated word inside one
  sentence.

Each hint will quote the exact earlier and later timestamped word spans. It is
advisory context only. The prompt will explicitly preserve explanations,
translations, comparisons, and emphasis. Sol remains the only decision-maker;
there are no automatic cuts, extra model calls, schema changes, or relaxed
guardrails.

## Expected result

On the same 15-video cohort, the candidate must:

- finish with zero failed sections;
- cut all four user-confirmed earlier spans while preserving the rest of each
  sentence;
- cut at least 9 of 12 positive repeat cases;
- add no cuts to the ten intentional-repeat controls;
- improve recall by at least 0.005 and reduce missed cuts by at least 25 words;
- lose no more than 0.005 precision, never reduce F1, and add at most ten
  overcut words;
- avoid an F1 loss greater than 0.03 on any video.

Only a cohort winner proceeds to all 98 fixtures. A failure is reverted; the
repeat-case measurement remains.

## Main risk

Educational speech repeats words deliberately. A broad detector would place
too many misleading hints in the prompt and could turn useful explanations or
comparisons into cuts. Conservative detection and explicit negative
instructions are therefore part of the single prompt-context change.

## Outcome

The model and pipeline were healthy, but the hypothesis failed its quality
gates. Positive repeat cases improved only from 2/12 to 5/12, and only two of
the four user-confirmed spans were cut. Recall fell from 0.687 to 0.678, missed
cuts increased by 63 words, and F1 fell from 0.736 to 0.733. `test-9` and
`test-47` each lost more than three F1 points.

All ten intentional-repeat controls remained kept, so the hints were not
recklessly aggressive. The problem was that they did not reliably turn into
the exact partial cuts we needed. The production prompt change was reverted in
commit `8739e51`; repeat-case scoring and the iteration artifacts remain.
