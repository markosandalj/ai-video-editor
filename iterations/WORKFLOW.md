# Quality Iteration Workflow

This workflow optimizes for clear, reproducible decisions. Iteration directories
are temporary working records, not a permanent knowledge base.

## Session start

Read only:

1. `iterations/WORKFLOW.md`;
2. `iterations/CURRENT_BASELINE.md`; and
3. the current `iterations/iter-NNN/` directory, if one exists.

Read `DECISION_HISTORY.md` only when a proposed change may repeat an old idea or
the user asks about history. Do not search Git history or load archived iteration
artifacts by default. The next available number is `iter-021`.

## Before an iteration

Create `iterations/iter-NNN/` with a concise `hypothesis.md` that states:

- the specific observed error class;
- one proposed change;
- expected benefit and plausible regression;
- pass/fail gates; and
- the baseline ID and evaluation protocol ID from `current-baseline.json`.

Record a protocol manifest before measuring anything. It must identify:

- scorer function and code commit;
- fixture count and fixture name-set hash;
- raw/ground-truth input hash;
- baseline EDL population hash;
- relevant model and pipeline configuration; and
- any reconciliation or special-case audit method.

If any of these differs from the current baseline, first create a new baseline
ID and measure the unchanged pipeline under it. Never compare measurements
across protocol IDs.

## Run the experiment

1. Preserve the baseline EDLs; write candidate artifacts outside
   `tests/fixtures` until promotion.
2. Implement exactly one hypothesis.
3. Use the same inputs, configuration, scorer, and audit for baseline and candidate.
4. Record local deltas, affected examples, regressions, and gate results in
   `result.md`; avoid a cross-iteration score table.
5. Present mixed results to the user. Promotion is a product decision, not a
   single-metric threshold.

Live-model experiments must record provider, model, prompt/config identity, and
repeat count. Deterministic projection against fixed EDLs is preferred when it
answers the hypothesis because it isolates the code change.

## Close the iteration

For a promoted result:

1. promote all intended EDLs into `tests/fixtures` and verify the exact file count;
2. update `current-baseline.json` and `CURRENT_BASELINE.md`, including new hashes;
3. add one compact decision entry to `DECISION_HISTORY.md`;
4. run focused tests plus the full relevant evaluation gates; and
5. remove the closed `iter-NNN/` working directory in the same or next cleanup
   commit—Git is the detailed archive.

For a rejected or reverted result, restore the implementation, add the compact
decision and lesson to `DECISION_HISTORY.md`, then remove the working directory.
Do not preserve large output trees merely to document that an attempt failed.

Use an iteration-numbered commit message and tag important promoted states.
Commit and push only when the user requests it.

## Authority boundaries

- `tests/fixtures/*-raw.edl.json` is the UI/production EDL population.
- `current-baseline.json` is the machine-readable comparison authority.
- `CURRENT_BASELINE.md` is its human-readable explanation.
- `DECISION_HISTORY.md` records why ideas were accepted or rejected.
- `output/` and temporary directories are generated evidence, never production
  or baseline authority.

