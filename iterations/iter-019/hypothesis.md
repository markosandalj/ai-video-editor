# Iteration 019 — Local repeat hints

**Date:** 2026-07-15  
**Status:** Candidates 1 and 2 failed and reverted; candidate 3 in analysis

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
gates. The initial permissive span check reported 2/12→5/12. After requiring
every non-target word in a partial sentence to remain kept, the truthful result
is 1/12→4/12. Only two of
the four user-confirmed spans were cut. Recall fell from 0.687 to 0.678, missed
cuts increased by 63 words, and F1 fell from 0.736 to 0.733. `test-9` and
`test-47` each lost more than three F1 points.

All ten intentional-repeat controls remained kept, so the hints were not
recklessly aggressive. The problem was that they did not reliably turn into
the exact partial cuts we needed. The production prompt change was reverted in
commit `8739e51`; repeat-case scoring and the iteration artifacts remain.

## Candidate 2 — Bilingual teaching-content protection

### Problem

On English lessons, Sol can interpret an English source phrase and its Croatian
translation or explanation as redundant versions of the same thought. The old
98-video EDL therefore cuts the Croatian explanation “Dakle, bila je
razočarana zbog nezahvalnih poslova” after the equivalent English sentence.
The human edit keeps both because they perform different teaching jobs.

The fresh baseline is model-variable: it keeps that exact user case, but fails
four other explicit bilingual keep spans. Across the corrected candidate-2
manifest it passes only 11/15 keep controls.

### Hypothesis

If the existing section-editor prompt states that English source text and its
Croatian translation or explanation are never duplicates merely because they
share meaning, Sol will preserve bilingual teaching content more consistently
without protecting genuine same-language retakes.

### Change plan

Add one rule to `SECTION_PROMPT`:

- keep both an English source/citation and its Croatian
  translation/explanation;
- allow deletion only for an independently broken, abandoned, or stuttered
  attempt—not because another language conveys the same meaning.

There are no detector, schema, model, guardrail, or EDL changes.

### Risk

The rule may be interpreted too broadly and protect genuinely abandoned mixed-
language attempts. That would reduce recall and increase missed-cut words.

### Candidate-2 gates

Against the same fresh 15-video baseline, candidate 2 must:

- finish with zero failed sections;
- keep the user-confirmed Croatian translation and at least 14/15 combined
  keep controls;
- rescue at least three of the four bilingual controls the baseline overcuts;
- improve precision by at least 0.005;
- reduce overcut words by at least 25;
- lose no more than 0.005 recall and add no more than ten missed-cut words;
- never reduce F1;
- avoid an F1 loss greater than 0.03 or more than ten new overcut words on any
  video.

### Candidate-2 outcome

The prompt rule did not rescue any of the four baseline-failing bilingual
controls: the keep score stayed 11/15. The traces show why. Sol continued to
classify those sentences as independently broken or abandoned attempts, which
the rule explicitly still allowed it to cut. The exact user-confirmed
English→Croatian example remained kept, but it was already kept by the fresh
baseline because the `redundant` guardrail rejected that proposal.

Aggregate precision was unchanged within noise (0.791→0.790), recall fell
0.687→0.682, F1 fell 0.736→0.732, and missed cuts increased by 34 words.
`engleski25ljeto-listening-1` and `test-9` exceeded the per-video F1-loss gate.
Candidate 2 was reverted in `71b5ce5`. The bilingual rule is still a valid
domain statement, but a global prompt addition did not produce a measurable,
safe improvement.
