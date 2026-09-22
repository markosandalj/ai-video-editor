from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_video_editor.cli.app import app
from ai_video_editor.duplicate.edl import (
    EditAction,
    EditDecision,
    EditDecisionList,
    EditReason,
    build_edl,
)
from ai_video_editor.experiments.manifest import load_manifest
from ai_video_editor.experiments.reconstruction import derive_cached_cutting_inputs
from ai_video_editor.experiments.runner import (
    ExperimentResults,
    ExperimentRunResult,
    format_report,
)
from ai_video_editor.experiments.section_pilot import run_section_pilot
from ai_video_editor.llm import LangChainModelConfig, build_chat_model
from ai_video_editor.qa.decision_eval import _cut_reason
from ai_video_editor.transcription.models import Sentence, Transcript, Word


def _install_fake_llm_module(module_name: str = "tests.fake_eval_llm"):
    module = types.ModuleType(module_name)

    class FakeChatModel:
        last_kwargs = None
        last_prompt = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeChatModel.last_kwargs = kwargs

        def with_structured_output(self, schema):
            return FakeStructured(schema)

    class FakeStructured:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, prompt: str):
            FakeChatModel.last_prompt = prompt
            schema_name = self.schema.__name__
            if schema_name == "SectionEdits":
                return self.schema.model_validate({"deletions": []})
            if schema_name == "AsideReview":
                return self.schema.model_validate({"verdicts": []})
            raise AssertionError(f"Unhandled fake schema: {schema_name}")

    module.FakeChatModel = FakeChatModel
    sys.modules[module_name] = module
    return module_name, FakeChatModel


def _sentence(text: str, start: float, end: float) -> Sentence:
    words = text.split() or [text]
    step = (end - start) / max(len(words), 1)
    return Sentence(
        text=text,
        start=start,
        end=end,
        words=[
            Word(text=word, start=start + i * step, end=start + (i + 1) * step)
            for i, word in enumerate(words)
        ],
    )


def _transcript(sentences: list[Sentence], source: str = "tiny-raw.mp4") -> Transcript:
    return Transcript(
        sentences=sentences,
        source_video=source,
        language="hr",
        model_size="test",
    )


def test_langchain_model_config_dynamic_import_uses_fake_class() -> None:
    class_path, fake_cls = _install_fake_llm_module()
    config = LangChainModelConfig.model_validate(
        {
            "id": "fake",
            "class_path": f"{class_path}.FakeChatModel",
            "model": "fake-model",
            "temperature": 0.2,
            "api_key_env": None,
            "kwargs": {"custom": "value"},
        }
    )

    model = build_chat_model(config)

    assert isinstance(model, fake_cls)
    assert fake_cls.last_kwargs == {
        "model": "fake-model",
        "temperature": 0.2,
        "custom": "value",
    }


