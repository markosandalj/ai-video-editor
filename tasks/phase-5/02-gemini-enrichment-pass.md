# Gemini Enrichment Pass (Clean Separate Step)

Status: `done`
Phase: 5
Depends on: 5.01

## Objective

Run a dedicated Gemini pass whose *only* job is to score and tag transcript chunks (and rate the salience of words within them). Keeping this separate from duplicate detection and grammar correction means each LLM call has one clear task, which improves quality and makes failures easy to isolate.

## Requirements

(Locked in Phase 5 grilling, 2026-06-10)

- Standalone pass over the transcript that returns one `SentenceEnrichment` per sentence.
- **Scope: all sentences** — both kept and cut. For cut sentences the prompt explicitly asks "does this actually belong despite being cut?" so the model can produce a `restore` suggestion via a high `keep_confidence`.
- Single responsibility: this prompt does **not** make cut decisions, fix grammar, or detect duplicates. It only assesses "how confidently does this belong, why, and which words carry the meaning."
- Per sentence the model returns: `keep_confidence` (0–100), `tags`, a Croatian `rationale`, and `word_salience` (0–100 per word, aligned to the sentence's word tokens).
- **Model: the stronger Gemini "pro" tier** (better judgment matters more than cost here), configured via `EnrichmentConfig`.
- Prompts written for Croatian educational content; the `rationale` field must come back in Croatian.
- Structured output via LangChain `with_structured_output` (same pattern as `grammar.py` and the Gemini duplicate verifier).
- Batched: send sentences in chunks (with surrounding context) to bound API calls; batch size from config.
- Low temperature (~0.1) for stable, repeatable scoring.
- Resilient: on API/parse failure for a batch, fall back to a neutral enrichment per sentence (`keep_confidence` from the EDL confidence, `status` from the cut flag, `tags=[needs_review]`, `word_salience` filled with the sentence score) rather than aborting the pipeline.

## Implementation Notes

- New module `ai_video_editor/enrich/runner.py` (`pass` is a Python keyword, so the file cannot be named `pass.py`):
  - `enrich_transcript(transcript, edl, config) -> EnrichmentResult`
  - Internal Gemini structured-output model mirrors the LLM-provided fields (`keep_confidence`, `tags`, `rationale`, `word_salience`); the deterministic `status` is computed afterward by 5.01's helper.
- Reuse the LangChain `ChatGoogleGenerativeAI` setup but allow the model name to be overridden to the pro tier; do not duplicate client config.
- The model receives, per sentence: text + word tokens, whether the pipeline kept or cut it, and the cut reason if any — so it can explain why a kept chunk is risky or why a cut chunk might be worth restoring.
- Cache results to `<stem>.enrichment.json` keyed like the transcript cache so reruns are cheap (mirror `transcription/cache.py`); recompute only on `--force`.

## Acceptance Criteria

- [x] `enrich_transcript(...)` returns one enrichment per sentence, for kept and cut alike
- [x] Dedicated prompt that only scores/tags/salience (no cut/grammar/duplicate logic)
- [x] Cut sentences can yield `restore` suggestions (high `keep_confidence`)
- [x] `keep_confidence`, Croatian `rationale`, `tags`, and `word_salience` all returned
- [x] Uses the pro Gemini tier via structured output (Pydantic + LangChain)
- [x] Batched calls with context; low temperature
- [x] Graceful per-batch fallback on failure
- [x] Results cached to `*.enrichment.json`, reused unless `--force`
