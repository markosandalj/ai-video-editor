# Iteration 018 — Analysis

**Date:** 2026-07-15  
**Fixture set:** 15 error-heavy videos  
**Model:** `gpt-5.6-sol`

## Scores

| Run | Cut precision | Cut recall | Cut F1 | True cut words | Overcut words | Missed-cut words | Failed sections |
|---|---:|---:|---:|---:|---:|---:|---:|
| Unchanged baseline | 0.784 | 0.673 | 0.724 | 5,008 | 1,378 | 2,436 | 0/34 |
| False-start evidence candidate | 0.782 | 0.659 | 0.715 | 4,904 | 1,365 | 2,540 | 0/34 |
| Delta | -0.002 | -0.014 | -0.009 | -104 | -13 | +104 | — |

The pipeline completed successfully. The hypothesis failed its promotion gate:
the rule saved only 13 overcut words while causing 104 additional missed cuts.

## False positives: pipeline kept, human cut

Representative missed cuts after the candidate became more conservative:

- `engleski25ljeto-reading-1`: “Moramo se sjetiti našeg pitanja...” and other
  genuine abandoned/repeated attempts were retained.
- `engleski25ljeto-listening-1`: valid false starts lost their cuts when there
  was no clean sentence-level replacement index.
- `test-45`: repeated intermediate calculation statements remained even though
  the human edit removed them.

The candidate produced 2,540 missed-cut words, 104 more than the baseline.

## False negatives: pipeline cut, human kept

Representative overcuts that remained:

- `test-18`: “I sada kako se radi o nekakvom volumenu tog našeg valjka...”
- `engleski25ljeto-reading-2`: a 47-word explanation about crop circles.
- `engleski25ljeto-reading-1`: a 36-word explanation quoting Francis.
- `engleski25ljeto-listening-1`: a 29-word explanation of the answer cue.

The candidate reduced overcuts from 1,378 to 1,365, far below the required 5%.

## Patterns

- A real false start does not always have a clean later sentence that can be
  referenced by `kept_index`; its completion can be partial, distributed, or
  implicit.
- The broad evidence requirement blocked many correct cuts, not just unsafe
  whole-sentence cuts.
- It helped `test-18` by 14 overcut words, but caused material regressions in
  `engleski25ljeto-listening-1`, `engleski25ljeto-reading-5`, and `test-45`.
- The successful provenance/tracing changes exposed the failure accurately and
  are retained. The behavior change itself was reverted.

## Decision

**REVERTED.** Commit `e10afca` was reverted by `90f4fb3`. The full 98-video
candidate run was correctly not started.
