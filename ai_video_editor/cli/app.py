from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import glob
import os
from pathlib import Path

import typer
from loguru import logger

from ai_video_editor.config.settings import Settings, get_settings
from ai_video_editor.logging.setup import attach_video_log, remove_video_log, setup_logging

app = typer.Typer(
    name="ai-video-editor",
    help="AI-assisted transcript-based video editing pipeline",
    no_args_is_help=True,
)


def _resolve_video_extensions() -> tuple[str, ...]:
    return (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")


def _default_worker_count() -> int:
    """
    Default to enough parallelism for a modern Apple Silicon laptop while
    avoiding excessive concurrent calls to ElevenLabs/Gemini.
    """
    return min(4, max(1, os.cpu_count() or 1))


DEFAULT_WORKERS = _default_worker_count()


def _process_video_file(
    p: Path,
    *,
    settings: Settings,
    force: bool,
    position: int,
    total: int,
) -> bool:
    from ai_video_editor.audio import (
        build_disruptions,
        compute_keep_regions,
        detect_silences,
        extract_audio,
        reduce_noise,
    )
    from ai_video_editor.decisions import decide_edits
    from ai_video_editor.duplicate.debug import save_debug_files
    from ai_video_editor.render import render_video
    from ai_video_editor.transcription import load_cached_transcript, save_transcript
    from ai_video_editor.transcription.pipeline import transcribe_with_elevenlabs_and_grammar

    stem = p.stem
    attach_video_log(settings, stem)
    log = logger.bind(video=stem)
    log.info("[{}/{}] Processing: {}", position, total, p)
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

        disruptions = build_disruptions(Path(meta.path), cached, settings.disruption)
        edl, _ = decide_edits(
            p, cached, keeps, silences, settings, force=force, log=log, disruptions=disruptions
        )

        edl_path = p.with_suffix(".edl.json")
        edl_path.write_text(edl.model_dump_json(indent=2), encoding="utf-8")

        save_debug_files(p, cached, edl)

        output = render_video(p, edl, Path(denoised.path), settings.render)

        log.info(
            "Done: {} sentences, keep={:.1f}s cut={:.1f}s → {}",
            len(cached.sentences), edl.keep_duration, edl.cut_duration, output.name,
        )
        return True
    except Exception:
        log.exception("Failed to process {}", p)
        return False
    finally:
        remove_video_log(stem)


def _eval_cut_decisions(raw_path: Path, edl, gt_sentences, *, name: str, issues: list):
    """Score the EDL's cut/keep calls against the human edit; append QA issues."""
    from ai_video_editor.qa.decision_eval import evaluate_decisions, to_cut_decision_result
    from ai_video_editor.qa.models import QAIssue, Severity
    from ai_video_editor.transcription.models import Transcript

    raw_transcript_path = raw_path.with_suffix(".transcript.json")
    if not raw_transcript_path.exists():
        logger.warning(
            "No raw transcript sidecar ({}) — skipping cut-decision eval",
            raw_transcript_path.name,
        )
        return None

    raw_transcript = Transcript.model_validate_json(raw_transcript_path.read_text("utf-8"))
    ds = evaluate_decisions(raw_transcript.sentences, edl, gt_sentences, name=name)
    cd = to_cut_decision_result(ds)

    if cd.needed_cuts and cd.true_cuts == 0:
        issues.append(QAIssue(
            check="cut_decisions", severity=Severity.ERROR,
            message=f"Missed all {cd.needed_cuts} cuts the human made",
        ))
    elif cd.missed_cuts:
        issues.append(QAIssue(
            check="cut_decisions", severity=Severity.WARNING,
            message=f"Missed {cd.missed_cuts}/{cd.needed_cuts} cuts the human made",
        ))
    if cd.overcuts:
        issues.append(QAIssue(
            check="cut_decisions", severity=Severity.WARNING,
            message=f"{cd.overcuts} overcut(s) — removed content the human kept",
            details={"by_mechanism": cd.wrong_cut_by_reason},
        ))
    return cd


def _run_qa_pair(pair: tuple[str, Path, Path], *, root: Path):
    from ai_video_editor.duplicate.edl import EditDecisionList
    from ai_video_editor.qa.continuity import verify_continuity
    from ai_video_editor.qa.ground_truth import (
        compare_temporal,
        compare_transcripts_from_videos,
        compare_transcripts_word_level,
        transcribe_for_qa,
    )
    from ai_video_editor.qa.models import QAIssue, QAReport, Severity
    from ai_video_editor.qa.splice import analyze_splices
    from ai_video_editor.qa.spectrogram import compare_spectrograms
    from ai_video_editor.transcription.models import Transcript

    name, raw_path, gt_path = pair
    logger.info("QA for pair: {}", name)

    pipeline_video = raw_path.with_name(f"{name}-raw_edited.mp4")
    edl_path = raw_path.with_suffix(".edl.json")
    edited_transcript_path = raw_path.with_name(f"{name}-raw_edited.transcript.json")
    denoised_path = root / ".ai_video_editor_tmp" / f"{name}-raw_denoised.wav"

    if not pipeline_video.exists():
        logger.warning("Pipeline output not found: {} — skipping", pipeline_video.name)
        return None

    report = QAReport(video_name=name)
    issues: list[QAIssue] = []

    pipeline_sentences = transcribe_for_qa(pipeline_video, force=True)
    gt_sentences = transcribe_for_qa(gt_path)

    tc = compare_transcripts_from_videos(pipeline_video, gt_path, pipeline_sentences=pipeline_sentences)
    report.transcript_comparison = tc
    if tc.f1 < 0.8:
        issues.append(QAIssue(
            check="transcript_comparison", severity=Severity.WARNING,
            message=f"Low F1 score: {tc.f1:.1%}",
        ))

    wl = compare_transcripts_word_level(pipeline_sentences, gt_sentences)
    report.word_level_comparison = wl

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

        report.cut_decisions = _eval_cut_decisions(
            raw_path, edl, gt_sentences, name=name, issues=issues
        )

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
    return report


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
    no_enrich: bool = typer.Option(False, "--no-enrich", help="Skip the transcript metadata enrichment pass."),
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
    if no_enrich:
        settings = settings.model_copy(
            update={"enrichment": settings.enrichment.model_copy(update={"enabled": False})}
        )

    setup_logging(settings)
    stem = input_path.stem
    attach_video_log(settings, stem)
    log = logger.bind(video=stem)
    log.info("Processing: {}", input_path)

    from ai_video_editor.audio import (
        build_disruptions,
        compute_keep_regions,
        detect_silences,
        extract_audio,
        reduce_noise,
    )
    from ai_video_editor.decisions import decide_edits
    from ai_video_editor.duplicate.debug import save_debug_files
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

    disruptions = build_disruptions(Path(meta.path), cached, settings.disruption)
    edl, _ = decide_edits(
        input_path, cached, keeps, silences, settings, force=force, log=log, disruptions=disruptions
    )

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
        "Pipeline complete: {} sentences, keep={:.1f}s cut={:.1f}s → {}",
        len(cached.sentences), edl.keep_duration, edl.cut_duration, output.name,
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
    no_enrich: bool = typer.Option(False, "--no-enrich", help="Skip the transcript metadata enrichment pass."),
    workers: int = typer.Option(
        DEFAULT_WORKERS,
        "--workers",
        "-w",
        min=1,
        help="Maximum videos to process concurrently. Use 1 for sequential execution.",
    ),
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
    if no_enrich:
        settings = settings.model_copy(
            update={"enrichment": settings.enrichment.model_copy(update={"enabled": False})}
        )

    setup_logging(settings)
    paths = sorted(Path(p) for p in glob.glob(pattern, recursive=True))
    exts = _resolve_video_extensions()
    videos = [p for p in paths if p.is_file() and p.suffix.lower() in exts]

    if not videos:
        logger.warning("No video files matched pattern: {}", pattern)
        raise typer.Exit(code=1)

    worker_count = min(workers, len(videos))
    logger.info("Batch processing {} videos with {} worker(s)", len(videos), worker_count)

    success = 0
    failed = 0
    if worker_count == 1:
        for i, p in enumerate(videos, 1):
            if _process_video_file(p, settings=settings, force=force, position=i, total=len(videos)):
                success += 1
            else:
                failed += 1
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _process_video_file,
                    p,
                    settings=settings,
                    force=force,
                    position=i,
                    total=len(videos),
                ): p
                for i, p in enumerate(videos, 1)
            }
            for future in as_completed(futures):
                if future.result():
                    success += 1
                else:
                    failed += 1

    logger.info("Batch complete: {}/{} succeeded, {} failed", success, len(videos), failed)


