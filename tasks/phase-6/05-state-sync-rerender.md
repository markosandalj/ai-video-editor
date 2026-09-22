# State Sync & Re-Render

Status: `done`
Phase: 6
Depends on: 6.02 (FastAPI backend), 6.04 (review workflow)

## Objective

POST modified timeline JSON to backend, trigger FFmpeg re-render with updated cut points, return final MP4.

## Requirements

- POST reviewed sentence decisions to the backend.
- Save the result as `*-review.edl.json`.
- Re-render from the reviewed sidecar using the existing FFmpeg render path.
- Provide simple UI status updates during save/render.

## Implementation Notes

- `save_reviewed_edl()` builds the reviewed EDL by applying sentence toggles to the original keep spans.
- `POST /api/videos/{video_id}/render` renders `<stem>_reviewed.mp4`.
- The React UI shows save/render progress through the shared status line.

## Acceptance Criteria

- [x] Modified timeline JSON accepted by API
- [x] Re-render triggered with updated cut points
- [x] Final MP4 written next to the source video
- [x] Progress feedback during render
