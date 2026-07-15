# Iteration 019 — Analysis

**Date:** 2026-07-15  
**Reference:** 98-video `gpt-5.6-sol` section-editor run

## Scores

| Cut precision | Cut recall | Cut F1 | True cut words | Overcut words | Missed-cut words | Failed sections |
|---:|---:|---:|---:|---:|---:|
| 0.797 | 0.674 | 0.730 | 10,687 | 2,726 | 5,166 | 0/120 |

## Fresh 15-video baseline

The unchanged section editor completed all 29 sections without retries or
fallbacks:

| Cut precision | Cut recall | Cut F1 | True cut words | Overcut words | Missed-cut words | Failed sections |
|---:|---:|---:|---:|---:|---:|---:|
| 0.791 | 0.687 | 0.736 | 4,382 | 1,158 | 1,992 | 0/29 |

It cuts only 2 of the 12 explicit positive repeat cases. One is the truncated
“Koja se nala-” restart and the other is a full repeat in `test-13`. It leaves
all ten intentional-repeat controls untouched. This gives iteration 19 a clean,
reproducible starting point and confirms that the target is mostly still
missing from the current model output.

## False negatives: pipeline kept, human cut

The user identified four source-timeline misses in `test-10` and `test-11`:

1. An eleven-word suffix repeated as the next sentence.
2. “Koja se nala-” before “koja se nalazi”.
3. A ten-word clause repeated more cleanly as the next sentence.
4. “i smjela je primiti” before “i smjeli smo primiti”.

A full-corpus scan found ten especially strong adjacent-sentence repetitions
that the current EDL leaves untouched. Beyond the two user examples, they occur
in `test-1`, `test-9`, `test-13`, `test-40`, `test-41`,
`engleski25ljeto-listening-1`, and twice in
`engleski25ljeto-listening-2`.

Clear within-sentence misses also include:

- “odgovor nam leži..., odgovor nam leži...”
- “i pogledajmo opciju pod B, i pogledajmo opciju pod B”
- “U formulama nam, u formulama nam...”

## False positives: pipeline cut, human kept

Local word repetition is not automatically an editing error. The corpus also
contains many intentional repetitions used for:

- vocabulary definitions and translations;
- mathematical comparison and substitution;
- emphasis and parallel sentence structure;
- quoting a phrase and then explaining it.

The old exact 2/3-gram detector finds 1,594 spans but has only about 30% raw
word precision against the human transcript. Reactivating it as an automatic
cutter would therefore be unsafe.

## Patterns

- The strongest adjacent misses share a long suffix/prefix match and a pause of
  at least one second. In the current 98-video artifacts, all ten candidates at
  90% similarity or higher correspond to content the human edit deduplicated.
- Truncated immediate restarts are also strong evidence. The section editor
  already catches most of them but still misses small examples such as
  “Koja se nala-”.
- Fuzzy within-sentence repetition alone is not safe enough to auto-cut because
  intentional teaching language looks mechanically similar.
- Saved outputs from several model families all missed the adjacent partial
  clause pattern. Some models caught individual within-sentence examples, so
  attention is part of the problem.
- Transcript alignment cannot reliably identify which of two identical copies
  the human retained. Explicit source-word spans are required to evaluate the
  agreed keep-later policy.

## Candidate result

The local-repeat hints were tested on the identical 15-video cohort. All 29
sections completed without retries or fallbacks.

| Run | Cut precision | Cut recall | Cut F1 | True cut words | Overcut words | Missed-cut words | Positive cases | Controls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 0.791 | 0.687 | 0.736 | 4,382 | 1,158 | 1,992 | 1/12 | 10/10 |
| Candidate | 0.799 | 0.678 | 0.733 | 4,319 | 1,087 | 2,055 | 4/12 | 10/10 |
| Change | +0.008 | -0.009 | -0.003 | -63 | -71 | +63 | +3 | 0 |

### Promotion gates

