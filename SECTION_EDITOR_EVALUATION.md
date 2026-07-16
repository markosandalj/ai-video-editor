# Section-Editor Model Evaluation

**Status:** decision made — living document, update as new models/runs land.
**Last updated:** 2026-07-12
**Decision:** production default = **`gpt-5.6-sol`** (via OpenRouter). Alternatives kept:
**`claude-fable-5`** (best precision, ~2× cost) and **`gemini-3.1-pro`** (budget, ~¼ cost).

---

## TL;DR

We replaced the old tiered duplicate detector with an **LLM section editor** (a strong
model reads paragraph-sized windows and returns verbatim spans to delete; deterministic
code maps them to word-level cuts and validates every one). We then bench-tested 14 models
on 10 fixtures, and the 5 finalists on the **full 98-video corpus**, scoring cuts at the
word level against the human editor.

- **Every finalist beats the old pipeline by a wide margin** — 5–6× fewer wrong cuts at
  equal-or-better recall. The architecture question is settled; only model choice remained.
- **Top three are effectively tied on quality** (F1 0.68–0.73); the real spread is **cost
  (~4×) and precision profile**.
- **Chosen: `gpt-5.6-sol`** as the sane middle ground — near-top quality, best recall,
  mid cost.

---

## The decision and why

Only three models are live options; the rest are ruled out on cost or quality (see tables).

| role | model | why |
|---|---|---|
| **Production default** | **gpt-5.6-sol** | Tied-top F1 (0.724), **best recall (0.682)** — catches the most real cuts. Mid cost (~$0.08/video). The balanced pick. |
| **Precision alternative** | claude-fable-5 | Highest precision (0.816), fewest wrong cuts. Use when overcutting must be minimised and budget is not the constraint (~$0.15/video, ~2× sol). |
| **Budget alternative** | gemini-3.1-pro | ~94% of sol's F1 at **~¼ the cost** (~$0.04/video). Precision-leaning but lower recall. Use for high-volume/cost-sensitive batches. |

**Why sol over fable, given fable's marginally higher F1 (0.727 vs 0.724):** the two are a
statistical dead heat on quality (they split per-fixture wins 26–25). Fable is the better
*precision* pick, but sol's higher recall means fewer flubs left in the video for the
human to catch manually, at roughly half the cost. Sol is the balanced default; fable
stays documented for precision-critical work.

---

## Full 98-video results (word-level cut scoring vs human edit)

Positive class = CUT. "wrong-cut words" = content the human kept that the model cut
(the expensive error — a human must notice and restore it). Higher precision = fewer of these.

| model | F1 | precision | recall | wrong-cut words | ~cost / video | ~cost / 98-run | health |
|---|---|---|---|---|---|---|---|
| claude-fable-5 | 0.727 | **0.816** | 0.655 | **2,333** | $0.15 | $14.56 | ⚠️ 2/120 retried\* |
| **gpt-5.6-sol** | **0.724** | 0.772 | **0.682** | 3,201 | $0.08 | $7.67 | ✅ OK |
| gpt-5.5 (openrouter) | 0.692 | 0.760 | 0.636 | 3,174 | $0.07 | $6.42 | ✅ OK |
| gpt-5.6-terra | 0.688 | 0.755 | 0.632 | 3,255 | $0.04 | $3.99 | ✅ OK |
| gemini-3.1-pro | 0.682 | 0.798 | 0.596 | 2,396 | $0.04 | $3.90 | ⚠️ 1/120 retried\* |
| *tiered baseline (old)* | *0.491* | *0.399* | *0.636* | *15,159* | — | — | — |

\* Health = failed section calls (transient OpenRouter/provider errors). A failed section
scores as zero cuts, so it understates that model slightly. The failures were 1–2 of 120
sections; the ranking is unchanged when the affected fixtures are excluded (fable 0.728,
sol 0.720). Worth an automatic section-retry before production (see Open Items).

