# Word-Level Output Parsing

Status: `done`
Phase: 2
Depends on: 2.01, 2.02

## Objective

Parse ElevenLabs Scribe tokens into standardized `Word` and `AudioEvent` models.

## Requirements

- Keep word tokens as timestamped `Word` objects
- Keep non-speech tokens as separate `AudioEvent` objects
- Drop spacing tokens so they never enter transcript text
- Preserve token ordering

## Implementation Notes

- ElevenLabs returns word, spacing, and audio-event tokens.
- `_parse_stt_tokens()` creates words and audio events in separate lists.

## Acceptance Criteria

- [x] ElevenLabs word tokens parsed into `Word` objects
- [x] Audio events kept outside transcript text
- [x] Word ordering preserved
