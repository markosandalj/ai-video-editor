# Gemini Duplicate Verification

Status: `done`
Phase: 3
Depends on: 3.03

## Objective

Use Gemini as a third-tier verification step for borderline duplicate pairs, and as the judge for false starts between confirmed duplicates.

## Requirements

- **Duplicate verification:** Given two sentences and their surrounding context, ask Gemini: "Is the first sentence a failed attempt that the speaker corrected with the second sentence?"
- **False start detection:** Given a block of sentences between a confirmed duplicate pair, ask Gemini: "Which of these sentences are filler / false starts / incomplete thoughts that should be removed?"
- Use LangChain `ChatGoogleGenerativeAI` + `with_structured_output` (same pattern as grammar correction).
- Only called on borderline cases from tiers 1+2 (cost control).

## Implementation Notes

- Reuse the LangChain + Gemini setup from `grammar.py`.
- Structured output models:
  - `DuplicateVerdict(is_duplicate: bool, confidence: float, reasoning: str)`
  - `FalseStartVerdict(filler_indices: list[int], reasoning: str)`
- Prompts in Croatian context (same as grammar prompts — the LLM needs to understand Croatian speech patterns).
- Temperature: low (0.1) for consistent judgments.
- Batch borderline pairs into a single prompt where possible to reduce API calls.

## Acceptance Criteria

- [x] Function: `verify_duplicates_with_gemini(pairs, sentences) -> list[DuplicateVerdict]`
- [x] Function: `detect_false_starts_with_gemini(block, before, after) -> FalseStartVerdict`
- [x] Uses structured output (Pydantic models via LangChain `with_structured_output`)
- [x] Only invoked on borderline pairs (not all pairs) — orchestrated by `pipeline.detect_duplicates`
- [x] Handles Croatian educational content correctly (prompts in Croatian)
