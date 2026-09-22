from __future__ import annotations

import os
import json
import threading
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from ai_video_editor.worker.contracts import job_request_adapter
from ai_video_editor.worker.executor import (
    CompletedEvent,
    FailedEvent,
    SubprocessMediaExecutor,
)


FIXTURES = Path(__file__).parent / "data" / "worker_contract"


def exit_abnormally(job_id, request, resolved_render_config, progress):
    del job_id, request, resolved_render_config, progress
    os._exit(7)


def finish_successfully(job_id, request, resolved_render_config, progress):
    progress(80, "uploading_artifacts")
    return json.loads((FIXTURES / "analysis-completed-snapshot.v1.json").read_text())[
        "result"
    ]


def test_successful_execution_still_completes_once() -> None:
    request = job_request_adapter.validate_json(
        (FIXTURES / "analysis-request.v1.json").read_text()
    )
    terminal = threading.Event()
    received = []

    def emit(event):
        if isinstance(event, (CompletedEvent, FailedEvent)):
            received.append(event)
            terminal.set()

    SubprocessMediaExecutor(finish_successfully, analysis_timeout_seconds=10).start(
        uuid4(), request, None, emit
    )
    assert terminal.wait(8)
    assert len(received) == 1
    assert isinstance(received[0], CompletedEvent)


def hang_ignoring_termination(job_id, request, resolved_render_config, progress):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    progress(10, "rendering")
    while True:
        time.sleep(0.05)


@pytest.mark.parametrize("operation", ["analysis", "render"])
def test_timeout_stops_stubborn_process_and_releases_slot(operation) -> None:
    request = job_request_adapter.validate_json(
        (FIXTURES / f"{operation}-request.v1.json").read_text()
    )
    executor = SubprocessMediaExecutor(
        hang_ignoring_termination,
        analysis_timeout_seconds=1.0 if operation == "analysis" else 60.0,
        render_timeout_seconds=1.0 if operation == "render" else 60.0,
        termination_grace_seconds=0.1,
    )
    for _ in range(2):
        terminal = threading.Event()
        received = []

        def emit(event):
            if isinstance(event, FailedEvent):
                received.append(event)
                terminal.set()

        executor.start(uuid4(), request, None, emit)
        assert terminal.wait(8)
        assert received[0].error.code == "processing_timeout"
        assert received[0].error.stage == "rendering"


class HangWithChild:
    def __init__(self, heartbeat: Path):
        self.heartbeat = heartbeat

    def __call__(self, job_id, request, resolved_render_config, progress):
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,time,pathlib,sys; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                "p=pathlib.Path(sys.argv[1]); "
                "exec('while True:\\n p.write_text(str(time.time()))\\n time.sleep(0.02)')",
                str(self.heartbeat),
            ]
        )
        while True:
            time.sleep(0.05)


def test_timeout_stops_descendants_before_reporting_failure(tmp_path) -> None:
    heartbeat = tmp_path / "heartbeat"
    request = job_request_adapter.validate_json(
        (FIXTURES / "analysis-request.v1.json").read_text()
    )
    terminal = threading.Event()
    executor = SubprocessMediaExecutor(
        HangWithChild(heartbeat),
        analysis_timeout_seconds=1.5,
        termination_grace_seconds=0.1,
    )
    executor.start(
        uuid4(),
        request,
        None,
        lambda event: terminal.set() if isinstance(event, FailedEvent) else None,
    )
    assert terminal.wait(8)
    assert heartbeat.exists()
    stopped_value = heartbeat.read_text()
    time.sleep(0.2)
    assert heartbeat.read_text() == stopped_value


def test_abnormal_media_subprocess_exit_becomes_processing_failure() -> None:
    request = job_request_adapter.validate_json(
        (FIXTURES / "analysis-request.v1.json").read_text()
    )
    terminal = threading.Event()
    received = []

    def emit(event):
        received.append(event)
        terminal.set()

    SubprocessMediaExecutor(exit_abnormally).start(uuid4(), request, None, emit)

    assert terminal.wait(timeout=10.0)
    assert len(received) == 1
    assert isinstance(received[0], FailedEvent)
    assert received[0].error.code == "processing_failed"
    assert received[0].error.message == "Media subprocess exited abnormally"


class WaitForRelease:
    def __init__(self, directory: Path):
        self.directory = directory

    def __call__(self, job_id, request, resolved_render_config, progress):
        progress(10, "rendering")
        while not (self.directory / str(job_id)).exists():
            time.sleep(0.01)
        operation = request["operation"]
        return json.loads((FIXTURES / f"{operation}-completed-snapshot.v1.json").read_text())["result"]


