# Iteration 006 — Hypothesis

## Problem

35 extra words remain from sentences that are contextually redundant but not detectable
by n-gram repetition or lexical/semantic duplicate matching. These require understanding
the full transcript context to identify.

## Hypothesis

A holistic Gemini review of the complete kept transcript can identify contextually
redundant sentences that existing detectors miss. Combined with algorithmic backup
checks (short sentence / trailing filler / near-duplicate), this will safely cut
the remaining extra words.

## Approach

1. After all existing duplicate/stutter detection, collect the list of sentences that
   will be KEPT in the final video
2. Send the full kept transcript (with sentence indices) to Gemini
3. Ask Gemini to flag sentences that are redundant (add no new information given context)
4. Only cut sentences where:
   - Gemini flags with ≥90% confidence, AND
   - At least one algorithmic check also flags the sentence:
     a. Very short (≤4 words) trailing filler
     b. Content is a subset of a nearby sentence
     c. Sentence is a question that is immediately answered (and question itself was
        already stated)
5. Add these as new flags in the EDL with reason `FILLER`

## Expected Outcome

- Word precision should improve from 94.5% toward ~97% (cutting ~20 of 35 extra words)
- Word recall should stay at ~99.8%
- Word F1 should improve from 97.1% toward ~98%
