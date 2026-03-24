# Iteration 003 — Hypothesis

## Problem

The biggest single source of extra words (~30 of 57) is an undetected intra-sentence stutter. The speaker says "a ovaj tu, a ovaj tu broj koji je sada predstavljen slo-- a ovaj broj koji je ovdje predstavljen slovom n..." — repeating phrases and false-starting within a single sentence. Our current false start detection only checks sentences BETWEEN confirmed duplicate pairs, so this never gets flagged.

## Hypothesis

Adding an intra-sentence stutter detector will catch repeated word sequences within individual sentences. Combined with a Gemini verification step, this will flag and cut stuttered sentences, reducing extra words by ~30.

## Change Plan

1. **New file:** `ai_video_editor/duplicate/stutter.py`
   - `detect_stutters(sentences) -> list[int]` — scans each sentence for repeated n-grams
   - Returns indices of sentences containing stutters
   - Detection: repeated 2-grams (if ≥3 total repeated words) or any repeated 3-gram

2. **Modified:** `ai_video_editor/duplicate/gemini_verify.py`
   - Add a `verify_stutters_with_gemini(sentences, stutter_indices, ...) -> list[FalseStartVerdict]` function
   - Sends each stuttered sentence with surrounding context to Gemini for a cut/keep decision

3. **Modified:** `ai_video_editor/duplicate/pipeline.py`
   - Integrate stutter detection after duplicate detection
   - Stutter-flagged + Gemini-confirmed sentences added to the DuplicateFlag list with reason `FlagReason.filler` or a new `FlagReason.stutter`

4. **Modified:** `ai_video_editor/duplicate/models.py`
   - Add `stutter` to `FlagReason` enum if not already there

## Risk

- Could false-positive on legitimate pedagogical repetition ("znači imamo... znači imamo..." used for emphasis)
- Gemini verification step mitigates this — it decides with context whether repetition is intentional

## Expected Outcome

- Word precision should improve from 91.2% toward ~95% (cutting ~30 extra words)
- Word recall should stay at ~97.7% (we're not cutting anything new that the human kept)
- Word F1 should improve from 94.3% toward ~96%
