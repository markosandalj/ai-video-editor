# Iteration 002 — Hypothesis

## Problem

The sentence-level comparison (F1=90%) is misleadingly low because 5 of 8 mismatches are sentence boundary differences, not real content disagreements. The same words exist in both transcripts but are chunked into different sentence boundaries by each transcriber. This makes it impossible to know our true accuracy.

## Hypothesis

Adding a **word-level Longest Common Subsequence (LCS)** metric will give us an accurate content-coverage score that is immune to sentence boundary differences. If we're right that most "errors" are boundary noise, the word-level score should be significantly higher than the sentence-level F1.

## Change Plan

- **File:** `ai_video_editor/qa/ground_truth.py` — add `compare_transcripts_word_level()` function
- **File:** `ai_video_editor/qa/models.py` — add `WordLevelComparisonResult` model
- **Algorithm:** Flatten both transcripts to ordered word lists, compute LCS length, derive:
  - `coverage` = LCS length / ground truth word count (like recall)
  - `precision` = LCS length / pipeline word count
  - `f1` = harmonic mean
  - List of words in pipeline but not in LCS (extra words)
  - List of words in ground truth but not in LCS (missing words)
- **Integration:** Add word-level results to `QAReport` alongside existing sentence-level results
- Keep sentence-level metrics unchanged — they may be useful later

## Risk

- LCS on full word arrays could be O(n*m) memory. For ~600 words this is fine (~360K cells).
- Word-level matching may be TOO forgiving — if we reorder content, LCS would still match. But since we're comparing edited videos (content order is preserved), this shouldn't be an issue.

## Expected Outcome

- Word-level F1 should be notably higher than sentence-level F1 (90%), probably 95%+
- This confirms the boundary-mismatch theory and gives us a more reliable metric to iterate against
- No change to pipeline behavior — this is measurement-only
