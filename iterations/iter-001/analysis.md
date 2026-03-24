# Iteration 001 — Baseline Analysis

**Date:** 2026-03-24
**Video:** test-2

## Scores

| Metric            | Value  |
|-------------------|--------|
| **F1**            | 90.0%  |
| **Precision**     | 87.8%  |
| **Recall**        | 92.3%  |
| **Temporal**      | 46.0%  |
| **Splices**       | 0/7 harsh |
| **Spectrogram**   | 0.9936 |
| **Continuity**    | 85.1%  |
| **Overall**       | 84.1%  |

## Delta vs Previous

Baseline — no previous iteration.

## False Positives (5 sentences we kept that the human cut)

These are sentences in our pipeline output that the human editor removed.

1. **"Pa znači vidimo da ovdje imamo običan a, s njim ne možemo ništa."**
   - The human split this differently — they kept the second half ("S njim ne možemo ništa.") as its own sentence. Our transcriber chunked it into one long sentence while the human's version has it as a separate short sentence. This is a **sentence boundary mismatch**, not a real content disagreement.

2. **"A ovaj tu, a ovaj tu broj koji je ovdje sada predstavljen slo-- a ovaj broj koji je ovdje predstavljen slovom n, on mi dolazi, a ovaj, znači imamo nekakvu potenciju a na n."**
   - Classic **false start / self-correction**. The speaker stumbles ("a ovaj tu, a ovaj tu..."), restarts, and the human editor trimmed this down. Our pipeline should have detected this as a false start or duplicate.

3. **"Evo, znači, to znači da..."**
   - **Filler / incomplete sentence**. Trailing off with "to znači da..." — the human cut this entirely. This is verbal filler that our pipeline failed to detect.

4. **"A kako se potencije množe?"**
   - **Rhetorical question the human merged** into the previous sentence. The ground truth has "...pomnožiti te naše potencije, a kako se potencije množe?" as one sentence, while our pipeline kept it as a separate sentence. Another **sentence boundary mismatch**.

5. **"Dakle, rekli smo bazu prepišemo."**
   - The human kept this content but **merged it into a longer sentence**: "Dakle, rekli smo bazu prepišemo, to mi je a, a eksponente...". Our pipeline has it as a standalone sentence. **Sentence boundary mismatch**.

## False Negatives (3 sentences the human kept that we cut)

These are sentences in the human edit that our pipeline removed.

1. **"S njim ne možemo ništa."**
   - Part of the split described in FP#1. The human kept this as its own sentence. Our pipeline has the content but chunked differently ("...s njim ne možemo ništa." is inside a longer sentence). This is a **matching failure**, not a real cut.

2. **"Dobro i ovdje imamo još drugi broj."**
   - The human kept this transitional sentence. Our pipeline appears to have cut it — possibly flagged as filler or caught by silence detection. Needs investigation.

3. **"Znači, imamo nekakvu potenciju a na n."**
   - Same content exists in our FP#2 as part of a longer sentence. The human extracted just this clean summary. **Sentence boundary mismatch**.

## Patterns

### 1. Sentence Boundary Mismatches (dominant issue)
FP#1, FP#4, FP#5, FN#1, FN#3 are all cases where the same content exists in both versions but is chunked differently. Our transcriber puts it in one long sentence, the human has it split (or vice versa). This inflates both false positives and false negatives.

**Impact:** At least 5 of 8 mismatches are boundary issues, not real content disagreements.

### 2. Undetected False Starts (1 case)
FP#2 is a clear false start that our pipeline should have caught. The speaker stammers and restarts.

### 3. Undetected Filler (1 case)
FP#3 is a trailing filler sentence ("Evo, znači, to znači da...") that adds no content.

### 4. Possibly Incorrect Cut (1 case)
FN#2 ("Dobro i ovdje imamo još drugi broj.") may be a real content sentence that was incorrectly cut.

### 5. Temporal Drift
The pipeline output is 16.1s longer than the human edit (203.1s vs 187.1s). The temporal offset grows progressively — early sentences are within 0.5s, but by the end the offset reaches ~17s. This suggests there are segments in our output that the human removed but we didn't, accumulating drift over the video's timeline.

### 6. Audio Quality
Splice quality is excellent — 0 harsh splices out of 7, max amplitude delta of 0.0099. Spectrogram similarity at 0.9936. No issues here.
