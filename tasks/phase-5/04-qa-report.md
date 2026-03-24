# QA Report Generation

Status: `done`
Phase: 5
Depends on: 5.01, 5.02, 5.03, 5.05, 5.06, 5.07

## Objective

Produce a per-video quality assurance report summarizing all verification results.

## Requirements

- Aggregate all QA results into a single per-video report.
- Include: splice scores (5.01), spectrogram similarity (5.02), transcript continuity (5.03), ground truth transcript accuracy (5.05), ground truth temporal accuracy (5.06).
- **JSON file** for machine consumption + **HTML report** for human review.
- Human-readable console summary printed after each run.
- List of flagged issues with severity levels (error / warning / info).
- Overall pass/fail verdict per video.

## Implementation Notes

- Pydantic model for the report structure, serialized to JSON.
- HTML generated from a simple template (Jinja2 or f-string based).
- Console summary via loguru or rich table.

## Acceptance Criteria

- [ ] JSON report with all QA scores aggregated
- [ ] HTML report for human review
- [ ] Human-readable console summary
- [ ] List of flagged issues with severity levels
- [ ] Summary pass/fail verdict per video
