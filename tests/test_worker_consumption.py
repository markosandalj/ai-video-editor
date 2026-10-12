import asyncio
import json
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
import pytest

from ai_video_editor.worker.callbacks import CallbackDispatcher
from ai_video_editor.worker.consumption import (
    ConsumptionTransport,
    ConsumptionV1,
    consumption_scope,
    start_attempt,
)
from ai_video_editor.worker.contracts import WorkerError, job_request_adapter
from ai_video_editor.worker.executor import SubprocessMediaExecutor
from ai_video_editor.worker.service import WorkerService
from ai_video_editor.worker.store import JobStore


def receipt(job, **changes):
    return ConsumptionV1(
        job_id=job,
        attempt_id=uuid4(),
        revision=1,
        operation="grammar",
        provider="google",
        started_at=datetime.now(UTC),
        outcome="started",
        **changes,
    )


def attempts(path):
    with sqlite3.connect(path) as db:
        return [
            ConsumptionV1.model_validate_json(row[0])
            for row in db.execute("SELECT payload_json FROM consumption_attempts")
        ]


def analysis_request():
    return job_request_adapter.validate_json(
        (Path(__file__).parent / "data/worker_contract/analysis-request.v1.json").read_text()
    )


def test_receipts_survive_restart_and_delivery_retries(tmp_path):
    path = tmp_path / "state.db"
    store = JobStore(path)
    store.initialize()
    original = receipt(uuid4())
    store.accept(original.job_id, analysis_request())
    store.record_consumption(original)
    final = original.model_copy(
        update={"revision": 2, "usage": {"totalTokenCount": 42}, "outcome": "succeeded"}
    )
    store.record_consumption(final)
    store.record_consumption(original)
    received = []

    class Online:
        def deliver(self, snapshot, *, consumption=None):
            received.append((snapshot, consumption))
            return True

    dispatcher = CallbackDispatcher(store, Online())
    assert dispatcher.dispatch_once()
    assert received[0][1] is None  # No consumption before terminal status.
    assert attempts(path) == [final]
    store.fail(original.job_id, WorkerError(code="processing_failed", stage="provider", message="failed"))
    restarted = JobStore(path)
    restarted.initialize()
    assert attempts(path) == [final]

    class Offline:
        def deliver(self, snapshot, *, consumption=None):
            assert consumption == [final]
            raise OSError("offline")

    dispatcher = CallbackDispatcher(restarted, Offline(), retry_base_seconds=0.001)
    assert dispatcher.dispatch_once()
    assert restarted.pending_outbox_count() == 1
    assert attempts(path) == [final]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE callback_outbox SET available_at=0")
    online = CallbackDispatcher(restarted, Online())
    assert online.dispatch_once()
    assert received[-1][0].status == "failed" and received[-1][1] == [final]
    assert restarted.pending_outbox_count() == 0
    assert attempts(path) == []


@pytest.mark.parametrize("failure", ["collection", "gradivo_consumption"])
def test_consumption_failure_still_delivers_result_and_retains_evidence(tmp_path, monkeypatch, failure):
    store = JobStore(tmp_path / "state.db")
    store.initialize()
    job_id = uuid4()
    store.accept(job_id, analysis_request())
    original = receipt(job_id)
    store.record_consumption(original)
    store.fail(job_id, WorkerError(code="processing_failed", stage="provider", message="failed"))
    delivered = []
    healthy = False

    class Client:
        def deliver(self, snapshot, *, consumption=None):
            delivered.append((snapshot, consumption))
            return healthy if failure == "gradivo_consumption" else True

    dispatcher = CallbackDispatcher(store, Client())
    collector = store.consumption_for_terminal_job
    if failure == "collection":
        monkeypatch.setattr(store, "consumption_for_terminal_job", Mock(side_effect=OSError("unavailable")))
    assert dispatcher.dispatch_once()  # Accepted status.
    assert dispatcher.dispatch_once()  # Terminal result, even without consumption.
    assert delivered[-1][0].status == "failed"
    assert store.pending_outbox_count() == 1 and len(attempts(store._path)) == 1
    if failure == "collection":
        assert delivered[-1][1] is None
    healthy = True
    monkeypatch.setattr(store, "consumption_for_terminal_job", collector)
    with sqlite3.connect(store._path) as db:
        db.execute("UPDATE callback_outbox SET available_at=0")
    assert dispatcher.dispatch_once()
    assert delivered[-1][0] == delivered[-2][0]
    assert delivered[-1][1][0].attempt_id == original.attempt_id
    assert delivered[-1][1][0].outcome == "interrupted"
    assert attempts(store._path) == [] and store.pending_outbox_count() == 0


