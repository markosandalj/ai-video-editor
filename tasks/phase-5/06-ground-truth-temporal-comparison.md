# Ground Truth Temporal Comparison

Status: `done`
Phase: 5
Depends on: phase-4 (rendered video), manually edited reference video

## Objective

Compare the timing and duration of our pipeline's cuts against the manually edited video to measure temporal accuracy — are we cutting at the right moments and keeping the right amount of content?

## Requirements

- Compare total duration of our edited video vs the human-edited video.
- Align cut points between the two edits to measure timing accuracy.
- Compute per-cut-point offset (how far off each of our cuts is from the human's nearest cut).
- Overall temporal similarity score.
- Both metrics (precision/recall from 5.05 and temporal score from here) weighted equally in the final assessment.

## Implementation Notes

- Duration comparison is trivial (ffprobe both files).
- For cut-point alignment: extract word-level timestamps from both transcriptions, find matching words, measure the time offset at those anchor points.
- Output: duration delta, per-anchor timing offset, overall temporal similarity score (0-1).

## Acceptance Criteria

- [ ] Duration comparison between pipeline output and human edit
- [ ] Timeline alignment: map our cut points to the human's cut points
- [ ] Measure timing drift / offset at each cut boundary
- [ ] Score overall temporal similarity
