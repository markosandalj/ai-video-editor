# Logging Setup

Status: `done`
Phase: 0
Depends on: 0.01, 0.02

## Objective

Structured logging so pipeline runs are debuggable, with output to console, per-run files, and per-video files in batch mode.

## Requirements

- Library: Loguru
- Log destinations:
  - Console (stdout) -- always on, colored output
  - Per-run log file -- one log file per pipeline invocation
  - Per-video log file -- in batch mode, each video gets its own log file
- Log level configurable via `Settings.general.log_level`
- Log files stored in output directory alongside results

## Implementation Notes

- `ai_video_editor/logging/setup.py` with `setup_logging(settings)` function
- Called once at CLI startup
- Console sink: INFO level by default, colored
- Run log sink: DEBUG level, written to `{output_dir}/logs/run_{timestamp}.log`
- Video log sink: added/removed dynamically per video in batch mode
- Loguru's `logger.bind()` used to tag log messages with video filename in batch mode

## Acceptance Criteria

- [x] `setup_logging()` configures console + per-run file sinks
- [x] Log level respects config setting
- [x] Per-video log files created during batch processing
- [x] Log output includes timestamps and module context
- [x] Colored console output for readability