@app.command()
def qa(
    fixtures_dir: Path = typer.Argument(
        "tests/fixtures",
        exists=True,
        help="Directory containing test pairs (<name>-raw.mp4 + <name>-edited.mp4).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Shortcut for DEBUG log level."),
    workers: int = typer.Option(
        DEFAULT_WORKERS,
        "--workers",
        "-w",
        min=1,
        help="Maximum video pairs to QA concurrently. Use 1 for sequential execution.",
    ),
) -> None:
    """Run QA checks on all test video pairs and record regression scores."""
    from ai_video_editor.qa.regression import check_regression, discover_pairs, record_scores
    from ai_video_editor.qa.report import print_summary, save_report

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

    worker_count = min(workers, len(pairs))
    logger.info("Running QA for {} pairs with {} worker(s)", len(pairs), worker_count)
    if worker_count == 1:
        for pair in pairs:
            report = _run_qa_pair(pair, root=root)
            if report is not None:
                reports.append(report)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_run_qa_pair, pair, root=root): pair
                for pair in pairs
            }
            for future in as_completed(futures):
                report = future.result()
                if report is not None:
                    reports.append(report)

    reports.sort(key=lambda r: r.video_name)
    for report in reports:
        print_summary(report)
        save_report(report, fixtures_dir)

    if reports:
        entry = record_scores(reports, history_path)
        warnings = check_regression(entry, history_path)
        logger.info("AGGREGATE SCORE: {:.1%}", entry.aggregate_score)
        if warnings:
            for w in warnings:
                logger.warning(w)

    logger.info("QA complete.")


