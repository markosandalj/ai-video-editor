# React Timeline UI

Status: `done`
Phase: 6
Depends on: 6.02 (FastAPI backend)

## Objective

Browser-based timeline editor where professors can visually review and adjust AI-generated cuts.

## Requirements

- Build a React + Vite + TypeScript review UI.
- Optimize the MVP for fast sentence-level review, not full NLE editing.
- Show a simple timeline preview that reflects current keep/cut decisions.
- Let reviewers click timeline blocks or transcript rows to seek the raw video.
- Defer draggable clip-edge editing until after the MVP proves useful.

## Implementation Notes

- Implemented in `frontend/src/App.tsx` and `frontend/src/App.css`.
- Vite dev server proxies `/api` and `/media` to the FastAPI server on port 8000.
- Timeline blocks are sentence-based and sized by sentence duration.

## Acceptance Criteria

- [x] Timeline renders sentence decisions as interactive visual blocks
- [x] Video playback with scrubbing
- [x] Sentence-level keep/cut controls adjust review decisions
