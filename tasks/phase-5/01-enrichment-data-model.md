# Enrichment Data Model & Tag Taxonomy

Status: `done`
Phase: 5
Depends on: phase-3 (edit decision list)

## Objective

Define the per-chunk metadata schema that lets a human editor instantly see which kept parts are 100% safe, which kept parts (though not cut) deserve a second look, and which cut parts the model thinks might actually belong. This is the contract every downstream consumer (EDL, JSON export, review UI) builds on.

## Requirements

(Locked in Phase 5 grilling, 2026-06-10)

- A per-sentence enrichment record with:
  - `keep_confidence`: float 0–100 — the LLM's confidence that this chunk belongs in the final video. **This is the source of truth**; `status` is derived from it deterministically.
  - `status`: derived signal with **four** values:
    - `green` — kept and safe, no attention needed
    - `yellow` — kept, but flagged for human review
    - `red` — cut by the pipeline, model agrees
    - `restore` — cut by the pipeline, but the model thinks it may belong (maybe-keep suggestion)
  - `tags`: list of typed labels from the closed taxonomy.
  - `rationale`: one short sentence **in Croatian** explaining the score/tags (the professor/editor reads it).
  - `word_salience`: list of floats 0–100, one per word in the sentence (aligned to the sentence's word tokens) — lets the editor see which words inside a sentence are core vs filler.
- Tag taxonomy (closed enum, extendable):
  - `verbatim_clean`, `minor_disfluency`, `filler_phrase`, `redundant_explanation`,
    `off_topic_aside`, `technical_term_check`, `low_audio_confidence`,
    `repetition_residue`, `incomplete_thought`, `needs_review`
- The enrichment is **additive**: it never changes the EDL keep/cut decision. `red`/`restore` annotate existing cuts; `yellow` annotates kept content; `restore` is purely a suggestion.
- Schema is versioned (`enrichment.v1`) and serializable to a `*.enrichment.json` sidecar.

## Implementation Notes

- New module `ai_video_editor/enrich/models.py` with Pydantic models:
  - `EnrichmentTag(str, Enum)`
  - `EnrichmentStatus(str, Enum)` = green | yellow | red | restore
  - `SentenceEnrichment(sentence_idx, keep_confidence, status, tags, rationale, word_salience)`
  - `EnrichmentResult(schema_version, source_video, sentences: list[SentenceEnrichment])`
- Deterministic status helper (config-driven thresholds), not decided by the LLM:
  - kept sentence: `green` if `keep_confidence >= green_threshold (80)` else `yellow`
  - cut sentence: `restore` if `keep_confidence >= restore_threshold (60)` else `red`
- `word_salience` length must equal the sentence's word count. Reconciliation lives here: if the LLM returns a mismatched length, pad/truncate or fall back to filling every word with the sentence `keep_confidence` (defensive — never throw).
- Keep models independent of `EditDecision`/`Sentence` so the pass stays self-contained.

## Acceptance Criteria

- [x] `EnrichmentTag` and `EnrichmentStatus` (4 values) enums
- [x] `SentenceEnrichment` (incl. `word_salience`) and `EnrichmentResult`, versioned
- [x] Deterministic `derive_status(keep_confidence, is_cut, config)` covering green/yellow/red/restore
- [x] `word_salience` reconciliation helper with safe fallback on length mismatch
- [x] Round-trips to/from `*.enrichment.json`
