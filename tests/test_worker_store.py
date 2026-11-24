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

        def read(self):
            return b'{"acknowledged": true, "consumption_acknowledged": true}'

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


@pytest.mark.parametrize("encoding_fails", [False, True])
def test_http_terminal_callback_prioritizes_result_and_reads_consumption_ack(monkeypatch, encoding_fails):
    from datetime import UTC, datetime
    from ai_video_editor.worker.consumption import ConsumptionV1

    snapshot = worker_snapshot_adapter.validate_json(
        (FIXTURES / "render-completed-snapshot.v1.json").read_text()
    )
    receipt = ConsumptionV1(
        job_id=snapshot.job_id, attempt_id=uuid4(), revision=2,
        operation="worker.llm", provider="openrouter", started_at=datetime.now(UTC),
        outcome="succeeded", usage={"total_tokens": 42},
    )
    bodies = []
    accepted_consumption = False

    class BadReceipt:
        def model_dump(self, **kwargs):
            raise ValueError("simulated evidence encoding failure")

    class Response:
        status = 200

        def read(self):
            return json.dumps({"acknowledged": True, "consumption_acknowledged": accepted_consumption}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def send(request, **kwargs):
        bodies.append(json.loads(request.data))
        assert request.full_url.endswith("/status")
        return Response()

    monkeypatch.setattr("ai_video_editor.worker.callbacks.urlopen", send)
    client = HttpCallbackClient(base_url="http://gradivo.localhost", token="fixture")
    assert client.deliver(snapshot, consumption=[BadReceipt() if encoding_fails else receipt]) is False
    assert bodies[-1]["result"] == snapshot.result.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert ("consumption" in bodies[-1]) is not encoding_fails
    accepted_consumption = True
    assert client.deliver(snapshot, consumption=[receipt]) is True
    assert bodies[-1]["consumption"][0]["usage"] == {"total_tokens": 42}


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


@pytest.mark.parametrize("failure_point", ["connect", "begin"])
def test_transaction_start_failure_does_not_block_other_threads(tmp_path, monkeypatch, failure_point):
    import threading

    store = JobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    request = job_request_adapter.validate_json(
        (FIXTURES / "analysis-request.v1.json").read_text()
    )
    # Close the persistent connection so the next transaction exercises _connect.
    store.close()
    connect = store._connect
    blocker = connect()

    def failing_connect(**kwargs):
        if failure_point == "connect":
            raise sqlite3.OperationalError("simulated connection failure")
        connection = connect(**kwargs)
        connection.execute("PRAGMA busy_timeout = 10")
        return connection

    blocker.execute("BEGIN IMMEDIATE")
    monkeypatch.setattr(store, "_connect", failing_connect)
    try:
        with pytest.raises(sqlite3.OperationalError):
            store.accept(uuid4(), request)
    finally:
        blocker.rollback()
        blocker.close()
        monkeypatch.setattr(store, "_connect", connect)

    completed = threading.Event()
    errors = []

    def accept_from_other_thread():
        try:
            store.accept(uuid4(), request)
        except Exception as exc:
            errors.append(exc)
        finally:
            completed.set()

    thread = threading.Thread(target=accept_from_other_thread, daemon=True)
    thread.start()
    try:
        assert completed.wait(2), "transaction failure leaked the store lock"
        assert not errors
    finally:
        # Unblock the regression's leaked RLock on the old implementation.
        if not completed.is_set():
            store._lock.release()
        thread.join(timeout=2)
        store.close()


def test_persistent_connection_avoids_wal_shm_churn_and_reconnects_after_close(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(db_path)
    connect_calls = 0
    real_connect = store._connect

    def counting_connect(**kwargs):
        nonlocal connect_calls
        connect_calls += 1
        return real_connect(**kwargs)

    monkeypatch.setattr(store, "_connect", counting_connect)
    store.initialize()
    request = job_request_adapter.validate_json(
        (FIXTURES / "analysis-request.v1.json").read_text()
    )
    job_id = uuid4()
    store.accept(job_id, request)
    assert connect_calls == 1

    wal_path = tmp_path / "jobs.sqlite3-wal"
    shm_path = tmp_path / "jobs.sqlite3-shm"
    assert wal_path.exists()
    assert shm_path.exists()
    wal_inode = wal_path.stat().st_ino
    shm_inode = shm_path.stat().st_ino

    for _ in range(10):
        assert store.next_outbox() is not None
        assert store.next_outbox_available_at() is not None
        assert store.get_snapshot(job_id) is not None

    assert connect_calls == 1
    assert wal_path.exists() and wal_path.stat().st_ino == wal_inode
    assert shm_path.exists() and shm_path.stat().st_ino == shm_inode

    store.close()
    assert store._connection is None
    assert store.get_snapshot(job_id).job_id == job_id
    assert connect_calls == 2
    store.close()


def test_worker_service_shutdown_closes_store_connection(tmp_path: Path) -> None:
    from unittest.mock import Mock

    from ai_video_editor.worker.callbacks import CallbackDispatcher
    from ai_video_editor.worker.service import WorkerService

    store = JobStore(tmp_path / "jobs.sqlite3")
    dispatcher = CallbackDispatcher(store, Mock())
    service = WorkerService(store, Mock(), dispatcher)
    service.startup(start_callback_dispatcher=False)
    assert store._connection is not None

    service.shutdown()
    assert store._connection is None
    # Subsequent read reconnects cleanly.
    assert store.pending_outbox_count() == 0
    store.close()


def test_shutdown_defers_store_close_until_in_flight_callback_finishes(
    tmp_path: Path,
) -> None:
    import threading

    from ai_video_editor.worker.callbacks import CallbackDispatcher

    store = JobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    request = job_request_adapter.validate_json(
        (FIXTURES / "analysis-request.v1.json").read_text()
    )
    store.accept(uuid4(), request)

    in_delivery = threading.Event()
    release_delivery = threading.Event()

    class SlowClient:
        def deliver(self, snapshot, *, consumption=None) -> bool:
            del snapshot, consumption
            in_delivery.set()
            assert release_delivery.wait(5)
            return True

    dispatcher = CallbackDispatcher(store, SlowClient())
    dispatcher.start()
    assert in_delivery.wait(2)

    # Stop with a short join timeout while the callback is still in flight:
    # the store must stay open for mark_outbox_delivered(), then close on exit.
    dispatcher.stop(timeout=0.05, close_store=True)
    thread = dispatcher._thread
    assert thread is not None and thread.is_alive()
    assert store._connection is not None

    release_delivery.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert store._connection is None
    assert store.pending_outbox_count() == 0
    store.close()


def test_callback_dispatcher_does_not_poll_when_idle_and_wakes_on_notify(
    tmp_path: Path, monkeypatch
) -> None:
    import threading
    import time

    from ai_video_editor.worker.callbacks import CallbackDispatcher

    store = JobStore(tmp_path / "jobs.sqlite3")
    store.initialize()

    next_outbox_calls = 0
    initial_check_done = threading.Event()
    real_next_outbox = store.next_outbox
    real_next_available_at = store.next_outbox_available_at

    def counting_next_outbox(*args, **kwargs):
        nonlocal next_outbox_calls
        next_outbox_calls += 1
        return real_next_outbox(*args, **kwargs)

    def tracking_next_available_at():
        result = real_next_available_at()
        initial_check_done.set()
        return result

    monkeypatch.setattr(store, "next_outbox", counting_next_outbox)
    monkeypatch.setattr(store, "next_outbox_available_at", tracking_next_available_at)

    delivered = []
    delivered_event = threading.Event()

    class Client:
        def deliver(self, snapshot, *, consumption=None) -> bool:
            delivered.append(snapshot)
            delivered_event.set()
            return True

    dispatcher = CallbackDispatcher(store, Client(), idle_wait_seconds=0.01)
    dispatcher.start()
    try:
        assert initial_check_done.wait(2)
        time.sleep(0.12)
        assert next_outbox_calls == 1, "dispatcher polled while outbox was empty"

        request = job_request_adapter.validate_json(
            (FIXTURES / "analysis-request.v1.json").read_text()
        )
        job_id = uuid4()
        store.accept(job_id, request)
        dispatcher.notify()
        assert delivered_event.wait(2)
        assert delivered[-1].job_id == job_id

        # Once drained, dispatcher returns to silent idle wait.
        time.sleep(0.05)
        settled_calls = next_outbox_calls
        time.sleep(0.12)
        assert next_outbox_calls == settled_calls
    finally:
        dispatcher.stop()
        store.close()


def test_callback_dispatcher_schedules_delayed_retry_and_wakes_early_on_notify(
    tmp_path: Path, monkeypatch
) -> None:
    import threading
    import time

    from ai_video_editor.worker.callbacks import CallbackDispatcher

    store = JobStore(tmp_path / "jobs.sqlite3", capacity=2)
    store.initialize()
    request = job_request_adapter.validate_json(
        (FIXTURES / "analysis-request.v1.json").read_text()
    )

    # First verify scheduled retry wakes on time without busy-polling.
    first_id = uuid4()
    store.accept(first_id, request)
    store.fail(
        first_id,
        WorkerError(code="processing_failed", stage="accepted", message="boom"),
    )

    next_outbox_calls = 0
    real_next_outbox = store.next_outbox

    def counting_next_outbox(*args, **kwargs):
        nonlocal next_outbox_calls
        next_outbox_calls += 1
        return real_next_outbox(*args, **kwargs)

    monkeypatch.setattr(store, "next_outbox", counting_next_outbox)

    attempts = 0
    terminal_delivered = threading.Event()

    class RetryingClient:
        def deliver(self, snapshot, *, consumption=None) -> bool:
            nonlocal attempts
            if snapshot.status == "failed":
                attempts += 1
                if attempts == 1:
                    raise OSError("temporary callback outage")
                terminal_delivered.set()
            return True

    dispatcher = CallbackDispatcher(
        store, RetryingClient(), retry_base_seconds=0.08, idle_wait_seconds=0.005
    )
    dispatcher.start()
    try:
        assert terminal_delivered.wait(2)
        assert attempts == 2
        # Accepted + failed attempt 1 + empty check before sleep + failed attempt 2 + empty check.
        assert next_outbox_calls <= 6
    finally:
        dispatcher.stop()

    # Now verify notify() wakes immediately even during a long retry backoff.
    second_id = uuid4()
    store.accept(second_id, request)
    store.fail(
        second_id,
        WorkerError(code="processing_failed", stage="accepted", message="still down"),
    )
    third_id = uuid4()
    waiting_on_backoff = threading.Event()
    third_delivered = threading.Event()
    real_next_available_at = store.next_outbox_available_at

    def track_backoff():
        result = real_next_available_at()
        if result is not None and result > time.time() + 1:
            waiting_on_backoff.set()
        return result

    monkeypatch.setattr(store, "next_outbox_available_at", track_backoff)

    class SelectiveClient:
        def deliver(self, snapshot, *, consumption=None) -> bool:
            if snapshot.job_id == second_id and snapshot.status == "failed":
                raise OSError("long outage")
            if snapshot.job_id == third_id:
                third_delivered.set()
            return True

    long_backoff_dispatcher = CallbackDispatcher(
        store, SelectiveClient(), retry_base_seconds=30.0
    )
    long_backoff_dispatcher.start()
    try:
        assert waiting_on_backoff.wait(2)
        store.accept(third_id, request)
        started = time.monotonic()
        long_backoff_dispatcher.notify()
        assert third_delivered.wait(2)
        assert time.monotonic() - started < 1.0
    finally:
        long_backoff_dispatcher.stop()
        store.close()
