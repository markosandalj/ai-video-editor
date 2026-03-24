# Sentence Chunking

Status: `done`
Phase: 2
Depends on: 2.03

## Objective

Aggregate word-level data into sentence-level chunks by splitting on terminal punctuation, capturing precise start/end timestamps per sentence.

## Requirements

- Split on terminal punctuation: `.`, `?`, `!`
- Trust WhisperX punctuation as-is (no post-processing)
- Each sentence: start = first word start, end = last word end
- Handle edge cases: abbreviations, decimal numbers, ellipses

## Implementation Notes

- Iterate through word list, accumulate into current sentence
- When a word ends with terminal punctuation, close the sentence
- If transcript ends without terminal punctuation, close final sentence anyway
- Function: `chunk_into_sentences(words: list[Word]) -> list[Sentence]`
- Croatian-specific: watch for abbreviations like "dr.", "prof.", "str."

## Acceptance Criteria

- [x] Words grouped into sentences on terminal punctuation (`.`, `?`, `!`)
- [x] Each sentence has start time of first word and end time of last word
- [x] Edge cases handled (Croatian abbreviations, final sentence without punctuation)
