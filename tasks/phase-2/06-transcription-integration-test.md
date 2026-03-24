# Transcription Integration Test

Status: `done`
Phase: 2
Depends on: 2.01, 2.03, 2.04

## Objective

End-to-end validation: raw video in, sentence-level transcript with precise timestamps out.

## Requirements

- Full pipeline: video → audio extraction → denoise → WhisperX → words → sentences
- Test on real sample files (Croatian lecture recordings)
- Verify timestamps are reasonable (not drifted, not negative)
- Verify sentence boundaries make linguistic sense

## Implementation Notes

- Run on test-2-raw.mp4 (shorter, 4 min)
- Spot-check: pick 3-5 sentences, verify start/end timestamps against video
- Automated: verify no zero-duration sentences, all timestamps monotonically increasing
- Output cached transcript.json for manual inspection

## Acceptance Criteria

- [x] Full pipeline runs: video → audio → denoise → WhisperX → words → sentences
- [x] Timestamps present and reasonable (first word at 1.168s, last word near end)
- [x] Output JSON well-formed: 24 sentences, 697 words, cached to disk
