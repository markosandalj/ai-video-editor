# Core Dependencies

Status: `done`
Phase: 0
Depends on: 0.01

## Objective

Add all required Python dependencies to `pyproject.toml` so the development environment is reproducible.

## Requirements

- Use version ranges (e.g., `>=X.Y`), let `uv.lock` handle exact pinning
- Python version: keep `>=3.13` for now, drop if ML deps break later
- Phase 0 deps only: `typer`, `pydantic`, `pydantic-settings`, `loguru`
- Additional deps added as phases require them (incremental approach)

## Implementation Notes

- `pyproject.toml` updated with Phase 0 dependencies using `>=` ranges
- `uv sync` to install and lock
- Future phases will add: `noisereduce`, `ffmpeg-python`, `whisperx`, `sentence-transformers`, `thefuzz`, `numpy`, `scipy`, `librosa`, `opentimelineio`

## Acceptance Criteria

- [x] `typer`, `pydantic`, `pydantic-settings`, `loguru` added to `pyproject.toml`
- [x] `uv sync` installs everything cleanly
- [x] No conflicting dependency versions
