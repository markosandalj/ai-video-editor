from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai_video_editor.worker.app import create_worker_app
from ai_video_editor.worker.contracts import job_request_adapter
from ai_video_editor.worker.executor import CompletedEvent, FailedEvent, SubprocessMediaExecutor
from tests.test_worker_api import auth_headers, request_payload, settings
from tests.test_worker_executor import finish_successfully


class ScratchRunner:
    def __init__(self, root: Path, outcome: str):
        self.root = root
        self.outcome = outcome

    def __call__(self, job_id, request, resolved_config, progress):
        job_dir = self.root / str(job_id)
        job_dir.mkdir(parents=True)
        (job_dir / "source.mp4").write_bytes(b"downloaded media")
        progress(20, "rendering")
        if self.outcome == "success":
            return finish_successfully(job_id, request, resolved_config, progress)
        if self.outcome == "failure":
            raise RuntimeError("test failure")
        if self.outcome == "crash":
            os._exit(7)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        heartbeat = self.root / f"{job_id}.heartbeat"
        subprocess.Popen([
            sys.executable, "-B", "-c",
            "import signal,time,pathlib,sys; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            "p=pathlib.Path(sys.argv[1]); "
            "exec('while True:\\n p.write_text(str(time.time()))\\n time.sleep(0.02)')",
            str(heartbeat),
        ])
        while True:
            time.sleep(0.02)


def analysis_request():
    return job_request_adapter.validate_python(request_payload())


@pytest.mark.parametrize("outcome", ["success", "failure", "crash", "timeout"])
def test_terminal_job_cleans_scratch_after_process_tree_stops(tmp_path, outcome):
    job_id = uuid4()
    executor = SubprocessMediaExecutor(
        ScratchRunner(tmp_path, outcome), scratch_dir=tmp_path,
        analysis_timeout_seconds=2, termination_grace_seconds=0.1,
    )
    done = threading.Event()
    received = []

    def emit(event):
        if isinstance(event, (CompletedEvent, FailedEvent)):
            received.append(event)
            done.set()

    executor.startup()
    try:
        executor.start(job_id, analysis_request(), None, emit)
        assert done.wait(8)
        assert not (tmp_path / str(job_id)).exists()
        assert len(received) == 1
        if outcome == "success":
            assert isinstance(received[0], CompletedEvent)
        else:
            assert isinstance(received[0], FailedEvent)
        if outcome == "timeout":
            assert received[0].error.code == "processing_timeout"
            heartbeat = tmp_path / f"{job_id}.heartbeat"
            previous = heartbeat.read_text()
            time.sleep(0.15)
            assert heartbeat.read_text() == previous
    finally:
        executor.shutdown()


