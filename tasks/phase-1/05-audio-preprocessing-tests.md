# Audio Pre-Processing Tests

Status: `done`
Phase: 1
Depends on: 1.01, 1.02, 1.03, 1.04

## Objective

Validate that the full audio pre-processing pipeline works correctly end-to-end with real sample files.

## Requirements

- User will provide real sample video files for testing
- Test the full chain: extract -> denoise -> silence detect -> keep regions
- Verify intermediate files are kept in temp_dir
- Verify keep regions produce natural-sounding results when concatenated

## Implementation Notes

- User provides sample files (not synthetic)
- Test runner: `pytest` (add as dev dependency)
- Manual spot-check: user listens to concatenated keep regions for quality
- Automated checks: verify region count, no zero-duration regions, regions are ordered and non-overlapping

## Acceptance Criteria

- [x] Test with at least one real sample recording (test-2-raw.mp4, 257.8s)
- [x] Noise reduction does not clip speech
- [x] Silence detection finds expected silences (5 regions, 18s total)
- [x] Keep regions + padding produce natural-sounding results (6 segments, 95% retained)
- [x] All intermediate files present in temp_dir (raw.wav + denoised.wav)
