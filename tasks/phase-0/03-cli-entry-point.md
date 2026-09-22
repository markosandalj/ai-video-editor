# CLI Entry Point

Status: `done`
Phase: 0
Depends on: 0.01, 0.02

## Objective

Create a Typer-based CLI that orchestrates the pipeline with two initial subcommands.

## Requirements

- Framework: Typer
- Subcommands for Phase 0:
  - `process` -- process a single video file (path as argument)
  - `batch` -- process multiple videos via glob pattern (e.g., `"lectures/**/*.mp4"`)
- Both commands are stubs for now, real logic added in later phases
- Config file is the single source of truth for parameters (no CLI overrides for pipeline settings)
- CLI flags limited to: input path/glob, output directory, config file path, verbosity

## Implementation Notes

- Entry point via `pyproject.toml` `[project.scripts]` so it's callable as `ai-video-editor process ...`
- Also runnable via `python -m ai_video_editor`
- Typer app in `ai_video_editor/cli/app.py`
- `process` takes a single file path argument
- `batch` takes a glob pattern string argument
- Both accept `--output-dir` and `--config` options

## Acceptance Criteria

- [x] `ai-video-editor` command available after install
- [x] `ai-video-editor process <file>` runs (stub output for now)
- [x] `ai-video-editor batch "<glob>"` runs (stub output for now)
- [x] `ai-video-editor --help` shows both subcommands with descriptions
- [x] `python -m ai_video_editor` also works
