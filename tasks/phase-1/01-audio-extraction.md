# Audio Extraction

Status: `done`
Phase: 1
Depends on: phase-0 complete

## Objective

Extract audio track from input video files to WAV format for downstream processing (noise reduction, transcription).

## Requirements

- Use `ffmpeg-python` wrapper to call FFmpeg
- Keep the source's original sample rate (no forced resampling at extraction)
- Downstream steps handle their own resampling as needed (e.g., Whisper needs 16kHz)
- Support common formats: MP4, MOV, MKV, AVI, WEBM, M4V
- Keep intermediate WAV in `temp_dir` for debugging
- Add `AudioConfig` section to Settings (sample_rate override if ever needed)

## Implementation Notes

- FFmpeg is installed at `/opt/homebrew/bin/ffmpeg` (v7.1.1)
- Create `ai_video_editor/audio/` module (incremental module addition)
- `extract_audio(input_path, output_path, settings) -> Path`
- Output: mono WAV (single channel simplifies all downstream processing)
- Use `ffmpeg.input(...).output(..., acodec='pcm_s16le', ac=1).run()`
- Handle errors: missing audio track, corrupted file, unsupported codec

## Acceptance Criteria

- [x] Extracts audio from MP4, MOV, MKV files to WAV
- [x] Preserves original sample rate (48kHz from test files)
- [x] Outputs mono WAV (single channel)
- [x] Handles edge cases (no audio track raises RuntimeError)
- [x] `AudioConfig` added to Settings
