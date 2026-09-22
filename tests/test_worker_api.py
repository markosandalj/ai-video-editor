from __future__ import annotations

import json
import time
import pytest
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ai_video_editor.worker.app import create_worker_app
from ai_video_editor.worker.contracts import (
    AnalysisResultV1,
    Progress,
    WorkerError,
    job_request_adapter,
)
from ai_video_editor.worker.executor import (
    CompletedEvent,
    EventSink,
    FailedEvent,
    ProgressEvent,
    SubprocessMediaExecutor,
)
from ai_video_editor.worker.settings import WorkerSettings


FIXTURES = Path(__file__).parent / "data" / "worker_contract"
API_TOKEN = "worker-api-token-000000000000"
CALLBACK_TOKEN = "callback-token-0000000000000"


class DeterministicFakeExecutor:
    def startup(self):
        pass

    def shutdown(self):
        pass

    def __init__(self):
        self._sinks: dict[UUID, EventSink] = {}

    def start(self, job_id, request, resolved_render_config, emit):
        del request, resolved_render_config
        self._sinks[job_id] = emit

    @property
    def started_job_ids(self) -> set[UUID]:
        return set(self._sinks)

    def progress(self, job_id: UUID, percent: int, stage: str) -> None:
        self._sinks[job_id](ProgressEvent(Progress(percent=percent, stage=stage)))

    def complete_analysis(self, job_id: UUID) -> None:
        result_payload = json.loads(
            (FIXTURES / "analysis-completed-snapshot.v1.json").read_text()
        )["result"]
        self._sinks[job_id](
            CompletedEvent(AnalysisResultV1.model_validate(result_payload))
        )

    def crash(self, job_id: UUID) -> None:
        self._sinks[job_id](
            FailedEvent(
                WorkerError(
                    code="processing_failed",
                    stage="processing",
                    message="Media subprocess exited abnormally",
                )
            )
        )


class RecordingCallbackClient:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.snapshots = []

    def deliver(self, snapshot) -> None:
        self.snapshots.append(snapshot)
        if self.fail:
            raise OSError("Gradivo unavailable")


def settings(db_path: Path) -> WorkerSettings:
    return WorkerSettings(
        AI_VIDEO_EDITOR_API_TOKEN=API_TOKEN,
        GRADIVO_VIDEO_CALLBACK_TOKEN=CALLBACK_TOKEN,
        GRADIVO_VIDEO_CALLBACK_BASE_URL="https://gradivo.example",
        VIDEO_PROCESSING_STATE_DB_PATH=db_path,
        VIDEO_PROCESSING_SCRATCH_DIR=db_path.parent / "scratch",
        callback_retry_base_seconds=0.001,
        callback_retry_max_seconds=0.001,
    )


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def request_payload(filename: str = "analysis-request.v1.json") -> dict:
    return json.loads((FIXTURES / filename).read_text())


def app_for(db_path, executor, callback_client=None):
    return create_worker_app(
        settings(db_path),
        executor=executor,
        callback_client=callback_client or RecordingCallbackClient(),
        start_callback_dispatcher=False,
    )


def test_every_worker_call_requires_application_bearer_token(tmp_path: Path) -> None:
    app = app_for(tmp_path / "jobs.sqlite3", DeterministicFakeExecutor())
    job_id = uuid4()

    with TestClient(app) as client:
        response = client.put(f"/v1/jobs/{job_id}", json=request_payload())
        get_response = client.get(f"/v1/jobs/{job_id}")

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthorized"}}
    assert get_response.status_code == 401


def test_strict_validation_maps_to_stable_invalid_request(tmp_path: Path) -> None:
    app = app_for(tmp_path / "jobs.sqlite3", DeterministicFakeExecutor())
    payload = request_payload()
    payload["callback_url"] = "https://attacker.invalid"

    with TestClient(app) as client:
        response = client.put(
            f"/v1/jobs/{uuid4()}", json=payload, headers=auth_headers()
        )

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_request"}}


