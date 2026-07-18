# Iteration 020 — Analysis

**Date:** 2026-07-17  
**Baseline:** post–iter-019 candidate-6 EDLs (`output/qa-iteration-19/candidate-6-projection-98/edls`, 98 videos)  
**Method:** word-level decision eval + sentence-level mistake bucketing (offline)

## Scores (current production baseline)

| Cut precision | Cut recall | Cut F1 | True cut words | Overcut words | Missed-cut words |
|---:|---:|---:|---:|---:|---:|
| 0.797 | 0.676 | 0.732 | 10,720 | 2,726 | 5,133 |

Wrong cuts by mechanism (words): silence 992 · duplicate 937 · false_start 791  
Right cuts by mechanism (words): duplicate 4,942 · false_start 4,188 · silence 1,582

## Delta vs previous

Iter-019 candidate 6 recovered +33 correct cut words with 0 new overcuts
(P/R/F1 0.7968/0.6741/0.7303 → 0.7973/0.6762/0.7318). This analysis is the
post-promotion residual surface.

## False negatives: pipeline kept, human cut

Sentence-level missed-cut buckets (240 sentences):

| Bucket | Count | Share |
|---|---:|---:|
| content_cut (no similar twin) | 121 | 50.4% |
| fragment (≤4 words or truncated) | 74 | 30.8% |
| retake_in_window (twin sim≥70 within ±5) | 40 | 16.7% |
| retake_out_of_window | 5 | 2.1% |

### Representative missed content

- `engleski25ljeto-listening-1[16]`: abandoned explanation before a corrected take
- `engleski25ljeto-esej[143]`: pacing/meta commentary with no twin
- `engleski25ljeto-listening-2[317–318]`: retakes just past the window (d=6)

### Explicit local-repeat cases still open

After candidate 6, only the three sandwich-chain spans pass. **13/16** cut
cases in `candidate-3-cases.json` still fail — mostly adjacent suffix/prefix
partials (`test-10`, `test-11`, `test-13`, listening/reading clips).

Naive adjacent-suffix auto-cut (n≥4, sim≥92, gap 0.5–12s) recovers only ~14
new correct words under raw LCS scoring and looks unsafe on the same scorer
because identical later copies make the earlier span look “kept”. Explicit
source-span scoring remains required for this family (same lesson as iter-019).

## False positives: pipeline cut, human kept

Sentence-level overcut buckets (218 sentences):

| Bucket | Count | Share |
|---|---:|---:|
| short false_start (≤4w or trunc-looking) | 104 | 47.7% |
| content duplicate | 25 | 11.5% |
| retake-like false_start | 24 | 11.0% |
| content silence | 19 | 8.7% |
| retake-like duplicate | 18 | 8.3% |
| other | 28 | 12.8% |

Word-level true false_start overcuts (human kept ≥80% of the sentence’s words):
**121 sentences / 474 words**. Examples include truncated teaching lead-ins the
human retained (`Nastavljamo na-`, `…musici-`, `job satisfi-`).

Silence is the largest single overcut *mechanism* at word level (**992 words**).
Token anatomy: `uhm` alone is 108; the rest is ordinary content bled into silence
gaps (`i`, `da`, `znači`, `dakle`, …) — not a pure filler problem.

### Bilingual / teaching overcuts still present

Canonical case still in the EDL as a duplicate overcut:

> `engleski25ljeto-listening-1[174]`: “Dakle, bila je razočarana zbog nezahvalnih poslova”

(Prompt-only bilingual protection failed in iter-019 candidate 2.)

## Patterns (ranked for a single-hypothesis iter-020)

1. **Recall gap is still mostly unique content** (Pattern 1 revisited). Half of
   sentence misses have no twin. The section editor deliberately rejects
   `redundant` proposals — this is policy, not a detector miss. Attacking it
   means a new high-precision content-cut lane, not a small local tweak.

2. **Adjacent partial repeats remain the best structured recall miss.**
   Candidate 6 solved non-adjacent sandwich chains; adjacent suffix/prefix
   partials are still almost entirely open. Prompt hints failed in iter-019;
   a second **deterministic** local-corrections lane (no Sol rerun) matches the
   winning delivery mechanism.

3. **False-start overcutting of kept truncated lead-ins** is the largest clean
   sentence-level precision failure (~474 words). Guarding whole-sentence
   `false_start` cuts that the human consistently keeps (or requiring a later
   completion twin) revisits the spirit of iter-018 without its broad
   `kept_index` gate.

4. **Silence bleed** is the largest word-level precision failure (992 words).
   Mix of filled pauses and real speech at keep-region edges. Likely an EDL /
   silence-rescue boundary issue rather than a section-editor decision.

5. **In-window retakes both kept** are smaller than the July-11 writeup
   suggested under Sol+candidate-6: only ~1 auto-safe case at sim≥90, ~8 at
   sim≥80. Low payoff as a solo iteration.

## Top error-heavy videos

Missed-cut words: reading-1 (513), listening-2 (292), reading-2 (279), test-45 (210)  
Overcut words: reading-1 (218), reading-2 (143), listening-2 (137), test-18 (108)

## Artifacts

- `iterations/iter-020/mine.json` — bucket counts and examples  
- `iterations/iter-020/deepdive.json` — retake/FS/silence/explicit-case detail  
- Explicit case manifest: `iterations/iter-019/candidate-3-cases.json`
