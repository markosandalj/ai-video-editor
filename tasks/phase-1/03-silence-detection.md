# Silence Detection

Status: `done`
Phase: 1
Depends on: 1.02 (runs on noise-reduced audio)

## Objective

Detect all silent regions in the (noise-reduced) audio track, producing precise start/end timestamps for each silence.

## Requirements

- Use FFmpeg's `silencedetect` filter for speed (operates on audio stream directly)
- Default threshold: -40 dB
- Minimum silence duration: 3 seconds
- Both values configurable in `AudioConfig`
- Output: list of `SilenceRegion(start, end, duration)` objects

## Implementation Notes

- Run via `ffmpeg-python`: pipe to `silencedetect` filter, parse stderr for timestamps
- Parse `silence_start` and `silence_end` lines from FFmpeg output
- Runs on the noise-reduced WAV (not raw audio) since noise reduction happens first
- Add `silence_threshold_db` (default -40) and `silence_min_duration_s` (default 3.0) to `AudioConfig`
- Define `SilenceRegion` Pydantic model in `ai_video_editor/audio/models.py`

## Acceptance Criteria

- [x] Silence regions detected with configurable dB threshold and minimum duration
- [x] Output is a list of SilenceRegion objects with start, end, duration
- [x] Works reliably on noise-reduced audio
- [x] FFmpeg stderr parsed correctly for silence timestamps
