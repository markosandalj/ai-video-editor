# ElevenLabs Scribe Integration

Status: `done`
Phase: 2
Depends on: phase-1 complete

## Objective

Transcribe Croatian recordings through ElevenLabs Scribe with word timestamps and
separate non-speech audio events.

## Requirements

- Language is configurable and defaults to Croatian (`hr`).
- Model defaults to `scribe_v2`.
- Accept the denoised audio produced by Phase 1.
- Preserve word-level timestamps.
- Keep coughs and other audio events separate from transcript text.
- Read `ELEVENLABS_API_KEY` from the environment.

## Implementation Notes

- Implemented in `ai_video_editor/transcription/elevenlabs_stt.py`.
- The provider handles media decoding and returns timestamped tokens.
- `TranscriptionConfig` controls language, model id, event tagging, sentence pause
  splitting, and the later grammar pass.

## Acceptance Criteria

- [x] Scribe returns Croatian words with timestamps.
- [x] Audio-event tokens are preserved separately.
- [x] Transcription settings are configurable.
- [x] No local WhisperX model or forced-alignment dependency is required.
