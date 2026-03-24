# Micro-Crossfade at Cuts

Status: `done`
Phase: 4
Depends on: 4.01

## Objective

Apply short audio crossfades at splice boundaries to prevent audible pops and clicks.

## Requirements

- Apply **30ms audio crossfade** at every splice point (cut → keep transition).
- **Audio only** — no visual dissolve/crossfade. Jump cuts are fine for screen recordings.
- Crossfade duration configurable via `RenderConfig.crossfade_ms` (default 30).
- Must handle edge cases: very short segments where crossfade would exceed segment length.

## Implementation Notes

- Implement as part of the FFmpeg filter graph in task 4.01 — use `acrossfade` filter between adjacent audio segments.
- Alternative: apply fade-in/fade-out on each audio segment's boundaries (`afade=t=in:d=0.03`, `afade=t=out:d=0.03`) which is simpler and avoids the complexity of pairwise crossfade.
- The fade-in/fade-out approach is more robust when segments vary widely in length.

## Acceptance Criteria

- [x] Audio crossfade/fade applied at every splice point (afade in/out per segment)
- [x] Crossfade duration configurable (default 30ms) via `RenderConfig.crossfade_ms`
- [x] No audible pops/clicks at cut boundaries
- [x] No visual crossfade (audio only)
