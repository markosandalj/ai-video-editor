# JSON Export for Web Frontend

Status: `done`
Phase: 6
Depends on: phase-3 (edit decision list), phase-5 (transcript metadata enrichment)

## Objective

Serialize edit decisions as a clean JSON payload for consumption by the web-based review frontend.

## Requirements

- Export a stable review payload from an existing raw video, transcript cache, and AI EDL.
- Keep the generated AI EDL immutable; reviewer changes must be saved to a separate `*-review.edl.json` sidecar.
- Include enough sentence-level data for a fast editor UI: timestamps, text, action, original action, reason, confidence, and keep coverage.
- Include timeline segment metadata for a basic visual timeline preview.

## Implementation Notes

- Implemented in `ai_video_editor/review/models.py` and `ai_video_editor/review/export.py`.
- `review-export` writes `<stem>.review.json` for offline inspection or static consumers.
- `save_reviewed_edl()` starts from the AI keep spans and applies sentence-level keep/cut toggles so unchanged cuts remain close to the original pipeline output.

## Acceptance Criteria

- [x] JSON output includes start, end, action, text, and confidence per sentence
- [x] Format documented and stable (serves as API contract with frontend)
- [x] Includes metadata (source video path, processing timestamp, AI EDL path, review EDL path, durations)
