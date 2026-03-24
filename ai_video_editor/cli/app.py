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


@app.command()
def qa(
    fixtures_dir: Path = typer.Argument(
        "tests/fixtures",
        exists=True,
        help="Directory containing test pairs (<name>-raw.mp4 + <name>-edited.mp4).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Shortcut for DEBUG log level."),
) -> None:
    """Run QA checks on all test video pairs and record regression scores."""
    from ai_video_editor.config.settings import Settings
    from ai_video_editor.duplicate.edl import EditDecisionList
    from ai_video_editor.qa.continuity import verify_continuity
    from ai_video_editor.qa.ground_truth import compare_temporal, compare_transcripts_from_videos, transcribe_for_qa
    from ai_video_editor.qa.models import QAIssue, QAReport, Severity
    from ai_video_editor.qa.regression import check_regression, discover_pairs, record_scores
    from ai_video_editor.qa.report import print_summary, save_report
    from ai_video_editor.qa.splice import analyze_splices
    from ai_video_editor.qa.spectrogram import compare_spectrograms
    from ai_video_editor.transcription.models import Transcript

    settings = Settings()
    if verbose:
        setup_logging(settings.model_copy(
            update={"general": settings.general.model_copy(update={"log_level": "DEBUG"})}
        ))

    pairs = discover_pairs(fixtures_dir)
    if not pairs:
        logger.error("No test pairs found in {}", fixtures_dir)
        raise typer.Exit(code=1)

    root = Path(__file__).resolve().parent.parent.parent
    history_path = fixtures_dir / "regression_scores.json"
    reports: list[QAReport] = []

    for name, raw_path, gt_path in pairs:
        logger.info("QA for pair: {}", name)

        pipeline_video = raw_path.with_name(f"{name}-raw_edited.mp4")
        edl_path = raw_path.with_suffix(".edl.json")
        edited_transcript_path = raw_path.with_name(f"{name}-raw_edited.transcript.json")
        denoised_path = root / ".ai_video_editor_tmp" / f"{name}-raw_denoised.wav"

        if not pipeline_video.exists():
            logger.warning("Pipeline output not found: {} — skipping", pipeline_video.name)
            continue

        report = QAReport(video_name=name)
        issues: list[QAIssue] = []

        pipeline_sentences = transcribe_for_qa(pipeline_video, force=True)

        tc = compare_transcripts_from_videos(pipeline_video, gt_path, pipeline_sentences=pipeline_sentences)
        report.transcript_comparison = tc
        if tc.f1 < 0.8:
            issues.append(QAIssue(
                check="transcript_comparison", severity=Severity.WARNING,
                message=f"Low F1 score: {tc.f1:.1%}",
            ))

        if tc.matches:
            tp = compare_temporal(pipeline_video, gt_path, [], [], tc.matches)
            report.temporal_comparison = tp
            if tp.temporal_score < 0.7:
                issues.append(QAIssue(
                    check="temporal_comparison", severity=Severity.WARNING,
                    message=f"Low temporal score: {tp.temporal_score:.1%}",
                ))

        if edl_path.exists():
            edl = EditDecisionList.model_validate_json(edl_path.read_text("utf-8"))
            sa = analyze_splices(pipeline_video, edl)
            report.splice_analysis = sa
            if sa.harsh_splices > 0:
                issues.append(QAIssue(
                    check="splice_analysis", severity=Severity.WARNING,
                    message=f"{sa.harsh_splices} harsh splices detected",
                ))

            if denoised_path.exists():
                sc = compare_spectrograms(pipeline_video, denoised_path, edl)
                report.spectrogram_comparison = sc
                if not sc.passed:
                    issues.append(QAIssue(
                        check="spectrogram_comparison", severity=Severity.ERROR,
                        message=f"Spectrogram similarity too low: {sc.similarity_score:.4f}",
                    ))

        if edited_transcript_path.exists():
            edited_transcript = Transcript.model_validate_json(
                edited_transcript_path.read_text("utf-8")
            )
            ct = verify_continuity(edited_transcript.sentences, pipeline_sentences)
            report.continuity = ct
            if ct.alignment_score < 0.9:
                issues.append(QAIssue(
                    check="continuity", severity=Severity.WARNING,
                    message=f"Low continuity: {ct.alignment_score:.1%} ({len(ct.missing_sentences)} missing)",
                ))

        report.issues = issues
        report.overall_passed = not any(i.severity == Severity.ERROR for i in issues)
        print_summary(report)
        save_report(report, fixtures_dir)
        reports.append(report)

    if reports:
        entry = record_scores(reports, history_path)
        warnings = check_regression(entry, history_path)
        logger.info("AGGREGATE SCORE: {:.1%}", entry.aggregate_score)
        if warnings:
            for w in warnings:
                logger.warning(w)

    logger.info("QA complete.")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
