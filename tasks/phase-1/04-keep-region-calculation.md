# Keep-Region Calculation

Status: `done`
Phase: 1
Depends on: 1.03

## Objective

Invert silence regions into "keep" segments with padding margins, producing the list of audio/video segments to retain.

## Requirements

- Invert silence regions to get speech regions
- Apply 500ms padding before and after each speech segment (configurable)
- Merge adjacent keep regions when the gap between them is smaller than `silence_min_duration`
- Clamp padding to file boundaries (don't go below 0 or beyond total duration)
- Output: list of `KeepRegion(start, end)` objects, chronologically ordered, non-overlapping

## Implementation Notes

- Padding value in `AudioConfig`: `padding_ms` (default 500)
- Algorithm: take complement of silence regions -> expand each by padding -> merge overlapping -> clamp to [0, total_duration]
- Define `KeepRegion` Pydantic model in `ai_video_editor/audio/models.py`
- Need total audio duration (from extraction step or ffprobe)

## Acceptance Criteria

- [x] Keep regions are the inverse of silence regions
- [x] 500ms padding applied before and after each speech segment
- [x] Adjacent keep regions merge when gaps are smaller than minimum silence duration
- [x] No overlapping or out-of-order regions in output
- [x] Padding clamped to file boundaries
