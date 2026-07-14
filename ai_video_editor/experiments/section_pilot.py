"""Offline pilot for the LLM section editor.

Runs the section editor over cached fixtures and scores its cuts at the word
level against the human edit — the fair metric for partial (word-trim) cuts —
alongside the cached baseline EDL for a side-by-side comparison. No rendering
and no re-transcription; the only cost is the section-editor model calls.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from ai_video_editor.config.settings import SectionEditorConfig
from ai_video_editor.duplicate.edl import EditDecisionList, build_edl
from ai_video_editor.duplicate.section_editor import SectionHealth, detect_section_edits
from ai_video_editor.experiments.reconstruction import derive_cached_cutting_inputs
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


def _section_config(llm_config: LangChainModelConfig) -> SectionEditorConfig:
    cfg = SectionEditorConfig()
    cfg.enabled = True
    cfg.llm = llm_config
    return cfg


def run_section_pilot(
    fixtures_dir: Path,
    output_dir: Path,
    *,
    names: list[str] | None = None,
    llm_config: LangChainModelConfig | None = None,
) -> list[FixturePilotResult]:
    llm_config = llm_config or default_section_editor_model_config()
    target = names or DEFAULT_PILOT_FIXTURES
    cfg = _section_config(llm_config)
    output_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = output_dir / "edls"
    debug_dir.mkdir(exist_ok=True)

    results: list[FixturePilotResult] = []
    for name in target:
        loaded = _load(fixtures_dir, name)
        if loaded is None:
            logger.warning("Skipping {} — missing sidecars", name)
            continue
        raw, baseline_edl, gt = loaded
        keeps, _silences = derive_cached_cutting_inputs(baseline_edl)

        health = SectionHealth()
        try:
            flags = detect_section_edits(
                raw.sentences, cfg, llm_config=llm_config, health=health
            )
        except Exception:
            logger.exception("Section editor failed for {} — skipping", name)
            continue
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

    report = format_pilot_report(results, model_id=llm_config.id or llm_config.model)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    (output_dir / "results.json").write_text(
        json.dumps(
            [
                {
                    "name": r.name,
                    "baseline": r.baseline.__dict__,
                    "section": r.section.__dict__,
                    "health": r.health.__dict__,
                }
                for r in results
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return results


def format_pilot_report(results: list[FixturePilotResult], *, model_id: str) -> str:
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
        f"{rejected}/{proposed} proposed spans rejected by guardrails."
        + ("" if healthy else " Scores are NOT trustworthy — failed sections score as zero cuts."),
    ]
    return "\n".join(lines)
