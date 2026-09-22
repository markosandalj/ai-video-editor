from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_video_editor.worker.contracts import (
    job_request_adapter,
    worker_snapshot_adapter,
)


FIXTURES = Path(__file__).parent / "data" / "worker_contract"


@pytest.mark.parametrize(
    "filename",
    ["analysis-request.v1.json", "render-request.v1.json"],
)
def test_canonical_requests_validate_with_public_schema(filename: str) -> None:
    job_request_adapter.validate_json((FIXTURES / filename).read_text())


@pytest.mark.parametrize(
    "filename",
    [
        "processing-snapshot.v1.json",
        "analysis-completed-snapshot.v1.json",
        "render-completed-snapshot.v1.json",
        "failed-snapshot.v1.json",
    ],
)
def test_canonical_snapshots_validate_with_public_schema(filename: str) -> None:
    worker_snapshot_adapter.validate_json((FIXTURES / filename).read_text())


def test_closed_request_rejects_unknown_fields() -> None:
    payload = json.loads((FIXTURES / "analysis-request.v1.json").read_text())
    payload["callback_url"] = "https://attacker.invalid"

    with pytest.raises(ValidationError):
        job_request_adapter.validate_python(payload)


def test_render_ranges_must_be_canonical() -> None:
    payload = json.loads((FIXTURES / "render-request.v1.json").read_text())
    payload["edit"]["cut_ranges"] = [
        {"start_ms": 100, "end_ms": 200},
        {"start_ms": 200, "end_ms": 300},
    ]

    with pytest.raises(ValidationError):
        job_request_adapter.validate_python(payload)


def test_contract_alias_cannot_be_replaced_with_internal_field_name() -> None:
    payload = json.loads((FIXTURES / "render-request.v1.json").read_text())
    payload["edit"]["schema_version"] = payload["edit"].pop("schema")

    with pytest.raises(ValidationError):
        job_request_adapter.validate_python(payload)
