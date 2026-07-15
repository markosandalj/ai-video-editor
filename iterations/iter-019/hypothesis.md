# Iteration 019 — Local repeat hints

**Date:** 2026-07-15  
**Status:** Candidates 1–4 failed and reverted; candidate 5 in analysis

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

## Candidate 3 — multi-attempt correction chains

### Problem

Some corrections are spread over two to four sentences. The clean result is a
stitch: keep an early clean prefix, remove an abandoned or repeated middle, and
keep the later completed wording. The current prompt describes one false start
followed by one completion, so Sol often cleans only the obvious short fragment
and misses another repeated clause in the same chain.

The five user-observed spans are represented directly in
`candidate-3-cases.json`: two spans in `engleski25ljeto-esej` and three in
`engleski25ljeto-listening-1` (the previously measured embedded English repeat
is one of them). Every partial case requires the rest of its sentence to remain
kept. The manifest also requires the later standalone English sentence and the
final complete take to remain kept.

### Hypothesis

If the existing prompt explicitly teaches Sol to treat two-to-four connected
attempts as one correction chain and to return only the exact abandoned spans,
it will remove these obvious missed cuts without the hundreds of noisy detector
hints used by candidate 1.

### Single change

Add one compact multi-attempt-chain rule and one synthetic example to
`SECTION_PROMPT`. There is no detector, automatic cut, additional model call,
schema change, EDL change, or bilingual rule in this candidate.

### Candidate-3 gates

Against the same fresh 15-video baseline, candidate 3 must:

- have zero failed sections;
- catch at least four of the five user-observed chain spans;
- preserve every required remainder and both later-take controls;
- catch at least 5/16 total positive repeat cases;
- keep every control the baseline currently keeps (at least 13/17); the four
  pre-existing bilingual-control failures are tracked but are not candidate 3's
  hypothesis;
- improve recall by at least 0.005 and reduce missed-cut words by at least 25;
- lose no more than 0.005 precision, never lower F1, and add no more than ten
  overcut words overall;
- avoid an F1 loss greater than 0.03 or more than ten new overcut words on any
  video.

### Candidate-3 outcome

The run was healthy, and aggregate metrics improved: precision 0.791→0.803,
recall stayed 0.687, F1 rose 0.736→0.741, and overcuts fell by 83 words. But the
specific hypothesis failed. Only two of the five new chain spans passed: the
obsolete Croatian tail in listening sentence [16] and the embedded English copy
in [17]. Both essay spans and the earlier full take [148] remained missed.

The total explicit score rose 1/16→5/16 and controls rose 13/17→14/17, but
`test-13`, `test-46`, and `test-9` exceeded the per-video F1-loss gate;
`test-13` and `test-9` also gained more than ten overcut words. Candidate 3 was
reverted in `2ec1beb`. Its useful result is narrower than its prompt: Sol can
follow an exact adjacent-chain example, but the global rule did not make it find
non-adjacent first takes on its own.

## Candidate 4 — sparse sandwich hints

### Problem

Candidate 3 proved that Sol can perform exact partial trimming after it notices
a chain, but it did not notice [40]→[43] or [148]→[150]. Candidate 1's detector
was too broad: it injected 305 adjacent/within-sentence hints across 71 of 98
videos and perturbed unrelated decisions.

### Hypothesis

If Sol is shown only high-confidence non-adjacent "sandwich" chains—an earlier
take, one or two visibly truncated middle attempts, and a later similar
completion—it will notice the missing first take while leaving sections without
such evidence byte-for-byte prompt-identical to the baseline.

### Single change

Before each existing Sol call, mechanically search only two- or three-sentence
gaps. A hint is eligible when:

- at least one intervening sentence visibly ends in `...`, `-`, or `–`;
- the later take starts no more than ten seconds after the earlier take ends;
- both endpoint sentences contain at least seven words;
- endpoint similarity is either at least 98%, or at least 65% with at least 85%
  similarity across their first four words.

Render the exact earlier, intervening, and later text plus the candidate-3 exact
span instruction only when a section owns an eligible earlier sentence. Sol
still decides every cut. There is no automatic cut, extra model call, output
schema change, EDL change, or hint in an unaffected section.

The measured detector surface is 37 hints across 21/98 fixture videos, compared
with candidate 1's 305 hints across 71/98. On the 15-video cohort it produces 15
hints across eight videos and includes both user-supplied non-adjacent chains.

### Candidate-4 gates

Against the same fresh 15-video baseline, candidate 4 must:

- have zero failed sections;
- cut all three still-missed non-adjacent source spans: essay [40] 3:12, essay
  [43] 0:7, and listening [148] 0:21;
- preserve the required partial-sentence remainders and the final takes [18]
  and [150];
- catch at least 4/16 total positive cases and lose none of the 13 controls the
  baseline keeps;
- improve recall by at least 0.005 and reduce missed-cut words by at least 25;
- lose no more than 0.005 precision, never lower F1, and add no more than ten
  overcut words overall;
- avoid an F1 loss greater than 0.03 or more than ten new overcut words on any
  video.

### Candidate-4 outcome

The sparse detector found both intended relationships, but plain endpoint hints
did not provide enough splice precision. It correctly caused listening [148] to
be cut as a full retake. For the essay chain, Sol cut all of [40], including the
three-word prefix the human kept, and still removed only 4/7 required words
from [43]. The core exact-span gate therefore failed: one of three target spans
passed.

Official aggregate metrics also failed (P 0.791→0.795, R 0.687→0.674, F1
0.736→0.729), with an affected-video regression on
`engleski25ljeto-reading-1`. Two other official per-video regressions occurred
on `engleski25ljeto-reading-5` and `test-9`, even though neither video received
a hint; conversely, other unchanged videos moved strongly upward. This exposes
meaningful Sol run-to-run noise in single-run per-video attribution, but it does
not rescue the failed exact-span hypothesis. Candidate 4 was reverted in
`a9fe4bb`.

## Candidate 5 — exact splice-boundary hints

### Hypothesis

Candidate 4 failed because it exposed whole endpoint sentences and left Sol to
infer the splice. If the deterministic hint supplies the exact candidate spans,
Sol can keep the clean early prefix in essay [40], remove only its abandoned
tail, and remove the entire restarted prefix in [43], while retaining candidate
4's successful full-take handling for listening [148].

### Single change

Retain candidate 4's truncated-middle, ten-second sandwich structure, but emit a
hint only when it can derive an exact boundary:

- endpoint similarity at least 98% → suggest the complete earlier sentence;
- otherwise, the later sentence must contain the same 2–6-word opening phrase
  twice with at most three intervening words, and the earlier sentence must
  share that opening → suggest the earlier tail after the shared phrase and the
  later prefix through the second occurrence.

Each suggestion is shown as exact timestamped-word text. It is advisory; Sol
still returns the deletion and all existing verification/guardrails remain.
There is no automatic cut, extra call, schema change, or EDL change. The dry
scan contracts the surface again to 26 hints across 18/98 videos and nine hints
across five cohort videos.

### Evaluation sequence and gates

First run only `engleski25ljeto-esej` and
`engleski25ljeto-listening-1`. Continue to the full 15-video cohort only if the
micro-pilot:

- completes every section;
- cuts essay [40] 3:12, essay [43] 0:7, and listening [148] 0:21 exactly;
- preserves all required remainders plus listening [150].

If that passes, apply candidate 4's full cohort gates: at least 4/16 positives,
no loss among the 13 baseline-passing controls, recall +0.005, at least 25 fewer
missed-cut words, precision loss no worse than 0.005, no F1 decrease, no more
than ten new aggregate overcuts, and the existing per-video safety limits.
