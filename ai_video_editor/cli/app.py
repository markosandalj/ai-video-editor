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
    force: bool = typer.Option(False, "--force", "-f", help="Ignore cached transcripts, re-process from scratch."),
) -> None:
    """Process a single video through the editing pipeline."""
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
    log.info("Processing: {}", input_path)

    from ai_video_editor.audio import compute_keep_regions, detect_silences, extract_audio, reduce_noise
    from ai_video_editor.duplicate.debug import save_debug_files
    from ai_video_editor.duplicate.edl import build_edl
    from ai_video_editor.duplicate.pipeline import detect_duplicates
    from ai_video_editor.render import render_video
    from ai_video_editor.transcription import load_cached_transcript, save_transcript
    from ai_video_editor.transcription.pipeline import transcribe_with_elevenlabs_and_grammar

    meta = extract_audio(input_path, settings)
    denoised = reduce_noise(meta, settings)
    silences = detect_silences(denoised, settings)
    keeps = compute_keep_regions(silences, denoised.duration_s, settings)

    cached = None if force else load_cached_transcript(input_path)
    if cached is not None:
        log.info("Using cached transcript ({} sentences)", len(cached.sentences))
    else:
        cached = transcribe_with_elevenlabs_and_grammar(denoised, input_path, settings)
        save_transcript(input_path, cached)

    flags = detect_duplicates(cached.sentences, settings.duplicate_detection)
    edl = build_edl(cached, keeps, flags)

    edl_path = input_path.with_suffix(".edl.json")
    edl_path.write_text(edl.model_dump_json(indent=2), encoding="utf-8")

    save_debug_files(input_path, cached, edl)

    output = render_video(
        input_path,
        edl,
        Path(denoised.path),
        settings.render,
    )

    log.info(
        "Pipeline complete: {} sentences, {} flagged, keep={:.1f}s cut={:.1f}s → {}",
        len(cached.sentences), len(flags), edl.keep_duration, edl.cut_duration, output.name,
    )
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
    force: bool = typer.Option(False, "--force", "-f", help="Ignore cached transcripts, re-process from scratch."),
) -> None:
    """Process all videos matching a glob pattern."""
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

    from ai_video_editor.audio import compute_keep_regions, detect_silences, extract_audio, reduce_noise
    from ai_video_editor.duplicate.debug import save_debug_files
    from ai_video_editor.duplicate.edl import build_edl
    from ai_video_editor.duplicate.pipeline import detect_duplicates
    from ai_video_editor.render import render_video
    from ai_video_editor.transcription import load_cached_transcript, save_transcript
    from ai_video_editor.transcription.pipeline import transcribe_with_elevenlabs_and_grammar

    success = 0
    failed = 0
    for i, p in enumerate(videos, 1):
        stem = p.stem
        attach_video_log(settings, stem)
        log = logger.bind(video=stem)
        log.info("[{}/{}] Processing: {}", i, len(videos), p)
        try:
            meta = extract_audio(p, settings)
            denoised = reduce_noise(meta, settings)
            silences = detect_silences(denoised, settings)
            keeps = compute_keep_regions(silences, denoised.duration_s, settings)

            cached = None if force else load_cached_transcript(p)
            if cached is not None:
                log.info("Using cached transcript ({} sentences)", len(cached.sentences))
            else:
                cached = transcribe_with_elevenlabs_and_grammar(denoised, p, settings)
                save_transcript(p, cached)

            flags = detect_duplicates(cached.sentences, settings.duplicate_detection)
            edl = build_edl(cached, keeps, flags)

            edl_path = p.with_suffix(".edl.json")
            edl_path.write_text(edl.model_dump_json(indent=2), encoding="utf-8")

            save_debug_files(p, cached, edl)

            output = render_video(p, edl, Path(denoised.path), settings.render)

            log.info(
                "Done: {} sentences, {} flagged, keep={:.1f}s cut={:.1f}s → {}",
                len(cached.sentences), len(flags), edl.keep_duration, edl.cut_duration, output.name,
            )
            success += 1
        except Exception:
            log.exception("Failed to process {}", p)
            failed += 1
        finally:
            remove_video_log(stem)

    logger.info("Batch complete: {}/{} succeeded, {} failed", success, len(videos), failed)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
