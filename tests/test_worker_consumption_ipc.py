import json
import os
import queue
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from ai_video_editor.worker.callbacks import CallbackDispatcher
from ai_video_editor.worker.consumption import ConsumptionV1, finish_attempt, start_attempt
from ai_video_editor.worker.consumption_ipc import (
    SubprocessConsumptionRecorder,
    receive_consumption,
)
from ai_video_editor.worker.contracts import job_request_adapter
from ai_video_editor.worker.executor import SubprocessMediaExecutor
from ai_video_editor.worker.service import WorkerService
from ai_video_editor.worker.store import JobStore

FIXTURES = Path(__file__).parent / "data/worker_contract"


class ProviderRunner:
    def __init__(self, *, crash=False):
        self.crash = crash

    def __call__(self, job_id, request, resolved_render_config, progress):
        # The media process must not need a SQLite connection for receipts.
        def reject_sqlite(*args, **kwargs):
            raise AssertionError("Media process tried to open SQLite")

        sqlite3.connect = reject_sqlite
        started = start_attempt("worker.llm", "openrouter", "fixture-no-network")
        finish_attempt(
            started,
            outcome="succeeded",
            payload={"usage": {"total_tokens": 42, "cost": 0.001}},
        )
        if self.crash:
            # No feeder flush or progress event: the receipt acknowledgement
            # must already mean a durable write in the control process.
            os._exit(7)
        progress(90, "uploading_artifacts")
        return json.loads((FIXTURES / "analysis-completed-snapshot.v1.json").read_text())["result"]


@pytest.mark.parametrize("scenario", ["success", "crash", "first_write_fails", "all_writes_fail", "missing_ack"])
def test_real_subprocess_receipts_are_control_owned_and_do_not_block_results(tmp_path, monkeypatch, scenario):
    store = JobStore(tmp_path / "state.db")
    parent_pid = os.getpid()
    writes = []
    record = store.record_consumption

    def controlled_record(payload):
        assert os.getpid() == parent_pid
        writes.append(payload)
        if scenario == "all_writes_fail" or (scenario == "first_write_fails" and len(writes) == 1):
            raise sqlite3.OperationalError("simulated evidence failure")
        record(payload)

    monkeypatch.setattr(store, "record_consumption", controlled_record)
    if scenario == "missing_ack":
        def save_without_ack(event, **kwargs):
            receive_consumption(event, **{**kwargs, "acknowledgements": None})

        monkeypatch.setattr("ai_video_editor.worker.executor.receive_consumption", save_without_ack)
    executor = SubprocessMediaExecutor(
        ProviderRunner(crash=scenario == "crash"),
        consumption_recorder=store,
        analysis_timeout_seconds=15,
        termination_grace_seconds=0.1,
    )
    terminal = threading.Event()
    delivered = []

    class Client:
        def deliver(self, snapshot, *, consumption=None):
            if snapshot.status != "processing":
                delivered.append((snapshot, consumption))
                terminal.set()
            return True

    service = WorkerService(store, executor, CallbackDispatcher(store, Client(), idle_wait_seconds=0.01))
    service.startup()
    job_id = uuid4()
    try:
        service.submit(job_id, job_request_adapter.validate_json((FIXTURES / "analysis-request.v1.json").read_text()))
        assert terminal.wait(10)
    finally:
        service.shutdown()
    snapshot, evidence = delivered[-1]
    assert snapshot.status == ("failed" if scenario == "crash" else "completed")
    assert [row.revision for row in writes] == [1, 2]
    if scenario == "all_writes_fail":
        assert evidence == []
    else:
        assert len(evidence) == 1
        assert evidence[0].job_id == job_id
        assert evidence[0].outcome == "succeeded"
        assert evidence[0].usage["total_tokens"] == 42
        assert evidence[0].cost_amount == "0.001000000000"
        if scenario in {"first_write_fails", "missing_ack"}:
            assert "worker_ledger_write_failed" in evidence[0].coverage_issues


def sample_receipt():
    return ConsumptionV1(
        job_id=uuid4(), attempt_id=uuid4(), revision=1, operation="worker.llm",
        provider="google", started_at=datetime.now(UTC), outcome="started",
    )


def test_late_acknowledgement_cannot_confirm_a_different_receipt():
    events, acknowledgements = queue.Queue(), queue.Queue()
    recorder = SubprocessConsumptionRecorder(events, acknowledgements, timeout_seconds=0.1)
    with pytest.raises(TimeoutError):
        recorder.record_consumption(sample_receipt())
    stale = events.get_nowait()
    acknowledgements.put((stale["receipt_id"], True))

    def reject_next():
        event = events.get(timeout=2)
        acknowledgements.put((event["receipt_id"], False))

    responder = threading.Thread(target=reject_next)
    responder.start()
    try:
        with pytest.raises(RuntimeError, match="could not save"):
            recorder.record_consumption(sample_receipt())
    finally:
        responder.join(timeout=2)


@pytest.mark.parametrize("invalid", ["malformed", "wrong_job"])
def test_invalid_receipt_is_rejected_without_throwing_into_media_monitor(tmp_path, invalid):
    store = JobStore(tmp_path / "state.db")
    store.initialize()
    acknowledgements = queue.Queue()
    payload = {} if invalid == "malformed" else sample_receipt().model_dump(mode="json")
    receive_consumption(
        {"type": "consumption", "receipt_id": "receipt-1", "payload": payload},
        job_id=uuid4(), recorder=store, acknowledgements=acknowledgements,
    )
    assert acknowledgements.get_nowait() == ("receipt-1", False)
    with sqlite3.connect(store._path) as db:
        assert db.execute("SELECT COUNT(*) FROM consumption_attempts").fetchone()[0] == 0


def test_full_ack_channel_does_not_block_control_or_lose_saved_receipt(tmp_path):
    store = JobStore(tmp_path / "state.db")
    store.initialize()
    acknowledgements = queue.Queue(maxsize=1)
    acknowledgements.put(("stale", True))
    payload = sample_receipt()
    receive_consumption(
        {"type": "consumption", "receipt_id": "new", "payload": payload.model_dump(mode="json")},
        job_id=payload.job_id, recorder=store, acknowledgements=acknowledgements,
    )
    with sqlite3.connect(store._path) as db:
        assert db.execute("SELECT COUNT(*) FROM consumption_attempts").fetchone()[0] == 1


@pytest.mark.parametrize("lock_kind", ["sqlite", "thread"])
def test_busy_consumption_store_fails_quickly_and_can_recover(tmp_path, lock_kind):
    store = JobStore(tmp_path / "state.db")
    store.initialize()
    ready, release = threading.Event(), threading.Event()

    def hold_lock():
        if lock_kind == "thread":
            with store._lock:
                ready.set()
                release.wait(5)
        else:
            with sqlite3.connect(store._path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                ready.set()
                release.wait(5)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    try:
        assert ready.wait(2)
        started = time.monotonic()
        with pytest.raises((sqlite3.OperationalError, TimeoutError)):
            store.record_consumption(sample_receipt())
        assert time.monotonic() - started < 2  # Never the normal 30-second DB wait.
    finally:
        release.set()
        holder.join(timeout=2)
    store.record_consumption(sample_receipt())
