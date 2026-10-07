# Preserving introductions and corrections

Audio false-start detection emits review candidates, not cuts. The section
editor receives each candidate with the surrounding transcript in its existing
model call. A pause, noise and a short phrase cannot independently delete speech
or upgrade a text decision.

For `retake` and `false_start`, the model must identify both the exact deletion
and a later retained replacement (`kept_index`, `kept_verbatim_text`). The prompt
requires the replacement to cover all the content being removed and to preserve
unique introductions and useful corrections. Meaning is still judged by the
model; a valid reference alone does not prove semantic equivalence.

Both snippets must match a unique contiguous run of words, ignoring outer
punctuation and case. Missing, ambiguous, non-contiguous, earlier, overlapping
or out-of-context replacements are rejected. Partial deletions are never rounded
up to a whole sentence, including proposals covering 90% of its words. The old
fuzzy-match and whole-sentence coverage thresholds no longer control these cuts.

Retained spans survive merging and are protected against section, deterministic
local-correction and aside cuts. Conflicting proposals are rejected as a whole.
Resolution is conservative and independent of proposal order: for A → B → C,
B remains if it was named as A's retained replacement. The model is instructed
to name the final surviving take instead of constructing deletion chains.

The precision tradeoff is that ambiguous repetitions and contradictory plans
may leave extra material. The next nine-example evaluation must check both
overcut useful content and missed cuts; fewer cuts alone is not an improvement.

## Decision traces

`decide_edits` saves an `edit_decisions.v2` JSON trace under
`Settings.general.output_dir/decision-traces/`. Each invocation has a unique
filename. It includes the transcript, silence/keep/disruption inputs, decision
source-code digest, original section proposals and model IDs, rejection reasons,
local-correction flags, retained spans, aside flags, final flags and the EDL
before acoustic boundary adjustment. It does not contain model credentials.

Worker analyses route these files to
`VIDEO_PROCESSING_LOG_DIR/analyses/<job-id>/decision-traces/`, outside job scratch,
so normal scratch cleanup preserves them. Their retention follows the worker's
log storage. They remain worker-owned diagnostics and do not change the Gradivo
HTTP contract or existing analysis snapshots.

## Verification

`tests/test_edit_safety.py` uses frozen transcript excerpts and original word
times from source 49913, cases 5 and 8. Model responses are controlled in these
tests: they verify exact cut application, retained replacement protection and
diagnostics, not the live model's editorial judgment. Other regressions cover
invalid replacements, conflicting chains, ambiguous matches and 90% proposals.
Worker tests verify trace persistence after scratch cleanup.

A new live run over the nine examples must write to a new output directory and
retain its traces. The frozen automatic cuts and immutable human render cuts
remain the comparison baseline. This implementation does not launch that run.
