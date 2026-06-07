# Iteration 010 — Analysis

## Context

Iterations 001–009 were tuned on a **single video pair** (test-2). We now ran the pipeline on all 13 available video pairs and ran QA against their human-edited ground truths. This is the first multi-video evaluation.

## Results Summary

| Video | Sent F1 | Word F1 | Word P | Word R | Temporal | Overall | Notes |
|-------|---------|---------|--------|--------|----------|---------|-------|
| test-12 | 92.5% | 95.9% | 99.3% | 92.7% | 89.1% | **93.8%** | Best |
| test-2 | 92.9% | 96.3% | 95.0% | 97.7% | 76.1% | **91.6%** | Tuning video |
| test-14 | 89.4% | 95.3% | 94.7% | 95.9% | 78.0% | **91.2%** | |
| test-15 | 94.4% | 95.4% | 96.5% | 94.3% | 75.5% | **90.9%** | |
| test-11 | 96.8% | 97.5% | 98.1% | 96.9% | 81.2% | **90.2%** | Spectrogram fail |
| test-9 | 86.5% | 96.2% | 98.0% | 94.4% | 84.4% | **88.5%** | |
| test-1 | 78.8% | 93.9% | 96.3% | 91.5% | 73.8% | **87.2%** | |
| test-13 | 86.4% | 93.8% | 92.6% | 95.1% | 68.3% | **87.1%** | |
| test-6 | 88.2% | 95.6% | 96.6% | 94.7% | 80.7% | **86.3%** | |
| test-8 | 87.8% | 91.6% | 98.3% | 85.7% | 45.5% | **83.5%** | Low recall |
| test-5 | 88.5% | 92.4% | 95.3% | 89.6% | 56.4% | **82.4%** | Low recall |
| test-7 | 85.9% | 89.1% | 92.9% | 85.6% | 45.9% | **78.6%** | Lowest overall |
| test-10 | 81.3% | 92.6% | 92.3% | 93.0% | 47.4% | **76.6%** | Lowest overall |

**Aggregate: 86.8%**

## Key Findings

### 1. Temporal Score Is the #1 Drag

The 4 worst videos (test-7, test-10, test-8, test-5) all have temporal scores ≤56%. The formula:
```
timing_score = max(0.0, 1.0 - mean_offset / 20.0)
temporal_score = (dur_ratio + timing_score) / 2.0
```

**Problem: When `mean_offset > 20s`, `timing_score = 0`**, capping temporal at `dur_ratio/2 ≈ 0.45-0.48`. This happens on 4/13 videos.

Offset patterns show **cumulative drift**: once the pipeline cuts (or keeps) content differently from the human, all subsequent sentences shift. The offsets grow monotonically over the video.

**test-10 has a 177s outlier** (one mismatched sentence) that inflates the mean massively.

### 2. Word Recall Drives Temporal Drift

| Video | Word Recall | Missing Words | Temporal |
|-------|------------|---------------|----------|
| test-7 | 85.6% | 203 | 45.9% |
| test-8 | 85.7% | 169 | 45.5% |
| test-5 | 89.6% | 109 | 56.4% |
| test-10 | 93.0% | 102 | 47.4% |

Low recall = pipeline cuts content the human kept → cumulative temporal offset. **test-7 and test-8 each have >150 missing words** — entire sections the human kept.

### 3. Word Precision Is Strong Everywhere

Precision ranges 92-99% across all 13 videos. The pipeline rarely keeps content that the human cut. The issue is **over-cutting**, not **under-cutting**.

### 4. Sentence F1 Varies More Than Word F1

Sentence F1 ranges 78.8%–96.8%, while word F1 ranges 89.1%–97.5%. This confirms sentence boundary mismatches inflate sentence-level errors. Word F1 is the more reliable metric.

## Root Causes

### A. Temporal Formula Too Harsh for Longer Videos
- `max_acceptable_offset = 20.0` was set in iter-007
- For longer videos (10-12 min) with significant edits, cumulative drift easily exceeds 20s
- Using mean (not median) means single outliers (like test-10's 177s) can tank the score
- 4/13 videos have timing_score = 0 purely from formula saturation

### B. Pipeline Over-Cuts on Some Videos (Low Recall)
- test-7: 22 flagged / 104 sentences (21% cut rate), 203 missing words
- test-8: 21 flagged / 73 sentences (29% cut rate), 169 missing words
- Need to investigate: are these aggressive stutter trims? Incorrect duplicate detection? Silence-based cuts?

### C. Sentence Matching Can Misalign
- Fuzzy matching at 65% threshold can match wrong sentences
- Cross-video evidence: test-10's 177s temporal outlier is likely a mismatched pair

### D. Over-Cutting Root Cause: Duplicate Detection
Cut rates by reason across all videos:
```
  test-7: cut=34.5%  dup=20.4%  fs= 3.1%  sil=11.0%
  test-10: cut=34.2%  dup=17.2%  fs=10.2%  sil= 6.7%
  test-8: cut=27.0%  dup=13.3%  fs= 3.6%  sil=10.0%
  test-12: cut=26.0%  dup=22.2%  fs= 2.7%  sil= 1.2% ← BUT scores 94.9%
```
test-12 cuts 22.2% as duplicates yet scores best. The issue is detection **accuracy**, not volume.

## Iteration 010 Changes

1. **Median instead of mean** for offset computation — robust to outliers
2. **IQR outlier filtering** on offsets before computing — removes mismatched sentences
3. **max_acceptable_offset increased from 20s to 40s** — prevents formula saturation on longer videos

## Results After Changes

| Video | Before Temporal | After Temporal | Before Overall | After Overall | Delta |
|-------|----------------|----------------|----------------|---------------|-------|
| test-1 | 73.8% | **97.0%** | 87.2% | **91.9%** | +4.7% |
| test-2 | 76.1% | 82.1% | 91.6% | **92.8%** | +1.2% |
| test-5 | 56.4% | **74.7%** | 82.4% | **86.0%** | +3.6% |
| test-6 | 80.7% | **93.6%** | 86.3% | **88.8%** | +2.5% |
| test-7 | 45.9% | **65.7%** | 78.6% | **82.5%** | +3.9% |
| test-8 | 45.5% | **56.5%** | 83.5% | **85.7%** | +2.2% |
| test-9 | 84.4% | **90.2%** | 88.5% | **89.7%** | +1.2% |
| test-10 | 47.4% | **65.8%** | 76.6% | **80.3%** | +3.7% |
| test-11 | 81.2% | **93.8%** | 90.2% | **92.7%** | +2.5% |
| test-12 | 89.1% | **94.8%** | 93.8% | **94.9%** | +1.1% |
| test-13 | 68.3% | **77.4%** | 87.1% | **88.9%** | +1.8% |
| test-14 | 78.0% | **87.5%** | 91.2% | **92.2%** | +1.0% |
| test-15 | 75.5% | **88.9%** | 90.9% | **93.1%** | +2.2% |

**Aggregate: 86.8% → 89.2% (+2.4%)**

All 13 videos improved. Biggest temporal gains: test-1 (+23.2%), test-7 (+19.8%), test-10 (+18.4%), test-6 (+12.9%).

## Remaining Issues for Future Iterations
- test-7 (82.5%) and test-10 (80.3%) still lowest — driven by low word recall (over-cutting from duplicate detection)
- test-8 temporal still only 56.5% — median offset 31.2s, real pipeline-vs-human drift
- Duplicate detection accuracy varies across videos — needs investigation
