# Regression Test Harness

Status: `done`
Phase: 5
Depends on: 5.05, 5.06

## Objective

Provide a single command that runs the full pipeline on test videos and compares the output against manually edited ground truth, producing a pass/fail score. This lets us verify that any change to thresholds, prompts, or pipeline logic makes things better — not worse.

## Requirements

- Single CLI command or script that runs the full pipeline on all test video pairs and produces scores.
- Discovers pairs by naming convention: `<name>-raw.mp4` + `<name>-edited.mp4` in a given directory.
- For each pair: run pipeline on raw, compare output against human-edited ground truth using tasks 5.05 + 5.06.
- Output transcript accuracy (precision, recall, F1), temporal accuracy, and a combined overall score.
- **Store scores in a JSON history file** so we can track improvement over time across runs.
- Clearly flag regressions (score dropped vs. previous best or vs. last run).
- Built for N pairs from the start.

## Implementation Notes

- History file: `tests/fixtures/regression_scores.json` (append-only, one entry per run with timestamp + per-pair scores + aggregate).
- Console output: table of scores per pair, delta vs last run, pass/fail.
- Could also be integrated into `pytest` as a special test that warns on regression.

## Acceptance Criteria

- [ ] Single CLI command or script to run the full comparison
- [ ] Accepts one or more raw/edited video pairs as input
- [ ] Outputs transcript accuracy, temporal accuracy, and overall score
- [ ] Scores are comparable across runs so we can track improvement over time
- [ ] Clearly flags regressions (score dropped vs. previous run)
