# Edit Decision List

Status: `pending`
Phase: 3
Depends on: 3.04, phase-1 (keep regions)

## Objective

Merge silence-based keep regions with duplicate detection results into a single, ordered edit decision list that drives all downstream operations.

## Requirements

_To be filled during grilling session._

## Implementation Notes

_To be filled during grilling session._

## Acceptance Criteria

- [ ] Unified list of `EditDecision(start, end, action, reason, confidence)` objects
- [ ] Silence cuts and duplicate cuts merged without conflicts
- [ ] Output is chronologically ordered and non-overlapping
- [ ] Serializable to JSON for export and caching
