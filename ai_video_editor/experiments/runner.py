from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from ai_video_editor.config.settings import EnrichmentConfig, Settings
from ai_video_editor.decisions import detect_all_flags
from ai_video_editor.duplicate.edl import EditDecisionList, build_edl
from ai_video_editor.enrich import enrich_transcript
from ai_video_editor.experiments.manifest import (
    ExperimentRunConfig,
    load_manifest,
)
from ai_video_editor.experiments.reconstruction import derive_cached_cutting_inputs
from ai_video_editor.experiments.scoring import (
    AnnotationActionabilityScore,
    aggregate_annotation_scores,
    aggregate_decision_scores,
    decision_score_to_dict,
    score_annotation_actionability,
)
from ai_video_editor.llm import LangChainModelConfig
from ai_video_editor.qa.decision_eval import DecisionScore, discover_fixture_names, evaluate_decisions
from ai_video_editor.transcription.models import Transcript


SCHEMA_VERSION = "model-eval.v1"


class FixtureRunResult(BaseModel):
    name: str
    status: str = "ok"
    runtime_s: float = 0.0
    artifact_path: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class ExperimentRunResult(BaseModel):
    id: str
    part: str
    model: str
    llm_config: dict[str, Any]
    runtime_s: float = 0.0
    aggregate: dict[str, Any] = Field(default_factory=dict)
    fixtures: list[FixtureRunResult] = Field(default_factory=list)


class ExperimentResults(BaseModel):
    schema_version: str = SCHEMA_VERSION
    manifest_path: Path
    fixtures_dir: Path
    output_dir: Path
    started_at: str
    completed_at: str = ""
    runs: list[ExperimentRunResult] = Field(default_factory=list)


