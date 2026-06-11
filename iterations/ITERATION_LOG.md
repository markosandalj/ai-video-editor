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
| 007  | 88.1%     | 96.1%     | 95.3%    | 96.9%    | 67.4%    | 88.4%   | Temporal formula fix + fragment detection | Improved: overall 84→88.4%, temporal 45→67%, +4.4% overall |
| 008  | 89.2%     | 96.3%     | 95.9%    | 96.7%    | 70.4%    | 89.0%   | Broader fragment detection + Gemini temp=0 | Improved: overall 88.4→89.0%, temporal 67→70%, -4 extra words |
| 009  | 92.9%     | 96.3%     | 95.0%    | 97.7%    | 76.1%    | 91.6%   | Fix per-word punctuation in fragment detection | Improved: overall 89→91.6%, sentence R=100%, temporal 70→76% |
| 010  | N/A (13v) | N/A (13v) | N/A      | N/A      | N/A      | 89.2%   | Temporal: median + IQR outlier filter + cap 40s (13-video bulk) | Improved: aggregate 86.8→89.2%, all 13 videos improved, temporal scores +2-23% |
| 011  | N/A (13v) | N/A (13v) | N/A      | N/A      | N/A      | 89.8%   | Keep-longer + length guard 1.5x + raise thresholds (lex 90, sem 0.95, gem 0.8) | Mixed: +7.2% test-8, +4.1% test-7, but -3.1% test-12, -3.0% test-10; net +0.6% |
| 012  | N/A (13v) | N/A (13v) | N/A      | N/A      | N/A      | 90.1%   | Gemini picks which duplicate to keep (all pairs) + remove length guard | Mixed: 9/13 improved (+6.2% test-13), but -8.6% test-7, -7.6% test-9; net +0.3% |
| 013  | N/A (13v) | N/A (13v) | N/A      | N/A      | N/A      | 92.7%   | Reweight overall score (word F1 50%, temporal 30%, continuity 20%) + "..." fragment prompt | Improved: all 13 videos up, +2.6% aggregate, best +5.4% test-7; zero regressions |
| 014  | 87.4%     | 94.3%     | 93.8%    | 94.9%    | 80.0%    | 88.5%   | Protect short instructional bridge sentences from full cuts (21-video fixture set) | REVERTED: regression 90.7→88.5%; temporal fell from extra kept material, worst drops test-40/test-47/test-9 |