**Per-fixture wins** (best F1 per video, ties split): sol 26.1 · fable 24.8 · gemini 19.8 ·
gpt-5.5 10.7 · terra 8.6.

**Small-edit regime** — the 28 videos where the human cut <30 words (overcutting hurts
most here): mean wrong-cut words/video — fable **6.6**, terra 6.2, sol 7.8, gemini 9.4,
gpt-5.5 9.9. Videos with zero wrong cuts: fable **7/28**, gemini 5, terra 5, sol 4.
(This is fable's strongest argument as the precision alternative.)

---

## 10-fixture pilot (all 14 models) — how the budget tier was ruled out

Before the full run, a 10-fixture sweep tested every candidate. The cheap tier failed
uniformly by **under-cutting** (very low recall) — a fail-safe direction (they leave the
mess in rather than butcher content), but not viable as the primary editor.

| tier | models | verdict |
|---|---|---|
| Top (F1 0.70–0.75) | gpt-5.6-sol, claude-fable-5, gemini-3.1-pro, gpt-5.6-terra, gpt-5.5 | advanced to full run |
| Mid (F1 0.60–0.64) | claude-sonnet-5, claude-opus-4.8, gemini-3.5-flash, gpt-5.6-luna | beat baseline, not top |
| Budget (F1 <0.50) | gemini-3.1-flash-lite (0.47), claude-haiku-4.5 (0.37), gpt-5-mini (0.26) | **ruled out** — recall too low |

Anchors (direct API, not OpenRouter): gpt-5.5-direct 0.682, gemini-2.5-pro-direct 0.670.
Note: gpt-5.5 via OpenRouter (0.699) ≈ direct (0.682) — no reliability tax once configured
correctly (see Methodology).

---

## Architecture context (why any of this beats the old pipeline)

The old tiered detector compared sentence *pairs* through a small model, one mechanism at
a time. Two structural failures fell out of that: it could only cut whole sentences (no
partial-sentence redo trimming), and each prompt saw ±2 sentences (couldn't tell a recap
from a retake). The section editor fixes both by giving one strong model a whole section
and having it return verbatim spans — whole sentences *or* partial spans.

**LLM proposes, deterministic code disposes.** Every proposed deletion is validated before
it becomes a cut (`ai_video_editor/duplicate/section_editor.py`):
- **verify-the-claim** — a span that can't be located verbatim is rejected;
- **short-interjection protection** — whole-sentence retake cuts of <4-word lines dropped;
- **keep-later** — retake deletions that keep the earlier take are demoted to review;
- **recap time-gap** — retake deletions whose twin is >60s away are demoted;
- **annotate-only** — "redundant" (unique-content) cuts surface as review suggestions.

Config: `SectionEditorConfig` (`ai_video_editor/config/settings.py`), enabled by default
with `gpt-5.6-sol` through OpenRouter. The audio lane (silence, disruptions, asides) runs
alongside; the section editor only replaces the text-judgment cuts.

---

## Cost detail

Estimates from **measured** token usage (real output incl. billed reasoning tokens),
~262k input tokens + 120 section calls per full 98-video run. Expect ±25% (temp 1.0 run
variance). One-time eval cost of the whole finalist sweep on 98 videos: **~$37**.

| model | in $/M | out $/M | ~$/98-run | notes |
|---|---|---|---|---|
| gpt-5.6-sol | 5.00 | 30.00 | $7.67 | chosen default |
| claude-fable-5 | 10.00 | 50.00 | $14.56 | priciest; heaviest tokenizer (+40% input) |
| gpt-5.5 (openrouter) | 5.00 | 30.00 | $6.42 | |
| gpt-5.6-terra | 2.50 | 15.00 | $3.99 | |
| gemini-3.1-pro | 2.00 | 12.00 | $3.90 | cheapest of the finalists |

These are eval-scale numbers, not production throughput. Against editor labour time the
absolute per-video cost ($0.04–0.15) is negligible; cost only matters at high volume,
which is where gemini-3.1-pro becomes attractive.

---

## Enrichment-arbiter A/B (2026-07-13): disabled for section-editor cuts

The former enrichment arbiter could override the cutter — restoring flags it was
confident about and adding tag-gated extra cuts. It was tuned to correct the old
tiered detector (word-level cut precision ~0.40). A/B on all 98 fixtures, same fresh
gpt-5.6-sol flags in both arms, enrichment scored by **gemini-3.1-pro**:

| arm | P | R | F1 | wrong-cut words |
|---|---|---|---|---|
| A — sol flags, arbiter OFF | 0.769 | 0.660 | **0.710** | 3,149 |
| B — sol flags + arbiter | 0.729 | 0.637 | 0.680 | 3,748 |

**ΔF1 = −0.030 — the arbiter hurts on both axes.** Action-level accounting against the
human edit is the decisive part:
- **Restores (un-cuts): 103 good / 103 bad — a literal coin flip.** Against a 77%-precision
  cutter, enrichment's independent keep-confidence carries no usable signal.
- **Extra cuts: 76 good / 95 bad — worse than a coin flip** (+599 wrong-cut words).
- Per fixture: helped 19, hurt 41, unchanged 38.

This is ensemble logic working as expected: an overrider only helps when it is more
accurate than the thing it overrides. Enrichment beat the old 0.40-precision detector;
it loses to the 0.77-precision section editor.

**Action taken (updated 2026-07-14):** enrichment and its arbiter were removed from the
active processing path entirely. Review and QA diff payloads also ignore historical
`.enrichment.json` sidecars, so old annotations cannot leak into a new review. The
enrichment runtime and experiment code have now been deleted. Historical result artifacts:
`output/arbiter-ab/` (results.json, per-fixture flags + enrichment sidecars).

Sanity note: arm A re-ran sol from scratch and scored 0.710 vs 0.724 recorded above —
that's temp-1.0 run-to-run variance (~±0.015), worth remembering when comparing tables.

---

## Excluded / not tested

- **grok-4.5** — requested, but **region-locked** by xAI (`"not available in your region"`
  via OpenRouter). Not a code issue; needs regional access or a different grok variant
  (catalog has grok-4.3, grok-4.20).

---

## Open items / next steps

1. **Completed 2026-07-14:** `gpt-5.6-sol` is the enabled section-editor default;
   enrichment and its arbiter are absent from processing and QA review payloads.
2. **Add an automatic section retry** for transient provider failures (the 1–2 degraded
   sections). Cheap and removes the health caveat.
3. **Bigger corpus / re-run** if the top-3 gap (0.68–0.73) needs tightening — it's within
   run-to-run variance today.
4. **Re-test grok-4.5** if regional access is sorted.

---

## How to reproduce / update this report

```bash
# 1. resolve model IDs + params against the live OpenRouter catalog
curl -s https://openrouter.ai/api/v1/models | ...

# 2. per-model full-corpus run (health-tracked, word-level scored)
set -a; . ./.env; set +a
uv run python -m ai_video_editor eval-section-editor \
    --manifest manifests/section-sweep.json --model <key> \
    --output-dir output/section-pilot/full/<key>
```

- Manifest: `manifests/section-sweep.json` (OpenRouter configs: temp 1.0, reasoning
  effort low, 16k output cap — the settings that avoid the reasoning-token "no output"
  failure seen early on).
- Per-model artifacts: `output/section-pilot/full/<model>/` (report.md, results.json,
  per-video EDLs).
- Scoring: word-level cut P/R/F1 (`qa/decision_eval.py::evaluate_decisions_word_level`),
  with health telemetry (`SectionHealth`) so a broken model can't masquerade as a careful
  one. Only compare models whose runs are healthy (or exclude the degraded fixtures).
- Pilot leaderboard artifact (10-fixture, all models): `output/section-pilot/sweep/LEADERBOARD.md`.
- Related: `MISTAKE_PATTERNS.md` (the failure-pattern analysis that motivated the section editor).
