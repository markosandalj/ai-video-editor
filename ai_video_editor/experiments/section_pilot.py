"""Offline pilot for the LLM section editor.

Runs the section editor over cached fixtures and scores its cuts at the word
level against the human edit — the fair metric for partial (word-trim) cuts —
alongside the cached baseline EDL for a side-by-side comparison. No rendering
and no re-transcription; the only cost is the section-editor model calls.
"""
from __future__ import annotations

import json
from hashlib import sha256
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from ai_video_editor.config.settings import SectionEditorConfig
from ai_video_editor.duplicate.edl import EditDecisionList, build_edl
from ai_video_editor.duplicate.section_editor import (
    SECTION_PROMPT,
    SectionHealth,
    SectionTrace,
    detect_section_edits,
)
from ai_video_editor.experiments.reconstruction import derive_cached_cutting_inputs
from ai_video_editor.experiments.repeat_eval import (
    RepeatCaseSummary,
    evaluate_repeat_cases,
    format_repeat_case_report,
)
from ai_video_editor.llm import LangChainModelConfig, default_section_editor_model_config
from ai_video_editor.qa.decision_eval import (
    WordDecisionScore,
    aggregate_word_scores,
    evaluate_decisions_word_level,
)
from ai_video_editor.transcription.models import Transcript

# A diverse default slice: two big engleski lectures (heavy editing), small
# fizika/kemija/hrvatski items (few cuts), and mixed test videos.
DEFAULT_PILOT_FIXTURES = [
    "engleski25ljeto-esej",
    "engleski25ljeto-reading-1",
    "fizika25ljeto-002",
    "fizika25ljeto-005",
    "kemija25ljeto-k1-3",
    "kemija25ljeto-k1-10",
    "hrvatski25ljeto-tekst-1",
    "test-9",
    "test-11",
    "test-45",
]


@dataclass
class FixturePilotResult:
    name: str
    baseline: WordDecisionScore
    section: WordDecisionScore
    health: SectionHealth = field(default_factory=SectionHealth)


@dataclass
class CandidateGateResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def evaluate_candidate_gates(
    candidate: list[FixturePilotResult],
    reference: list[FixturePilotResult],
) -> CandidateGateResult:
    """Apply the safety-first promotion gates to two comparable runs."""
    failures: list[str] = []
    candidate_by_name = {result.name: result for result in candidate}
    reference_by_name = {result.name: result for result in reference}
    if candidate_by_name.keys() != reference_by_name.keys():
        missing = sorted(reference_by_name.keys() - candidate_by_name.keys())
        extra = sorted(candidate_by_name.keys() - reference_by_name.keys())
        failures.append(f"fixture mismatch (missing={missing}, extra={extra})")

    common = sorted(candidate_by_name.keys() & reference_by_name.keys())
    candidate_agg = aggregate_word_scores(
        [candidate_by_name[name].section for name in common]
    )
    reference_agg = aggregate_word_scores(
        [reference_by_name[name].section for name in common]
    )

    failed_sections = sum(result.health.sections_failed for result in candidate)
    if failed_sections:
        failures.append(f"{failed_sections} section(s) failed")
    if candidate_agg.cut_precision < reference_agg.cut_precision - 0.005:
        failures.append(
            "cut precision dropped by more than 0.005 "
            f"({reference_agg.cut_precision:.3f} → {candidate_agg.cut_precision:.3f})"
        )
    if candidate_agg.cut_recall < reference_agg.cut_recall - 0.01:
        failures.append(
            "cut recall dropped by more than 0.010 "
            f"({reference_agg.cut_recall:.3f} → {candidate_agg.cut_recall:.3f})"
        )
    if candidate_agg.cut_f1 < reference_agg.cut_f1 - 0.005:
        failures.append(
            "cut F1 dropped by more than 0.005 "
            f"({reference_agg.cut_f1:.3f} → {candidate_agg.cut_f1:.3f})"
        )

    for name in common:
        old = reference_by_name[name].section
        new = candidate_by_name[name].section
        if new.cut_f1 < old.cut_f1 - 0.03:
            failures.append(
                f"{name} lost more than 0.030 cut F1 "
                f"({old.cut_f1:.3f} → {new.cut_f1:.3f})"
            )
        if new.fp > old.fp + 10:
            failures.append(
                f"{name} gained more than 10 overcut words ({old.fp} → {new.fp})"
            )

    return CandidateGateResult(passed=not failures, failures=failures)


