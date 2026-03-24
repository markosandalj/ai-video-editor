# Duplicate Detection Tests

Status: `done`
Phase: 3
Depends on: 3.04, 3.05

## Objective

Verify duplicate detection precision and recall with synthetic and real transcripts.

## Requirements

- Synthetic transcripts with known duplicates correctly detected.
- Paraphrased duplicates detected (semantic tier).
- Legitimate recaps/summaries not flagged (no false positives).
- False starts between duplicates correctly identified.
- Use `test-2-raw.mp4` vs `test-2-edited.mp4` as a real-world test case (the edited version IS the ground truth of what a human editor kept).

## Implementation Notes

- Build 2-3 synthetic Croatian transcript fixtures with:
  - Exact repeats (should be caught by lexical tier)
  - Paraphrased repeats (should be caught by semantic tier)
  - Legitimate recap at the end (should NOT be flagged)
  - False starts between a mistake and correction
- Compare pipeline output against `test-2-edited.mp4` transcript to measure real-world accuracy.
- Precision and recall numbers don't need to be perfect for V1, but should be documented.

## Acceptance Criteria

- [x] Synthetic transcripts with known duplicates correctly detected (23 tests)
- [x] Paraphrased duplicates detected (semantic tier test)
- [x] Legitimate recaps/summaries not flagged (window boundary test)
- [x] False starts between duplicates correctly identified (Gemini integration)
- [ ] Real-world test against test-2 video pair (deferred to integration run)
- [ ] Precision and recall measured and documented (deferred to integration run)
