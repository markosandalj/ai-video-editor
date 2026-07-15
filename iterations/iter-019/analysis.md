# Iteration 019 — Analysis

**Date:** 2026-07-15  
**Reference:** 98-video `gpt-5.6-sol` section-editor run

## Scores

| Cut precision | Cut recall | Cut F1 | True cut words | Overcut words | Missed-cut words | Failed sections |
|---:|---:|---:|---:|---:|---:|
| 0.797 | 0.674 | 0.730 | 10,687 | 2,726 | 5,166 | 0/120 |

## False positives: pipeline kept, human cut

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

## False negatives: pipeline cut, human kept

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

## Recommended hypothesis

Mechanically surface conservative local-repeat candidates inside the existing
section-editor prompt. They are attention hints only: Sol still decides, and all
existing verification and guardrails remain authoritative.
