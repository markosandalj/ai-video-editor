# Final Render Orchestration

Status: `done`
Phase: 4
Depends on: 4.01, 4.03, 4.04

## Objective

Combine all assembly steps into a single render pipeline: noise-reduced audio + trimmed segments + crossfades -> final MP4.

## Requirements

- Single function: `render_video(video_path, edl, denoised_audio_path, settings) -> Path`.
- Reads EDL keep segments, builds FFmpeg filter graph with audio crossfades, produces `<stem>_edited.mp4`.
- Codec: H.265 (libx265), CRF 18, preset slow.
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
- [x] Output codec (H.265) and quality (CRF 18, slow) configurable via `RenderConfig`
- [x] Render completes without manual intervention
- [x] Integrated into existing CLI process/batch commands
