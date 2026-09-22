from __future__ import annotations

import logging
import math
import multiprocessing
import os
import queue
import signal
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal, Protocol
from uuid import UUID

from ai_video_editor.worker.contracts import (
    AnalysisJobRequest,
    AnalysisResultV1,
    Progress,
    RenderJobRequest,
    RenderResultV1,
    ResolvedRenderConfigV1,
    WorkerError,
    job_result_adapter,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProgressEvent:
    progress: Progress


@dataclass(frozen=True)
class CompletedEvent:
    result: AnalysisResultV1 | RenderResultV1


@dataclass(frozen=True)
class FailedEvent:
    error: WorkerError


ExecutionEvent = ProgressEvent | CompletedEvent | FailedEvent
EventSink = Callable[[ExecutionEvent], None]


class MediaExecutor(Protocol):
    def start(
        self,
        job_id: UUID,
        request: AnalysisJobRequest | RenderJobRequest,
        resolved_render_config: ResolvedRenderConfigV1 | None,
        emit: EventSink,
    ) -> None: ...


MediaRunner = Callable[
    [
        UUID,
        dict[str, object],
        dict[str, object] | None,
        Callable[[int, str], None],
    ],
    dict[str, object],
]


class MediaExecutionFailure(Exception):
    def __init__(self, *, code: str, stage: str, message: str):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message


def _subprocess_entry(
    runner: MediaRunner,
    job_id: UUID,
    request: dict[str, object],
    resolved_render_config: dict[str, object] | None,
    events: multiprocessing.queues.Queue,
) -> None:
    # FFmpeg and other child processes inherit this dedicated process group.
    # Docker/Linux and the local macOS runner both support POSIX sessions.
    os.setsid()
    current_stage = "accepted"

    def progress(percent: int, stage: str) -> None:
        nonlocal current_stage
        current_stage = stage
        events.put({"type": "progress", "percent": percent, "stage": stage})

    try:
        result = runner(job_id, request, resolved_render_config, progress)
        events.put({"type": "completed", "result": result})
    except MediaExecutionFailure as exc:
        events.put(
            {
                "type": "failed",
                "code": exc.code,
                "stage": exc.stage,
                "message": exc.message,
            }
        )
    except BaseException:
        events.put(
            {
                "type": "failed",
                "code": "processing_failed",
                "stage": current_stage,
                "message": "Media processing failed unexpectedly",
            }
        )


class SubprocessMediaExecutor:
    """Owns one media subprocess and reports its events to the control process."""

    def __init__(
        self,
        runner: MediaRunner,
        *,
        analysis_timeout_seconds: float = 4 * 60 * 60,
        render_timeout_seconds: float = 4 * 60 * 60,
        termination_grace_seconds: float = 5.0,
    ):
        for value in (
            analysis_timeout_seconds,
            render_timeout_seconds,
            termination_grace_seconds,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("execution time limits must be positive and finite")
        self._runner = runner
        self._timeouts = {
            "analysis": analysis_timeout_seconds,
            "render": render_timeout_seconds,
        }
        self._termination_grace_seconds = termination_grace_seconds
        self._lock = threading.Lock()
        self._active = False
        self._context = multiprocessing.get_context("spawn")

    def start(
        self,
        job_id: UUID,
        request: AnalysisJobRequest | RenderJobRequest,
        resolved_render_config: ResolvedRenderConfigV1 | None,
        emit: EventSink,
    ) -> None:
        with self._lock:
            if self._active:
                raise RuntimeError("media subprocess slot is already occupied")
            self._active = True
            events = self._context.Queue()
            process = self._context.Process(
                target=_subprocess_entry,
                args=(
                    self._runner,
                    job_id,
                    request.model_dump(mode="json", by_alias=True, exclude_none=True),
                    (
                        resolved_render_config.model_dump(
                            mode="json", by_alias=True, exclude_none=True
                        )
                        if resolved_render_config is not None
                        else None
                    ),
                    events,
                ),
                name=f"video-job-{job_id}",
            )
            try:
                started_at = time.monotonic()
                process.start()
            except BaseException:
                self._active = False
                events.close()
                raise

        monitor = threading.Thread(
            target=self._monitor,
            args=(process, events, request.operation, emit, job_id, started_at),
            name=f"video-job-monitor-{job_id}",
            daemon=True,
        )
        monitor.start()

    def _monitor(
        self,
        process: multiprocessing.Process,
        events: multiprocessing.queues.Queue,
        operation: Literal["analysis", "render"],
        emit: EventSink,
        job_id: UUID,
        started_at: float,
    ) -> None:
        terminal_event: CompletedEvent | FailedEvent | None = None
        last_stage = "accepted"
        deadline = started_at + self._timeouts[operation]
        logger.info("job_started job_id=%s operation=%s", job_id, operation)

        def handle(raw: object) -> None:
            nonlocal last_stage, terminal_event
            event = self._parse_event(raw, operation)
            if isinstance(event, (CompletedEvent, FailedEvent)):
                terminal_event = event
            else:
                last_stage = event.progress.stage
                emit(event)

        try:
            try:
                while process.is_alive():
                    if time.monotonic() >= deadline:
                        terminal_event = FailedEvent(
                            WorkerError(
                                code="processing_timeout",
                                stage=last_stage,
                                message="Media processing exceeded its configured time limit",
                            )
                        )
                        break
                    try:
                        raw = events.get(
                            timeout=min(0.1, max(0.001, deadline - time.monotonic()))
                        )
                    except queue.Empty:
                        continue
                    handle(raw)
                # Never join a live, timed-out process before terminating it.
                while not process.is_alive():
                    try:
                        raw = events.get(timeout=0.05)
                    except queue.Empty:
                        break
                    handle(raw)
            except Exception:
                terminal_event = None
            if terminal_event is None:
                terminal_event = FailedEvent(
                    WorkerError(
                        code="processing_failed",
                        stage=last_stage,
                        message="Media subprocess exited abnormally",
                    )
                )
        finally:
            try:
                self._stop_process_tree(process)
            except Exception:
                logger.error(
                    "job_cleanup_failed job_id=%s operation=%s capacity_retained=true",
                    job_id,
                    operation,
                )
                raise
            events.close()
            with self._lock:
                self._active = False
        assert terminal_event is not None
        logger.info(
            "job_finished job_id=%s operation=%s outcome=%s stage=%s elapsed_seconds=%.3f",
            job_id,
            operation,
            terminal_event.error.code
            if isinstance(terminal_event, FailedEvent)
            else "completed",
            terminal_event.error.stage
            if isinstance(terminal_event, FailedEvent)
            else last_stage,
            time.monotonic() - started_at,
        )
        emit(terminal_event)

    def _stop_process_tree(self, process: multiprocessing.Process) -> None:
        # Address only the session created by this child, never our own group.
        # Even if the parent exited, its FFmpeg descendants may still be alive.
        assert process.pid is not None
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            if process.is_alive():
                process.terminate()  # Timeout during spawn, before setsid().
        process.join(timeout=self._termination_grace_seconds)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.is_alive():
            process.kill()
        process.join(timeout=self._termination_grace_seconds)
        if process.is_alive():
            # Fail closed: do not release capacity while media can still run.
            raise RuntimeError("media process could not be stopped")

    @staticmethod
    def _parse_event(
        raw: object,
        operation: Literal["analysis", "render"],
    ) -> ExecutionEvent:
        if not isinstance(raw, dict):
            raise ValueError("invalid subprocess event")
        event_type = raw.get("type")
        if event_type == "progress":
            return ProgressEvent(
                Progress(percent=raw.get("percent"), stage=raw.get("stage"))
            )
        if event_type == "failed":
            return FailedEvent(
                WorkerError(
                    code=raw.get("code"),
                    stage=raw.get("stage"),
                    message=raw.get("message"),
                )
            )
        if event_type == "completed":
            result = job_result_adapter.validate_python(raw.get("result"))
            if operation == "analysis" and not isinstance(result, AnalysisResultV1):
                raise ValueError("analysis executor returned a render result")
            if operation == "render" and not isinstance(result, RenderResultV1):
                raise ValueError("render executor returned an analysis result")
            return CompletedEvent(result)
        raise ValueError("invalid subprocess event type")


def media_adapters_not_configured(
    job_id: UUID,
    request: dict[str, object],
    resolved_render_config: dict[str, object] | None,
    progress: Callable[[int, str], None],
) -> dict[str, object]:
    """DEV-784 boundary placeholder until Drive/R2 media adapters are provided."""

    del job_id, request, resolved_render_config, progress
    raise MediaExecutionFailure(
        code="processing_failed",
        stage="accepted",
        message="Media executor adapters are not configured",
    )
