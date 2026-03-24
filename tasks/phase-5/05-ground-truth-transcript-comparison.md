# Ground Truth Transcript Comparison

Status: `pending`
Phase: 5
Depends on: phase-4 (rendered video), manually edited reference video

## Objective

Compare the transcript of our pipeline's edited video against the transcript of the manually edited video to measure how accurately our automated cuts match a human editor's decisions.

## Requirements

_To be filled during grilling session._

## Implementation Notes

_To be filled during grilling session._

## Acceptance Criteria

- [ ] Transcribe both the pipeline output and the manually edited video
- [ ] Sentence-level comparison: which sentences were kept/cut by each
- [ ] Precision and recall metrics computed (vs. human edit as ground truth)
- [ ] Report of false positives (we cut something the human kept) and false negatives (we kept something the human cut)
