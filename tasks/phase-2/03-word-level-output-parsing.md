# Word-Level Output Parsing

Status: `done`
Phase: 2
Depends on: 2.01, 2.02

## Objective

Parse WhisperX raw output into the standardized `Word` model instances, handling edge cases.

## Requirements

- Parse WhisperX segment/word JSON into `Word` objects
- Drop words with missing start or end timestamps
- Log count of dropped words for visibility
- Preserve word ordering

## Implementation Notes

- WhisperX returns `{"segments": [{"words": [{"word": "...", "start": ..., "end": ...}]}]}`
- Filter out any word dict where `start` or `end` is None/missing
- Create `Word` instances from remaining dicts
- Function: `parse_whisperx_output(result) -> list[Word]`

## Acceptance Criteria

- [x] WhisperX output parsed into `Word` objects
- [x] Words with missing timestamps dropped (with log message)
- [x] Word ordering preserved from WhisperX output
