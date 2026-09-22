# Transcript Data Models

Status: `done`
Phase: 2
Depends on: phase-0 complete

## Objective

Define strict Pydantic models for words, sentences, and transcripts to enforce data structure throughout the pipeline.

## Requirements

- `Word`: text, start, end (nullable for unaligned words)
- `Sentence`: list of words, full text, start, end timestamps
- `Transcript`: list of sentences, source metadata
- Words with missing timestamps are dropped (not interpolated)

## Implementation Notes

- Define in `ai_video_editor/transcription/models.py`
- `Word.start` and `Word.end` are required floats (unaligned words filtered out before model creation)
- `Sentence.start` = first word's start, `Sentence.end` = last word's end
- `Transcript` includes metadata: source_video, language, model_size, processing timestamp
- JSON serialization via Pydantic `.model_dump_json()`

## Acceptance Criteria

- [x] `Word`, `Sentence`, `Transcript` Pydantic models defined
- [x] Models enforce required fields (text, start, end timestamps)
- [x] JSON serialization/deserialization works correctly
