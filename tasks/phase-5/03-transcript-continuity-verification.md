# Transcript Continuity Verification

Status: `done`
Phase: 5
Depends on: phase-4 (rendered video), phase-2 (transcription)

## Objective

Re-transcribe the final video and compare against the expected filtered transcript to verify no content was accidentally dropped.

## Requirements

- Re-transcribe the rendered `_edited.mp4` using **ElevenLabs** (same as our pipeline for consistency).
- Compare the re-transcription against the `_edited.transcript.json` (the expected post-edit transcript).
- Use fuzzy text matching to align sentences and detect any content that was accidentally dropped or garbled during rendering.
- Flag missing or severely mismatched sentences.

## Implementation Notes

- The expected transcript is the `_edited.transcript.json` debug file (post-EDL, with timestamps recalculated).
- The re-transcription gives us what's actually in the rendered video.
- Use `rapidfuzz` for sentence-level matching (already a dependency).
- Output: list of matched/unmatched sentences with similarity scores.

## Acceptance Criteria

- [ ] Final MP4 re-transcribed via ElevenLabs
- [ ] Post-edit transcript aligned against expected transcript (fuzzy matching)
- [ ] Alignment score below threshold triggers a warning
- [ ] Missing educational content detected and reported
