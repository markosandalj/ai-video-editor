from __future__ import annotations

import glob
from pathlib import Path

import typer
from loguru import logger

from ai_video_editor.config.settings import get_settings
from ai_video_editor.logging.setup import attach_video_log, remove_video_log, setup_logging

app = typer.Typer(
    name="ai-video-editor",
    help="AI-assisted transcript-based video editing pipeline",
    no_args_is_help=True,
)


def _resolve_video_extensions() -> tuple[str, ...]:
    return (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")


@app.command()
def process(
    input_path: Path = typer.Argument(..., exists=True, readable=True, help="Path to a single video file."),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Output directory (default: from Settings.general.output_dir).",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        exists=True,
        readable=True,
        help="Optional Python file defining `settings` (a Settings instance).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Shortcut for DEBUG log level."),
) -> None:
    """Process a single video (pipeline not yet implemented)."""
    settings = get_settings(config_path=config)
    g_updates: dict = {}
    if output_dir is not None:
        g_updates["output_dir"] = output_dir.expanduser().resolve()
    if verbose:
        g_updates["log_level"] = "DEBUG"
    if g_updates:
        settings = settings.model_copy(
            update={"general": settings.general.model_copy(update=g_updates)}
        )

    setup_logging(settings)
    stem = input_path.stem
    attach_video_log(settings, stem)
    log = logger.bind(video=stem)
    log.info("Stub: single-file processing not implemented yet. Input: {}", input_path)
    remove_video_log(stem)


@app.command()
def batch(
    pattern: str = typer.Argument(..., help='Glob pattern, e.g. "videos/**/*.mp4"'),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Output directory (default: from Settings.general.output_dir).",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        exists=True,
        readable=True,
        help="Optional Python file defining `settings` (a Settings instance).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Shortcut for DEBUG log level."),
) -> None:
    """Process all videos matching a glob pattern (pipeline not yet implemented)."""
    settings = get_settings(config_path=config)
    g_updates: dict = {}
    if output_dir is not None:
        g_updates["output_dir"] = output_dir.expanduser().resolve()
    if verbose:
        g_updates["log_level"] = "DEBUG"
    if g_updates:
        settings = settings.model_copy(
            update={"general": settings.general.model_copy(update=g_updates)}
        )

    setup_logging(settings)
    paths = sorted(Path(p) for p in glob.glob(pattern, recursive=True))
    exts = _resolve_video_extensions()
    videos = [p for p in paths if p.is_file() and p.suffix.lower() in exts]

    if not videos:
        logger.warning("No video files matched pattern: {}", pattern)
        raise typer.Exit(code=1)

    for p in videos:
        stem = p.stem
        attach_video_log(settings, stem)
        log = logger.bind(video=stem)
        log.info("Stub: batch item not processed yet. File: {}", p)
        remove_video_log(stem)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
