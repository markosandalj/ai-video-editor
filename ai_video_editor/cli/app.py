from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path

import typer
from loguru import logger

from ai_video_editor.config.settings import Settings
from ai_video_editor.logging.setup import setup_logging

app = typer.Typer(
    name="ai-video-editor",
    help="Development QA and quality iteration for the headless media worker",
    no_args_is_help=True,
)


def _default_worker_count() -> int:
    """
    Default to enough parallelism for a modern Apple Silicon laptop while
    avoiding excessive concurrent calls to ElevenLabs/Gemini.
    """
    return min(4, max(1, os.cpu_count() or 1))


DEFAULT_WORKERS = _default_worker_count()


def _eval_cut_decisions(raw_path: Path, edl, gt_sentences, *, name: str, issues: list):
    """Score the EDL's cut/keep calls against the human edit; append QA issues."""
    from ai_video_editor.qa.decision_eval import (
        evaluate_decisions_word_level,
        to_word_cut_decision_result,
    )
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
    ds = evaluate_decisions_word_level(raw_transcript.sentences, edl, gt_sentences, name=name)
    cd = to_word_cut_decision_result(ds)

    if cd.needed_cuts and cd.true_cuts == 0:
        issues.append(QAIssue(
            check="cut_decisions", severity=Severity.ERROR,
            message=f"Missed all {cd.needed_cuts} words the human cut",
        ))
    elif cd.missed_cuts:
        issues.append(QAIssue(
            check="cut_decisions", severity=Severity.WARNING,
            message=f"Missed {cd.missed_cuts}/{cd.needed_cuts} words the human cut",
        ))
    if cd.overcuts:
        issues.append(QAIssue(
            check="cut_decisions", severity=Severity.WARNING,
            message=f"{cd.overcuts} overcut word(s) — removed content the human kept",
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
) -> None:
    """Compare pipeline cut/keep decisions to human ground truth, offline (no APIs)."""
    from ai_video_editor.qa.decision_eval import (
        discover_fixture_names,
        evaluate_fixture,
        format_report,
    )

    target_names = names or discover_fixture_names(fixtures_dir)

    scores = []
    for name in target_names:
        score = evaluate_fixture(fixtures_dir, name)
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


@app.command("eval-models")
def eval_models(
    manifest: Path = typer.Argument(
        ...,
        exists=True,
        readable=True,
        help="JSON or TOML experiment manifest defining models and runs.",
    ),
    fixtures_dir: Path = typer.Option(
        Path("tests/fixtures"),
        "--fixtures-dir",
        file_okay=False,
        dir_okay=True,
        help="Directory with cached transcript, EDL, and ground-truth sidecars.",
    ),
    output_dir: Path = typer.Option(
        Path("output/experiments"),
        "--output-dir",
        file_okay=False,
        dir_okay=True,
        help="Directory for results.json, report.md, and debug artifacts.",
    ),
    names: list[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Restrict to specific fixture names (repeatable). Default: manifest fixtures or all cached fixtures.",
    ),
) -> None:
    """Evaluate cutting LLMs independently from cached fixture sidecars."""
    from ai_video_editor.experiments import run_experiments

    results = run_experiments(
        manifest,
        fixtures_dir=fixtures_dir,
        output_dir=output_dir,
        names=names,
    )
    logger.info("Model evaluation complete: {}", output_dir)
    print(f"results: {results.output_dir / 'results.json'}")
    print(f"report:  {results.output_dir / 'report.md'}")


@app.command("eval-section-editor")
def eval_section_editor(
    fixtures_dir: Path = typer.Option(
        Path("tests/fixtures"),
        "--fixtures-dir",
        file_okay=False,
        dir_okay=True,
        help="Directory with cached transcript, EDL, and ground-truth sidecars.",
    ),
    output_dir: Path = typer.Option(
        Path("output/section-pilot"),
        "--output-dir",
        "-o",
        file_okay=False,
        dir_okay=True,
        help="Directory for report.md, results.json, and per-fixture EDLs.",
    ),
    names: list[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Fixture names to run (repeatable). Default: a curated diverse slice.",
    ),
    all_fixtures: bool = typer.Option(
        False,
        "--all-fixtures",
        help="Run every fixture with raw transcript, baseline EDL, and human transcript.",
    ),
    manifest: Path = typer.Option(
        None,
        "--manifest",
        exists=True,
        readable=True,
        help="Optional experiment manifest to pull the section-editor model from.",
    ),
    model: str = typer.Option(
        None,
        "--model",
        help="Model key within the manifest (defaults to gpt-5.6-sol if no manifest).",
    ),
    compare_to: Path = typer.Option(
        None,
        "--compare-to",
        exists=True,
        readable=True,
        help="Reference results.json or run directory for candidate gate comparison.",
    ),
    repeat_cases: Path = typer.Option(
        None,
        "--repeat-cases",
        exists=True,
        readable=True,
        help="Optional explicit source-span repeat cases to score against saved EDLs.",
    ),
) -> None:
    """Pilot the LLM section editor on fixtures, word-level scored vs the human edit."""
    from ai_video_editor.experiments.section_pilot import (
        discover_fixture_names,
        run_section_pilot,
    )
    from ai_video_editor.llm import direct_gemini_model_config

    llm_config = None
    if manifest is not None:
        from ai_video_editor.experiments import load_manifest

        loaded = load_manifest(manifest)
        if model is None or model not in loaded.models:
            logger.error("--model must name one of: {}", ", ".join(loaded.models))
            raise typer.Exit(code=1)
        llm_config = loaded.models[model].with_id(model)
    elif model is not None:
        llm_config = direct_gemini_model_config(model=model)

    if all_fixtures and names:
        logger.error("Use either --all-fixtures or --name, not both")
        raise typer.Exit(code=1)
    selected_names = discover_fixture_names(fixtures_dir) if all_fixtures else names or None
    results = run_section_pilot(
        fixtures_dir,
        output_dir,
        names=selected_names,
        llm_config=llm_config,
        compare_to=compare_to,
        repeat_cases_path=repeat_cases,
    )
    if not results:
        logger.error("No evaluable fixtures found in {}", fixtures_dir)
        raise typer.Exit(code=1)
    print((output_dir / "report.md").read_text("utf-8"))
    print(f"\nreport:  {output_dir / 'report.md'}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