def _load(fixtures_dir: Path, name: str):
    raw_p = fixtures_dir / f"{name}-raw.transcript.json"
    edl_p = fixtures_dir / f"{name}-raw.edl.json"
    gt_p = fixtures_dir / f"{name}-edited.qa-transcript.json"
    if not (raw_p.exists() and edl_p.exists() and gt_p.exists()):
        return None
    raw = Transcript.model_validate_json(raw_p.read_text("utf-8"))
    edl = EditDecisionList.model_validate_json(edl_p.read_text("utf-8"))
    gt = Transcript.model_validate_json(gt_p.read_text("utf-8"))
    return raw, edl, gt


def _section_config(
    llm_config: LangChainModelConfig,
) -> SectionEditorConfig:
    cfg = SectionEditorConfig()
    cfg.enabled = True
    cfg.llm = llm_config
    return cfg


def discover_fixture_names(fixtures_dir: Path) -> list[str]:
    """Find every fixture with the three sidecars required by this evaluator."""
    names = []
    suffix = "-raw.transcript.json"
    for raw_path in sorted(fixtures_dir.glob(f"*{suffix}")):
        name = raw_path.name.removesuffix(suffix)
        if _load(fixtures_dir, name) is not None:
            names.append(name)
    return names


def _result_from_dict(data: dict) -> FixturePilotResult:
    def score(raw: dict) -> WordDecisionScore:
        values = dict(raw)
        values["wrong_cut_by_reason"] = Counter(values.get("wrong_cut_by_reason", {}))
        values["right_cut_by_reason"] = Counter(values.get("right_cut_by_reason", {}))
        return WordDecisionScore(**values)

    return FixturePilotResult(
        name=data["name"],
        baseline=score(data["baseline"]),
        section=score(data["section"]),
        health=SectionHealth(**data.get("health", {})),
    )


def _write_pilot_artifacts(
    output_dir: Path,
    results: list[FixturePilotResult],
    *,
    fixtures_dir: Path,
    model_id: str,
    reference_results: list[FixturePilotResult] | None = None,
    repeat_cases_path: Path | None = None,
) -> None:
    """Atomically checkpoint after each video so long runs can resume safely."""
    payload = [
        {
            "name": r.name,
            "baseline": r.baseline.__dict__,
            "section": r.section.__dict__,
            "health": r.health.__dict__,
        }
        for r in results
    ]
    results_tmp = output_dir / "results.json.tmp"
    results_tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    results_tmp.replace(output_dir / "results.json")

    repeat_summary = None
    if repeat_cases_path is not None:
        repeat_summary = evaluate_repeat_cases(
            fixtures_dir,
            output_dir / "edls",
            repeat_cases_path,
            fixture_names={result.name for result in results},
        )
        repeat_payload = {
            "positive_cases": repeat_summary.positive_cases,
            "positive_passed": repeat_summary.positive_passed,
            "control_cases": repeat_summary.control_cases,
            "control_passed": repeat_summary.control_passed,
            "results": [
                {
                    "case": result.case.model_dump(),
                    "cut_words": result.cut_words,
                    "total_words": result.total_words,
                    "passed": result.passed,
                    "remainder_preserved": result.remainder_preserved,
                }
                for result in repeat_summary.results
            ],
        }
        repeat_tmp = output_dir / "repeat-results.json.tmp"
        repeat_tmp.write_text(json.dumps(repeat_payload, indent=2), encoding="utf-8")
        repeat_tmp.replace(output_dir / "repeat-results.json")

    report_tmp = output_dir / "report.md.tmp"
    report_tmp.write_text(
        format_pilot_report(
            results,
            model_id=model_id,
            reference_results=reference_results,
            repeat_summary=repeat_summary,
        ),
        encoding="utf-8",
    )
    report_tmp.replace(output_dir / "report.md")


