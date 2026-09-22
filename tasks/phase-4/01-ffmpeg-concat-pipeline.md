# FFmpeg Concat Pipeline

Status: `done`
Phase: 4
Depends on: phase-3 (edit decision list)

## Objective

Build FFmpeg filter chains from the edit decision list to concatenate surviving video/audio segments into a single rendered output.

## Requirements

- Read `EditDecisionList` JSON and extract all `keep` segments.
- For each keep segment, trim the source video to the exact `(start, end)` timestamps.
- Use **noise-reduced audio** (from Phase 1 denoised WAV) as the audio source, not the original video audio.
- Always **re-encode** (no stream-copy) — cuts are at sentence boundaries, not keyframes.
- Output codec: **H.265 (libx265)**, CRF 18, preset `slow`.
- Concatenate all trimmed segments into a single continuous output.
- Output file: `<stem>_edited.mp4` alongside the original video.

## Implementation Notes

- Use `ffmpeg-python` or direct `subprocess` calls to FFmpeg.
- Strategy: build an FFmpeg complex filter graph with `trim`/`atrim` + `concat` filter, or use the concat demuxer with intermediate segments.
- The concat filter approach is cleaner for re-encoding: trim each segment in the filter graph, then concat them all.
- Audio source: align the denoised WAV timestamps with the video — they share the same timeline since denoising doesn't shift timestamps.
- Video-only jump cuts are acceptable (no visual dissolve) since content is screen recordings without a face.

## Acceptance Criteria

- [x] Keep segments extracted from EDL
- [x] All keep segments concatenated via FFmpeg re-encode
- [x] Noise-reduced audio used as audio source
- [x] H.265 CRF 18, preset slow
- [x] Output `<stem>_edited.mp4` alongside input
- [x] Output video plays correctly with no sync issues
