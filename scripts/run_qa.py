"""
Run the full QA suite on all test video pairs in tests/fixtures/.

Discovers pairs by naming convention (<name>-raw.mp4 + <name>-edited.mp4),
runs the pipeline on each raw video (using cached results if available),
then compares against the human-edited ground truth.

Produces QA reports (JSON + HTML) and records regression scores.
"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
HISTORY_PATH = FIXTURES / "regression_scores.json"


def main() -> None:
    from ai_video_editor.config import Settings
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
    pairs = discover_pairs(FIXTURES)

    if not pairs:
        logger.error("No test pairs found in {}", FIXTURES)
        sys.exit(1)

    reports: list[QAReport] = []

    for name, raw_path, gt_path in pairs:
        logger.info("=" * 60)
        logger.info("QA for pair: {} ", name)
        logger.info("=" * 60)

        pipeline_video = raw_path.with_name(f"{name}-raw_edited.mp4")
        edl_path = raw_path.with_suffix(".edl.json")
        transcript_path = raw_path.with_suffix(".transcript.json")
        edited_transcript_path = raw_path.with_name(f"{name}-raw_edited.transcript.json")
        denoised_path = ROOT / ".ai_video_editor_tmp" / f"{name}-raw_denoised.wav"

        if not pipeline_video.exists():
            logger.warning("Pipeline output not found: {} — run the pipeline first", pipeline_video.name)
            continue

        report = QAReport(video_name=name)
        issues: list[QAIssue] = []

        logger.info("--- Transcribing pipeline output (once) ---")
        pipeline_sentences = transcribe_for_qa(pipeline_video, force=True)

        logger.info("--- Transcript comparison (5.05) ---")
        tc = compare_transcripts_from_videos(pipeline_video, gt_path, pipeline_sentences=pipeline_sentences)
        report.transcript_comparison = tc
        if tc.f1 < 0.8:
            issues.append(QAIssue(
                check="transcript_comparison",
                severity=Severity.WARNING,
                message=f"Low F1 score: {tc.f1:.1%}",
            ))

        logger.info("--- Temporal comparison (5.06) ---")
        if tc.matches:
            tp = compare_temporal(pipeline_video, gt_path, [], [], tc.matches)
            report.temporal_comparison = tp
            if tp.temporal_score < 0.7:
                issues.append(QAIssue(
                    check="temporal_comparison",
                    severity=Severity.WARNING,
                    message=f"Low temporal score: {tp.temporal_score:.1%}",
                ))

        logger.info("--- Splice analysis (5.01) ---")
        if edl_path.exists():
            edl = EditDecisionList.model_validate_json(edl_path.read_text("utf-8"))
            sa = analyze_splices(pipeline_video, edl)
            report.splice_analysis = sa
            if sa.harsh_splices > 0:
                issues.append(QAIssue(
                    check="splice_analysis",
                    severity=Severity.WARNING,
                    message=f"{sa.harsh_splices} harsh splices detected",
                ))

            logger.info("--- Spectrogram comparison (5.02) ---")
            if denoised_path.exists():
                sc = compare_spectrograms(pipeline_video, denoised_path, edl)
                report.spectrogram_comparison = sc
                if not sc.passed:
                    issues.append(QAIssue(
                        check="spectrogram_comparison",
                        severity=Severity.ERROR,
                        message=f"Spectrogram similarity too low: {sc.similarity_score:.4f}",
                    ))

        logger.info("--- Continuity verification (5.03) ---")
        if edited_transcript_path.exists():
            edited_transcript = Transcript.model_validate_json(
                edited_transcript_path.read_text("utf-8")
            )
            ct = verify_continuity(edited_transcript.sentences, pipeline_sentences)
            report.continuity = ct
            if ct.alignment_score < 0.9:
                issues.append(QAIssue(
                    check="continuity",
                    severity=Severity.WARNING,
                    message=f"Low continuity: {ct.alignment_score:.1%} ({len(ct.missing_sentences)} missing)",
                ))

        report.issues = issues
        report.overall_passed = not any(i.severity == Severity.ERROR for i in issues)

        print_summary(report)
        save_report(report, FIXTURES)
        reports.append(report)

    if reports:
        logger.info("--- Regression check (5.07) ---")
        entry = record_scores(reports, HISTORY_PATH)
        warnings = check_regression(entry, HISTORY_PATH)

        logger.info("")
        logger.info("AGGREGATE SCORE: {:.1%}", entry.aggregate_score)
        if warnings:
            for w in warnings:
                logger.warning(w)
        else:
            logger.info("No regressions detected.")

    logger.info("QA complete.")


if __name__ == "__main__":
    main()
