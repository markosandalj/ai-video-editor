# Iteration Log

Quality iteration loop for improving pipeline edit accuracy against human-edited ground truth.

## Scores

| Iter | F1 (sent) | F1 (word) | P (word) | R (word) | Temporal | Overall | Hypothesis                          | Outcome       |
|------|-----------|-----------|----------|----------|----------|---------|-------------------------------------|---------------|
| 001  | 90.0%     | N/A       | N/A      | N/A      | 46.0%    | 84.1%   | Baseline (no changes)               | —             |
| 002  | 88.9%     | 94.3%     | 91.2%    | 97.7%    | 45.2%    | 84.2%   | Add word-level LCS metric           | Confirmed: sentence F1 inflated by boundary noise |
