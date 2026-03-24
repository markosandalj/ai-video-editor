# Splice Quality Analysis

Status: `done`
Phase: 5
Depends on: phase-4 (rendered video)

## Objective

Automatically detect harsh audio splices (pops/clicks) at cut boundaries in the rendered video.

## Requirements

- Extract audio from the rendered `_edited.mp4` file.
- At each EDL cut boundary, extract a 50ms audio window (25ms before, 25ms after the splice point).
- Compute the amplitude delta across the splice point.
- Flag splice points where the delta exceeds a configurable threshold as "harsh transitions".
- This verifies our 30ms audio crossfade is actually working in the rendered output.

## Implementation Notes

- Use `scipy` / `numpy` to load the rendered audio and measure amplitude deltas at splice boundaries.
- Splice points are derived from the EDL keep regions (the transition between one keep segment's end and the next's start in the rendered timeline).
- Output: list of splice points with their amplitude delta and pass/fail status.

## Acceptance Criteria

- [ ] 50ms audio window extracted at each cut boundary
- [ ] Amplitude delta across splice point measured
- [ ] Harsh transitions flagged when exceeding threshold
