# Transcript Caching

Status: `done`
Phase: 2
Depends on: 2.03, 2.04

## Objective

Cache transcription results to disk so re-runs don't re-transcribe already processed videos.

## Requirements

- Cache stored alongside source video: `video.mp4` → `video.transcript.json`
- No automatic cache invalidation (user deletes file or uses `--force`)
- Add `--force` flag to CLI to skip cached transcripts
- Cache contains full `Transcript` model serialized as JSON

## Implementation Notes

- Save: `transcript.model_dump_json(indent=2)` to `{video_stem}.transcript.json`
- Load: `Transcript.model_validate_json(path.read_text())`
- Check: `if cache_path.exists() and not force: load from cache`
- Add `--force` flag to `process` and `batch` CLI commands

## Acceptance Criteria

- [x] Transcript saved as JSON next to source video (test-2-raw.transcript.json)
- [x] Pipeline skips transcription if cache exists (and --force not set)
- [x] --force flag added to both process and batch CLI commands
