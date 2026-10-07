# Sol 6.1 low: prompt selection

The section editor uses `openai/gpt-6.1-sol` with low reasoning through
OpenRouter, pinned to OpenAI with no provider fallback. No temperature is sent.
The selected prompt combines all three evaluated additions:

- **H1:** choose the complete retained take before deleting earlier attempts.
- **H2:** distinguish a recording retake from redundant explanation; preserve recaps.
- **H3:** check the remaining text and retained replacements before returning JSON.

## Results

Eight variants × nine frozen examples × ten repetitions = **720 completed runs**.
The control is a fresh series using the previous prompt with the same model,
transcripts, audio inputs and deterministic processing. Human-edited cuts are
the target; original automatic cuts are preserved separately as a baseline.

| Prompt | Difference from human cuts | Variation between runs | Overcut words* |
|---|---:|---:|---:|
| Control | 137.72 s | 10.69 s | 7.9 |
| H1 | 140.75 s | 4.50 s | 8.0 |
| H2 | 137.53 s | 5.28 s | 8.0 |
| H3 | 135.36 s | 10.33 s | 8.0 |
| H1 + H2 | 136.34 s | 10.67 s | 7.9 |
| H1 + H3 | 139.54 s | 2.74 s | 8.0 |
| H2 + H3 | 126.18 s | 7.20 s | 8.0 |
| **H1 + H2 + H3** | **124.92 s** | **5.19 s** | **8.0** |

Difference is the duration of the symmetric difference between generated and
human source-time cut ranges, averaged across repetitions and summed across
nine cases. Variation sums each case's mean pairwise cut difference across the
45 pairs of repetitions. Lower is better for both measures.
*Word counts use frozen word timestamp centers, not a new listening assessment.

- Case 1: the earlier formalin explanation is fully removed in **8/10** runs
  with all three additions, compared with **2/10** for the control.
- Case 5: “Maseni udio određenog atoma X…” remains in **10/10** runs in every variant.
- Case 8: “Sa volumenom otopine.” remains in **10/10** runs in every variant.

The selected variant reduces difference by **9.3%** and variation by **51.5%**.
Overcut word counts are essentially unchanged. About **86% of the improvement
comes from case 1**; nine examples do not establish a general improvement across
other recordings. H2 + H3 provides most of the benefit; adding H1 improves the
mean by another 1.26 seconds across the nine cases. H1 alone performs worse.

The matrix used at most 12 concurrent calls. All runs completed after 732 HTTP
attempts, including retries for 11 read timeouts and one read error. Returned
usage reports total $4.63; timeouts may have additional unreported charges.
The control and selected variant cost $0.56 and $0.60 per 90 completed runs.

## Promotion verification

The application contains the exact evaluated H1 + H2 + H3 template and timed-word
span locator, together with retained-span protection and content review of audio
candidates. Matching several lexical tokens inside one timed word cannot create
new internal time boundaries. Ambiguous quotes and joined tokens such as
`koncen—ako` remain limitations.

- **285 tests pass**, including provider payload, retained introductions and
  corrections, competing cuts, multiword timestamps and worker trace persistence.
- **90/90 saved responses replay identically** through application code: provider
  prompts, strict JSON schema, decision traces, EDLs and final cut ranges match.
  Only the newly generated EDL creation timestamp is excluded from comparison.
- Replay makes **zero API calls** and uses frozen transcripts; it does not rerun
  transcription, rendering or assess new recordings.

Local evidence is retained under `output/gradivo-prompt-matrix-20261007/`
(`manifest.json`, `validation.json`, `report.md`, per-run requests and results)
and `output/prompt-promotion-pr-20261007/replay-validation.json`. These ignored
runtime artifacts and raw provider responses are not part of the PR.
