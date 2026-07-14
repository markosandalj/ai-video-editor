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

    monkeypatch.setattr(
        "ai_video_editor.experiments.section_pilot.detect_section_edits",
        lambda *args, **kwargs: [],
    )
    first = run_section_pilot(fixtures, output, names=["tiny"])
    assert len(first) == 1
    assert (output / "results.json").exists()
    assert (output / "report.md").exists()

    def should_not_run(*args, **kwargs):
        raise AssertionError("completed fixture should have been resumed")

    monkeypatch.setattr(
        "ai_video_editor.experiments.section_pilot.detect_section_edits",
        should_not_run,
    )
    resumed = run_section_pilot(fixtures, output, names=["tiny"])
    assert len(resumed) == 1
    assert resumed[0].name == "tiny"
