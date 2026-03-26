# Iteration 009 — Hypothesis

## Problem

Fragment detection misses "Evo, ja." because `_normalise` only strips punctuation from
the string boundaries, not from individual words. "evo," is treated as a content word
(4 chars, not in filler set) instead of being recognised as "evo" (a filler marker).

Additionally, "A ovaj broj koji je ovdje predstavljen slovom n, on mi dolazi..." (s18's
stutter-trimmed remainder) may appear in the output and should be caught as a fragment.

## Hypothesis

Fixing per-word punctuation stripping in `is_incomplete_fragment` will correctly identify
"Evo, ja." as a fragment candidate. This, combined with Gemini confirmation, should
remove ~3 more words from the extra count.

## Changes

1. Add a `_normalise_word` helper that strips punctuation from individual words
2. Use it in `is_incomplete_fragment` when checking against filler markers
3. Verify other fragments ("A ovaj broj...") are also catchable

## Expected Outcome

- Extra words: 25 → ~22 (cutting "Evo, ja." = 2 words + any other newly detected)
- Duration delta: 13.4s → ~12s
- Overall: 89.0% → ~89.5%
