# Iteration 015 — Decision-Quality Bundle

> Note: This is a multi-change bundle, not a single-hypothesis iteration. It was
> driven by a holistic review of the keep/cut/annotate decision layer rather than
> the usual one-change loop. Results below are the full 21-video fixture set.

## Scores (21-video aggregate)

| Metric          | iter-014 (prev) | iter-015 (this) | Δ        |
|-----------------|-----------------|-----------------|----------|
| Overall         | 0.886           | **0.943**       | **+0.058** |
| Word-F1         | 0.943           | 0.953           | +0.010   |
| Temporal        | 0.800           | **0.967**       | **+0.168** |
| Continuity      | 0.872           | 0.884           | +0.012   |
| Sentence F1     | 0.874           | 0.876           | +0.002   |
| Cut precision*  | 0.722           | **0.857**       | **+0.135** |
| Cut F1*         | 0.599           | 0.633           | +0.034   |

\* Decision-level eval (CUT vs human ground truth), network-free harness.

Every video improved or held flat; zero regressions. Biggest per-video overall
gains: test-47 +0.162, test-10 +0.160, test-40 +0.153, test-7 +0.126,
test-44 +0.107. Only test-6 was flat (already 0.945).

## Changes in this bundle

1. **Enrichment-as-arbiter** (`enrich/arbiter.py`): the independent per-sentence
   Gemini enrichment scores now revise the EDL — un-cutting high-confidence keeps
   and adding extra cuts only for low-confidence sentences carrying
   aside/filler/incomplete tags. Calibrated by an 18-video offline sweep
   (extra_cut_confidence=15, REPETITION_RESIDUE excluded as the largest source of
   wrong extra-cuts).
2. **Dedicated aside / production-noise detector** (`duplicate/aside.py`): catches
   non-duplicate cuts (the ~70% of human cuts the duplicate-anchored pipeline was
   structurally blind to) using audio-event tags and silence-flanked short
   sentences, verified by Gemini.
3. **Retake clustering + chain consistency** (`duplicate/pipeline.py`): union-find
   over duplicate pairs so only one survivor is kept per cluster, with real
   confidence scores instead of hardcoded 1.0.
4. **Gemini duplicate context + completeness-aware which-to-keep**
   (`duplicate/gemini_verify.py`): neighbor sentences + inter-version time gaps in
   the prompt; for educational content the more complete version is preferred.
5. **Pause-split chunking** (`transcription/chunking.py`): sentences split on long
   intra-sentence pauses (`pause_split_s=1.5`) to isolate false starts.
6. **QA metric fixes** (`qa/ground_truth.py`, `qa/continuity.py`): order-preserving
   monotonic sentence alignment + local-drift temporal metric (replacing greedy
   matching and absolute-offset accumulation).
7. **Network-free decision-eval harness** (`qa/decision_eval.py`, CLI
   `eval-decisions`): scores cut decisions against ground truth from cached
   sidecars, enabling fast threshold sweeps without rendering or API calls.
8. **Gemini timeout/retry hardening**: all four Gemini call sites now bound every
   request (timeout + max_retries), so a dropped connection fails and retries
   instead of hanging the whole batch (the previous batch-stall failure mode).

## Follow-ups (next places to push)

- test-8 / test-9 have the weakest cut precision (0.50 / 0.42) — pause-split may
  over-fragment their speech into false-start candidates; worth a targeted look.
- Spectrogram check still flags a few (e.g. test-7 at 0.747) and continuity sits
  at 0.884 — the next ceilings if pushing past 94.3%.