def test_worker_restart_bundles_abandoned_calls_with_failed_job(tmp_path):
    path = tmp_path / "state.db"
    previous = JobStore(path)
    previous.initialize()
    job_id = uuid4()
    previous.accept(job_id, analysis_request())
    previous.record_consumption(receipt(job_id))
    received = []

    class Client:
        def deliver(self, snapshot, *, consumption=None):
            received.append((snapshot, consumption))
            return True

    store = JobStore(path)
    dispatcher = CallbackDispatcher(store, Client())
    service = WorkerService(store, Mock(), dispatcher)
    service.startup(start_callback_dispatcher=False)
    while dispatcher.dispatch_once():
        pass
    snapshot, consumption = received[-1]
    assert snapshot.error.code == "worker_interrupted"
    assert len(consumption) == 1 and consumption[0].outcome == "interrupted"
    assert consumption[0].usage == {} and consumption[0].cost_amount is None
    assert attempts(path) == []


def test_crash_preserves_unknown_started_calls_not_zero_usage(tmp_path):
    store = JobStore(tmp_path / "state.db")
    store.initialize()
    row = receipt(uuid4())
    store.record_consumption(row)
    store.recover_consumption()
    recovered = attempts(store._path)[0]
    assert recovered.outcome == "interrupted"
    assert not {"duration_ms", "timing_scope"} & recovered.model_dump().keys()
    assert recovered.usage == {}
    assert recovered.coverage_issues == ["worker_interrupted_before_receipt"]


def test_receipt_recovery_only_finalizes_the_stopped_job_and_is_idempotent(tmp_path):
    store = JobStore(tmp_path / "state.db")
    store.initialize()
    unfinished = receipt(
        uuid4(), usage={"total_tokens": 60}, coverage_issues=["worker_ledger_write_failed"]
    )
    active = receipt(uuid4())
    completed = receipt(unfinished.job_id).model_copy(
        update={"revision": 2, "outcome": "succeeded", "usage": {"total_tokens": 42}}
    )
    for row in (unfinished, active, completed):
        store.record_consumption(row)

    store.recover_consumption(job_id=unfinished.job_id)
    store.recover_consumption(job_id=unfinished.job_id)
    recovered, still_active, still_completed = attempts(store._path)
    assert recovered.revision == 2 and recovered.outcome == "interrupted"
    assert recovered.usage == {"total_tokens": 60} and recovered.cost_amount is None
    assert recovered.coverage_issues == [
        "worker_interrupted_before_receipt", "worker_ledger_write_failed"
    ]
    assert still_active == active and still_completed == completed
    assert len(attempts(store._path)) == 3


class UnfinishedProviderRunner:
    def __init__(self, outcome):
        self.outcome = outcome

    def __call__(self, job_id, request, resolved_render_config, progress):
        start_attempt("worker.llm", "openrouter", "fixture-no-network")
        progress(20, "provider")
        if self.outcome == "crash":
            os._exit(7)
        if self.outcome == "completed":
            fixture = Path(__file__).parent / "data/worker_contract/analysis-completed-snapshot.v1.json"
            return json.loads(fixture.read_text())["result"]
        time.sleep(30)


@pytest.mark.parametrize("outcome", ["timeout", "crash", "completed", "shutdown"])
def test_terminal_job_delivers_interrupted_receipts_without_worker_restart(tmp_path, outcome):
    store = JobStore(tmp_path / "state.db")
    executor = SubprocessMediaExecutor(
        UnfinishedProviderRunner(outcome),
        analysis_timeout_seconds=3 if outcome == "timeout" else 30,
        termination_grace_seconds=0.1,
        consumption_recorder=store,
    )
    received = []
    delivered = threading.Event()
    started = threading.Event()

    class Client:
        def deliver(self, snapshot, *, consumption=None):
            if snapshot.status == "processing":
                assert consumption is None
                if snapshot.progress.percent == 20:
                    started.set()
            else:
                received.extend(consumption or [])
                delivered.set()
            return True

    dispatcher = CallbackDispatcher(store, Client(), idle_wait_seconds=0.01)
    service = WorkerService(store, executor, dispatcher)
    service.startup()
    job_id = uuid4()
    request = job_request_adapter.validate_json(
        (Path(__file__).parent / "data/worker_contract/analysis-request.v1.json").read_text()
    )
    try:
        service.submit(job_id, request)
        if outcome == "shutdown":
            assert started.wait(8)
            # Keep callbacks running to inspect the receipt after child termination.
            executor.shutdown()
        assert delivered.wait(8)
        executor.shutdown()  # Wait for the terminal job snapshot to be committed too.
        snapshot = store.get_snapshot(job_id)
        assert snapshot.status == ("completed" if outcome == "completed" else "failed")
        if outcome == "timeout":
            assert snapshot.error.code == "processing_timeout"
        final = [row for row in received if row.outcome != "started"]
        assert len(final) == 1
        assert final[0].job_id == job_id and final[0].revision == 2
        assert final[0].outcome == "interrupted"
        assert final[0].usage == {} and final[0].cost_amount is None
        assert final[0].coverage_issues == ["worker_interrupted_before_receipt"]
    finally:
        service.shutdown()


