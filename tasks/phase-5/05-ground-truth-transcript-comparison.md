# Ground Truth Transcript Comparison

Status: `done`
Phase: 5
Depends on: phase-4 (rendered video), manually edited reference video

## Objective

Compare the transcript of our pipeline's edited video against the transcript of the manually edited video to measure how accurately our automated cuts match a human editor's decisions.

## Requirements

- **Transcribe both edited videos independently** using ElevenLabs:
  - Our pipeline output (`<name>-raw_edited.mp4`)
  - The human-edited ground truth (`<name>-edited.mp4`)
- Fuzzy-match sentences between the two transcripts to determine overlap.
- Compute **precision** (of our kept sentences, how many match the human's) and **recall** (of the human's kept sentences, how many did we also keep).
- Report **false positives** (we kept something the human cut) and **false negatives** (we cut something the human kept).
- Must handle mid-sentence trims (the human editor sometimes cuts partway through a sentence).
- Test pairs discovered by naming convention: `<name>-raw.mp4` + `<name>-edited.mp4` in the same folder.
- System built for N pairs from the start (more will be added over time).

## Implementation Notes

- Use ElevenLabs for both transcriptions (consistent transcriber reduces noise in comparison).
- Fuzzy matching via `rapidfuzz` at sentence level; may need word-level fallback for mid-sentence trims.
- Output: per-pair precision, recall, F1 score, plus a list of mismatches with the actual sentence text.

## Acceptance Criteria

- [ ] Transcribe both the pipeline output and the manually edited video
- [ ] Sentence-level comparison: which sentences were kept/cut by each
- [ ] Precision and recall metrics computed (vs. human edit as ground truth)
- [ ] Report of false positives (we cut something the human kept) and false negatives (we kept something the human cut)
