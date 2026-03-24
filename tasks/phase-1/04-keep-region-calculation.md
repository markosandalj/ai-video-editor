# Keep-Region Calculation

Status: `pending`
Phase: 1
Depends on: 1.03

## Objective

Invert silence regions into "keep" segments with padding margins, producing the list of audio/video segments to retain.

## Requirements

_To be filled during grilling session._

## Implementation Notes

_To be filled during grilling session._

## Acceptance Criteria

- [ ] Keep regions are the inverse of silence regions
- [ ] Configurable padding (ms) applied before and after each speech segment
- [ ] Adjacent keep regions merge when gaps between them are smaller than minimum silence duration
- [ ] No overlapping or out-of-order regions in output
