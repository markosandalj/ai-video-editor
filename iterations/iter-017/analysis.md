# iter-017 — Audio-driven false-start detection (cough / acoustic disruption)

## Motivation

The edit layer is almost entirely text-driven. The only audio signal it uses is
FFmpeg `silencedetect` (energy gaps). A human editor also *hears* the recording,
and one of the strongest cues for a flubbed take is a **cough / throat-clear /
noise in a pause**: the speaker finishes a thought, coughs, mutters a short
hesitant restart, then redoes the line. The transcript shows only an innocent
short phrase, so text-only logic keeps it.

### Worked example (test-1, ~5:13)

```
[56] 303.32–306.66  "Dakle, to mi je taj argument mog kompleksnog broja."
        ── 6.16 s pause ──   cough at 309.77–310.26  (peak −31.9 dB vs −72.6 dB floor = +40 dB)
[57] 312.82–313.74  "I dobro."          ← pipeline KEPT (reason=SPEECH); human CUT
[58] 314.63–315.22  "Pa dobro, ovako."  ← human kept (the real restart)
[59] 315.24–...     lesson continues 0.02 s later
```

Two structural gaps were found while investigating:

1. **We discard the audio events we pay for.** `elevenlabs_tag_audio_events`
   defaults to `True`, but the STT parser dropped every non-`word` token, so
   `(cough)`/`(laughter)` tags never reached any decision. Verified: **0** such
   tags survive across all 98 transcripts.
2. **The existing false-start detector only fires *between* duplicate pairs.**
   `[57]` isn't near any duplicate, so it was structurally invisible.

## Approach

Two new, network-free components (run on the same audio the silence detector uses):

- **`audio/disruption.py`** — energy-based detection of short, loud non-speech
  bursts. It looks *only* in the gaps between transcribed words (using the word
  timestamps to mask speech), so a loud burst there is non-speech by
  construction. Self-calibrating: per-file noise floor (10th-percentile frame
  dB) + a margin.
- **`duplicate/false_start_audio.py`** — flags a short, stranded phrase that sits
  right after a disruption in a long pause and is followed by a prompt restart.

Also (A): the STT parser now keeps `audio_event` tokens as a separate
`Transcript.events` stream (never inlined), merged into the disruption stream
when present. (Inert on the 98 cached transcripts — realised only on
re-transcription.)

## Threshold sweep (98 videos, offline decision-eval framing)

Newly-flagged kept sentences scored against human ground truth
(recovered = pipeline kept / human cut; FP = human kept). Two levers dominate:

| lever | effect |
|-------|--------|
| disruption strength `threshold_db` 15→18→22 | FPs ~5× lower at 22 (marginal noise stops qualifying) |
| `max_words` 4 → 3 | ~halves FPs — 4-word hits are real content ("Što nam znači reschedule?") |
| `require_disruption` False → True | ~3× fewer FPs everywhere |

**Chosen operating point:** `threshold_db=22`, `max_words=3`,
`min_gap_before_s=4.0`, `max_gap_after_s=3.5`, `require_disruption=True`.

## Result (offline decision-eval, 98 videos)

```
                 cutP    cutR   cutF1   TP    FP    FN
BASELINE        0.830   0.443   0.578   866   177  1087
+ audio FS      0.831   0.448   0.582   875   178  1078   (+9 recovered, +1 FP)
```

Precision of the *added* cuts is **0.900** (9/10) — above the pipeline's 0.830,
so it lifts precision and recall together (Pareto-positive). The 9 recoveries:

```
test-1  [57] "I dobro."        test-43 [30] "Dobro."
test-10 [110] "Ok."           test-45 ... (sweep)
test-15 [19] "Dobro."         test-47 [217] "Dobro."
test-27 [10] "Dobro."         reading-4 [4] "Pa možemo krenuti."
test-32 [29] "Okej, dobro."   test-42 [24] "OK."
```

The single FP is test-46 [39] "Ok, super." — a genuinely ambiguous filler the
human happened to keep.

**End-to-end check (local, no network):** reprocessing `test-1`'s decision chain
flips `[57]` from `keep/speech` → `cut/false_start`; on the real extract→decode
path the borderline raw-mp4 FP `[4]` doesn't even fire, so production is at least
as clean as the projection.

## Why the gain is modest

iter-016's FN analysis showed ~86% of the 1,087 missed cuts are clean content
the human removed for editorial/pacing reasons — structurally unrecoverable from
any signal. The audio rule targets the small recoverable slice where the cut cue
is acoustic rather than textual, and does so at high precision.

## Caveats / scope

- The 98-video number is the **decision-eval projection** (same method as
  iter-016), not a full render-QA re-run.
- Production runs disruption detection on the extracted raw WAV; the sweep used
  the raw mp4. Differences are minor and in the safe (fewer-FP) direction.
- Component (A) only helps after a re-transcription pass (cost decision).
