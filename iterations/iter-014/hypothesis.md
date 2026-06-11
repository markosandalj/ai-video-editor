# Iteration 014 — Hypothesis

## Problem

The expanded fixture set shows a recall/continuity problem. The pipeline cuts or compresses instructional setup and bridge sentences that human edits keep, especially in weaker videos like `test-7`, `test-44`, and `test-47`.

Examples include:

- "Pa dobro, onda možda ima smisla prvo... riješiti tu našu nejednadžbu..."
- "Pa evo, možda nije loša ideja da si skiciramo jednu takvu prizmu."
- "Dobro, evo pa idemo pokazati onda samo kratko oba načina."
- "Znači, nemojte da vas zbune ove oznake."

At the same time, the pipeline still keeps a smaller number of obvious non-lesson asides such as "Čekaj, otvaraju se vrata.", "Khm.", and "a ne mogu više pričati."

## Hypothesis

If we protect short instructional setup/bridge sentences before EDL construction, recall and continuity will improve on the expanded fixture set without materially harming precision.

The protection should be conservative: only sentences with clear teaching intent should be protected. Explicit asides/noise should remain cuttable.

## Change Plan

Make exactly one behavioral change in the duplicate/EDL decision path:

- Add a conservative "instructional bridge" protection that prevents cutting sentences containing teaching/action context such as `idemo`, `pogledamo`, `izračunati`, `skiciramo`, `pokazati`, `riješiti`, `označiti`, `sjetimo`, or phrases that introduce the next calculation or explanation.
- Exclude obvious non-lesson asides/noise from protection.
- Apply this protection only at the final cut-decision boundary so existing duplicate, false-start, stutter, and fragment detection can remain unchanged and debuggable.

Likely files:

- `ai_video_editor/duplicate/pipeline.py`
- Possibly `ai_video_editor/duplicate/edl.py` if final EDL construction is the cleaner decision boundary.

## Risk

The main risk is keeping more filler and reducing precision, especially around short transition sentences like `Dobro.`, `Ok.`, and `Evo.`. To reduce that risk, standalone one-word/very-short transitions should not be protected unless they contain explicit task context.

## Expected Outcome

- Improve continuity on low-continuity videos, especially `test-7`, `test-44`, `test-46`, and `test-47`.
- Improve or stabilize aggregate score across all 21 fixtures.
- Potential small precision decrease if some protected transition sentences were intentionally cut by the human editor.
- No expected change to splice quality; current run already has 0 harsh splices across 493 splices.

## Outcome

Rejected and reverted. The rerun dropped aggregate score from 90.7% to 88.5%. Word recall improved to 94.9%, but precision and especially temporal alignment regressed because the protection kept too many transition/setup sentences that the human edit removed. The largest regressions were `test-40`, `test-47`, `test-9`, `test-10`, and `test-11`.
