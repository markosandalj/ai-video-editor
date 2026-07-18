# Iteration 020 — Deterministic adjacent partial-repeat cuts

**Date:** 2026-07-18
**Grilling decision:** target adjacent partial repeats; deliver via a
deterministic post-pass (same lane family as iter-019 candidate 6).

## Problem

After iter-019's candidate 6 solved non-adjacent sandwich chains, 13 of 16
explicit cut cases in `iterations/iter-019/candidate-3-cases.json` still fail.
Eleven of those thirteen share one structure the pipeline never handles:
**the trailing words of a sentence are restated as the opening of the very
next sentence (or as the entire next sentence), and the human cuts the earlier
copy.** Examples:

- `test-10[87]` → `[88]`: an 11-word trailing clause repeated verbatim as the
  next sentence;
- `test-1[20]` → `[21]`: trailing "a y os gleda imaginarni dio" restated and
  then extended;
- `test-40[39]` → `[40]`: a whole 4-word truncated restart ("Od tud onda
  nastavljamo..." → "Odtud onda nastavljamo dalje...");
- `test-13[45]` → `[46]`: a 15-word restatement with a small word-order swap.

The existing `detect_local_corrections` lane structurally excludes this
family: it only examines sentence pairs at distance 2–3 with a visibly
truncated middle, and requires ≥7-word endpoints. Distance-1 pairs are never
considered.

Prompt-based attempts at this family failed in iter-019 (candidates 1, 4, 5:
hints perturbed unrelated Sol decisions). The deterministic post-editor lane
is the only mechanism that shipped a clean win.

Two of the thirteen open cases are *within-sentence* restarts
(`test-10[23]`, `test-11[71]`) and one is a paraphrase restart with a
different opening (`engleski25ljeto-listening-1[16]`); these are out of scope
for this iteration.

## Hypothesis

If the deterministic local-corrections lane also detects **adjacent
suffix→prefix repeats** — an earlier sentence's trailing token span that
fuzzily matches the next sentence's opening token span with anchored
endpoints — and cuts only the earlier copy, then at least 8 of the 13 open
explicit cases will pass with remainders preserved, recovering roughly 60–80
correct cut words across the 98 fixtures with zero true overcut words,
without touching any Sol decision.

## Change plan

One change: extend `ai_video_editor/duplicate/local_corrections.py` with an
adjacent-pair (distance-1) detector, emitted through the same
`DuplicateFlag`/`WordTrim` merge point in `section_editor.py`. No prompt,
model, schema, or EDL-builder change.

Detection for each adjacent pair `(i, i+1)`:

- the later sentence starts no more than 10 s after the earlier ends (same
  budget as the chain lane);
- normalized alnum tokens (same `_indexed_tokens` normalization);
- search the **longest** earlier-suffix ↔ later-prefix match, span ≥ 3
  tokens, allowing the prefix length to differ by ±2 tokens (insertions like
  "dalje", token merges like "od tud"/"odtud");
- **anchored endpoints**: the first tokens of both spans and the last tokens
  of both spans must be equal or one a string-prefix of the other — this
  rejects order-flipped synonym pairs and paraphrase restarts;
- span similarity `fuzz.ratio ≥ 90` on the joined normalized tokens;
- if the match covers only part of the earlier sentence → `WordTrim` from the
  match start to the sentence end (trailing abandoned copy);
- if the match covers the **whole** earlier sentence → full-sentence flag,
  but **only when the later sentence continues past the matched prefix**.
  This continuation requirement structurally excludes exact adjacent twins —
  the deliberate-dictation/emphasis repeats that the human keeps both of.

Starting operating point (span ≥ 3, sim ≥ 90, gap ≤ 10 s, slack ±2) may be
refined by a pre-implementation fixed-EDL projection over the 98 fixtures,
exactly as candidate 6 refined its ratio/continuation conditions; any
refinement is documented here before the gates are scored.

**Refinement from the projection sweep (documented before gate scoring):**
the first sweep produced 150 spans with 6 audited both-kept violations and
one control regression (listening-1 [108]). All seven shared one structure —
the *restate-and-elaborate* teaching pattern, where the repeated phrase is a
small opening fraction of the later sentence which then predicates new
content on it ("…tlak od sedam bara." → "Tlak od sedam bara **nalazi se
između**…"). In every true restart the repeat covers at least half of the
later sentence. Added condition: the matched later prefix must cover
**≥ 50% of the later sentence's tokens** (`_ADJACENT_MIN_LATER_COVERAGE`).
No other constant changed.

## Evaluation method

Offline, network-free, against the iter-020 baseline EDLs
(`output/qa-iteration-19/candidate-6-projection-98/edls`) and raw fixture
transcripts — no Sol rerun, so no model variance:

1. **Explicit-case scoring** via `evaluate_repeat_cases` on projected EDLs
   (baseline EDL + detector delta, keep-spans punched like `build_edl`).
2. **Standalone span audit**: every detector-emitted span is scored
   position-aware against the human transcript — locate the local
   ground-truth window, count surviving copies of the repeated span. A cut is
   correct iff the human's window retains fewer copies than the raw
   transcript and the surviving copy is present; if the human kept **both**
   copies, the cut is a true overcut. This bypasses the raw-LCS attribution
   trap ("identical later copies make the earlier span look kept") that
   invalidated the naive adjacent-suffix scoring in the iter-020 analysis.
3. **Aggregate word-level projection** (`evaluate_decisions_word_level`) for
   the official scoreboard numbers, with the caveat that sub-sentence echo
   cuts can be mis-attributed by LCS; any apparent new overcut word must be
   individually explained by the audit as a twin-attribution artifact, or the
   gate fails.

## Gates (fixed before implementation)

Iter-020 passes only if:

- at least **8 of the 13** open explicit cut cases newly pass, each with its
  required sentence remainder preserved;
- the 3 previously passing sandwich-chain spans still pass;
- **zero** regressions among the manifest keep controls (all 14 baseline-
  passing controls still pass, including the bilingual and
  intentional-repetition controls);
- standalone audit: at least **60 correct cut words**, **zero spans where the
  human kept both copies**;
- aggregate projection: recall and F1 improve; no per-video F1 loss that the
  audit cannot attribute to twin mis-attribution;
- the full test suite passes, plus new unit tests covering: a verbatim echo
  suffix, an extended-prefix restart, a token-merge restart, a whole-sentence
  restart with continuation, an exact adjacent twin (must NOT fire), and a
  short synonym/emphasis repeat (must NOT fire).

On any gate failure: `git revert`, record in `ITERATION_LOG.md`.

## Risk

Educational speech repeats content deliberately — dictation in
listening/reading lessons is the canonical danger (31 both-kept twin pairs
exist in the corpus). Mitigations: the continuation requirement excludes
exact standalone twins; anchored endpoints plus sim ≥ 90 exclude synonym
flips and paraphrases; span ≥ 3 excludes two-word emphasis. The standalone
audit's "human kept both copies" check is the hard backstop — any such span
fails the iteration.

Residual risk: echo cases where the human kept the *earlier* copy and cut the
later one (take swap). The cut content survives either way; the audit counts
copies rather than positions, so these score as take-consistent, mirroring
the sentence-level reconciliation already used by the official scorer.

## Expected outcome

- Explicit cases: 3/16 → ≥11/16 positives, controls unchanged.
- ~60–80 recovered cut words: recall 0.6762 → ≈0.680–0.681, precision
  ~flat-to-up (0.7973 → ≈0.799), F1 0.7318 → ≈0.734–0.736.
- Only videos containing detector hits change; every changed video improves
  or is neutral under audit-corrected attribution.
