# Semantic Embedding Similarity

Status: `done`
Phase: 3
Depends on: phase-2 complete

## Objective

Detect semantically identical sentences (same meaning, different wording) using vector embeddings and cosine similarity. This is the second tier in the tiered duplicate detection pipeline.

## Requirements

- Use `paraphrase-multilingual-MiniLM-L12-v2` from sentence-transformers (trained on 50+ languages including Croatian, 384-dim embeddings).
- Encode all sentences, compute cosine similarity between pairs within the lookahead window.
- Accept a configurable threshold (default TBD during integration with 3.04).
- Runs locally on M2 16GB — no API calls.

## Implementation Notes

- Library: `sentence-transformers` (add to pyproject.toml).
- Model: `paraphrase-multilingual-MiniLM-L12-v2` (~471MB, downloads on first use).
- Pre-compute all embeddings in one batch, then compute pairwise cosine similarity only within the window.
- Device: use MPS if available for faster encoding, fall back to CPU.
- Cache embeddings per transcript to avoid recomputation.

## Acceptance Criteria

- [x] `sentence-transformers` added to dependencies
- [x] Function: `compute_semantic_similarity(sentences, window, threshold) -> list[SimilarityScore]`
- [x] Uses `paraphrase-multilingual-MiniLM-L12-v2` model
- [x] Cosine similarity computed between embedding pairs (batch encode + dot product)
- [x] Only compares within the lookahead window
- [x] Paraphrased duplicates detected (not just exact repeats)