def run_section_pilot(
    fixtures_dir: Path,
    output_dir: Path,
    *,
    names: list[str] | None = None,
    llm_config: LangChainModelConfig | None = None,
    resume: bool = True,
    compare_to: Path | None = None,
    repeat_cases_path: Path | None = None,
) -> list[FixturePilotResult]:
    llm_config = llm_config or default_section_editor_model_config()
    target = names or DEFAULT_PILOT_FIXTURES
    cfg = _section_config(llm_config)
    reference_results: list[FixturePilotResult] | None = None
    if compare_to is not None:
        reference_path = compare_to / "results.json" if compare_to.is_dir() else compare_to
        reference_results = [
            _result_from_dict(item)
            for item in json.loads(reference_path.read_text(encoding="utf-8"))
        ]
    output_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = output_dir / "edls"
    debug_dir.mkdir(exist_ok=True)
    traces_dir = output_dir / "traces"
    traces_dir.mkdir(exist_ok=True)
    (output_dir / "run.json").write_text(
        json.dumps(
            {
                "model_id": llm_config.id or llm_config.model,
                "model": llm_config.public_dict(),
                "fixtures": list(target),
                "prompt_sha256": sha256(SECTION_PROMPT.encode("utf-8")).hexdigest(),
                "compare_to": str(compare_to) if compare_to is not None else None,
                "repeat_cases": (
                    str(repeat_cases_path) if repeat_cases_path is not None else None
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    checkpoint_path = output_dir / "results.json"
    results: list[FixturePilotResult] = []
    if resume and checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        target_names = set(target)
        results = [
            result
            for item in checkpoint
            if (result := _result_from_dict(item)).name in target_names
            and result.health.sections_failed == 0
        ]
        if results:
            logger.info("Resuming section pilot with {} completed fixtures", len(results))
    completed = {result.name for result in results}

    for name in target:
        if name in completed:
            logger.info("Resume: skipping completed fixture {}", name)
            continue
        loaded = _load(fixtures_dir, name)
        if loaded is None:
            logger.warning("Skipping {} — missing sidecars", name)
            continue
        raw, baseline_edl, gt = loaded
        keeps, _silences = derive_cached_cutting_inputs(baseline_edl)

        health = SectionHealth()
        trace = SectionTrace()
        try:
            flags = detect_section_edits(
                raw.sentences,
                cfg,
                llm_config=llm_config,
                health=health,
                trace=trace,
            )
        except Exception:
            logger.exception("Section editor failed for {} — skipping", name)
            continue
        (traces_dir / f"{name}.json").write_text(
            trace.model_dump_json(indent=2), encoding="utf-8"
        )
        section_edl = build_edl(raw, keeps, flags)
        (debug_dir / f"{name}.edl.json").write_text(
            section_edl.model_dump_json(indent=2), encoding="utf-8"
        )

        baseline_score = evaluate_decisions_word_level(
            raw.sentences, baseline_edl, gt.sentences, name=name
        )
        section_score = evaluate_decisions_word_level(
            raw.sentences, section_edl, gt.sentences, name=name
        )
        results.append(FixturePilotResult(name, baseline_score, section_score, health))
        logger.info(
            "{}: baseline F1={:.3f} → section F1={:.3f} (health: {}/{} sections failed)",
            name, baseline_score.cut_f1, section_score.cut_f1,
            health.sections_failed, health.sections_total,
        )
        _write_pilot_artifacts(
            output_dir,
            results,
            fixtures_dir=fixtures_dir,
            model_id=llm_config.id or llm_config.model,
            reference_results=reference_results,
            repeat_cases_path=repeat_cases_path,
        )

    _write_pilot_artifacts(
        output_dir,
        results,
        fixtures_dir=fixtures_dir,
        model_id=llm_config.id or llm_config.model,
        reference_results=reference_results,
        repeat_cases_path=repeat_cases_path,
    )
    return results


def format_pilot_report(
    results: list[FixturePilotResult],
    *,
    model_id: str,
    reference_results: list[FixturePilotResult] | None = None,
    repeat_summary: RepeatCaseSummary | None = None,
) -> str:
    lines = [
        "# Section-editor pilot (word-level cut scoring vs human)",
        "",
        f"- Model: `{model_id}`",
        f"- Fixtures: {len(results)}",
        "",
        f"| {'fixture':<28} | {'base P':>6} {'base R':>6} {'base F1':>7} "
        f"| {'sec P':>6} {'sec R':>6} {'sec F1':>7} | {'ΔF1':>6} | {'fail':>5} | {'rej':>4} |",
        f"|{'-' * 30}|{'-' * 23}|{'-' * 23}|{'-' * 8}|{'-' * 7}|{'-' * 6}|",
    ]
    for r in results:
        b, s, h = r.baseline, r.section, r.health
        delta = s.cut_f1 - b.cut_f1
        fail = f"{h.sections_failed}/{h.sections_total}"
        rej = h.deletions_rejected_unverifiable + h.deletions_rejected_guardrail
        lines.append(
            f"| {r.name:<28} | {b.cut_precision:>6.3f} {b.cut_recall:>6.3f} {b.cut_f1:>7.3f} "
            f"| {s.cut_precision:>6.3f} {s.cut_recall:>6.3f} {s.cut_f1:>7.3f} | {delta:>+6.3f} "
            f"| {fail:>5} | {rej:>4} |"
        )
    base_agg = aggregate_word_scores([r.baseline for r in results])
    sec_agg = aggregate_word_scores([r.section for r in results])
    sections_total = sum(r.health.sections_total for r in results)
    sections_failed = sum(r.health.sections_failed for r in results)
    section_retries = sum(r.health.section_retries for r in results)
    sections_fallback = sum(r.health.sections_fallback for r in results)
    proposed = sum(r.health.deletions_proposed for r in results)
    rejected = sum(
        r.health.deletions_rejected_unverifiable + r.health.deletions_rejected_guardrail
        for r in results
    )
    healthy = sections_failed == 0
    lines += [
        f"|{'-' * 30}|{'-' * 23}|{'-' * 23}|{'-' * 8}|{'-' * 7}|{'-' * 6}|",
        f"| {'AGGREGATE':<28} | {base_agg.cut_precision:>6.3f} {base_agg.cut_recall:>6.3f} "
        f"{base_agg.cut_f1:>7.3f} | {sec_agg.cut_precision:>6.3f} {sec_agg.cut_recall:>6.3f} "
        f"{sec_agg.cut_f1:>7.3f} | {sec_agg.cut_f1 - base_agg.cut_f1:>+6.3f} "
        f"| {sections_failed}/{sections_total:<3} | {rejected:>4} |",
        "",
        f"Baseline words: TP={base_agg.tp} FP={base_agg.fp} FN={base_agg.fn}",
        f"Section words:  TP={sec_agg.tp} FP={sec_agg.fp} FN={sec_agg.fn}",
        "",
        f"**Health: {'OK' if healthy else 'DEGRADED'}** — "
        f"{sections_failed}/{sections_total} sections failed, "
        f"{section_retries} retries, "
        f"{sections_fallback} direct-OpenAI fallbacks, "
        f"{rejected}/{proposed} proposed spans rejected by guardrails."
        + ("" if healthy else " Scores are NOT trustworthy — failed sections score as zero cuts."),
    ]
    if reference_results is not None:
        reference_by_name = {result.name: result for result in reference_results}
        current_by_name = {result.name: result for result in results}
        common = sorted(reference_by_name.keys() & current_by_name.keys())
        gate = evaluate_candidate_gates(results, reference_results)
        lines += [
            "",
            "## Reference comparison",
            "",
            f"**Safety gate: {'PASS' if gate.passed else 'FAIL'}**",
            "",
            "| fixture | ref P | cand P | ΔP | ref R | cand R | ΔR | ref F1 | cand F1 | ΔF1 | ΔFP | verdict |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for name in common:
            old = reference_by_name[name].section
            new = current_by_name[name].section
            delta_f1 = new.cut_f1 - old.cut_f1
            delta_fp = new.fp - old.fp
            regressed = delta_f1 < -0.03 or delta_fp > 10
            lines.append(
                f"| {name} | {old.cut_precision:.3f} | {new.cut_precision:.3f} | "
                f"{new.cut_precision - old.cut_precision:+.3f} | {old.cut_recall:.3f} | "
                f"{new.cut_recall:.3f} | {new.cut_recall - old.cut_recall:+.3f} | "
                f"{old.cut_f1:.3f} | {new.cut_f1:.3f} | {delta_f1:+.3f} | "
                f"{delta_fp:+d} | {'REGRESSION' if regressed else 'OK'} |"
            )
        if gate.failures:
            lines += ["", "Gate failures:"]
            lines.extend(f"- {failure}" for failure in gate.failures)
    if repeat_summary is not None:
        lines += ["", format_repeat_case_report(repeat_summary)]
    return "\n".join(lines)
