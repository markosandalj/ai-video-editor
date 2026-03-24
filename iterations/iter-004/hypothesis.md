# Iteration 004 — Hypothesis

## Problem

Two bugs causing 14 missing words (content we cut that the human kept):

### Bug 1: Speech swallowed by silence regions

Sentence 13 ("Taj naš broj...eksponent...ali dolje u razlomku") at [68.6s-75.6s] falls
inside silence region [67.4s-77.2s]. The silence detector flagged the entire 9.8s region
as silence, but there's actual speech in the middle. The EDL builder only keeps sentences
that are inside keep_regions, so this sentence is silently dropped.

**Fix:** After building keep_regions from silence detection, cross-reference with the
transcript. If any sentence falls inside a silence region (between keep_regions), split
the silence region to include the sentence as a keep span.

### Bug 2: False start detector cuts the "keep" side of a duplicate pair

Sentence 20 and 22 are a duplicate pair (keep=22, cut=20). Sentence 21 is flagged as a
separate duplicate (keep=23, cut=21). The false start detector then scans the block
BETWEEN sentences 21 and 23 (which is just sentence 22) and asks Gemini if it's filler.
Gemini says yes. But sentence 22 is the KEEP side of the 20→22 duplicate pair!

**Fix:** In `pipeline.py`, before running false start detection on a block, exclude
sentences that are the `idx_keep` of any confirmed duplicate pair.

## Expected Outcome

- Word recall should improve from ~97.7% (recover 14 missing words → approach 99%)
- Word precision should stay at ~91.2% (we're not changing what we keep additionally)
- Word F1 should improve from ~94.3% toward ~95%