def test_startup_cleans_uuid_remnants_without_following_symlinks(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    outside = tmp_path / "keep"
    outside.mkdir()
    (outside / "important").write_text("keep")
    old_job = root / str(uuid4())
    old_job.mkdir()
    (old_job / "source.mp4").write_bytes(b"left after restart")
    (old_job / "outside").symlink_to(outside, target_is_directory=True)
    job_link = root / str(uuid4())
    job_link.symlink_to(outside, target_is_directory=True)
    unrelated = root / "iterations"
    unrelated.mkdir()
    executor = SubprocessMediaExecutor(finish_successfully, scratch_dir=root)
    executor.startup()
    assert not old_job.exists()
    assert not job_link.is_symlink()
    assert unrelated.is_dir()
    assert (outside / "important").read_text() == "keep"
    executor.shutdown()


def test_shutdown_stops_all_jobs_and_persists_terminal_state_before_return(tmp_path):
    config = settings(tmp_path / "jobs.sqlite3").model_copy(update={"max_number_of_jobs": 2})
    root = config.scratch_dir
    executor = SubprocessMediaExecutor(
        ScratchRunner(root, "hang"), scratch_dir=root, max_number_of_jobs=2,
        analysis_timeout_seconds=20, termination_grace_seconds=0.1,
    )
    app = create_worker_app(config, executor=executor, start_callback_dispatcher=False)
    job_ids = [uuid4(), uuid4()]
    with TestClient(app) as client:
        for job_id in job_ids:
            response = client.put(f"/v1/jobs/{job_id}", json=request_payload(), headers=auth_headers())
            assert response.status_code == 201
        deadline = time.monotonic() + 8
        while not all((root / f"{job_id}.heartbeat").exists() for job_id in job_ids):
            assert time.monotonic() < deadline
            time.sleep(0.02)
        with pytest.raises(RuntimeError, match="current state"):
            executor.startup()
        assert all((root / str(job_id)).is_dir() for job_id in job_ids)

    store = app.state.worker_service.store
    revisions = {}
    for job_id in job_ids:
        snapshot = store.get_snapshot(job_id)
        assert snapshot.status == "failed"
        assert snapshot.error.code == "worker_interrupted"
        revisions[job_id] = snapshot.revision
        assert not (root / str(job_id)).exists()
    heartbeats = [(root / f"{job_id}.heartbeat").read_text() for job_id in job_ids]
    time.sleep(0.15)
    assert heartbeats == [(root / f"{job_id}.heartbeat").read_text() for job_id in job_ids]
    with pytest.raises(RuntimeError, match="stopping"):
        executor.start(uuid4(), analysis_request(), None, lambda event: None)
    executor.shutdown()  # Idempotent shutdown must not emit a second terminal revision.
    pending = store.pending_outbox_count()
    restarted = create_worker_app(config, start_callback_dispatcher=False)
    with TestClient(restarted):
        for job_id in job_ids:
            assert restarted.state.worker_service.store.get_snapshot(job_id).revision == revisions[job_id]
        assert restarted.state.worker_service.store.pending_outbox_count() == pending


def test_shutdown_waits_for_terminal_event_persistence(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    shutdown_done = threading.Event()
    executor = SubprocessMediaExecutor(finish_successfully, scratch_dir=tmp_path)

    def emit(event):
        if isinstance(event, CompletedEvent):
            entered.set()
            assert release.wait(5)

    executor.start(uuid4(), analysis_request(), None, emit)
    assert entered.wait(5)

    def shutdown():
        executor.shutdown()
        shutdown_done.set()

    thread = threading.Thread(target=shutdown)
    thread.start()
    try:
        assert not shutdown_done.wait(0.1)
    finally:
        release.set()
        thread.join(timeout=5)
    assert shutdown_done.is_set()


def test_restart_recovers_job_and_removes_its_abandoned_scratch(tmp_path):
    from ai_video_editor.worker.store import JobStore

    config = settings(tmp_path / "jobs.sqlite3")
    previous_store = JobStore(config.state_db_path)
    previous_store.initialize()
    job_id = uuid4()
    previous_store.accept(job_id, analysis_request())
    job_dir = config.scratch_dir / str(job_id)
    job_dir.mkdir(parents=True)
    (job_dir / "partial.flac").write_bytes(b"left after interrupted worker")
    app = create_worker_app(config, start_callback_dispatcher=False)
    with TestClient(app):
        snapshot = app.state.worker_service.store.get_snapshot(job_id)
        assert snapshot.error.code == "worker_interrupted"
        assert not job_dir.exists()
        assert app.state.worker_service.store.pending_outbox_count() == 2


def test_failed_scratch_cleanup_stops_new_execution(tmp_path, monkeypatch, caplog):
    attempted = threading.Event()

    def cannot_remove(root, job_id):
        attempted.set()
        raise PermissionError("simulated scratch cleanup failure")

    monkeypatch.setattr("ai_video_editor.worker.executor.remove_job_scratch", cannot_remove)
    executor = SubprocessMediaExecutor(
        ScratchRunner(tmp_path, "success"), scratch_dir=tmp_path,
        termination_grace_seconds=0.1,
    )
    job_id = uuid4()
    executor.start(job_id, analysis_request(), None, lambda event: None)
    assert attempted.wait(5)
    with pytest.raises(RuntimeError, match="did not shut down cleanly"):
        executor.shutdown()
    with pytest.raises(RuntimeError, match="stopping|recovery"):
        executor.start(uuid4(), analysis_request(), None, lambda event: None)
    assert (tmp_path / str(job_id)).is_dir()
    assert str(job_id) in caplog.text
