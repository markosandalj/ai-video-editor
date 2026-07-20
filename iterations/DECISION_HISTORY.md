# Quality Decision History

This file preserves decisions, not a score leaderboard. Absolute scores from
iterations 1-20 were removed because their scorers, corpora, alignment methods,
and even pipeline architecture changed. A number is retained only when it is a
same-protocol local comparison needed to explain a decision.

The full pre-compaction reports and artifacts remain recoverable from Git at
commit `eb3e892c8edc2a7f1b90489a6660db327c46c3ed`.

## Legacy detector era

| Iteration | Decision | Durable lesson | Current relevance |
|---|---|---|---|
| 001 | Established the original single-video baseline. | Sentence boundaries and timing can distort quality judgments. | Superseded baseline. |
| 002 | Added word-level LCS measurement. | Word coverage is more useful than sentence identity for partial edits. | Concept retained; implementation evolved. |
| 003 | Disabled whole-sentence stutter cutting after it removed valid content. | A local defect needs a local word trim, not necessarily a sentence cut. | Failure avoided by current exact-span passes. |
| 004 | Promoted silence rescue and keep-side protection. | Missing-content protection must be evaluated alongside cutting accuracy. | Old implementation superseded. |
| 005 | Promoted sub-sentence stutter trimming. | Word-timed trims can safely remove defects inside otherwise useful speech. | Principle retained. |
| 006 | Reverted holistic Gemini redundancy review. | Broad semantic cleanup can overcut content the editor wants. | Current model path uses bounded sections and deterministic post-passes. |
| 007 | Promoted temporal-score repair and fragment detection. | QA formulas can change the apparent result as much as pipeline code. | Scorer superseded; lesson drives protocol IDs. |
| 008 | Promoted broader fragment handling and deterministic model temperature. | Determinism helps reproducibility but does not establish correctness. | General operating rule. |
| 009 | Promoted punctuation normalization in fragment detection. | Normalize token punctuation before applying lexical rules. | Durable normalization lesson. |
| 010 | Replaced temporal scoring with a robust aggregate over 13 videos. | A scorer change starts a new comparison regime. | Historical scorer superseded. |
| 011 | Kept a mixed threshold/keep-longer change. | “Keep the longer take” is not a generally reliable quality rule. | Heuristic no longer authoritative. |
| 012 | Kept a mixed Gemini which-to-keep experiment. | Take selection needs context; a global choice heuristic is unstable. | Superseded by Section Editor. |
| 013 | Changed aggregate weighting and fragment prompting. | Aggregate score design encodes product priorities and cannot be treated as neutral. | Historical scorer superseded. |

## Transition to the current architecture

| Iteration | Decision | Durable lesson | Current relevance |
|---|---|---|---|
| 014 | Reverted blanket protection for short instructional bridges. | Broad protection rules recover content at the cost of missed cuts. | Do not reintroduce without a narrowly identified class. |
| 015 | Promoted a multi-change decision-quality bundle. | The bundle improved the result but could not establish which change caused it. | Motivated isolated hypotheses and the Section Editor transition. |
| 016 | Promoted tiny enrichment-artifact cuts. | Threshold rules delivered only a small local gain; most residual disagreement was clean content. | Enrichment path was later removed. |
| 017 | Promoted acoustic disruption-driven false-start detection. | Some false starts are invisible in text and require an audio cue. | Active in `audio/disruption.py` and `duplicate/false_start_audio.py`. |
| 018 | Reverted mandatory `kept_index` links for every whole-sentence false start. | A universal completion-link gate suppresses too many valid cuts. | Health, trace, and comparison tooling survived; the gate did not. |

## Deterministic post-pass era

| Iteration | Decision | Durable lesson | Current relevance |
|---|---|---|---|
| 019 | Reverted five prompt/hint variants, then promoted candidate 6: deterministic non-adjacent local correction chains. | Exact deterministic post-passes can recover a narrow error class without destabilizing the Section Editor; evaluate them against fixed EDLs. | Active in `duplicate/local_corrections.py`. |
| 020 | Promoted deterministic adjacent suffix-to-prefix restart cuts with later-coverage and twin-exclusion guards. | Repeated-word evaluation needs position-aware auditing because raw LCS can credit the wrong copy. | Current production/UI baseline and starting point for iteration 21. |

## Current inherited decisions

The current baseline therefore inherits four durable choices:

1. Section Editor is the primary semantic edit-decision path.
2. Deterministic local-correction passes handle narrow non-adjacent and adjacent
   restart patterns after the model decision.
3. Acoustic disruptions may identify short stranded false starts that text alone
   cannot explain.
4. A comparison is valid only inside one explicit evaluation protocol.

## Recovering archived detail

Use Git only when a historical question requires it; agents should not load the
archive during normal iteration work.

```bash
git show eb3e892:iterations/ITERATION_LOG.md
git show eb3e892:iterations/iter-020/hypothesis.md
git ls-tree -r --name-only eb3e892 iterations/
```

Tags `iter-014` through `iter-020` and their candidate tags provide additional
revert points. Earlier iteration material is available from ordinary Git history.