def test_accept_get_and_semantic_idempotency(tmp_path: Path) -> None:
    executor = DeterministicFakeExecutor()
    app = app_for(tmp_path / "jobs.sqlite3", executor)
    job_id = uuid4()
    payload = request_payload()

    with TestClient(app) as client:
        created = client.put(f"/v1/jobs/{job_id}", json=payload, headers=auth_headers())
        known = client.put(
            f"/v1/jobs/{job_id}",
            content=json.dumps(payload, sort_keys=True),
            headers={**auth_headers(), "Content-Type": "application/json"},
        )
        fetched = client.get(f"/v1/jobs/{job_id}", headers=auth_headers())

    assert created.status_code == 201
    assert known.status_code == 200
    assert fetched.status_code == 200
    assert created.json() == known.json() == fetched.json()
    assert created.json()["revision"] == 1


def test_payload_mismatch_does_not_mutate_existing_job(tmp_path: Path) -> None:
    app = app_for(tmp_path / "jobs.sqlite3", DeterministicFakeExecutor())
    job_id = uuid4()
    changed = request_payload()
    changed["source"]["file_id"] = "different-file"

    with TestClient(app) as client:
        original = client.put(
            f"/v1/jobs/{job_id}", json=request_payload(), headers=auth_headers()
        )
        mismatch = client.put(
            f"/v1/jobs/{job_id}", json=changed, headers=auth_headers()
        )
        fetched = client.get(f"/v1/jobs/{job_id}", headers=auth_headers())

    assert original.status_code == 201
    assert mismatch.status_code == 409
    assert mismatch.json() == {"error": {"code": "job_payload_mismatch"}}
    assert fetched.json() == original.json()


def test_capacity_rejects_only_new_job_and_releases_on_terminal_event(
    tmp_path: Path,
) -> None:
    executor = DeterministicFakeExecutor()
    app = app_for(tmp_path / "jobs.sqlite3", executor)
    first_id = uuid4()
    second_id = uuid4()

    with TestClient(app) as client:
        assert (
            client.put(
                f"/v1/jobs/{first_id}", json=request_payload(), headers=auth_headers()
            ).status_code
            == 201
        )
        at_capacity = client.put(
            f"/v1/jobs/{second_id}", json=request_payload(), headers=auth_headers()
        )
        known = client.put(
            f"/v1/jobs/{first_id}", json=request_payload(), headers=auth_headers()
        )
        missing = client.get(f"/v1/jobs/{second_id}", headers=auth_headers())

        executor.crash(first_id)
        accepted_after_release = client.put(
            f"/v1/jobs/{second_id}", json=request_payload(), headers=auth_headers()
        )

    assert at_capacity.status_code == 429
    assert at_capacity.headers["retry-after"] == "30"
    assert at_capacity.json() == {
        "error": {"code": "worker_at_capacity", "retryable": True}
    }
    assert known.status_code == 200
    assert missing.status_code == 404
    assert accepted_after_release.status_code == 201


def test_progress_and_completion_are_revisioned_and_durable(tmp_path: Path) -> None:
    executor = DeterministicFakeExecutor()
    db_path = tmp_path / "jobs.sqlite3"
    app = app_for(db_path, executor)
    job_id = uuid4()

    with TestClient(app) as client:
        client.put(f"/v1/jobs/{job_id}", json=request_payload(), headers=auth_headers())
        executor.progress(job_id, 40, "transcribing")
        executor.complete_analysis(job_id)
        completed = client.get(f"/v1/jobs/{job_id}", headers=auth_headers())

    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["revision"] == 3
    assert completed.json()["result"]["schema"] == "analysis_result.v1"

    reopened = app_for(db_path, DeterministicFakeExecutor())
    with TestClient(reopened) as client:
        durable = client.get(f"/v1/jobs/{job_id}", headers=auth_headers())
    assert durable.json() == completed.json()


