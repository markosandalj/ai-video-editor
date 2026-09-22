# Final Render Orchestration

Status: `done`
Phase: 4
Depends on: 4.01, 4.03, 4.04

## Objective

Combine all assembly steps into a single render pipeline: noise-reduced audio + trimmed segments + crossfades -> final MP4.

## Requirements

- Single function: `render_video(video_path, edl, denoised_audio_path, settings) -> Path`.
- Reads EDL keep segments, builds FFmpeg filter graph with audio crossfades, produces `<stem>_edited.mp4`.
- Codec, CRF, and preset are configurable. The implemented development defaults
  are H.264 through `libx264`, CRF 28, and `ultrafast`; this historical task does
  not define the later production profile.
- Audio crossfade: 30ms at splice points.
- No intro/outro (deferred).
- All parameters configurable via `RenderConfig` in settings.

## Implementation Notes

- This is the orchestration function that ties 4.01, 4.03, and 4.04 together.
- Practically, these three tasks likely merge into a single FFmpeg command with a complex filter graph.
- Add `RenderConfig` to `Settings` with fields: `codec`, `crf`, `preset`, `crossfade_ms`, `output_suffix`.
- Integrate into the existing `process` and `batch` CLI commands — no separate render command.

## Acceptance Criteria

- [x] Single function `render_video()` produces final MP4 from raw input + EDL + denoised audio
- [x] Output codec, CRF, and preset configurable via `RenderConfig`
- [x] Render completes without manual intervention
- [x] Integrated into existing CLI process/batch commands
