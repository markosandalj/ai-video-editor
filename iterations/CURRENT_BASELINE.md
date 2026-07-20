# Current Quality Baseline

This is the only baseline against which iteration 21 may be compared. Historical
scores are intentionally absent: earlier iterations changed scorers, fixture
sets, alignment rules, and pipeline architecture, so their absolute numbers do
not form a valid time series.

## Promoted state

- **Baseline ID:** `iter-020-promoted-98-fixed-edl-v1`
- **Status:** promoted on 2026-07-18
- **Next iteration:** `iter-021`
- **Fixture population:** all 98 videos in `tests/fixtures`
- **UI/production EDL population:** the 98 `tests/fixtures/*-raw.edl.json` files
- **Adjacent-repeat implementation:** commit `1dfe4eb5a9af434ca01b13d63fd945231e7649d6`
- **Promotion record:** commit `61af91167588d2602e2db29da3cb5851e329fd55`
- **Last commit containing the full iteration 1-20 archive:** `eb3e892c8edc2a7f1b90489a6660db327c46c3ed`

The current editing path is the Section Editor followed by deterministic local
corrections, with the acoustic-disruption/false-start lane running alongside it.
Iteration 19 contributed non-adjacent correction-chain cuts; iteration 20 added
adjacent suffix-to-prefix restart cuts. Both deterministic passes remain active
in `ai_video_editor/duplicate/local_corrections.py`.

## Evaluation protocol

The protocol ID is `fixed-edl-word-coverage-repeat-audit-v1`.

It uses:

- raw word timings from `*-raw.transcript.json`;
- human edited ground truth from `*-edited.qa-transcript.json`;
- the fixed promoted `*-raw.edl.json` population;
- `ai_video_editor.qa.decision_eval.evaluate_decisions_word_level` for cut/keep
  classification at word granularity; and
- a position-aware repeat audit to reconcile LCS attribution when identical
  words occur in both the discarded attempt and the kept take.

The reproducibility identifiers are:

- fixture name-set SHA-256: `01a62ce69679552e7ec6cae6c3a38b43fe48cb9125429c3c5d74763af1dc2fa8`
- raw/ground-truth input SHA-256: `126f84057e3d50283412ad4a02a205cbd7d5ed05ec8fb546a99c705f1f936a6e`
- promoted EDL population SHA-256: `5dcf68e9cf49eac27f691197a4e52bb45bb30edb7000814a11c2155b76c845ff`

Any change to the scorer, alignment/reconciliation method, fixture name set,
ground truth, baseline EDLs, or relevant configuration creates a **new protocol
and baseline ID**. Recompute the baseline; do not append the new result to the
old score series.

## Current measurements

The promoted EDL population has these word-decision measurements under the
protocol above:

| Attribution | Precision | Recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| Raw LCS | 0.7948 | 0.6779 | 0.7317 | 10,747 | 2,774 | 5,106 |
| Repeat-reconciled | 0.8101 | 0.6888 | 0.7445 | 10,953 | 2,568 | 4,949 |

Iteration 20's promotion gates also established:

- explicit repeat cases improved from 3/16 to 13/16;
- intentional-repeat controls stayed at 14/17 with the same three pre-existing failures;
- all 86 emitted repeat spans were correct, covering 879 words, with zero
  both-kept and zero unlocated spans;
- 75 additional EDL words were cut; and
- all eight videos whose reconciled score changed improved, with no regressions.

Raw LCS can assign an identical repeated word to the wrong copy. That is why the
raw aggregate appears flat while the position-aware audit shows the intended
improvement. Future repeat work must retain both the raw metric and the same
reconciliation audit.

The same data is available to tooling in `iterations/current-baseline.json`.
`output/` is not an authoritative source and is not required by the UI.