def test_startup_recovers_processing_job_without_rerun(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    first_executor = DeterministicFakeExecutor()
    job_id = uuid4()

    with TestClient(app_for(db_path, first_executor)) as client:
        client.put(f"/v1/jobs/{job_id}", json=request_payload(), headers=auth_headers())
        first_executor.progress(job_id, 25, "extracting_audio")

    second_executor = DeterministicFakeExecutor()
    with TestClient(app_for(db_path, second_executor)) as client:
        recovered = client.get(f"/v1/jobs/{job_id}", headers=auth_headers())
        replacement = client.put(
            f"/v1/jobs/{uuid4()}", json=request_payload(), headers=auth_headers()
        )

    assert recovered.json()["status"] == "failed"
    assert recovered.json()["revision"] == 3
    assert recovered.json()["progress"] == {
        "percent": 25,
        "stage": "extracting_audio",
    }
    assert recovered.json()["error"]["code"] == "worker_interrupted"
    assert job_id not in second_executor.started_job_ids
    assert replacement.status_code == 201


def test_terminal_callback_outbox_retries_after_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    executor = DeterministicFakeExecutor()
    failing_callbacks = RecordingCallbackClient(fail=True)
    app = app_for(db_path, executor, failing_callbacks)
    job_id = uuid4()

    with TestClient(app):
        service = app.state.worker_service
        service.submit(job_id, job_request_adapter.validate_python(request_payload()))
        executor.crash(job_id)
        assert service.dispatch_callbacks_once()
        assert service.dispatch_callbacks_once()
        assert service.store.pending_outbox_count() == 1

    successful_callbacks = RecordingCallbackClient()
    reopened = app_for(db_path, DeterministicFakeExecutor(), successful_callbacks)
    with TestClient(reopened):
        service = reopened.state.worker_service
        time.sleep(0.005)
        while service.dispatch_callbacks_once():
            pass

    assert successful_callbacks.snapshots
    assert successful_callbacks.snapshots[-1].status == "failed"
    assert successful_callbacks.snapshots[-1].error.code == "processing_failed"


def hang_until_deadline(job_id, request, resolved_render_config, progress):
    progress(10, "transcribing")
    while True:
        time.sleep(0.01)


def test_real_executor_timeout_is_durable_and_delivered_without_rerun(
    tmp_path: Path,
) -> None:
    callbacks = RecordingCallbackClient()
    app = create_worker_app(
        settings(tmp_path / "timeout.sqlite3"),
        executor=SubprocessMediaExecutor(
            hang_until_deadline, analysis_timeout_seconds=0.8
        ),
        callback_client=callbacks,
        start_callback_dispatcher=False,
    )
    job_id = uuid4()
    with TestClient(app) as client:
        assert (
            client.put(
                f"/v1/jobs/{job_id}", json=request_payload(), headers=auth_headers()
            ).status_code
            == 201
        )
        assert client.get("/healthz", headers=auth_headers()).status_code == 200
        assert (
            client.put(
                f"/v1/jobs/{uuid4()}", json=request_payload(), headers=auth_headers()
            ).status_code
            == 429
        )
        deadline = time.monotonic() + 8
        while True:
            snapshot = client.get(f"/v1/jobs/{job_id}", headers=auth_headers()).json()
            if snapshot["status"] == "failed":
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert snapshot["error"]["code"] == "processing_timeout"
        replay = client.put(
            f"/v1/jobs/{job_id}", json=request_payload(), headers=auth_headers()
        )
        assert replay.status_code == 200
        assert replay.json() == snapshot
        while app.state.worker_service.dispatch_callbacks_once():
            pass
        assert callbacks.snapshots[-1].error.code == "processing_timeout"

    reopened = app_for(tmp_path / "timeout.sqlite3", DeterministicFakeExecutor())
    with TestClient(reopened) as client:
        assert (
            client.get(f"/v1/jobs/{job_id}", headers=auth_headers()).json() == snapshot
        )
        assert (
            client.put(
                f"/v1/jobs/{uuid4()}", json=request_payload(), headers=auth_headers()
            ).status_code
            == 201
        )


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_execution_deadlines_must_be_positive_and_finite(tmp_path, value) -> None:
    from pydantic import ValidationError

    for name in (
        "VIDEO_PROCESSING_ANALYSIS_TIMEOUT_SECONDS",
        "VIDEO_PROCESSING_RENDER_TIMEOUT_SECONDS",
    ):
        values = settings(tmp_path / "jobs.sqlite3").model_dump(by_alias=True)
        values[name] = value
        with pytest.raises(ValidationError):
            WorkerSettings.model_validate(values)


@pytest.mark.parametrize("value", ["1", "2", "4"])
def test_capacity_accepts_environment_integer(monkeypatch, tmp_path, value):
    monkeypatch.setenv("MAX_NUMBER_OF_JOBS", value)
    assert settings(tmp_path / "jobs.sqlite3").max_number_of_jobs == int(value)


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "true", "invalid"])
def test_capacity_rejects_invalid_environment_value(monkeypatch, tmp_path, value):
    from pydantic import ValidationError

    monkeypatch.setenv("MAX_NUMBER_OF_JOBS", value)
    with pytest.raises(ValidationError):
        settings(tmp_path / "jobs.sqlite3")


