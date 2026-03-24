# Transcript Continuity Verification

Status: `pending`
Phase: 6
Depends on: phase-4 (rendered video), phase-2 (transcription)

## Objective

Re-transcribe the final video and compare against the expected filtered transcript to verify no content was accidentally dropped.

## Requirements

_To be filled during grilling session._

## Implementation Notes

_To be filled during grilling session._

## Acceptance Criteria

- [ ] Final MP4 re-transcribed via Whisper
- [ ] Post-edit transcript aligned against expected transcript (DTW or Needleman-Wunsch)
- [ ] Alignment score below threshold triggers a warning
- [ ] Missing educational content detected and reported
