# Spectrogram Comparison

Status: `done`
Phase: 5
Depends on: phase-4 (rendered video)

## Objective

Verify rendered audio matches expected output by comparing spectrograms.

## Requirements

- Generate spectrograms for the rendered audio and the expected audio (constructed by virtually concatenating the denoised WAV keep segments).
- Compute SSIM or cross-correlation between the two spectrograms.
- Flag severe deviations as potential encoding/muxing failures.
- Safety net to catch FFmpeg encoding bugs, dropped frames, or sync drift.

## Implementation Notes

- Use `librosa` or `scipy` for spectrogram generation.
- The "expected" spectrogram comes from the denoised WAV segments stitched in memory (no re-encode), so any difference is attributable to the FFmpeg render step.
- Output: similarity score and flag if below threshold.

## Acceptance Criteria

- [ ] Spectrograms generated for rendered audio and expected audio
- [ ] SSIM or cross-correlation computed between them
- [ ] Severe deviations flagged as potential encoding/muxing failures
