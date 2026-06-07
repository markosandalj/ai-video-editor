# Iteration 012 — Hypothesis

## Baseline
- Aggregate score: 89.8% (13 videos)
- "Keep longer" heuristic caused regressions on 5 videos (-2.8% avg) while helping 6 (+3.7% avg)
- Root cause: length alone can't determine which duplicate version is better

## Changes

### Change 1: Gemini decides which sentence to keep (all pairs)
Replace the blunt `_pick_keep_cut` (keep-longer) with a Gemini call for ALL confirmed duplicate pairs — including auto-confirmed ones.

Add a new prompt that receives both sentences and asks Gemini to pick the better version. Criteria:
- Cleaner delivery (fewer filler words, hesitations, incomplete words)
- More complete thought (more informational content)
- Slight bias toward the later version (speaker typically improves on retake)

### Change 2: Remove length guard (1.5x)
The raised thresholds (lex 90, sem 0.95, gem 0.8) are sufficient to prevent false positives. The length guard is no longer needed since Gemini now evaluates all pairs.

### Change 3: New "which to keep" prompt
Add a `preferred_index` field to the duplicate response. For auto-confirmed pairs, route them through a lightweight "which is better" Gemini call after confirmation.

## Expected Impact
- Fix regressions on test-2, test-10, test-11, test-14 (Gemini will prefer the cleaner retake)
- Maintain improvements on test-7, test-8 (Gemini will prefer the more complete version)
- Small cost increase: extra Gemini calls for auto-confirmed pairs (~5-15 per video)

## Risks
- More API calls = higher cost + latency
- Gemini's preference may not always match the human editor's
