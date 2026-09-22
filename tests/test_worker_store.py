from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from ai_video_editor.worker.callbacks import HttpCallbackClient
from ai_video_editor.worker.contracts import (
    ResolvedRenderConfigV1,
    WorkerError,
    job_request_adapter,
    worker_snapshot_adapter,
)
from ai_video_editor.worker.store import JobStore


FIXTURES = Path(__file__).parent / "data" / "worker_contract"


def test_acceptance_rolls_back_job_and_slot_when_outbox_insert_fails(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    store.initialize()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_callback_outbox
            BEFORE INSERT ON callback_outbox
            BEGIN
                SELECT RAISE(ABORT, 'simulated outbox failure');
            END
            """
        )
    request = job_request_adapter.validate_json(
        (FIXTURES / "analysis-request.v1.json").read_text()
    )
    rejected_id = uuid4()

    with pytest.raises(sqlite3.IntegrityError):
        store.accept(rejected_id, request)

    assert store.get_snapshot(rejected_id) is None
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        connection.execute("DROP TRIGGER reject_callback_outbox")

    assert store.accept(uuid4(), request).created


def test_http_callback_uses_configured_url_and_independent_bearer_token(
    monkeypatch,
) -> None:
    snapshot = worker_snapshot_adapter.validate_json(
        (FIXTURES / "failed-snapshot.v1.json").read_text()
    )
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

    def fake_urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["user_agent"] = request.get_header("User-agent")
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("ai_video_editor.worker.callbacks.urlopen", fake_urlopen)
    client = HttpCallbackClient(
        base_url="https://configured-gradivo.example/",
        token="callback-only-token",
        timeout_seconds=4.0,
    )

    client.deliver(snapshot)

    assert captured["url"] == (
        "https://configured-gradivo.example/wt/internal/api/video-processing/jobs/"
        f"{snapshot.job_id}/status"
    )
    assert captured["authorization"] == "Bearer callback-only-token"
    assert captured["user_agent"] == "ai-video-worker/1.0"
    assert captured["body"] == snapshot.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert captured["timeout"] == 4.0


def _render_config(*, crf: int) -> ResolvedRenderConfigV1:
    return ResolvedRenderConfigV1(
        schema="resolved_render_config.v1",
        render_profile="student_video.v1",
        codec="libx264",
        crf=crf,
        preset="ultrafast",
        crossfade_ms=30,
        output_suffix="-final",
        audio_codec="aac",
        audio_bitrate="192k",
        movflags="+faststart",
    )


def test_render_config_snapshot_survives_replay_and_new_jobs_use_new_config(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    request = job_request_adapter.validate_json(
        (FIXTURES / "render-request.v1.json").read_text()
    )
    first_id = uuid4()
    first = JobStore(db_path, resolved_render_config=_render_config(crf=28))
    first.initialize()
    accepted = first.accept(first_id, request)
    assert accepted.resolved_render_config.crf == 28
    first.fail(
        first_id,
        WorkerError(code="processing_failed", stage="accepted", message="failed"),
    )

    changed = JobStore(db_path, resolved_render_config=_render_config(crf=20))
    changed.initialize()
    replay = changed.accept(first_id, request)
    assert not replay.created
    assert replay.resolved_render_config.crf == 28

    later = changed.accept(uuid4(), request)
    assert later.resolved_render_config.crf == 20


def test_initialize_migrates_legacy_jobs_table_before_accepting_render(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                slot_reserved INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )

    store = JobStore(db_path, resolved_render_config=_render_config(crf=24))
    store.initialize()
    request = job_request_adapter.validate_json(
        (FIXTURES / "render-request.v1.json").read_text()
    )
    job_id = uuid4()

    store.accept(job_id, request)

    assert store.get_resolved_render_config(job_id).crf == 24
    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
    assert "resolved_render_config_json" in columns
