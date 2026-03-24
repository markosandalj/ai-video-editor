# WhisperX Integration

Status: `done`
Phase: 2
Depends on: phase-1 complete

## Objective

Integrate WhisperX for transcription with VAD pre-segmentation and Wav2Vec2 forced alignment, producing word-level timestamps.

## Requirements

- Default model size: `small`
- Compute device: MPS (Apple Silicon), configurable
- Input: noise-reduced audio from Phase 1
- Language: Croatian (`hr`), configurable
- Alignment model: `classla/wav2vec2-xls-r-parlaspeech-hr`
- Load/unload model per video (don't keep in GPU memory across batch)
- Hugging Face token: user will create one if needed for alignment model download
- Add `TranscriptionConfig` to Settings

## Implementation Notes

- Create `ai_video_editor/transcription/` module
- WhisperX handles 16kHz resampling internally
- Feed denoised WAV path to WhisperX
- `TranscriptionConfig`: model_size, device, language, batch_size
- Model lifecycle: load -> transcribe -> align -> unload per video
- HF token stored in env or passed via config (not hardcoded)

## Acceptance Criteria

- [x] WhisperX transcribes Croatian audio with word-level timestamps (697 words from 4min test)
- [x] Forced alignment via wav2vec2 produces precise word boundaries
- [x] Model loads/unloads per video via gc.collect()
- [x] Configurable model size, device, and language via TranscriptionConfig
- Note: MPS not supported by WhisperX/ctranslate2, using CPU. Device set to "cpu" by default.
