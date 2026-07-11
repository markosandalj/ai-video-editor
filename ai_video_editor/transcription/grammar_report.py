from __future__ import annotations

from pathlib import Path

from loguru import logger

from ai_video_editor.transcription.grammar import GrammarReport


def grammar_report_path_for(video_path: Path) -> Path:
    return video_path.with_suffix(".grammar-report.json")


def load_cached_grammar_report(video_path: Path) -> GrammarReport | None:
    path = grammar_report_path_for(video_path)
    if not path.exists():
        return None
    logger.info("Loading cached grammar report: {}", path.name)
    return GrammarReport.model_validate_json(path.read_text(encoding="utf-8"))


def save_grammar_report(video_path: Path, report: GrammarReport) -> Path:
    path = grammar_report_path_for(video_path)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    logger.info(
        "Saved grammar report: {} (passes={}, suggestions={}, replacements={})",
        path.name,
        report.passes,
        report.total_suggestions,
        report.total_corrections,
    )
    return path
