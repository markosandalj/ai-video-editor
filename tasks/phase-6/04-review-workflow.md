# Review Workflow

Status: `done`
Phase: 6
Depends on: 6.03 (React timeline UI)

## Objective

Complete review experience: play, scrub, adjust, approve/reject cuts, submit.

## Requirements

- Provide a local browser workflow for correcting the remaining automated edit errors.
- Reviewers can play/scrub the raw video, inspect AI decisions, toggle sentences between Keep and Cut, save a review sidecar, and request a reviewed render.
- Reviewed changes must not overwrite the original AI EDL.

## Implementation Notes

- Implemented in the React app and FastAPI review endpoints.
- Review state is submitted as sentence decisions to `POST /api/videos/{video_id}/review`.
- Saved review files use the `*-review.edl.json` naming convention.

## Acceptance Criteria

- [x] Play/pause/scrub through source video
- [x] Approve/reject individual cuts via Keep/Cut sentence toggles
- [x] Visual reason/confidence context per sentence
- [x] Submit button sends modified timeline to backend
