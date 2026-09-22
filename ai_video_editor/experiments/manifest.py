from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_video_editor.llm import LangChainModelConfig


ExperimentPart = Literal["cutting"]


class ExperimentRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    part: ExperimentPart
    model: str = Field(min_length=1)


class ExperimentManifest(BaseModel):
    """Cutting-model experiment manifest.

    Annotation experiments were removed with the enrichment subsystem.
    """

    model_config = ConfigDict(extra="forbid")

    models: dict[str, LangChainModelConfig] = Field(default_factory=dict)
    runs: list[ExperimentRunConfig] = Field(default_factory=list)
    fixtures: list[str] | None = Field(
        default=None,
        description="Optional fixture-name allowlist. Defaults to all cached fixtures.",
    )

    @model_validator(mode="after")
    def validate_references(self) -> ExperimentManifest:
        run_ids = [run.id for run in self.runs]
        duplicate_run_ids = sorted({run_id for run_id in run_ids if run_ids.count(run_id) > 1})
        if duplicate_run_ids:
            raise ValueError(f"Duplicate run ids: {', '.join(duplicate_run_ids)}")

        missing_models = sorted({run.model for run in self.runs if run.model not in self.models})
        if missing_models:
            raise ValueError(f"Runs reference unknown models: {', '.join(missing_models)}")
        if not self.runs:
            raise ValueError("Manifest must contain at least one run.")
        if not self.models:
            raise ValueError("Manifest must contain at least one model.")
        return self

    def model_for_run(self, run: ExperimentRunConfig) -> LangChainModelConfig:
        return self.models[run.model].with_id(run.model)


def load_manifest(path: Path) -> ExperimentManifest:
    raw = path.read_text(encoding="utf-8")
    data = tomllib.loads(raw) if path.suffix.lower() == ".toml" else json.loads(raw)
    return ExperimentManifest.model_validate(data)
