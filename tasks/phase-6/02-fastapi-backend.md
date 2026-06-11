# FastAPI Backend

Status: `done`
Phase: 6
Depends on: 6.01 (JSON export), phase-4 (rendered segments)

## Objective

REST API that serves video files and edit decision JSON, and accepts modified timelines back from the frontend.

## Requirements

- Serve processed videos discovered from a local media root.
- Serve review payloads generated from `*.edl.json` and `*.transcript.json`.
- Accept modified sentence decisions and save reviewed cuts as `*-review.edl.json`.
- Keep the original AI EDL untouched.
- Trigger a reviewed MP4 render from the reviewed sidecar when requested.

## Implementation Notes

- Implemented in `ai_video_editor/web/app.py`.
- CLI entry point is `ai-video-editor review-serve [MEDIA_ROOT]`.
- API exposes `GET /api/videos`, `GET /api/videos/{video_id}/review`, `POST /api/videos/{video_id}/review`, `POST /api/videos/{video_id}/render`, and `GET /media/{video_id}`.
- The render endpoint looks for `.ai_video_editor_tmp/<stem>_denoised.wav` and writes `<stem>_reviewed.mp4`.

## Acceptance Criteria

- [x] Endpoints: GET edit decisions, GET video media, POST modified timeline
- [x] Video streaming supported
- [x] Modified timeline can trigger re-render
