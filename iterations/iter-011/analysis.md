# Iteration 011 — Analysis

## Changes
1. **Keep longer sentence** instead of always keeping the later one
2. **Length ratio guard (1.5x)**: force Gemini verification when one sentence is >1.5x longer
3. **Raised thresholds**: lexical_definite 85→90, semantic_definite 0.90→0.95, gemini_confidence 0.70→0.80

## Results

| Video | Before Overall | After Overall | Delta | Key Change |
|-------|---------------|---------------|-------|------------|
| test-8 | 85.7% | **92.9%** | **+7.2%** | Temporal 56.5→91.5% |
| test-9 | 89.7% | **93.9%** | **+4.2%** | Temporal 90.2→97.5% |
| test-7 | 82.5% | **86.6%** | **+4.1%** | Temporal 65.7→92.8%, Word F1 89.1→92.8% |
| test-5 | 86.0% | **88.9%** | **+2.9%** | Temporal 74.7→94.3% |
| test-15 | 93.1% | **95.0%** | **+1.9%** | Temporal 88.9→97.8% |
| test-1 | 91.9% | **93.7%** | **+1.8%** | Word F1 93.9→97.0% |
| test-13 | 88.9% | **89.2%** | +0.3% | Stable |
| test-6 | 88.8% | 88.7% | -0.1% | Stable |
| test-2 | 92.8% | 90.7% | **-2.1%** | Extra words 32→65, precision drop |
| test-14 | 92.2% | 89.6% | **-2.6%** | Extra words 58→79, dur_delta +27→+41s |
| test-11 | 92.7% | 89.8% | **-2.9%** | dur_delta +17→+29s |
| test-10 | 80.3% | 77.3% | **-3.0%** | Extra words 112→130, dur_delta +25→+46s |
| test-12 | 94.9% | 91.8% | **-3.1%** | Missing words 71→83 |

**Aggregate: 89.2% → 89.8% (+0.6%)**

## Analysis

### What worked
- **test-8**: The biggest win (+7.2%). The 30.7s pedagogical explanation (duplicate #3) that was incorrectly cut is now kept. Word recall jumped from 85.7% to 93.2%.
- **test-7**: Temporal score jumped from 65.7% to 92.8% — the false positive duplicate cuts that caused cumulative drift are now avoided.
- **Temporal scores improved dramatically** on the targeted videos because fewer false cuts = less cumulative drift.

### What regressed
- **test-2, test-10, test-11, test-12, test-14**: The "keep longer" logic keeps the verbose first occurrence, but the human preferred the shorter, cleaner restatement. This causes:
  - More extra words (lower precision)
  - Longer pipeline output (higher duration delta)
  - Worse temporal alignment

### Root cause of regressions
The "keep longer" heuristic is too blunt. In educational videos:
- Sometimes the first take IS the complete version (test-7, test-8) → keep longer is correct
- Sometimes the first take IS the verbose draft and the retake IS the polished version (test-2, test-10) → keep later is correct

## Quantitative Breakdown

**6 improved, 5 regressed, 2 stable.**

| Category | Videos | Avg Delta | Temporal Driver |
|----------|--------|-----------|-----------------|
| Improved | test-8, test-9, test-7, test-5, test-1, test-15 | **+3.7%** | Temporal improved avg +16.1% (fewer false duplicate cuts → less drift) |
| Regressed | test-12, test-10, test-11, test-14, test-2 | **-2.8%** | Temporal regressed avg -11.5% (keep-longer makes output too long → more drift) |
| Stable | test-13, test-6 | **+0.1%** | — |

The regressions are primarily **temporal** (not word-level). "Keep longer" makes the pipeline output longer than the human edit, pushing all subsequent sentences later and increasing duration delta.

Evidence from duration deltas:
- test-10: +24.9s → **+45.5s** (pipeline got 20s longer)
- test-11: +17.0s → **+29.1s** (+12s)
- test-14: +27.1s → **+41.3s** (+14s)
- test-2: +13.6s → **+21.4s** (+8s)

## Verdict

Net positive (+0.6% aggregate) but the "keep longer" heuristic is too blunt. It correctly fixes over-cutting on some videos but causes under-cutting (keeping verbose first takes) on others. The **thresholds** (lex 90, sem 0.95, gem 0.8) are good and should be kept. The **length guard** (1.5x) is also sound. The **keep-longer logic** needs refinement.

## Recommendations for iter-012
1. **Let Gemini decide which version to keep** — add a `which_to_keep` field to the duplicate verification prompt. Gemini can assess which version is cleaner/more complete based on content quality, not just length.
2. **Alternatively, use quality signals** — count hesitation markers, filler words, incomplete words in each duplicate. Keep the version with fewer disfluencies.
3. **Keep thresholds at current levels** — lex 90, sem 0.95, gem 0.8 reduced false positives without losing true positives.
4. **Keep the length guard** — requiring Gemini verification when length differs by >1.5x prevents cutting elaborations.
