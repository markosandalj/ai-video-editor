# Iteration 013 — Hypothesis

## Problem

1. **Overall score formula is misleading**: Current formula equally averages sentence F1, temporal, splice, spectrogram, and continuity. But sentence F1 is noisy (boundary mismatches inflate/deflate it), spectrogram punishes encoding differences rather than cut accuracy, and splice detection is not actionable at this stage. Word-level F1 — the most reliable measure of cut accuracy — is not even included in the overall score.

2. **Ellipsis-ending false starts ("...") not strongly weighted**: The pipeline already detects "..." fragments via `is_incomplete_fragment` (up to 15 words), but the Gemini verification prompt doesn't call out "..." as a strong signal. Longer "..." sentences (16–25 words) also slip through.

## Changes

### 1. Reweight overall score
- **Word F1: 50%** — primary signal; immune to sentence boundary noise
- **Temporal: 30%** — secondary; captures duration and timing alignment  
- **Continuity: 20%** — ensures no sentences are dropped
- **Drop**: sentence F1, spectrogram, splice (still computed, just not in overall score)

### 2. Improve "..." fragment detection (hybrid)
- **Rule-based**: Increase `max_words_ellipsis` from 15 → 25 (catch longer false starts)
- **Gemini signal**: Update `FRAGMENT_PROMPT` to explicitly flag "..." endings as strong indicator of incomplete/abandoned thought

## Expected outcome
- Overall scores will shift to better reflect actual cut accuracy (word overlap)
- Videos with good word F1 but low spectrogram (e.g. test-7 at 0.609) will score more fairly
- More "..." fragments caught and confirmed → fewer extra words in pipeline output
- Net improvement in aggregate score due to formula better reflecting real quality
