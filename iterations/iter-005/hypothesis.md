# Iteration 005 — Hypothesis

## Problem

66 extra words from intra-sentence stutters. The speaker repeats phrases within a
sentence, then says the clean version. The human editor surgically trimmed just the
stuttered portion. Our pipeline keeps the entire sentence because it only operates
at sentence-level granularity.

Key examples:
- "Taj naš broj, **taj naš broj** će mi zapravo..." → human kept "Taj naš broj će mi zapravo..."
- "Evo, ja. **Evo, ja** sam si nekako..." → human kept "Evo, ja sam si nekako..."
- "A ovaj tu, **a ovaj tu** broj koji..." → human kept the clean second take

## Hypothesis

Adding sub-sentence (word-level) trimming will allow us to cut just the stuttered
portion within a sentence while keeping the actual content. This should reduce the
66 extra words significantly while maintaining our 99.8% recall.

## Approach: Hybrid (Algorithmic + Gemini)

1. **Algorithmic detection:** Use `detect_stutters()` (already built in iter-003) to
   find sentences with repeated n-grams
2. **Identify repeated portion:** Algorithmically find the repeated word sequence and
   its positions within the sentence
3. **Gemini verification:** Send the sentence to Gemini with the detected repetitions,
   ask it to return which word indices to KEEP (the clean take)
4. **Word-level EDL:** The EDL gets a new field for word-level trim points, specifying
   sub-sentence cuts using word timestamps from ElevenLabs

## Change Plan

1. **Modified:** `ai_video_editor/duplicate/stutter.py`
   - Add `find_stutter_spans(sentence) -> list[StutterSpan]` — returns word index
     ranges of the repeated portions
   - `StutterSpan(repeat_start, repeat_end, clean_start, clean_end)` identifying
     which words are the stutter and which are the clean take

2. **Modified:** `ai_video_editor/duplicate/gemini_verify.py`
   - Modify `verify_stutters_with_gemini` to return word-level keep ranges instead
     of a binary cut/keep verdict

3. **Modified:** `ai_video_editor/duplicate/models.py`
   - Add `WordTrim` model with `start_time`, `end_time` for sub-sentence cuts
   - Add `word_trims` field to `DuplicateFlag` for sub-sentence cut info

4. **Modified:** `ai_video_editor/duplicate/edl.py`
   - Support word-level trim points in EDL decisions
   - When a sentence has word_trims, split the sentence's keep span at the trim
     boundaries

5. **Modified:** `ai_video_editor/duplicate/pipeline.py`
   - Re-enable stutter detection, but now with word-level trims instead of
     whole-sentence cuts

## Expected Outcome

- Word precision should improve from 90.1% toward ~95%+ (cutting ~40-50 extra words)
- Word recall should stay at ~99.8% (we're trimming stutters, not cutting content)
- Word F1 should improve from 94.7% toward ~97%
