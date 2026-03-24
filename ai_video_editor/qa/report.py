from __future__ import annotations

from pathlib import Path

from loguru import logger

from ai_video_editor.qa.models import QAIssue, QAReport, Severity

HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>QA Report: {video_name}</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3em; }}
.score {{ font-size: 2em; font-weight: bold; }}
.pass {{ color: #16a34a; }} .fail {{ color: #dc2626; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f5f5f5; }}
.issue-error {{ background: #fef2f2; }} .issue-warning {{ background: #fefce8; }}
.section {{ margin: 2em 0; }}
</style></head><body>
<h1>QA Report: {video_name}</h1>
<p>Generated: {created_at}</p>
<p class="score {pass_class}">Overall: {overall_score:.1%} — {verdict}</p>

{sections}

<div class="section">
<h2>Issues ({issue_count})</h2>
{issues_html}
</div>
</body></html>"""


def _build_sections(report: QAReport) -> str:
    parts: list[str] = []

    if report.transcript_comparison:
        tc = report.transcript_comparison
        parts.append(f"""<div class="section"><h2>Transcript Comparison</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
<tr><td>Pipeline sentences</td><td>{tc.pipeline_sentences}</td></tr>
<tr><td>Ground truth sentences</td><td>{tc.ground_truth_sentences}</td></tr>
<tr><td>Matched</td><td>{tc.matched}</td></tr>
<tr><td>Precision</td><td>{tc.precision:.1%}</td></tr>
<tr><td>Recall</td><td>{tc.recall:.1%}</td></tr>
<tr><td>F1</td><td>{tc.f1:.1%}</td></tr>
<tr><td>Pipeline only (false positives)</td><td>{len(tc.pipeline_only)}</td></tr>
<tr><td>Ground truth only (false negatives)</td><td>{len(tc.ground_truth_only)}</td></tr>
</table></div>""")

    if report.temporal_comparison:
        tp = report.temporal_comparison
        parts.append(f"""<div class="section"><h2>Temporal Comparison</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
<tr><td>Pipeline duration</td><td>{tp.pipeline_duration:.1f}s</td></tr>
<tr><td>Ground truth duration</td><td>{tp.ground_truth_duration:.1f}s</td></tr>
<tr><td>Duration delta</td><td>{tp.duration_delta:+.1f}s</td></tr>
<tr><td>Mean timing offset</td><td>{tp.mean_offset:.3f}s</td></tr>
<tr><td>Temporal score</td><td>{tp.temporal_score:.1%}</td></tr>
</table></div>""")

    if report.splice_analysis:
        sa = report.splice_analysis
        parts.append(f"""<div class="section"><h2>Splice Analysis</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
<tr><td>Total splices</td><td>{sa.total_splices}</td></tr>
<tr><td>Harsh splices</td><td>{sa.harsh_splices}</td></tr>
<tr><td>Max amplitude delta</td><td>{sa.max_amplitude_delta:.4f}</td></tr>
</table></div>""")

    if report.spectrogram_comparison:
        sc = report.spectrogram_comparison
        parts.append(f"""<div class="section"><h2>Spectrogram Comparison</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
<tr><td>Similarity</td><td>{sc.similarity_score:.4f}</td></tr>
<tr><td>Passed</td><td>{"Yes" if sc.passed else "No"}</td></tr>
</table></div>""")

    if report.continuity:
        ct = report.continuity
        parts.append(f"""<div class="section"><h2>Transcript Continuity</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
<tr><td>Expected sentences</td><td>{ct.expected_sentences}</td></tr>
<tr><td>Found sentences</td><td>{ct.found_sentences}</td></tr>
<tr><td>Missing</td><td>{len(ct.missing_sentences)}</td></tr>
<tr><td>Alignment score</td><td>{ct.alignment_score:.1%}</td></tr>
</table></div>""")

    return "\n".join(parts)


def _build_issues_html(issues: list[QAIssue]) -> str:
    if not issues:
        return "<p>No issues found.</p>"
    rows = []
    for issue in issues:
        css = f"issue-{issue.severity.value}" if issue.severity != Severity.INFO else ""
        rows.append(
            f'<tr class="{css}"><td>{issue.severity.value.upper()}</td>'
            f"<td>{issue.check}</td><td>{issue.message}</td></tr>"
        )
    return f'<table><tr><th>Severity</th><th>Check</th><th>Message</th></tr>{"".join(rows)}</table>'


def generate_report(report: QAReport) -> str:
    """Generate HTML report string from a QAReport."""
    return HTML_TEMPLATE.format(
        video_name=report.video_name,
        created_at=report.created_at,
        overall_score=report.overall_score,
        pass_class="pass" if report.overall_passed else "fail",
        verdict="PASS" if report.overall_passed else "FAIL",
        sections=_build_sections(report),
        issue_count=len(report.issues),
        issues_html=_build_issues_html(report.issues),
    )


def save_report(report: QAReport, output_dir: Path) -> dict[str, Path]:
    """Save QA report as JSON and HTML."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = report.video_name

    json_path = output_dir / f"{stem}.qa.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    html_path = output_dir / f"{stem}.qa.html"
    html_path.write_text(generate_report(report), encoding="utf-8")

    logger.info("QA report saved: {} + {}", json_path.name, html_path.name)
    return {"json": json_path, "html": html_path}


def print_summary(report: QAReport) -> None:
    """Print a human-readable summary to the console via loguru."""
    logger.info("=" * 60)
    logger.info("QA REPORT: {}", report.video_name)
    logger.info("=" * 60)

    if report.transcript_comparison:
        tc = report.transcript_comparison
        logger.info(
            "  Transcript: P={:.1%} R={:.1%} F1={:.1%} (matched {}/{})",
            tc.precision, tc.recall, tc.f1, tc.matched, tc.ground_truth_sentences,
        )

    if report.temporal_comparison:
        tp = report.temporal_comparison
        logger.info(
            "  Temporal: score={:.1%} delta={:+.1f}s offset={:.3f}s",
            tp.temporal_score, tp.duration_delta, tp.mean_offset,
        )

    if report.splice_analysis:
        sa = report.splice_analysis
        logger.info(
            "  Splices: {}/{} harsh (max_delta={:.4f})",
            sa.harsh_splices, sa.total_splices, sa.max_amplitude_delta,
        )

    if report.spectrogram_comparison:
        sc = report.spectrogram_comparison
        logger.info("  Spectrogram: similarity={:.4f} passed={}", sc.similarity_score, sc.passed)

    if report.continuity:
        ct = report.continuity
        logger.info(
            "  Continuity: {}/{} found (score={:.1%})",
            ct.found_sentences, ct.expected_sentences, ct.alignment_score,
        )

    for issue in report.issues:
        logger.info("  [{}] {}: {}", issue.severity.value.upper(), issue.check, issue.message)

    verdict = "PASS" if report.overall_passed else "FAIL"
    logger.info("  Overall: {:.1%} — {}", report.overall_score, verdict)
    logger.info("=" * 60)