@app.command("eval-decisions")
def eval_decisions(
    fixtures_dir: Path = typer.Argument(
        "tests/fixtures",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Directory with cached <name>-raw.transcript.json, .edl.json, and -edited.qa-transcript.json.",
    ),
    names: list[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Restrict to specific fixture names (repeatable). Default: all.",
    ),
    method: str = typer.Option(
        "words",
        "--method",
        help="Human verdict derivation: words (default) or sentences (legacy).",
    ),
    compare_methods: bool = typer.Option(
        False,
        "--compare-methods",
        help="Print aggregate legacy sentence scoring vs word-coverage scoring.",
    ),
) -> None:
    """Compare pipeline cut/keep decisions to human ground truth, offline (no APIs)."""
    from ai_video_editor.qa.decision_eval import (
        aggregate,
        discover_fixture_names,
        evaluate_fixture,
        format_report,
    )

    target_names = names or discover_fixture_names(fixtures_dir)

    if compare_methods:
        by_method = {}
        for verdict_method in ("sentences", "words"):
            scores = []
            for name in target_names:
                score = evaluate_fixture(fixtures_dir, name, method=verdict_method)
                if score is not None:
                    scores.append(score)
            by_method[verdict_method] = aggregate(scores)

        old = by_method["sentences"]
        new = by_method["words"]
        print("Decision-eval method comparison (aggregate)")
        print("")
        print(f"{'method':<10} {'cutP':>6} {'cutR':>6} {'cutF1':>6} {'acc':>6} {'TP':>5} {'FP':>5} {'FN':>5} {'swap':>5}")
        print("-" * 65)
        for label, score in (("sentences", old), ("words", new)):
            print(
                f"{label:<10} {score.cut_precision:>6.3f} {score.cut_recall:>6.3f} "
                f"{score.cut_f1:>6.3f} {score.accuracy:>6.3f} "
                f"{score.tp:>5} {score.fp:>5} {score.fn:>5} {score.take_disagreements:>5}"
            )
        print("-" * 65)
        print(
            f"{'delta':<10} {new.cut_precision - old.cut_precision:>+6.3f} "
            f"{new.cut_recall - old.cut_recall:>+6.3f} "
            f"{new.cut_f1 - old.cut_f1:>+6.3f} "
            f"{new.accuracy - old.accuracy:>+6.3f} "
            f"{new.tp - old.tp:>+5} {new.fp - old.fp:>+5} "
            f"{new.fn - old.fn:>+5} {new.take_disagreements - old.take_disagreements:>+5}"
        )
        return

    if method not in {"words", "sentences"}:
        raise typer.BadParameter("method must be 'words' or 'sentences'")

    scores = []
    for name in target_names:
        score = evaluate_fixture(fixtures_dir, name, method=method)
        if score is not None:
            scores.append(score)
    if not scores:
        logger.error("No evaluable fixtures found in {}", fixtures_dir)
        raise typer.Exit(code=1)
    print(format_report(scores))


