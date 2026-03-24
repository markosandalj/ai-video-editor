# Production Render Settings

Status: `pending`
Phase: 6
Depends on: phase-4 complete

## Objective

Switch render defaults from fast development settings to production-quality output for final delivery.

## Requirements

- Change default codec from `libx264` to `libx265`.
- Change default CRF from `28` to `18` (visually lossless).
- Change default preset from `ultrafast` to `slow` (best compression at high quality).
- Verify output quality on real test videos before shipping.

## Implementation Notes

- This is a one-line config change in `RenderConfig` defaults in `settings.py`.
- During development we use `libx264 / CRF 28 / ultrafast` for fast iteration.
- Production target: `libx265 / CRF 18 / slow` for best quality and compression.

## Acceptance Criteria

- [ ] Default codec: libx265
- [ ] Default CRF: 18
- [ ] Default preset: slow
- [ ] Output quality verified on test videos
