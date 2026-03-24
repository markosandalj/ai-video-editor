# RL Agent (V4)

Status: `pending`
Phase: 9
Depends on: 9.04

## Objective

Frame video editing as a sequential decision problem where an RL agent learns optimal Keep/Cut policies from ground-truth data.

## Requirements

_To be filled during grilling session._

## Implementation Notes

_To be filled during grilling session._

## Acceptance Criteria

- [ ] Agent steps through transcript chronologically, choosing Keep/Cut per sentence
- [ ] Reward function based on match to ground-truth professional edit
- [ ] Agent penalized for cutting unique semantic content
- [ ] Agent rewarded for removing silences and redundant patterns
- [ ] Trained agent outperforms Transformer classifier on test set