| Gate | Required | Result | Verdict |
|---|---:|---:|---|
| Failed sections | 0 | 0/29 | pass |
| Four user-confirmed spans | 4/4 | 2/4 | **fail** |
| Positive repeat cases | at least 9/12 | 4/12 | **fail** |
| Intentional-repeat controls | 10/10 kept | 10/10 | pass |
| Recall change | at least +0.005 | -0.009 | **fail** |
| Missed-cut words | at least 25 fewer | 63 more | **fail** |
| Precision change | no worse than -0.005 | +0.008 | pass |
| F1 change | no decrease | -0.003 | **fail** |
| Overcut words | no more than 10 extra | 71 fewer | pass |
| Worst per-video F1 loss | no more than 0.030 | `test-9` -0.058; `test-47` -0.032 | **fail** |

The generic safety comparison also failed because `engleski25ljeto-esej` and
`engleski25ljeto-listening-1` gained more than ten overcut words.

## Representative findings

- The hints helped the exact grammatical correction in `test-11` and raised
  the explicit positive-case score by three cases.
- The two long user-confirmed repeats in `test-10` still remained uncut. Sol
  saw the matching spans but did not consistently emit the desired partial
  deletion.
- For `test-40`, the hint used exact timestamped words (`Od tud`), but Sol
  rewrote the proposal as the prettified transcript text (`Odtud`). Existing
  verification correctly rejected the unverifiable span.
- `test-9` exposed a policy mismatch: Sol proposed the short repeated sentence,
  but the existing short-interjection guardrail protected it. The guardrail was
  intentionally out of scope for this iteration.
- The hints reduced overcuts overall, but changed broader model judgment enough
  to lose 63 true cut words. Prompting the model to pay attention to repeats did
  not isolate the change to repeat decisions.

## Conclusion

The mechanical detector was useful as measurement—it found all 12 explicit
positive spans and produced only about 305 hints across the 98 transcripts,
far fewer than the old 1,594-span bigram detector. But advisory prompt hints
were not a reliable actuator: Sol caught only 4/12 with correct partial-span
validation, and overall recall worsened.

Candidate 1 therefore failed. The 98-video candidate run was skipped, the
single production change was reverted in `8739e51`, and the repeat-case
manifest/scorer were retained. Iteration 19 remains open for isolated follow-up
candidates.

## Candidate-2 analysis: bilingual protection

The user's new example exposed a distinct overcut category. The old full-98 EDL
cuts this Croatian explanation immediately after its English source:

> Dakle, bila je razočarana zbog nezahvalnih poslova

The human edit keeps both languages. The English statement supplies the source
material; Croatian makes it understandable to the learner. Semantic equivalence
is therefore not evidence of a retake.

This exact cut is unstable: the fresh baseline keeps it because Sol labels it
`redundant` and the existing protected-type guardrail rejects the proposal.
However, four other human-kept bilingual spans are cut in that same baseline:

- `engleski25ljeto-listening-2[14]`: English source before a corrected Croatian
  explanation (14 overcut words);
- `engleski25ljeto-reading-1[109]`: Croatian framing plus an English teaching
  phrase (15 overcut words);
- `engleski25ljeto-reading-1[157]`: English phrase explained in Croatian (9
  overcut words);
- `engleski25ljeto-reading-5[64]`: Croatian translation framing after an
  English source (5 overcut words).

The new candidate-2 manifest fixes a measurement weakness discovered in
candidate 1: every partial positive now requires the sentence remainder to stay
kept. On the unchanged baseline it scores 1/12 positive repeats and 11/15 keep
controls. Candidate 2 will change only the prompt's bilingual-content rule and
must rescue at least three of the four failing bilingual controls without
materially lowering recall.

## Candidate-2 result

| Run | Cut precision | Cut recall | Cut F1 | True cut words | Overcut words | Missed-cut words | Keep controls |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 0.791 | 0.687 | 0.736 | 4,382 | 1,158 | 1,992 | 11/15 |
| Candidate 2 | 0.790 | 0.682 | 0.732 | 4,348 | 1,157 | 2,026 | 11/15 |
| Change | -0.001 | -0.005 | -0.004 | -34 | -1 | +34 | 0 |

The run was healthy: 0/29 sections failed, one structured-output retry
succeeded, and no direct fallback was needed.

### Failed gates

- No bilingual control was rescued; the required result was at least three.
- Precision did not improve by 0.005.
- Overcuts decreased by only one word, not 25.
- Missed cuts increased by 34 words, exceeding the +10 limit.
- F1 decreased by 0.004.
- `engleski25ljeto-listening-1` lost 0.033 F1 and `test-9` lost 0.039.
- `engleski25ljeto-esej`, `engleski25ljeto-listening-1`, and `test-9`
  each gained more than ten overcut words.

