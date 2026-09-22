# Audio-Video Muxing

Status: `done`
Phase: 4
Depends on: 4.01, phase-1 (noise-reduced audio)

## Objective

Mux noise-reduced audio with trimmed video, ensuring perfect sync.

## Requirements

- Always use the **noise-reduced (denoised) audio** from Phase 1 as the audio source.
- The denoised WAV shares the same timeline as the original video — timestamps align directly.
- In the FFmpeg filter graph: use the denoised WAV as audio input, original MP4 as video input.
- Trim both audio and video to the same EDL keep regions so they stay in sync.

## Implementation Notes

- This is effectively part of task 4.01's filter graph rather than a separate step. The FFmpeg command takes two inputs: (1) original video (for video stream), (2) denoised WAV (for audio stream).
- Both streams are trimmed to the same keep regions and concatenated together.
- If there's any sub-millisecond duration mismatch, pad the shorter stream with silence/freeze.

## Acceptance Criteria

- [x] Noise-reduced audio correctly replaces original audio track
- [x] Audio and video remain in sync throughout
- [x] Duration mismatches from processing handled gracefully
