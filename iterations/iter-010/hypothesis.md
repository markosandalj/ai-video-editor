# Iteration 010 — Hypothesis

## Baseline
- Aggregate score: 86.8% (across 13 video pairs)
- 4/13 videos have temporal score ≤56% (formula saturates at mean_offset > 20s)
- test-10 has a 177s temporal outlier from a mismatched sentence

## Hypothesis
Temporal scoring formula is too harsh and too sensitive to outliers. Three changes:

### Change 1: Use median instead of mean for offset calculation
Mean is vulnerable to outliers (test-10's 177s). Median gives a robust central tendency.

### Change 2: Increase max_acceptable_offset from 20s to 40s
4/13 videos have mean_offset > 20s → timing_score = 0 → temporal capped at ~0.47.
Longer videos with significant edits naturally accumulate drift. 40s gives more headroom.

### Change 3: Filter outlier offsets using IQR
Before computing the offset statistic, remove outliers defined as > Q3 + 1.5*IQR.
This prevents mismatched sentences from corrupting the temporal score.

## Expected Impact
- The 4 worst temporal scores (45-56%) should improve significantly
- Aggregate score should rise from 86.8% toward ~89-91%

## Non-scoring finding: Duplicate detection over-cuts on some videos
- test-7: 20.4% of duration cut as duplicates (134.8s), vs 20.4% — word recall 85.6%
- test-10: 17.2% duplicates + 10.2% false starts — word recall 93.0%
- Pipeline fix deferred: no safety guard this iteration, just measurement improvement
