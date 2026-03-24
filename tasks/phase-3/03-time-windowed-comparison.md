# Time-Windowed Comparison

Status: `pending`
Phase: 3
Depends on: 3.01, 3.02

## Objective

Build a bounded self-similarity matrix that only compares temporally adjacent sentences, preventing false positives from legitimate pedagogical recaps.

## Requirements

_To be filled during grilling session._

## Implementation Notes

_To be filled during grilling session._

## Acceptance Criteria

- [ ] Each sentence compared only against next N sentences (configurable window)
- [ ] No comparison across distant parts of the lecture
- [ ] Legitimate recaps/summaries not flagged as duplicates
