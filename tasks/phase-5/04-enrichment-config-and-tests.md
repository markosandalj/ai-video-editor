# Enrichment Config & Tests

Status: `done`
Phase: 5
Depends on: 5.02, 5.03

## Objective

Make the enrichment pass configurable and well-tested so thresholds and the model can be tuned without code changes and regressions are caught.

## Requirements

(Locked in Phase 5 grilling, 2026-06-10)

- `EnrichmentConfig` in `ai_video_editor/config/settings.py`:
  - `enabled: bool = True` (on by default; `--no-enrich` overrides)
  - `model` — defaults to the Gemini **pro** tier; reuse Gemini config conventions
  - `temperature: float = 0.1`
  - `batch_size: int` for sentence batching
  - `green_threshold: float = 80.0` (kept ≥ this → green, else yellow)
  - `restore_threshold: float = 60.0` (cut ≥ this → restore, else red)
- CLI: `--no-enrich` flag to skip enrichment for a run; `--force` recomputes the cached `*.enrichment.json`.
- Tests:
  - `derive_status` across all four outcomes (green/yellow/red/restore) at the threshold boundaries
  - `word_salience` reconciliation: correct length, too short, too long, empty → safe fallback
  - Model round-trip to/from `*.enrichment.json`
  - `build_review_payload` maps enrichment → `ReviewSentence`/`ReviewWord`: yellow on kept-but-uncertain, restore on cut, `keep_score` from salience
  - Fallback path when the enrichment sidecar is absent or enrichment disabled
  - `enrich_transcript` with a mocked/stubbed LLM (no live API calls in unit tests), mirroring how grammar/duplicate tests stub the model

## Implementation Notes

- Follow the existing config dataclass/pydantic pattern in `settings.py`.
- Unit tests stub the LangChain model so they run offline (duplicate/grammar tests already establish this pattern).
- Keep defaults conservative (bias toward `yellow`/`restore` over false `green`) so the editor is never lulled into trusting a risky chunk; tune later with real footage.

## Acceptance Criteria

- [x] `EnrichmentConfig` with enable flag, model (pro), temperature, batching, and both thresholds
- [x] `--no-enrich` and `--force` honored
- [x] Tests for status derivation (4 outcomes), salience reconciliation, serialization, payload mapping, and fallback
- [x] Gemini pass tested with a stubbed LLM (offline)
