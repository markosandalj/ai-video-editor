# Pipeline & EDL Integration (Backend + Payload Contract)

Status: `done`
Phase: 5
Depends on: 5.01, 5.02

## Objective

Wire the enrichment pass into the processing pipeline and thread its metadata through the review JSON contract, so a later frontend phase can render green/yellow/red/restore and per-word salience. **This phase is backend-only — no React/UI changes.**

## Requirements

(Locked in Phase 5 grilling, 2026-06-10)

- The pipeline runs enrichment as its own step **after** duplicate detection / EDL construction and **before** the JSON export.
- Enrichment runs on **all** sentences (kept and cut); the valuable new signals are `yellow` on kept chunks and `restore` on cut chunks.
- Enrichment must **not** mutate keep/cut decisions — the rendered automated edit is byte-for-byte identical with enrichment on vs off.
- **On by default**; `--no-enrich` skips it. Persist `*.enrichment.json` next to `*.edl.json` / `*.transcript.json`; reuse cache unless `--force`.
- Extend the review payload (backend data contract only) so the metadata is available to consumers:
  - `ReviewSentence` carries `status`, `tags`, `keep_confidence`, `rationale`.
  - `ReviewWord.keep_score` is populated from `word_salience` (replacing the current `keep_score = 1.0` shortcut for kept words). Cut words keep the existing reason/confidence path.
  - Cut sentences with `status == restore` are marked so a future UI can offer a restore hint.
- Defensive fallback: if no `*.enrichment.json` exists (older processed videos, or `--no-enrich`), `build_review_payload` behaves exactly as it does today.
- **Out of scope this phase:** any change to `frontend/` — surfacing yellow/restore/salience in the React editor is the next phase.

## Implementation Notes

- Add the step to the pipeline orchestrator (where `detect_duplicates` / EDL build happens).
- Touch points: `pipeline` (new step + sidecar write), `ai_video_editor/review/models.py` (new fields on `ReviewSentence`/`ReviewWord`), `ai_video_editor/review/export.py` (`build_review_payload` loads the enrichment sidecar and maps it on).
- Map `SentenceEnrichment.word_salience` onto the sentence's `ReviewWord.keep_score` by index; fall back to the sentence `keep_confidence` if lengths disagree (use 5.01's reconciliation helper).
- Keep the mapping additive and backward-compatible so the existing review UI keeps working unchanged.

## Acceptance Criteria

- [x] Pipeline produces `*.enrichment.json` as a discrete post-EDL step, on by default
- [x] EDL keep/cut output is identical with enrichment on vs off (enrichment is additive)
- [x] `ReviewSentence` exposes `status`, `tags`, `keep_confidence`, `rationale`
- [x] `ReviewWord.keep_score` comes from `word_salience` (no more hardcoded 1.0 for kept words)
- [x] Cut sentences flagged `restore` are represented in the payload
- [x] Missing/disabled enrichment falls back to today's behavior (no crash, UI unaffected)
- [x] No changes under `frontend/`
