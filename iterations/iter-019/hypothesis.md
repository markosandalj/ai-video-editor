# Iteration 019 — Local repeat hints

**Date:** 2026-07-15  
**Status:** Ready to test

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
