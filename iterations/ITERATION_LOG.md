# Iteration Log

Quality iteration loop for improving pipeline edit accuracy against human-edited ground truth.

## Scores

| Iter | F1 (sent) | F1 (word) | P (word) | R (word) | Temporal | Overall | Hypothesis                          | Outcome       |
|------|-----------|-----------|----------|----------|----------|---------|-------------------------------------|---------------|
| 001  | 90.0%     | N/A       | N/A      | N/A      | 46.0%    | 84.1%   | Baseline (no changes)               | —             |
| 002  | 88.9%     | 94.3%     | 91.2%    | 97.7%    | 45.2%    | 84.2%   | Add word-level LCS metric           | Confirmed: sentence F1 inflated by boundary noise |
| 003  | 90.0%     | 92.4%     | 97.8%    | 87.6%    | 45.8%    | 85.1%   | Intra-sentence stutter detection    | DISABLED: detection works but cutting whole sentences loses content; needs sub-sentence trimming |
| 004  | 90.7%     | 94.7%     | 90.1%    | 99.8%    | 42.8%    | 84.2%   | Fix missing words (silence rescue + protect keep-side) | Improved: recall 97.7→99.8%, F1 94.3→94.7%, 13 fewer missing words |
| 005  | 93.8%     | 97.1%     | 94.5%    | 99.8%    | 45.2%    | 84.0%   | Sub-sentence word-level stutter trimming | Improved: F1 94.7→97.1%, precision 90.1→94.5%, -31 extra words |
| 006  | 90.2%     | 96.3%     | 93.9%    | 98.8%    | 45.6%    | 82.5%   | Holistic Gemini redundancy review + algorithmic backup | DISABLED: regression — cut content human kept, +6 missing words |
