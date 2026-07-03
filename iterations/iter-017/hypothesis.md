# iter-017 — Hypothesis

## Problem

Flubbed takes whose only cut cue is acoustic (a cough/noise in a pause, a long
hesitation, a hesitant short restart) are kept by the pipeline because it decides
purely from transcript text. The canonical case is test-1 `[57] "I dobro."`,
which the speaker mutters after coughing and then redoes — text-indistinguishable
from a natural transition, so it survives.

## Hypothesis

Detecting loud non-speech bursts in pauses (acoustic disruptions) and flagging a
short, stranded phrase that follows such a disruption — in a long pause, with a
prompt restart afterward — recovers these missed cuts at high precision without
hurting the ones we already get right.

## Change plan

- `ai_video_editor/audio/disruption.py` (new): energy-based disruption detection,
  speech-masked by word timestamps, self-calibrating noise floor.
- `ai_video_editor/duplicate/false_start_audio.py` (new): the stranded-phrase
  rule → `FALSE_START` flags.
- `ai_video_editor/audio/models.py`: `DisruptionRegion`.
- `ai_video_editor/config/settings.py`: `DisruptionConfig`, `FalseStartAudioConfig`.
- `ai_video_editor/decisions.py` + `cli/app.py`: thread `disruptions` into the
  decision layer (computed from the extracted WAV).
- (A) `transcription/elevenlabs_stt.py` + `models.py` + `pipeline.py`: stop
  discarding `audio_event` tokens; carry them as `Transcript.events`; merge into
  the disruption stream.

Operating point (98-video sweep): `threshold_db=22`, `max_words=3`,
`min_gap_before_s=4.0`, `max_gap_after_s=3.5`, `require_disruption=True`.

## Risk

Cutting a genuine short instructional line that happens to follow a cough + pause
(over-cut → lost content, the costly error class per iter-014). Mitigated by the
conjunction of guards (short + long pause + loud disruption + prompt resume) and
the conservative thresholds chosen by the sweep.

## Expected outcome

Decision-eval (98 videos): +9 recovered cuts, +1 FP →
cut precision 0.830→0.831, recall 0.443→0.448, F1 0.578→0.582. Pareto-positive.