def test_manifest_validation_rejects_unknown_model(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "models": {"a": {"model": "fake", "api_key_env": None}},
                "runs": [{"id": "r1", "part": "cutting", "model": "missing"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown models"):
        load_manifest(path)


def test_cached_cutting_reconstruction_keeps_silence_fixed() -> None:
    transcript = _transcript(
        [
            _sentence("first", 0.0, 1.0),
            _sentence("controllable", 1.0, 2.0),
            _sentence("inside silence", 2.0, 3.0),
        ]
    )
    baseline = EditDecisionList(
        source_video="tiny-raw.mp4",
        total_duration=3.0,
        decisions=[
            EditDecision(start=0.0, end=1.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
            EditDecision(start=1.0, end=2.0, action=EditAction.CUT, reason=EditReason.DUPLICATE),
            EditDecision(start=2.0, end=3.0, action=EditAction.CUT, reason=EditReason.SILENCE),
        ],
    )

    keeps, silences = derive_cached_cutting_inputs(baseline)
    rebuilt = build_edl(transcript, keeps, [], rescue_outside_keep_regions=False)

    assert [(r.start, r.end) for r in keeps] == [(0.0, 2.0)]
    assert [(s.start, s.end) for s in silences] == [(2.0, 3.0)]
    assert _cut_reason(transcript.sentences[1], rebuilt)[0] is False
    assert _cut_reason(transcript.sentences[2], rebuilt)[0] is True


def test_report_generation_contains_only_cutting_scores() -> None:
    results = ExperimentResults(
        manifest_path=Path("manifest.json"),
        fixtures_dir=Path("tests/fixtures"),
        output_dir=Path("output/experiments"),
        started_at="2026-07-03T00:00:00+00:00",
        completed_at="2026-07-03T00:00:01+00:00",
        runs=[
            ExperimentRunResult(
                id="cut",
                model="fake",
                llm_config={"model": "fake"},
                aggregate={
                    "cut_precision": 1.0,
                    "cut_recall": 0.5,
                    "cut_f1": 0.667,
                    "accuracy": 0.9,
                    "fp": 1,
                    "fn": 2,
                },
            )
        ],
    )

    report = format_report(results)

    assert "Cutting Score" in report
    assert "Annotation" not in report


def test_eval_models_cli_writes_cutting_results_without_real_apis(tmp_path: Path) -> None:
    class_path, fake_cls = _install_fake_llm_module("tests.fake_eval_cli_llm")
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    output = tmp_path / "experiments"

    raw = _transcript(
        [
            _sentence("First useful sentence", 0.0, 1.0),
            _sentence("Second useful sentence", 1.0, 2.0),
        ]
    )
    edl = EditDecisionList(
        source_video="tiny-raw.mp4",
        total_duration=2.0,
        decisions=[
            EditDecision(start=0.0, end=2.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
        ],
    )
    gt = _transcript(raw.sentences, source="tiny-edited.mp4")
    (fixtures / "tiny-raw.transcript.json").write_text(raw.model_dump_json(), encoding="utf-8")
    (fixtures / "tiny-raw.edl.json").write_text(edl.model_dump_json(), encoding="utf-8")
    (fixtures / "tiny-edited.qa-transcript.json").write_text(gt.model_dump_json(), encoding="utf-8")

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "models": {
                    "fake": {
                        "class_path": f"{class_path}.FakeChatModel",
                        "model": "fake-model",
                        "api_key_env": None,
                    }
                },
                "runs": [{"id": "cut-fake", "part": "cutting", "model": "fake"}],
                "fixtures": ["tiny"],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "eval-models",
            str(manifest),
            "--fixtures-dir",
            str(fixtures),
            "--output-dir",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert [run["id"] for run in data["runs"]] == ["cut-fake"]
    assert fake_cls.last_kwargs["model"] == "fake-model"
    assert "First useful sentence" in fake_cls.last_prompt
    assert (output / "report.md").exists()
    assert (output / "debug" / "cut-fake" / "tiny.edl.json").exists()


def test_section_pilot_checkpoints_and_resumes_completed_fixture(
    tmp_path: Path, monkeypatch
) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    output = tmp_path / "section-pilot"
    raw = _transcript(
        [
            _sentence("First useful sentence", 0.0, 1.0),
            _sentence("Second useful sentence", 1.0, 2.0),
        ]
    )
    edl = EditDecisionList(
        source_video="tiny-raw.mp4",
        total_duration=2.0,
        decisions=[
            EditDecision(
                start=0.0,
                end=2.0,
                action=EditAction.KEEP,
                reason=EditReason.SPEECH,
            ),
        ],
    )
    gt = _transcript(raw.sentences, source="tiny-edited.mp4")
    (fixtures / "tiny-raw.transcript.json").write_text(
        raw.model_dump_json(), encoding="utf-8"
    )
    (fixtures / "tiny-raw.edl.json").write_text(
        edl.model_dump_json(), encoding="utf-8"
    )
    (fixtures / "tiny-edited.qa-transcript.json").write_text(
        gt.model_dump_json(), encoding="utf-8"
    )
    repeat_cases = tmp_path / "repeat-cases.json"
    repeat_cases.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "fixture": "tiny",
                        "sentence_index": 0,
                        "start_word": 0,
                        "end_word": 1,
                        "expected": "keep",
                        "label": "control",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "ai_video_editor.experiments.section_pilot.detect_section_edits",
        lambda *args, **kwargs: [],
    )
    first = run_section_pilot(
        fixtures,
        output,
        names=["tiny"],
        repeat_cases_path=repeat_cases,
    )
    assert len(first) == 1
    assert (output / "results.json").exists()
    assert (output / "report.md").exists()
    assert json.loads((output / "traces" / "tiny.json").read_text()) == {
        "proposals": []
    }
    run_manifest = json.loads((output / "run.json").read_text())
    assert run_manifest["model_id"] == "gpt-5.6-sol"
    assert run_manifest["fixtures"] == ["tiny"]
    assert run_manifest["repeat_cases"] == str(repeat_cases)
    assert "Explicit local-repeat cases" in (output / "report.md").read_text()
    repeat_results = json.loads((output / "repeat-results.json").read_text())
    assert repeat_results["control_cases"] == 1
    assert repeat_results["control_passed"] == 1
    candidate_output = tmp_path / "section-candidate"
    run_section_pilot(
        fixtures,
        candidate_output,
        names=["tiny"],
        compare_to=output / "results.json",
    )
    candidate_report = (candidate_output / "report.md").read_text()
    assert "Reference comparison" in candidate_report
    assert "Safety gate:" in candidate_report

    def should_not_run(*args, **kwargs):
        raise AssertionError("completed fixture should have been resumed")

    monkeypatch.setattr(
        "ai_video_editor.experiments.section_pilot.detect_section_edits",
        should_not_run,
    )
    resumed = run_section_pilot(fixtures, output, names=["tiny"])
    assert len(resumed) == 1
    assert resumed[0].name == "tiny"


def test_section_comparison_uses_generic_safety_gates() -> None:
    from ai_video_editor.duplicate.section_editor import SectionHealth
    from ai_video_editor.experiments.section_pilot import (
        FixturePilotResult,
        evaluate_candidate_gates,
        format_pilot_report,
    )
    from ai_video_editor.qa.decision_eval import WordDecisionScore

    reference = [
        FixturePilotResult(
            name="ordinary-fixture",
            baseline=WordDecisionScore(name="ordinary-fixture"),
            section=WordDecisionScore(name="ordinary-fixture", tp=100, fp=20, fn=30),
            health=SectionHealth(sections_total=1),
        )
    ]
    candidate = [
        FixturePilotResult(
            name="ordinary-fixture",
            baseline=WordDecisionScore(name="ordinary-fixture"),
            section=WordDecisionScore(name="ordinary-fixture", tp=99, fp=15, fn=31),
            health=SectionHealth(sections_total=1),
        )
    ]

    gate = evaluate_candidate_gates(candidate, reference)

    assert gate.passed is True
    assert gate.failures == []
    report = format_pilot_report(
        candidate,
        model_id="candidate-model",
        reference_results=reference,
    )
    assert "Reference comparison" in report
    assert "Safety gate: PASS" in report
    assert "ordinary-fixture" in report


def test_section_safety_gate_allows_an_unchanged_candidate() -> None:
    from ai_video_editor.duplicate.section_editor import SectionHealth
    from ai_video_editor.experiments.section_pilot import (
        FixturePilotResult,
        evaluate_candidate_gates,
    )
    from ai_video_editor.qa.decision_eval import WordDecisionScore

    score = WordDecisionScore(name="control", tp=100, fp=20, fn=30)
    reference = [
        FixturePilotResult(
            name="control",
            baseline=WordDecisionScore(name="control"),
            section=score,
            health=SectionHealth(sections_total=1),
        )
    ]
    candidate = [
        FixturePilotResult(
            name="control",
            baseline=WordDecisionScore(name="control"),
            section=score,
            health=SectionHealth(sections_total=1),
        )
    ]

    gate = evaluate_candidate_gates(candidate, reference)

    assert gate.passed is True
    assert gate.failures == []


def test_repeat_case_evaluator_scores_explicit_source_spans(tmp_path: Path) -> None:
    from ai_video_editor.experiments.repeat_eval import evaluate_repeat_cases

    fixtures = tmp_path / "fixtures"
    edls = tmp_path / "edls"
    fixtures.mkdir()
    edls.mkdir()
    transcript = _transcript(
        [
            _sentence("raniji ponovljeni dio ostali sadržaj", 0.0, 5.0),
            _sentence("namjerna usporedba ostaje cijela", 6.0, 10.0),
        ]
    )
    (fixtures / "tiny-raw.transcript.json").write_text(
        transcript.model_dump_json(), encoding="utf-8"
    )
    edl = EditDecisionList(
        source_video="tiny-raw.mp4",
        total_duration=10.0,
        decisions=[
            EditDecision(
                start=0.0,
                end=2.0,
                action=EditAction.CUT,
                reason=EditReason.FALSE_START,
            ),
            EditDecision(
                start=2.0,
                end=10.0,
                action=EditAction.KEEP,
                reason=EditReason.SPEECH,
            ),
        ],
    )
    (edls / "tiny.edl.json").write_text(edl.model_dump_json(), encoding="utf-8")
    manifest = tmp_path / "repeat-cases.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "fixture": "tiny",
                        "sentence_index": 0,
                        "start_word": 0,
                        "end_word": 2,
                        "expected": "cut",
                        "preserve_sentence_remainder": True,
                        "label": "confirmed restart",
                    },
                    {
                        "fixture": "tiny",
                        "sentence_index": 1,
                        "start_word": 0,
                        "end_word": 2,
                        "expected": "keep",
                        "label": "intentional repetition control",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = evaluate_repeat_cases(fixtures, edls, manifest)

    assert summary.positive_cases == 1
    assert summary.positive_passed == 1
    assert summary.control_cases == 1
    assert summary.control_passed == 1
    assert summary.results[0].passed is True
    assert summary.results[0].remainder_preserved is True