The four failing traces remained cuts because Sol interpreted them as broken
attempts, not as deletion solely due to cross-language equivalence. The prompt
rule therefore did not constrain the decisions that caused those measured
overcuts. Candidate 2 was reverted in `71b5ce5`; its artifacts remain under
`output/qa-iteration-19/candidate-2-15`.

## Candidate-3 measurement

The new examples are correction chains rather than simple adjacent repeats:

- `engleski25ljeto-esej` [40–43] keeps the first three words from [40], drops
  its abandoned completion and two intervening fragments, then keeps [43] only
  after its doubled seven-word start;
- `engleski25ljeto-listening-1` [16–18] keeps the first six words from [16],
  drops its obsolete explanation, keeps the Croatian portion of [17], drops
  the embedded English copy, and keeps the standalone English sentence [18];
- `engleski25ljeto-listening-1` [148–150] drops the first full take and the
  intervening false start, then keeps the final complete take.

This explains why candidate 1's adjacent suffix/prefix hints were insufficient.
It also sharpens the required granularity: cutting a whole mixed sentence is a
failure even if it removes the target words.

On the unchanged baseline, the expanded manifest scores 1/16 positive spans and
13/17 keep controls. None of the five user-observed chain spans passes. The two
new later-take controls ([18] and [150]) are already kept. Candidate 3 therefore
must add at least four exact chain-span successes without losing any of the 13
baseline-passing controls; it is not expected to solve candidate 2's four
pre-existing bilingual failures.

## Candidate-3 result

| Run | Cut precision | Cut recall | Cut F1 | True cut words | Overcut words | Missed-cut words | Explicit positives | Keep controls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 0.791 | 0.687 | 0.736 | 4,382 | 1,158 | 1,992 | 1/16 | 13/17 |
| Candidate 3 | 0.803 | 0.687 | 0.741 | 4,381 | 1,075 | 1,993 | 5/16 | 14/17 |
| Change | +0.012 | 0.000 | +0.005 | -1 | -83 | +1 | +4 | +1 |

All 29 sections completed without retries or fallbacks. The candidate nevertheless
failed its core gate: only two of five newly supplied chain spans passed, not
four. The traces are decisive:

- listening [16] and [17] were proposed as exact partial retakes and accepted;
- listening [148] was never proposed; Sol only removed the obvious intervening
  false start [149];
- essay [40] was never proposed;
- essay [43] received only the same four-word stutter trim as the baseline,
  leaving three more repeated words uncut.

It also failed per-video safety: `test-13` lost 0.047 F1 and gained 14 overcut
words, `test-46` lost 0.062 F1, and `test-9` lost 0.066 F1 and gained 13 overcut
words. Candidate 3 was reverted in `2ec1beb`; artifacts remain under
`output/qa-iteration-19/candidate-3-15`.

The next candidate stays inside iteration 19 but must be localized. A global
instruction can teach exact trimming once Sol notices a chain, yet it does not
make Sol discover the non-adjacent [40]→[43] or [148]→[150] relationship. The
next analysis therefore tests whether a very sparse two-to-three-sentence
"sandwich" hint can expose only those chains without reintroducing candidate
1's 305 broad repeat hints.

## Candidate-4 detector analysis

A fixture-wide dry scan found a useful structural separator. Requiring a
visibly truncated intervening attempt, at most a ten-second endpoint gap, and
strong endpoint similarity finds 37 candidate chains in 21 of 98 videos. The
same scan finds 15 chains in eight of the 15 cohort videos. It includes both
missed non-adjacent examples:

- essay [40]→[43]: exact opening frame plus a truncated `a...` in the middle;
- listening [148]→[150]: 98.9% endpoint similarity plus the truncated `our...`
  middle attempt.

This is 81% fewer hints and touches 70% fewer videos than candidate 1. It still
does not authorize a cut: the detector only makes the relationship explicit in
the existing Sol prompt. Sections with no eligible chain must receive the
unchanged baseline prompt so their model behavior is not intentionally
perturbed.

## Candidate-4 result

