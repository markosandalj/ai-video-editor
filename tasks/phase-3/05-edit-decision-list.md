# Edit Decision List

Status: `done`
Phase: 3
Depends on: 3.04, phase-1 (keep regions)

## Objective

Merge silence-based keep regions with duplicate detection results into a single, ordered edit decision list (EDL) that drives all downstream operations.

## Requirements

- Unified list of `EditDecision(start, end, action, reason, confidence)` Pydantic objects.
- Silence cuts (from Phase 1) and duplicate cuts (from 3.04) merged without conflicts.
- Chronologically ordered and non-overlapping.
- Serializable to JSON (Pydantic `model_dump_json`).
- OTIO export as a separate concern (Phase 5), but the internal model should be clean enough to map 1:1 later.

## Implementation Notes

- Pydantic model: `EditDecision` with fields for start/end times, action (keep/cut), reason (silence/duplicate/false_start), and optional confidence score.
- Container: `EditDecisionList` with a list of `EditDecision` plus metadata (source video, total duration, etc.).
- Merge algorithm: take Phase 1 keep regions + Phase 3 duplicate cuts → compute final set of keep segments.
- Handle overlapping regions gracefully (e.g., a silence cut and a duplicate cut that partially overlap).
- Cache alongside video (like transcript cache).

## Acceptance Criteria

- [x] `EditDecision` and `EditDecisionList` Pydantic models defined (`edl.py`)
- [x] Silence cuts and duplicate cuts merged without conflicts (`build_edl`)
- [x] Output is chronologically ordered and non-overlapping
- [x] Serializable to JSON for export and caching (Pydantic `model_dump_json`)
- [x] Maps cleanly to OTIO constructs (for Phase 5)