def test_transport_records_each_real_sdk_retry_and_response_before_parse(tmp_path):
    from openai import OpenAI

    store = JobStore(tmp_path / "state.db")
    store.initialize()
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                429, json={"error": {"message": "busy", "type": "rate_limit_error"}}
            )
        return httpx.Response(
            200,
            json={
                "id": "gen-2",
                "model": "openai/model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                    "cost": 0.0012,
                },
            },
        )

    transport = ConsumptionTransport(
        "openrouter",
        "requested",
        "section_editor",
        transport=httpx.MockTransport(respond),
    )
    client = OpenAI(
        api_key="contract-fixture",
        base_url="https://openrouter.ai/api/v1",
        max_retries=1,
        http_client=httpx.Client(transport=transport),
    )
    with consumption_scope(store, uuid4()):
        result = client.chat.completions.create(
            model="requested",
            messages=[{"role": "user", "content": "private prompt never stored"}],
        )
    api = attempts(store._path)
    assert len(calls) == len(api) == 2
    assert [row.outcome for row in api] == ["failed", "succeeded"]
    assert api[1].usage["total_tokens"] == 14
    assert float(api[1].cost_amount) == 0.0012
    assert api[1].provider_request_id == result.id
    assert all(
        not {"duration_ms", "timing_scope"} & row.model_dump().keys() for row in api
    )
    assert "private prompt" not in str(attempts(store._path))


def test_timeout_and_ledger_error_never_invent_free_calls_or_fail_content(tmp_path):
    store = JobStore(tmp_path / "state.db")
    store.initialize()

    def fail(request):
        raise httpx.ReadTimeout("timeout")

    transport = ConsumptionTransport(
        "google", "gemini", "grammar", transport=httpx.MockTransport(fail)
    )
    with (
        consumption_scope(store, uuid4()),
        pytest.raises(httpx.ReadTimeout),
    ):
        httpx.Client(transport=transport).post(
            "https://generativelanguage.googleapis.com/models/model:generateContent"
        )
    row = next(row for row in attempts(store._path) if row.provider == "google")
    assert row.cost_amount is None and row.usage == {} and row.outcome == "failed"
    real = store.record_consumption
    count = 0

    def flaky(payload):
        nonlocal count
        count += 1
        if count == 1:
            raise OSError("simulated ledger failure")
        real(payload)

    store.record_consumption = flaky
    with (
        consumption_scope(store, uuid4()),
        httpx.Client(
            transport=ConsumptionTransport(
                "openai",
                "model",
                "grammar",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, json={"usage": {"total_tokens": 5}}
                    )
                ),
            )
        ) as client,
    ):
        assert (
            client.post("https://api.openai.com/v1/chat/completions").status_code == 200
        )
    assert any(
        "worker_ledger_write_failed" in row.coverage_issues
        for row in attempts(store._path)
    )


def test_real_langchain_gemini_sync_and_async_pass_through_transport(
    tmp_path, monkeypatch
):
    from ai_video_editor.llm import build_chat_model, direct_gemini_model_config

    store = JobStore(tmp_path / "state.db")
    store.initialize()
    monkeypatch.setenv("GEMINI_API_KEY", "contract-fixture-no-paid-calls")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "Fixture answer"}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "gemini-2.5-flash",
                "responseId": "google-contract-response",
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 4,
                    "thoughtsTokenCount": 2,
                    "totalTokenCount": 16,
                },
            },
        )

    transport = ConsumptionTransport(
        "google",
        "gemini-2.5-flash",
        "worker.llm",
        transport=httpx.MockTransport(respond),
        async_transport=httpx.MockTransport(respond),
    )
    with (
        patch(
            "ai_video_editor.worker.consumption.ConsumptionTransport",
            return_value=transport,
        ),
        consumption_scope(store, uuid4()),
    ):
        model = build_chat_model(direct_gemini_model_config(model="gemini-2.5-flash"))
        assert model.invoke("fixture input").content == "Fixture answer"
        assert asyncio.run(model.ainvoke("fixture input")).content == "Fixture answer"
    api = [row for row in attempts(store._path) if row.provider == "google"]
    assert len(requests) == len(api) == 2
    assert all(row.provider_request_id == "google-contract-response" for row in api)
    assert all(row.usage["thoughtsTokenCount"] == 2 for row in api)