def test_two_job_capacity_preserves_replay_and_releases_only_finished_job(tmp_path):
    executor = DeterministicFakeExecutor()
    config = settings(tmp_path / "jobs.sqlite3").model_copy(update={"max_number_of_jobs": 2})
    app = create_worker_app(config, executor=executor, start_callback_dispatcher=False)
    first, second, third, fourth = [uuid4() for _ in range(4)]
    with TestClient(app) as client:
        def submit(job_id):
            return client.put(f"/v1/jobs/{job_id}", json=request_payload(), headers=auth_headers())

        assert submit(first).status_code == 201
        assert submit(second).status_code == 201
        assert submit(third).status_code == 429
        assert submit(first).status_code == 200
        executor.complete_analysis(first)
        assert submit(third).status_code == 201
        assert submit(fourth).status_code == 429
        executor.crash(second)
        assert submit(fourth).status_code == 201


def test_default_app_executor_runs_configured_capacity(monkeypatch, tmp_path):
    from tests.test_worker_executor import WaitForRelease

    monkeypatch.setenv("MAX_NUMBER_OF_JOBS", "2")
    monkeypatch.setattr("ai_video_editor.worker.app.run_configured_media_job", WaitForRelease(tmp_path))
    config = settings(tmp_path / "jobs.sqlite3").model_copy(update={"analysis_timeout_seconds": 10})
    app = create_worker_app(config, start_callback_dispatcher=False)
    job_ids = [uuid4(), uuid4()]
    with TestClient(app) as client:
        try:
            for job_id in job_ids:
                assert client.put(f"/v1/jobs/{job_id}", json=request_payload(), headers=auth_headers()).status_code == 201
            deadline = time.monotonic() + 6
            while True:
                snapshots = [client.get(f"/v1/jobs/{job_id}", headers=auth_headers()).json() for job_id in job_ids]
                assert all(snapshot["status"] == "processing" for snapshot in snapshots)
                if all(snapshot["progress"]["percent"] == 10 for snapshot in snapshots):
                    break
                assert time.monotonic() < deadline
                time.sleep(0.02)
            assert client.get("/healthz", headers=auth_headers()).status_code == 200
            assert client.put(f"/v1/jobs/{uuid4()}", json=request_payload(), headers=auth_headers()).status_code == 429
        finally:
            for job_id in job_ids:
                (tmp_path / str(job_id)).touch()
        deadline = time.monotonic() + 6
        while True:
            snapshots = [client.get(f"/v1/jobs/{job_id}", headers=auth_headers()).json() for job_id in job_ids]
            if all(snapshot["status"] == "completed" for snapshot in snapshots):
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
