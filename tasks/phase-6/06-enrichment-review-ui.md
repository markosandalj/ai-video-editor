# Enrichment Metadata in the Review UI

Status: `done`
Phase: 6
Depends on: 6.03 (React timeline UI), phase-5 (transcript metadata enrichment)

## Objective

Surface the Phase 5 enrichment metadata (per-sentence status/tags/confidence/rationale and
per-word salience) inside the existing word-level review editor so editors can triage and fix the
remaining ~10% of errors as fast as possible.

## Requirements

- Regenerate the frontend OpenAPI types so `ReviewSentence` exposes `status`, `tags`,
  `keep_confidence`, and `rationale`.
- Sentence status (green/yellow/red/restore) shown as a colored left-edge stripe plus a small
  status dot in the timestamp gutter. No bulky per-sentence chrome.
- Per-word salience: only de-emphasize very-low-salience AI-kept words as "trim candidates"
  (faded / dotted underline). Do not full-heatmap every word.
- Navigation: keep the existing "Next AI cut" jump and add a "Next attention item" jump that
  cycles through yellow/red kept sentences and restore-suggested cuts.
- A compact detail strip near the video shows the currently active/selected sentence's rationale
  (Croatian), tags, and keep confidence.
- Restore suggestions (AI cut but enrichment status = restore) get a distinct "restore?" marker on
  the cut span and are included in attention navigation.
- An "attention-only" focus toggle dims confident green sentences (kept visible at low opacity) so
  reviewers can scan for work.

## Implementation Notes

- Frontend lives in `frontend/src/App.tsx` (+ supporting `frontend/src/api/*`, styling via Tailwind
  classes / CSS variables).
- Backend already emits enrichment fields through `ReviewSentence`/`ReviewWord`
  (`ai_video_editor/review/export.py`); `keep_score` on AI-kept words is the salience signal.
- Status taxonomy: green = confident keep, yellow = needs review, red = likely cut/keep mismatch,
  restore = AI cut but probably should be kept.
- Keep the editor compact and keyboard-driven; new affordances must not slow the existing flow.

## Acceptance Criteria

- [x] Frontend types include enrichment fields and build cleanly
- [x] Sentence status visible via gutter stripe + dot
- [x] Low-salience kept words flagged as trim candidates (threshold 0.1 ≈ near-zero salience)
- [x] "Next attention item" navigation works alongside "Next AI cut" (key: A)
- [x] Active-sentence detail strip shows rationale + tags + confidence
- [x] Restore suggestions are marked ("restore?" pill) and reachable via navigation
- [x] Attention-only focus toggle dims green sentences

## Verification

Verified live against `test-1-raw` (95 sentences: 48 green / 30 yellow / 14 red / 3 restore):
gutter stripes/dots render, "47 to review" badge, detail strip shows Croatian rationale + `filler
phrase` tag + "40% keep", "Attention (A)" cycles attention items, restore pills render inline, and
"Attention only" dims confident green sentences. `npm run lint` and `npm run build` pass.