def test_elevenlabs_sdk_records_unknown_cost_without_measuring_audio(tmp_path, monkeypatch):
    from ai_video_editor.transcription.elevenlabs_stt import transcribe_elevenlabs

    store = JobStore(tmp_path / "state.db")
    store.initialize()
    monkeypatch.setenv("ELEVENLABS_API_KEY", "contract-fixture-no-paid-calls")
    media = tmp_path / "fixture.wav"
    media.write_bytes(b"local contract fixture")
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "scribe-receipt"},
            json={
                "language_code": "hr",
                "language_probability": 1,
                "text": "Bok",
                "words": [{"text": "Bok", "type": "word", "start": 0, "end": 1}],
            },
        )

    transport = ConsumptionTransport(
        "elevenlabs",
        "scribe_v2",
        "worker.transcription",
        transport=httpx.MockTransport(respond),
    )
    with (
        patch(
            "ai_video_editor.worker.consumption.ConsumptionTransport",
            return_value=transport,
        ),
        patch("subprocess.run") as probe,
        consumption_scope(store, uuid4()),
    ):
        words, text, events = transcribe_elevenlabs(media)
    row = next(row for row in attempts(store._path) if row.provider == "elevenlabs")
    assert text == "Bok" and words[0].end == 1 and events == []
    probe.assert_not_called()
    assert len(calls) == 1 and row.usage == {}
    assert row.provider_request_id == "scribe-receipt" and row.cost_amount is None
    assert row.cost_basis == "unavailable" and row.coverage_issues == []


def test_bad_provider_cost_does_not_fail_successful_content(tmp_path):
    store = JobStore(tmp_path / "state.db")
    store.initialize()
    with consumption_scope(store, uuid4()):
        client = httpx.Client(
            transport=ConsumptionTransport(
                "openrouter",
                "model",
                "worker.llm",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, json={"usage": {"total_tokens": 3, "cost": "invalid"}}
                    )
                ),
            )
        )
        assert (
            client.post("https://openrouter.ai/api/v1/chat/completions").status_code
            == 200
        )
    row = next(row for row in attempts(store._path) if row.provider == "openrouter")
    assert row.outcome == "succeeded" and row.cost_amount is None
    assert (
        row.usage["total_tokens"] == 3
        and "invalid_provider_cost" in row.coverage_issues
    )


def test_processing_without_provider_usage_creates_no_consumption(tmp_path):
    store = JobStore(tmp_path / "state.db")
    store.initialize()
    with consumption_scope(store, uuid4()):
        pass
    assert attempts(store._path) == []


def test_real_grammar_passes_reach_terminal_consumption(tmp_path, monkeypatch):
    from ai_video_editor.transcription.grammar import correct_grammar
    from ai_video_editor.transcription.models import Sentence, Transcript, Word

    monkeypatch.setenv("GEMINI_API_KEY", "contract-fixture-no-paid-calls")
    store = JobStore(tmp_path / "state.db")
    store.initialize()
    job_id = uuid4()
    store.accept(job_id, analysis_request())
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        corrections = (
            [{"wrong": "korjen", "correct": "korijen"}] if len(requests) == 1 else []
        )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": json.dumps({"corrections": corrections})}
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "gemini-2.5-flash",
                "responseId": f"grammar-pass-{len(requests)}",
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 10,
                    "totalTokenCount": 110,
                },
            },
        )

    def instrumented_transport(provider, model, operation):
        assert operation == "worker.transcript_grammar"
        return ConsumptionTransport(
            provider, model, operation, transport=httpx.MockTransport(respond)
        )
    transcript = Transcript(
        sentences=[
            Sentence(
                text="korjen",
                start=0,
                end=1,
                words=[Word(text="korjen", start=0, end=1)],
            )
        ],
        source_video="fixture.mp4",
        language="hr",
        model_size="fixture",
    )
    with (
        patch(
            "ai_video_editor.worker.consumption.ConsumptionTransport",
            side_effect=instrumented_transport,
        ),
        consumption_scope(store, job_id),
    ):
        corrected, report = correct_grammar(transcript)
    assert report.passes == 2 and report.converged
    assert corrected.sentences[0].text == "korijen"
    assert "korjen" in json.dumps(requests[0]) and "korijen" in json.dumps(requests[1])
    store.fail(
        job_id,
        WorkerError(code="processing_failed", stage="later_step", message="fixture"),
    )
    delivered = []

    class Receiver:
        def deliver(self, snapshot, *, consumption=None):
            delivered.append((snapshot, consumption))
            return True

    dispatcher = CallbackDispatcher(store, Receiver())
    while dispatcher.dispatch_once():
        pass
    snapshot, receipts = delivered[-1]
    assert snapshot.status == "failed"
    assert {row.provider_request_id for row in receipts} == {
        "grammar-pass-1",
        "grammar-pass-2",
    }
    assert sum(row.usage["totalTokenCount"] for row in receipts) == 220
    assert all(
        row.provider == "google"
        and row.outcome == "succeeded"
        and row.operation == "worker.transcript_grammar"
        for row in receipts
    )
