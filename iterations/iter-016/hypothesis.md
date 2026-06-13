# Iteration 016 — Hypothesis

## Problem
1,087 missed cuts (cut recall 0.443). Analysis shows 85.7% are clean content
both the pipeline and an independent LLM judge consider keep-worthy — an
editorial/pacing decision invisible at the transcript level, hence unrecoverable
without hurting precision. A small, clearly-separable slice is pure transcription
junk: punctuation-only fragments (`"."`, `"..."`) and 1–2 word interjections
(`"Aaaaj."`, `"Ne."`) that enrichment already scores near-zero but the
duplicate-anchored pipeline keeps because they aren't duplicates/asides.

## Hypothesis
Adding a tightly-scoped artifact extra-cut in the enrichment arbiter — cut a
still-kept sentence that is punctuation-only OR ≤2 words **and** has enrichment
`keep_confidence < 25` — recovers these junk frames without touching real
content.

## Change plan
- `ai_video_editor/config/settings.py`: add `arbiter_artifact_max_words` (=2) and
  `arbiter_artifact_confidence` (=25.0) to `EnrichmentConfig`.
- `ai_video_editor/enrich/arbiter.py`: in the extra-cut pass, add an artifact
  branch (`_is_artifact(sentence, max_words)` = punctuation-only text OR word
  count ≤ max_words) gated on `keep_confidence < arbiter_artifact_confidence`.
  Emit a `FILLER` flag (maps to `false_start` in the EDL). This is independent of
  the existing tag-gated extra-cut.

Exactly one change: artifact cleanup. No threshold changes to existing rules.

## Risk
Cutting a meaningful short answer (e.g. *"Točno."* / "Correct.") if enrichment
mis-scores it low. Mitigated by the `keep_confidence < 25` guard — in the offline
sim this produced **0** new false positives across all 98 videos.

## Expected outcome
- Cut recall 0.443 → ~0.450, cut precision 0.830 → ~0.832, cut F1 0.578 → 0.584.
- +13 recovered, 0 new false positives (offline simulation).
- Render-QA: neutral-to-slightly-positive (removes dangling micro-segments that
  can only help continuity/spectrogram). Full paid re-render optional to confirm.