| Run | Cut precision | Cut recall | Cut F1 | True cut words | Overcut words | Missed-cut words | Explicit positives | Keep controls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 0.791 | 0.687 | 0.736 | 4,382 | 1,158 | 1,992 | 1/16 | 13/17 |
| Candidate 4 | 0.795 | 0.674 | 0.729 | 4,295 | 1,107 | 2,079 | 3/16 | 13/17 |
| Change | +0.004 | -0.013 | -0.007 | -87 | -51 | +87 | +2 | 0 |

All 29 sections completed without retries or fallbacks. The detector did expose
both target chains, and the traces show Sol acted on them:

- listening [148] was correctly cut in full, with [150] kept;
- essay [40] was proposed and cut in full, which wrongly removed its clean
  three-word prefix;
- essay [43] still received only the existing four-word stutter trim instead of
  the required seven-word trim.

Thus only one of the three still-missed non-adjacent spans passed. The next
candidate should not merely show whole endpoint sentences. It should derive and
show the exact proposed splice boundaries: a full earlier-take cut for near
identical endpoints, or exact partial spans when the later endpoint contains an
internal restarted prefix.

### Attribution warning discovered by candidate 4

`engleski25ljeto-reading-5` and `test-9` received no hint, so their prompts were
identical to the baseline, yet they lost 0.051 and 0.108 F1. Other unchanged
videos moved strongly upward. Single reruns therefore contain material Sol
variance. Official gates remain authoritative for promotion, but future
analysis must distinguish affected from unaffected videos and avoid claiming
that an untouched video's movement was caused by the candidate.

## Candidate-5 boundary analysis

The exact essay splice is mechanically derivable. Both endpoints begin with
`Zatim nam slijedi`; the later endpoint repeats that three-word opening after
one intervening word. Therefore the suggested cuts are exactly:

- essay [40] words 3:12 — keep the first `Zatim nam slijedi`;
- essay [43] words 0:7 — remove both restarted openings and keep the completion
  beginning with `možda ovaj najbitniji dio...`.

Listening [148] and [150] have 98.9% endpoint similarity, so the suggested cut
is the complete earlier [148], exactly as candidate 4 successfully proposed.

Requiring one of these two exact-boundary forms reduces the detector from
candidate 4's 37 hints in 21 videos to 26 hints in 18 videos. In the 15-video
cohort it drops from 15 hints in eight videos to nine hints in five videos. A
two-video micro-pilot will test the three exact source spans before another full
cohort spend.

## Candidate-5 result

The micro-pilot established that the derived boundaries are correct and usable
by Sol. All three target spans passed exactly. One micro-run side effect cut
bilingual control [174] by incorrectly claiming it was a retake of unrelated
sentence [177], but that stochastic proposal did not recur in the full run.

The first full cohort artifact at `candidate-5-15` is invalid outage evidence:
DNS failure caused 29/29 sections to fail on both providers. It must never be
used for model-quality conclusions. A later OpenRouter request stalled inside
provider retries before application fallback, so the valid cohort was run as
`candidate-5-15-direct` with direct OpenAI as primary.

| Run | Cut precision | Cut recall | Cut F1 | True cut words | Overcut words | Missed-cut words | Explicit positives | Keep controls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 0.791 | 0.687 | 0.736 | 4,382 | 1,158 | 1,992 | 1/16 | 13/17 |
| Candidate 5 direct | 0.784 | 0.680 | 0.728 | 4,335 | 1,197 | 2,039 | 5/16 | 14/17 |
| Change | -0.007 | -0.007 | -0.008 | -47 | +39 | +47 | +4 | +1 |

The healthy run completed all 29 sections without retries. All three core
source spans passed exactly, and [174] remained kept. Official safety still
failed. On the five actually affected videos, aggregate P/R/F1 changed
0.788/0.701/0.742→0.795/0.688/0.738: fewer overcuts but more missed cuts and a
small F1 loss. Reading-1 lost 0.038 F1, while the two listening videos gained 12
and 16 overcut words.

Candidate 5 proves the deterministic boundary derivation, not the prompt-based
delivery mechanism. The next candidate should evaluate the derived spans as
isolated deterministic additions to a fixed baseline EDL, avoiding any rerun of
unrelated Sol decisions. This can be projected offline before another paid call.
