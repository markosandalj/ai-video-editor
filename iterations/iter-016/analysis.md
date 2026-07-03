# Iteration 016 — Analysis: the 1,087 missed cuts

Baseline is the 98-video run (post fixture expansion). Decision-level eval
against human ground truth, positive class = CUT:

| Metric        | Value |
|---------------|-------|
| Cut precision | 0.830 |
| Cut recall    | 0.443 |
| Cut F1        | 0.578 |
| Accuracy      | 0.840 |
| Human cuts    | 1953  |
| Pipeline cuts | 1043  |
| **Missed cuts (FN)** | **1087** |

Overall (render-QA) score at baseline: **94.3%** (word-F1 95.5, temporal 95.5,
continuity 89.4).

## What the missed cuts actually are

Joined every FN to its independent enrichment score/tags (network-free, over
cached sidecars):

- **85.7% (932/1087) have enrichment `keep_confidence ≥ 80`** — status `green`.
  An independent Gemini judge *agrees they should be kept*. Both the pipeline
  and the LLM consider these legitimate, kept lesson content; the human removed
  them anyway.
- Only **~126 (12%)** have `keep_confidence < 40` — i.e. a low-confidence signal
  we already have but don't act on.
- The rest sit in a thin 40–79 band.

### Distribution
- **By group:** test 561, engleski 324, kemija 101, hrvatski 61, fizika 40.
  Long, heavily-edited English readings + the original test set dominate.
- **By length:** 62% are 7+ words (substantial sentences, not fragments);
  15.5% are 1–3 words.
- **By tag:** `verbatim_clean` 372, `filler_phrase` 310, none/no-enrichment 172,
  `minor_disfluency` 108, `repetition_residue` 96.

### Interpretation
The recall gap is **~86% structural**. The human cuts a large amount of clean,
coherent content for **editorial/pacing reasons that are invisible at the
transcript level** (e.g. *"Dakle, na kraju sam postavio retoričko pitanje."* —
"So at the end I posed a rhetorical question"). No transcript-redundancy /
disfluency / aside signal can recover those without also cutting content the
human kept.

## Precision/recall simulation (marginal effect on top of shipped EDL, 98 videos)

| Rule | P | R | F1 | recovered | new FP |
|------|----:|----:|----:|----:|----:|
| baseline (shipped)        | 0.830 | 0.443 | 0.578 | – | – |
| **punct OR (≤2w & conf<25)** | **0.832** | **0.450** | **0.584** | **+13** | **0** |
| keep_conf<10              | 0.801 | 0.466 | 0.589 | +45 | +50 |
| keep_conf<20              | 0.757 | 0.485 | 0.592 | +82 | +127 |
| keep_conf<30              | 0.720 | 0.506 | 0.594 | +122 | +207 |
| conf<25 AND cut-tag       | 0.731 | 0.497 | 0.592 | +105 | +180 |
| conf<40 AND cut-tag       | 0.719 | 0.505 | 0.594 | +121 | +209 |

Every aggressive rule buys ≤0.016 F1 while **collapsing precision** (0.83 → 0.72)
and adding 100–200 false positives (cutting content the human kept). Net F1 is
essentially flat across the whole sweep — confirming the gap is not a threshold
problem.

The **only Pareto-positive** change is artifact cleanup: cut sentences that are
punctuation-only OR ≤2 words with `keep_confidence < 25`. It recovers 13 missed
cuts (literal junk frames — `"."`, `"..."`, `"Aaaaj."`, `"Ne."`) with **zero new
false positives**, nudging precision *up* to 0.832.

## Decision
Ship the safe artifact cleanup as iter-016. Do **not** chase the remaining ~86%
of misses with confidence thresholds — it is a precision-destroying dead end.
The real recall ceiling needs a per-teacher editorial/pacing-style signal that
does not exist at the transcript level (separate research direction).