@app.command("dump-alignments")
def dump_alignments(
    fixtures_dir: Path = typer.Argument(
        "tests/fixtures",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Directory with cached <name>-raw.transcript.json, .edl.json, and -edited.qa-transcript.json.",
    ),
    output_dir: Path = typer.Option(
        Path("output/alignments"),
        "--output-dir",
        "-o",
        file_okay=False,
        dir_okay=True,
        help="Where to write <name>.alignment.json / .alignment.txt decision diffs.",
    ),
    names: list[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Restrict to specific fixture names (repeatable). Default: all.",
    ),
) -> None:
    """Write per-sentence decision diffs (pipeline vs human edit), offline (no APIs)."""
    from ai_video_editor.duplicate.edl import EditDecisionList
    from ai_video_editor.qa.alignment import dump_alignment
    from ai_video_editor.qa.decision_eval import discover_fixture_names
    from ai_video_editor.transcription.models import Transcript

    target_names = names or discover_fixture_names(fixtures_dir)
    dumped = 0
    for name in target_names:
        raw_t = fixtures_dir / f"{name}-raw.transcript.json"
        edl_p = fixtures_dir / f"{name}-raw.edl.json"
        gt_t = fixtures_dir / f"{name}-edited.qa-transcript.json"
        if not (raw_t.exists() and edl_p.exists() and gt_t.exists()):
            logger.warning("Skipping {} — missing sidecars", name)
            continue
        raw = Transcript.model_validate_json(raw_t.read_text("utf-8")).sentences
        edl = EditDecisionList.model_validate_json(edl_p.read_text("utf-8"))
        gt = Transcript.model_validate_json(gt_t.read_text("utf-8")).sentences
        dump_alignment(name, raw, edl, gt, output_dir)
        dumped += 1
    if not dumped:
        logger.error("No evaluable fixtures found in {}", fixtures_dir)
        raise typer.Exit(code=1)
    logger.info("Wrote {} decision diffs to {}", dumped, output_dir)


@app.command("review-export")
def review_export(
    input_path: Path = typer.Argument(..., exists=True, readable=True, help="Raw source video to export for review."),
) -> None:
    """Create a review JSON payload from an existing transcript + EDL."""
    from ai_video_editor.review import write_review_payload

    output = write_review_payload(input_path)
    logger.info("Review payload written: {}", output)


@app.command("review-serve")
def review_serve(
    media_root: Path = typer.Argument(
        Path("tests/fixtures"),
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Directory containing processed videos, transcripts, and EDL files.",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    port: int = typer.Option(8000, "--port", help="Port to bind."),
    frontend_dist: Path | None = typer.Option(
        None,
        "--frontend-dist",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Optional built frontend dist directory.",
    ),
) -> None:
    """Serve the review API and built frontend."""
    import uvicorn

    from ai_video_editor.web import create_app

    web_app = create_app(media_root=media_root, frontend_dist=frontend_dist)
    uvicorn.run(web_app, host=host, port=port)


@app.command("review-render")
def review_render(
    input_path: Path = typer.Argument(..., exists=True, readable=True, help="Raw source video to render from review EDL."),
    denoised_audio: Path | None = typer.Option(
        None,
        "--denoised-audio",
        exists=True,
        readable=True,
        help="Denoised WAV to use for rendering. Defaults to .ai_video_editor_tmp/<stem>_denoised.wav.",
    ),
) -> None:
    """Render a reviewed sidecar EDL to <stem>_reviewed.mp4."""
    from ai_video_editor.config.settings import RenderConfig
    from ai_video_editor.duplicate.edl import EditDecisionList
    from ai_video_editor.render import render_video
    from ai_video_editor.review import review_edl_path_for

    review_path = review_edl_path_for(input_path)
    if not review_path.exists():
        logger.error("Reviewed EDL not found: {}", review_path)
        raise typer.Exit(code=1)

    audio_path = denoised_audio or _default_denoised_audio_path(input_path)
    if not audio_path.exists():
        logger.error("Denoised audio not found: {}", audio_path)
        raise typer.Exit(code=1)

    edl = EditDecisionList.model_validate_json(review_path.read_text(encoding="utf-8"))
    output = render_video(input_path, edl, audio_path, RenderConfig(output_suffix="_reviewed"))
    logger.info("Reviewed render complete: {}", output)


def _default_denoised_audio_path(input_path: Path) -> Path:
    return Path.cwd() / ".ai_video_editor_tmp" / f"{input_path.stem}_denoised.wav"


def main() -> None:
    app()


if __name__ == "__main__":
    main()