def run_experiments(
    manifest_path: Path,
    *,
    fixtures_dir: Path = Path("tests/fixtures"),
    output_dir: Path = Path("output/experiments"),
    names: list[str] | None = None,
) -> ExperimentResults:
    manifest = load_manifest(manifest_path)
    fixture_names = names or manifest.fixtures or discover_fixture_names(fixtures_dir)
    if not fixture_names:
        raise ValueError(f"No fixtures found in {fixtures_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "debug").mkdir(parents=True, exist_ok=True)

    results = ExperimentResults(
        manifest_path=manifest_path,
        fixtures_dir=fixtures_dir,
        output_dir=output_dir,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    for run in manifest.runs:
        model_config = manifest.model_for_run(run)
        logger.info(
            "Experiment run {}: {} using {}",
            run.id,
            run.part,
            model_config.public_dict(),
        )
        run_started = time.perf_counter()
        if run.part == "cutting":
            run_result = _run_cutting(run, model_config, fixture_names, fixtures_dir, output_dir)
        else:
            run_result = _run_annotations(run, model_config, fixture_names, fixtures_dir, output_dir)
        run_result.runtime_s = time.perf_counter() - run_started
        results.runs.append(run_result)

    results.completed_at = datetime.now(timezone.utc).isoformat()
    results_path = output_dir / "results.json"
    results_path.write_text(results.model_dump_json(indent=2), encoding="utf-8")
    report_path = output_dir / "report.md"
    report_path.write_text(format_report(results), encoding="utf-8")
    return results


def _run_cutting(
    run: ExperimentRunConfig,
    model_config: LangChainModelConfig,
    fixture_names: list[str],
    fixtures_dir: Path,
    output_dir: Path,
) -> ExperimentRunResult:
    settings = Settings()
    debug_dir = output_dir / "debug" / run.id
    debug_dir.mkdir(parents=True, exist_ok=True)

    fixture_results: list[FixtureRunResult] = []
    scores: list[DecisionScore] = []
    for name in fixture_names:
        started = time.perf_counter()
        try:
            raw, baseline_edl, gt = _load_fixture(fixtures_dir, name)
            keeps, silences = derive_cached_cutting_inputs(baseline_edl)
            flags = detect_all_flags(
                raw,
                silences,
                [],
                settings,
                cutting_llm_config=model_config,
            )
            edl = build_edl(
                raw,
                keeps,
                flags,
                rescue_outside_keep_regions=False,
            )
            artifact = debug_dir / f"{name}.edl.json"
            artifact.write_text(edl.model_dump_json(indent=2), encoding="utf-8")
            score = evaluate_decisions(raw.sentences, edl, gt.sentences, name=name)
            scores.append(score)
            fixture_results.append(
                FixtureRunResult(
                    name=name,
                    runtime_s=time.perf_counter() - started,
                    artifact_path=str(artifact),
                    metrics=decision_score_to_dict(score),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one bad fixture should not hide the rest
            logger.exception("Cutting experiment failed for {}", name)
            fixture_results.append(
                FixtureRunResult(
                    name=name,
                    status="error",
                    runtime_s=time.perf_counter() - started,
                    error=str(exc),
                )
            )

    return ExperimentRunResult(
        id=run.id,
        part=run.part,
        model=run.model,
        llm_config=model_config.public_dict(),
        aggregate=aggregate_decision_scores(scores),
        fixtures=fixture_results,
    )


def _run_annotations(
    run: ExperimentRunConfig,
    model_config: LangChainModelConfig,
    fixture_names: list[str],
    fixtures_dir: Path,
    output_dir: Path,
) -> ExperimentRunResult:
    debug_dir = output_dir / "debug" / run.id
    debug_dir.mkdir(parents=True, exist_ok=True)
    config = EnrichmentConfig(
        enabled=True,
        arbiter_enabled=False,
        llm=model_config,
    )

    fixture_results: list[FixtureRunResult] = []
    scores: list[AnnotationActionabilityScore] = []
    for name in fixture_names:
        started = time.perf_counter()
        try:
            raw, baseline_edl, gt = _load_fixture(fixtures_dir, name)
            enrichment = enrich_transcript(
                raw,
                baseline_edl,
                config,
                llm_config=model_config,
            )
            artifact = debug_dir / f"{name}.enrichment.json"
            artifact.write_text(enrichment.model_dump_json(indent=2), encoding="utf-8")
            score = score_annotation_actionability(
                raw.sentences,
                baseline_edl,
                gt.sentences,
                enrichment,
                name=name,
            )
            scores.append(score)
            fixture_results.append(
                FixtureRunResult(
                    name=name,
                    runtime_s=time.perf_counter() - started,
                    artifact_path=str(artifact),
                    metrics=score.model_dump(mode="json"),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one bad fixture should not hide the rest
            logger.exception("Annotation experiment failed for {}", name)
            fixture_results.append(
                FixtureRunResult(
                    name=name,
                    status="error",
                    runtime_s=time.perf_counter() - started,
                    error=str(exc),
                )
            )

    aggregate = aggregate_annotation_scores(scores)
    return ExperimentRunResult(
        id=run.id,
        part=run.part,
        model=run.model,
        llm_config=model_config.public_dict(),
        aggregate=aggregate.model_dump(mode="json"),
        fixtures=fixture_results,
    )


def _load_fixture(fixtures_dir: Path, name: str) -> tuple[Transcript, EditDecisionList, Transcript]:
    raw_path = fixtures_dir / f"{name}-raw.transcript.json"
    edl_path = fixtures_dir / f"{name}-raw.edl.json"
    gt_path = fixtures_dir / f"{name}-edited.qa-transcript.json"
    missing = [path.name for path in (raw_path, edl_path, gt_path) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Fixture {name!r} missing sidecars: {', '.join(missing)}")

    raw = Transcript.model_validate_json(raw_path.read_text(encoding="utf-8"))
    edl = EditDecisionList.model_validate_json(edl_path.read_text(encoding="utf-8"))
    gt = Transcript.model_validate_json(gt_path.read_text(encoding="utf-8"))
    return raw, edl, gt


def format_report(results: ExperimentResults) -> str:
    lines = [
        "# Model Evaluation Report",
        "",
        f"- Manifest: `{results.manifest_path}`",
        f"- Fixtures: `{results.fixtures_dir}`",
        f"- Output: `{results.output_dir}`",
        f"- Started: {results.started_at}",
        f"- Completed: {results.completed_at}",
        "",
    ]

    for run in results.runs:
        ok_count = sum(1 for fixture in run.fixtures if fixture.status == "ok")
        error_count = sum(1 for fixture in run.fixtures if fixture.status != "ok")
        lines.extend([
            f"## {run.id}",
            "",
            f"- Part: `{run.part}`",
            f"- Model: `{run.model}`",
            f"- Runtime: {run.runtime_s:.2f}s",
            f"- Fixtures: {ok_count} ok, {error_count} error",
            "",
        ])
        if run.part == "cutting":
            lines.extend(_format_cutting_summary(run.aggregate))
        else:
            lines.extend(_format_annotation_summary(run.aggregate))
        lines.append("")

        failed = [fixture for fixture in run.fixtures if fixture.status != "ok"]
        if failed:
            lines.append("### Errors")
            lines.append("")
            for fixture in failed[:20]:
                lines.append(f"- `{fixture.name}`: {fixture.error}")
            if len(failed) > 20:
                lines.append(f"- ...and {len(failed) - 20} more")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _format_cutting_summary(aggregate: dict[str, Any]) -> list[str]:
    return [
        "### Cutting Score",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| cut precision | {_fmt_float(aggregate.get('cut_precision'))} |",
        f"| cut recall | {_fmt_float(aggregate.get('cut_recall'))} |",
        f"| cut F1 | {_fmt_float(aggregate.get('cut_f1'))} |",
        f"| accuracy | {_fmt_float(aggregate.get('accuracy'))} |",
        f"| false positives | {aggregate.get('fp', 0)} |",
        f"| false negatives | {aggregate.get('fn', 0)} |",
        "",
        f"Wrong cuts by reason: `{aggregate.get('wrong_cut_by_reason', {})}`",
        "",
        f"Right cuts by reason: `{aggregate.get('right_cut_by_reason', {})}`",
    ]


def _format_annotation_summary(aggregate: dict[str, Any]) -> list[str]:
    restore = aggregate.get("restore", {})
    attention = aggregate.get("attention", {})
    return [
        "### Annotation Actionability",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| wrong cuts | {aggregate.get('wrong_cuts', 0)} |",
        f"| missed cuts | {aggregate.get('missed_cuts', 0)} |",
        f"| restore precision | {_fmt_float(restore.get('precision'))} |",
        f"| restore recall | {_fmt_float(restore.get('recall'))} |",
        f"| restore F1 | {_fmt_float(restore.get('f1'))} |",
        f"| attention precision | {_fmt_float(attention.get('precision'))} |",
        f"| attention recall | {_fmt_float(attention.get('recall'))} |",
        f"| attention F1 | {_fmt_float(attention.get('f1'))} |",
        f"| ranking average precision | {_fmt_float(aggregate.get('ranking_average_precision'))} |",
        "",
        f"Status counts: `{aggregate.get('status_counts', {})}`",
    ]


def _fmt_float(value: object) -> str:
    return f"{float(value):.3f}" if isinstance(value, (int, float)) else "0.000"
