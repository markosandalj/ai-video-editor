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
