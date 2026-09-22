# Spectral Noise Reduction

Status: `done`
Phase: 1
Depends on: 1.01

## Objective

Remove background noise (fan hum, stylus taps, HVAC) from extracted audio without degrading vocal quality, using spectral gating.

## Requirements

- Library: `noisereduce`
- Non-stationary mode only (adapts to changing noise floor)
- Noise profile: auto-detect from silent zones (no manual noise sample support)
- Runs BEFORE silence detection (cleaner audio improves silence detection accuracy)
- Output: noise-reduced WAV saved to `temp_dir`
- Configurable: `prop_decrease` (noise reduction strength) in `AudioConfig`

## Implementation Notes

- `noisereduce.reduce_noise(y=audio, sr=sample_rate, stationary=False)`
- Load audio via `librosa.load()` or `soundfile.read()` at native sample rate
- Write output via `soundfile.write()`
- Auto noise profile: `noisereduce` handles this internally when `y_noise` is not provided
- Add `noise_reduction_strength` (prop_decrease, default 1.0) to `AudioConfig`

## Acceptance Criteria

- [x] Background noise visibly reduced in spectrogram comparison
- [x] Speech clarity preserved (no clipping of plosives/fricatives)
- [x] Non-stationary noise handling works (adapts to changing noise floor)
- [x] Output WAV written to temp_dir
