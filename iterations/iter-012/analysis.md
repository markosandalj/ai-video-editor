# Iteration 012 — Analysis

## Changes
1. **Gemini decides which sentence to keep** for ALL confirmed duplicate pairs (new `pick_best_version_with_gemini` call)
2. **Removed length guard** (1.5x threshold) — raised thresholds are sufficient
3. **Reverted keep logic** from "keep longer" to "keep later" as default, Gemini overrides where needed
4. **Updated duplicate prompt** to include `preferred_index` field with quality criteria + later bias

## Results (vs iter-011)

| Video | 011 Overall | 012 Overall | Delta | 011 Temporal | 012 Temporal | T Delta |
|-------|------------|------------|-------|-------------|-------------|---------|
| test-13 | 89.2% | **95.3%** | **+6.2%** | 72.9% | 94.3% | +21.4% |
| test-2 | 90.7% | **93.9%** | **+3.2%** | 71.5% | 85.9% | +14.4% |
| test-10 | 77.3% | **80.1%** | **+2.8%** | 56.2% | 68.1% | +11.9% |
| test-11 | 89.8% | **92.0%** | **+2.2%** | 78.1% | 90.5% | +12.5% |
| test-14 | 89.6% | **91.7%** | **+2.1%** | 73.3% | 86.8% | +13.5% |
| test-6 | 88.7% | **90.8%** | **+2.1%** | 91.1% | 94.9% | +3.8% |
| test-5 | 88.9% | **90.9%** | **+2.0%** | 94.3% | 94.0% | -0.3% |
| test-12 | 91.8% | **92.9%** | **+1.2%** | 87.6% | 83.1% | -4.5% |
| test-8 | 92.9% | **93.4%** | **+0.5%** | 91.5% | 96.8% | +5.3% |
| test-1 | 93.7% | 92.7% | -1.0% | 95.4% | 98.4% | +3.0% |
| test-15 | 95.0% | 93.2% | **-1.8%** | 97.8% | 90.6% | -7.1% |
| test-9 | 93.9% | 86.2% | **-7.6%** | 97.5% | 78.1% | -19.4% |
| test-7 | 86.6% | 77.9% | **-8.6%** | 92.8% | 54.8% | -37.9% |

**Aggregate: 89.8% → 90.1% (+0.3%)**

## Analysis

### What worked
- **Fixed all 5 iter-011 regressions**: test-2, test-10, test-11, test-14 all improved significantly
- **test-13** had the biggest gain (+6.2%) — temporal jumped from 72.9% to 94.3%
- 9 out of 13 videos improved

### What regressed
- **test-7**: -8.6%, temporal dropped 92.8% → 54.8%. The "keep longer" heuristic was correct here — Gemini chose the wrong version.
- **test-9**: -7.6%, temporal dropped 97.5% → 78.1%. Same pattern.
- **test-15**: -1.8%, minor regression

### Root cause of regressions
Gemini's "later bias" is overriding the correct choice on test-7 and test-9, where the first take IS the complete explanation. The later version is shorter/cleaner but missing key content, causing the pipeline output to lose words → temporal drift.

## Verdict
Net positive (+0.3% aggregate), fixed iter-011's regressions on 5 videos, but introduced new regressions on test-7 and test-9. Gemini's preference is not reliable enough — it gets the right answer for ~9/13 videos but catastrophically wrong on 2.

## Remaining issues
- test-7 (77.9%) and test-10 (80.1%) still lowest
- Gemini's sentence preference is inconsistent across videos
- Non-determinism: Gemini may make different choices on re-runs
