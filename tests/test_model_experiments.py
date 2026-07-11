from __future__ import annotations

import json
import re
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
from ai_video_editor.enrich.models import (
    EnrichmentResult,
    EnrichmentStatus,
    SentenceEnrichment,
)
from ai_video_editor.experiments.manifest import load_manifest
from ai_video_editor.experiments.reconstruction import derive_cached_cutting_inputs
from ai_video_editor.experiments.runner import (
    ExperimentResults,
    ExperimentRunResult,
    format_report,
)
from ai_video_editor.experiments.scoring import score_annotation_actionability
from ai_video_editor.llm import LangChainModelConfig, build_chat_model
from ai_video_editor.qa.decision_eval import _cut_reason
from ai_video_editor.transcription.models import Sentence, Transcript, Word


def _install_fake_llm_module(module_name: str = "tests.fake_eval_llm"):
    module = types.ModuleType(module_name)

    class FakeChatModel:
        last_kwargs = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            FakeChatModel.last_kwargs = kwargs

        def with_structured_output(self, schema):
            return FakeStructured(schema)

    class FakeStructured:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, prompt: str):
            schema_name = self.schema.__name__
            if schema_name == "EnrichmentBatch":
                indices = [int(match) for match in re.findall(r"^\[(\d+)\]$", prompt, re.MULTILINE)]
                return self.schema.model_validate(
                    {
                        "sentences": [
                            {
                                "sentence_idx": idx,
                                "keep_confidence": 90.0,
                                "tags": ["verbatim_clean"],
                                "rationale": "fake",
                                "word_salience": [90.0],
                            }
                            for idx in indices
                        ]
                    }
                )
            if schema_name == "KeepDecisions":
                return self.schema.model_validate({"decisions": []})
            if schema_name == "DuplicateVerdicts":
                return self.schema.model_validate({"verdicts": []})
            if schema_name == "FalseStartVerdict":
                return self.schema.model_validate({"filler_indices": [], "reasoning": "fake"})
            if schema_name == "AsideReview":
                return self.schema.model_validate({"verdicts": []})
            if schema_name == "StutterVerdict":
                return self.schema.model_validate(
                    {"is_stutter": False, "word_indices_to_cut": [], "confidence": 0.0, "reasoning": "fake"}
                )
            if schema_name == "FragmentReview":
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


def test_annotation_actionability_scores_wrong_and_missed_cuts() -> None:
    raw = _transcript(
        [
            _sentence("Human kept this", 0.0, 1.0),
            _sentence("Human removed this", 1.0, 2.0),
            _sentence("Human also kept this", 2.0, 3.0),
        ]
    )
    ground_truth = _transcript([raw.sentences[0], raw.sentences[2]], source="tiny-edited.mp4")
    baseline = EditDecisionList(
        source_video="tiny-raw.mp4",
        total_duration=3.0,
        decisions=[
            EditDecision(start=0.0, end=1.0, action=EditAction.CUT, reason=EditReason.FALSE_START),
            EditDecision(start=1.0, end=3.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
        ],
    )
    enrichment = EnrichmentResult(
        source_video="tiny-raw.mp4",
        sentences=[
            SentenceEnrichment(sentence_idx=0, keep_confidence=95.0, status=EnrichmentStatus.RESTORE),
            SentenceEnrichment(sentence_idx=1, keep_confidence=20.0, status=EnrichmentStatus.YELLOW),
            SentenceEnrichment(sentence_idx=2, keep_confidence=95.0, status=EnrichmentStatus.GREEN),
        ],
    )

    score = score_annotation_actionability(
        raw.sentences,
        baseline,
        ground_truth.sentences,
        enrichment,
        name="tiny",
    )

    assert score.wrong_cuts == 1
    assert score.missed_cuts == 1
    assert score.restore.tp == 1 and score.restore.f1 == 1.0
    assert score.attention.tp == 1 and score.attention.f1 == 1.0
    assert score.ranking_average_precision == 1.0


def test_report_generation_mentions_cutting_and_annotation_scores() -> None:
    results = ExperimentResults(
        manifest_path=Path("manifest.json"),
        fixtures_dir=Path("tests/fixtures"),
        output_dir=Path("output/experiments"),
        started_at="2026-07-03T00:00:00+00:00",
        completed_at="2026-07-03T00:00:01+00:00",
        runs=[
            ExperimentRunResult(
                id="cut",
                part="cutting",
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
            ),
            ExperimentRunResult(
                id="ann",
                part="annotations",
                model="fake",
                llm_config={"model": "fake"},
                aggregate={
                    "wrong_cuts": 1,
                    "missed_cuts": 2,
                    "restore": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
                    "attention": {"precision": 0.5, "recall": 1.0, "f1": 0.667},
                    "ranking_average_precision": 0.75,
                },
            ),
        ],
    )

    report = format_report(results)

    assert "Cutting Score" in report
    assert "Annotation Actionability" in report
    assert "ranking average precision" in report


def test_eval_models_cli_writes_results_and_report_without_real_apis(tmp_path: Path) -> None:
    class_path, _ = _install_fake_llm_module("tests.fake_eval_cli_llm")
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    output = tmp_path / "experiments"

    raw = _transcript([_sentence("Only content", 0.0, 1.0)])
    edl = EditDecisionList(
        source_video="tiny-raw.mp4",
        total_duration=1.0,
        decisions=[
            EditDecision(start=0.0, end=1.0, action=EditAction.KEEP, reason=EditReason.SPEECH),
        ],
    )
    gt = _transcript([raw.sentences[0]], source="tiny-edited.mp4")
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
                "runs": [
                    {"id": "cut-fake", "part": "cutting", "model": "fake"},
                    {"id": "ann-fake", "part": "annotations", "model": "fake"},
                ],
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
    assert (output / "results.json").exists()
    assert (output / "report.md").exists()
    data = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert [run["id"] for run in data["runs"]] == ["cut-fake", "ann-fake"]
    assert (output / "debug" / "cut-fake" / "tiny.edl.json").exists()
    assert (output / "debug" / "ann-fake" / "tiny.enrichment.json").exists()
