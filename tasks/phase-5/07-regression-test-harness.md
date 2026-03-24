# Regression Test Harness

Status: `pending`
Phase: 5
Depends on: 5.05, 5.06

## Objective

Provide a single command that runs the full pipeline on test videos and compares the output against manually edited ground truth, producing a pass/fail score. This lets us verify that any change to thresholds, prompts, or pipeline logic makes things better — not worse.

## Requirements

_To be filled during grilling session._

## Implementation Notes

_To be filled during grilling session._

## Acceptance Criteria

- [ ] Single CLI command or script to run the full comparison
- [ ] Accepts one or more raw/edited video pairs as input
- [ ] Outputs transcript accuracy, temporal accuracy, and overall score
- [ ] Scores are comparable across runs so we can track improvement over time
- [ ] Clearly flags regressions (score dropped vs. previous run)
