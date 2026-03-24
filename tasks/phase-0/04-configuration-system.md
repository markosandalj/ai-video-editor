# Configuration System

Status: `done`
Phase: 0
Depends on: 0.01, 0.02

## Objective

Centralized, type-safe Python configuration using Pydantic Settings so all pipeline parameters are validated and documented in code.

## Requirements

- Python-based config using Pydantic Settings classes
- No CLI overrides for pipeline parameters -- config is the single source of truth
- No environment variable support for pipeline params
- Config organized into logical sections (audio, transcription, editing, export, etc.)
- Sections added incrementally as phases require them
- Phase 0 defines the base config structure + any global settings (output dir, temp dir)

## Implementation Notes

- `ai_video_editor/config/settings.py` with a root `Settings` class
- Nested Pydantic models for each section (e.g., `AudioConfig`, `TranscriptionConfig`)
- Default values for everything so the pipeline runs out of the box
- Config loaded once at startup, passed through the pipeline
- Phase 0 sections: `GeneralConfig` (output_dir, temp_dir, log_level)
- Future phases add sections: `AudioConfig`, `TranscriptionConfig`, `EditingConfig`, `ExportConfig`

## Acceptance Criteria

- [x] `Settings` class with nested config sections defined
- [x] All fields have sensible defaults
- [x] Validation on load (e.g., paths exist, thresholds in valid range)
- [x] Config importable and usable: `from ai_video_editor.config import get_settings` (factory; optional `--config` loads a Python file defining `settings`)
