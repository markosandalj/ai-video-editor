# Production Render Settings

Status: `pending`
Phase: 7
Depends on: phase-4 complete

## Objective

Tune and validate production-quality render output after the cross-application
end-to-end integration is working.

## Requirements

- Do not block the current Gradivo/worker integration milestone on final video
  settings; the existing configurable renderer is sufficient for the first real
  end-to-end video.
- After that tracer bullet works, define codec, resolution, frame rate, color,
  quality, audio, and splice settings from representative production inputs.
- Verify output quality and resource cost on real videos before promoting a
  production-quality configuration.

## Implementation Notes

- Render settings remain worker configuration rather than caller-supplied API
  fields.
- The worker must snapshot resolved settings with each accepted immutable render
  job so later configuration changes do not alter retries of the same UUID.

## Acceptance Criteria

- [ ] Initial real `analysis` and `render` tracer bullet complete
- [ ] Representative production inputs and resource measurements collected
- [ ] Exact production render settings settled
- [ ] Output quality verified on test videos
