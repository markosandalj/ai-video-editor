# Batch Processing

Status: `done`
Phase: 4
Depends on: 4.05

## Objective

Extend the existing `batch` CLI command to include rendering as the final step.

## Requirements

- The existing `batch` command already handles audio + transcription + duplicate detection + EDL.
- Extend it to also call the render function for each video.
- Failed renders are skipped (don't crash the batch) — existing error handling pattern.
- Summary report at end includes render timing and output file sizes.

## Implementation Notes

- This is mostly about wiring the render function into the existing batch loop in `cli/app.py`.
- Minimal new code — the existing batch error handling (`try/except` per video) already covers failure recovery.

## Acceptance Criteria

- [x] Existing `batch` command extended to include rendering
- [x] Each video produces `<stem>_edited.mp4` output
- [x] Failed renders skipped without crashing batch (existing try/except)
- [x] Summary report includes per-video render timing