def test_parallel_jobs_have_independent_capacity_and_timeouts(tmp_path):
    from ai_video_editor.worker.executor import ProgressEvent

    executor = SubprocessMediaExecutor(
        WaitForRelease(tmp_path),
        max_number_of_jobs=2,
        analysis_timeout_seconds=2,
        render_timeout_seconds=15,
        termination_grace_seconds=0.1,
    )
    analysis = job_request_adapter.validate_json((FIXTURES / "analysis-request.v1.json").read_text())
    render = job_request_adapter.validate_json((FIXTURES / "render-request.v1.json").read_text())
    job_ids = [uuid4() for _ in range(3)]
    running = [threading.Event() for _ in job_ids]
    finished = [threading.Event() for _ in job_ids]
    outcomes = {}

    def sink(index):
        def emit(event):
            if isinstance(event, ProgressEvent):
                running[index].set()
            else:
                outcomes[index] = event
                finished[index].set()
        return emit

    try:
        executor.start(job_ids[0], analysis, None, sink(0))
        executor.start(job_ids[1], render, None, sink(1))
        assert running[0].wait(1.5) and running[1].wait(1.5)
        with pytest.raises(RuntimeError, match="capacity"):
            executor.start(job_ids[2], analysis, None, sink(2))
        assert finished[0].wait(5)
        assert outcomes[0].error.code == "processing_timeout"
        assert not finished[1].is_set()
        executor.start(job_ids[2], analysis, None, sink(2))
        assert running[2].wait(1.5)
        with pytest.raises(RuntimeError, match="capacity"):
            executor.start(uuid4(), analysis, None, lambda event: None)
        (tmp_path / str(job_ids[2])).touch()
        assert finished[2].wait(5)
        assert isinstance(outcomes[2], CompletedEvent)
        assert not finished[1].is_set()
        (tmp_path / str(job_ids[1])).touch()
        assert finished[1].wait(5)
        assert isinstance(outcomes[1], CompletedEvent)
    finally:
        for job_id in job_ids:
            (tmp_path / str(job_id)).touch()
        for event in finished:
            event.wait(3)


def fail_unexpectedly(job_id, request, resolved_render_config, progress):
    progress(45, "transcribing")
    try:
        raise KeyError("missing transcript segment")
    except KeyError as exc:
        raise RuntimeError(f"unexpected failure {os.environ['TEST_PROVIDER_API_KEY']}") from exc


def fail_ffmpeg(job_id, request, resolved_render_config, progress):
    from ai_video_editor.analysis import InvalidMediaError, _run_ffmpeg
    from ai_video_editor.worker.executor import MediaExecutionFailure

    try:
        _run_ffmpeg(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "anullsrc=r=8000", "-t", "0.01", "-c:a", "missing_test_encoder", "-f", "null", "-"],
            failure="Could not encode lossless processed audio",
            stage="building_review_artifacts",
        )
    except InvalidMediaError as exc:
        raise MediaExecutionFailure(
            code="invalid_media", stage=exc.stage,
            message="Source is not a supported video with audio",
        ) from exc


@pytest.mark.parametrize(
    "runner,code,stage,diagnostic",
    [(fail_unexpectedly, "processing_failed", "transcribing", "KeyError"),
     (fail_ffmpeg, "invalid_media", "building_review_artifacts", "missing_test_encoder")],
)
def test_subprocess_failure_logs_cause_without_exposing_it_in_event(
    monkeypatch, caplog, runner, code, stage, diagnostic,
):
    monkeypatch.setenv("TEST_PROVIDER_API_KEY", "fake-sensitive-provider-key")
    request = job_request_adapter.validate_json((FIXTURES / "analysis-request.v1.json").read_text())
    terminal = threading.Event()
    received = []
    job_id = uuid4()

    def emit(event):
        if isinstance(event, FailedEvent):
            received.append(event)
            terminal.set()

    SubprocessMediaExecutor(runner, analysis_timeout_seconds=15).start(job_id, request, None, emit)
    assert terminal.wait(12)
    assert len(received) == 1
    error = received[0].error
    assert error.code == code and error.stage == stage
    assert set(error.model_dump()) == {"code", "stage", "message"}
    assert diagnostic not in error.message
    assert str(job_id) in caplog.text
    assert diagnostic in caplog.text
    assert '"frames":' in caplog.text
    assert '"line":' in caplog.text
    assert "fake-sensitive-provider-key" not in caplog.text
