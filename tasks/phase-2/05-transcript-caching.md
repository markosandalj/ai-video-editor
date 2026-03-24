# Transcript Caching

Status: `pending`
Phase: 2
Depends on: 2.03, 2.04

## Objective

Cache transcription results to disk so re-runs don't re-transcribe already processed videos.

## Requirements

_To be filled during grilling session._

## Implementation Notes

_To be filled during grilling session._

## Acceptance Criteria

- [ ] Transcript saved to JSON after processing
- [ ] Pipeline skips transcription if cached transcript exists
- [ ] Cache invalidation when source video changes (hash check)
